"""
Read incomplete reminders from the macOS Reminders SQLite database.
"""

import logging
import os
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

STORES_DIR = Path.home() / "Library/Group Containers/group.com.apple.reminders/Container_v1/Stores"
CORE_DATA_EPOCH = 978307200  # 2001-01-01 in Unix time


def _tcc_candidate_paths() -> list[str]:
    """Binaries that TCC may attribute Reminders DB access to, in order of likelihood.

    The production wrappers now invoke `<repo>/scripts/.venv/bin/python3` directly,
    so the responsible process is the resolved python interpreter (sys.executable's
    realpath). Listed first. `uv` is kept as a fallback in case someone is still
    invoking via `uv run` manually — historically this project granted FDA to uv.
    """
    paths: list[str] = []
    if sys.executable:
        resolved = os.path.realpath(sys.executable)
        if resolved not in paths:
            paths.append(resolved)
        if sys.executable != resolved and sys.executable not in paths:
            paths.append(sys.executable)
    uv = shutil.which("uv")
    if uv and uv not in paths:
        paths.append(uv)
    return paths


def _find_db() -> Path | None:
    try:
        entries = list(STORES_DIR.iterdir())
    except FileNotFoundError:
        log.warning("Reminders store dir does not exist: %s", STORES_DIR)
        return None
    except PermissionError:
        # TCC denied directory listing. Path.glob() would silently swallow this
        # and return []; iterdir() raises so we can surface an actionable error.
        candidates = " or ".join(_tcc_candidate_paths())
        log.error(
            "Permission denied reading %s — Full Disk Access grant is missing or stale. "
            "Fix: System Settings → Privacy & Security → Full Disk Access → remove and re-add %s "
            "(whichever was actually used to launch this script). "
            "TCC keys grants by binary signature, so any upgrade silently invalidates the existing entry.",
            STORES_DIR, candidates,
        )
        return None

    best, best_count = None, 0
    for db_path in entries:
        if db_path.suffix != ".sqlite":
            continue
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            count = conn.execute(
                "SELECT count(*) FROM ZREMCDREMINDER WHERE ZCOMPLETED = 0 AND ZMARKEDFORDELETION = 0"
            ).fetchone()[0]
            conn.close()
            if count > best_count:
                best, best_count = db_path, count
        except Exception:
            continue
    return best


def get_reminders(target_date: datetime, include_overdue: bool = True) -> dict[str, list[str]]:
    """Fetch reminders relevant to target_date.

    Returns dict with keys:
        "overdue" — reminders with due date before today (if include_overdue)
        "due" — reminders due on target_date
    Each item is a string like "Title" or "Title (List Name)" if not default list.
    """
    db_path = _find_db()
    if not db_path:
        log.warning("Reminders database not found")
        return {"overdue": [], "due": []}

    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    target_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    target_end = target_start + timedelta(days=1)

    today_ts = today_start.timestamp() - CORE_DATA_EPOCH
    target_start_ts = target_start.timestamp() - CORE_DATA_EPOCH
    target_end_ts = target_end.timestamp() - CORE_DATA_EPOCH

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        rows = conn.execute(
            """
            SELECT r.ZTITLE, r.ZDUEDATE, l.ZNAME
            FROM ZREMCDREMINDER r
            LEFT JOIN ZREMCDBASELIST l ON r.ZLIST = l.Z_PK
            WHERE r.ZCOMPLETED = 0
              AND r.ZMARKEDFORDELETION = 0
              AND r.ZDUEDATE IS NOT NULL
              AND r.ZDUEDATE < ?
            ORDER BY r.ZDUEDATE ASC
            """,
            (target_end_ts,),
        ).fetchall()
        conn.close()
    except Exception as e:
        log.warning("Failed to read reminders DB: %s", e)
        return {"overdue": [], "due": []}

    overdue, due = [], []
    for title, due_ts, list_name in rows:
        if not title:
            continue
        label = title if (not list_name or list_name == "Reminders") else f"{title} ({list_name})"
        if due_ts < today_ts:
            overdue.append(label)
        elif target_start_ts <= due_ts < target_end_ts:
            due.append(label)

    if not include_overdue:
        overdue = []

    return {"overdue": overdue, "due": due}
