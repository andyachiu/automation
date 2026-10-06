#!/usr/bin/env python3
"""
Two-way sync between Apple Reminders and TASKS.md.

  --pull   Add new incomplete reminders to TASKS.md, and check off tasks whose
           reminder was completed in Reminders.
  --push   Mark reminders complete in Apple Reminders for tasks checked off in
           TASKS.md.
  --sync   Push, then pull (default).
  --dry-run  Show what would change without writing anything.

Reads go straight to the Reminders SQLite DB (fast, needs Full Disk Access for
the venv python — same grant the briefs use). Writes use one targeted
AppleScript call per completed task (needs Automation → Reminders permission).

Each synced task carries a hidden marker: `<!-- rem:UUID -->`. Tasks without a
marker are yours alone and are never touched.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shared.reminders import CORE_DATA_EPOCH, _find_db  # noqa: E402

log = logging.getLogger("reminders_sync")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TASKS_FILE = REPO_ROOT / "TASKS.md"
OSASCRIPT_BIN = os.environ.get("OSASCRIPT_BIN", "osascript")
APPLESCRIPT_TIMEOUT_S = 30

MARKER_RE = re.compile(r"<!--\s*rem:([0-9A-Fa-f-]+)\s*-->")
TASK_RE = re.compile(r"^(\s*-\s*\[)([ xX])(\].*)$")

TEMPLATE = """# Tasks

## Active

## Waiting On

## Someday

## Done
"""


class SyncError(RuntimeError):
    pass


# ── Reminders DB ─────────────────────────────────────────────────────────────


def _connect() -> sqlite3.Connection:
    db_path = _find_db()
    if not db_path:
        raise SyncError(
            "Reminders database not found or not readable. "
            "Check Full Disk Access for the venv python (see TROUBLESHOOTING.md)."
        )
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


def fetch_reminders(conn: sqlite3.Connection) -> dict[str, dict]:
    """Return {uuid: {title, due, list, completed}} for all non-deleted reminders."""
    rows = conn.execute(
        """
        SELECT r.ZCKIDENTIFIER, r.ZTITLE, r.ZDUEDATE, r.ZCOMPLETED, l.ZNAME
        FROM ZREMCDREMINDER r
        LEFT JOIN ZREMCDBASELIST l ON r.ZLIST = l.Z_PK
        WHERE r.ZMARKEDFORDELETION = 0 AND r.ZCKIDENTIFIER IS NOT NULL
        ORDER BY r.ZDUEDATE IS NULL, r.ZDUEDATE ASC
        """
    ).fetchall()
    out: dict[str, dict] = {}
    for uuid, title, due_ts, completed, list_name in rows:
        if not title:
            continue
        out[uuid.upper()] = {
            "title": title.strip(),
            "due": datetime.fromtimestamp(due_ts + CORE_DATA_EPOCH) if due_ts else None,
            "list": list_name,
            "completed": bool(completed),
        }
    return out


# ── TASKS.md ─────────────────────────────────────────────────────────────────


def format_task(uuid: str, rem: dict) -> str:
    line = f"- [ ] **{rem['title']}**"
    if rem["list"] and rem["list"] != "Reminders":
        line += f" ({rem['list']})"
    if rem["due"]:
        line += f" - due {rem['due'].strftime('%a %b %-d, %Y %-I:%M %p')}"
    return f"{line} <!-- rem:{uuid} -->"


def parse_tasks(lines: list[str]) -> dict[str, tuple[int, bool]]:
    """Return {uuid: (line_index, checked)} for marker-tagged task lines."""
    found: dict[str, tuple[int, bool]] = {}
    for i, line in enumerate(lines):
        m, t = MARKER_RE.search(line), TASK_RE.match(line)
        if m and t:
            found[m.group(1).upper()] = (i, t.group(2).lower() == "x")
    return found


def _set_checked(line: str) -> str:
    return TASK_RE.sub(lambda m: f"{m.group(1)}x{m.group(3)}", line, count=1)


def _insert_under_active(lines: list[str], new: list[str]) -> list[str]:
    for i, line in enumerate(lines):
        if line.strip().lower() == "## active":
            j = i + 1
            while j < len(lines) and not lines[j].startswith("## "):
                j += 1
            while j > i + 1 and not lines[j - 1].strip():
                j -= 1
            return lines[:j] + new + lines[j:]
    return lines + ["", "## Active", *new]


def read_tasks(path: Path) -> list[str]:
    if not path.exists():
        return TEMPLATE.splitlines()
    return path.read_text().splitlines()


def write_tasks(path: Path, lines: list[str]) -> None:
    tmp = path.with_suffix(".md.tmp")
    tmp.write_text("\n".join(lines).rstrip() + "\n")
    tmp.replace(path)


# ── AppleScript ──────────────────────────────────────────────────────────────


def complete_in_reminders(uuid: str) -> None:
    script = (
        f"with timeout of {APPLESCRIPT_TIMEOUT_S} seconds\n"
        'tell application "Reminders"\n'
        f'set completed of reminder id "x-apple-reminder://{uuid}" to true\n'
        "end tell\nend timeout"
    )
    try:
        res = subprocess.run(
            [OSASCRIPT_BIN, "-e", script],
            capture_output=True,
            text=True,
            timeout=APPLESCRIPT_TIMEOUT_S + 10,
        )
    except subprocess.TimeoutExpired as e:
        raise SyncError(f"AppleScript timed out completing {uuid}") from e
    if res.returncode != 0:
        raise SyncError(f"AppleScript error completing {uuid}: {res.stderr.strip()}")


# ── Commands ─────────────────────────────────────────────────────────────────


def push(tasks_file: Path, reminders: dict[str, dict], dry_run: bool) -> int:
    print("📤  Pushing completions TASKS.md → Apple Reminders …")
    tagged = parse_tasks(read_tasks(tasks_file))
    todo = [
        u for u, (_, checked) in tagged.items()
        if checked and u in reminders and not reminders[u]["completed"]
    ]
    if not todo:
        print("✅  No completed tasks to push.")
        return 0
    for uuid in todo:
        title = reminders[uuid]["title"]
        if dry_run:
            print(f"    would complete: {title}")
            continue
        complete_in_reminders(uuid)
        reminders[uuid]["completed"] = True
        print(f"    ✔ {title}")
    print(f"✅  {'Would mark' if dry_run else 'Marked'} {len(todo)} reminder(s) complete.")
    return len(todo)


def pull(tasks_file: Path, reminders: dict[str, dict], dry_run: bool) -> int:
    print("📥  Pulling from Apple Reminders → TASKS.md …")
    lines = read_tasks(tasks_file)
    tagged = parse_tasks(lines)

    closed = []
    for uuid, (idx, checked) in tagged.items():
        rem = reminders.get(uuid)
        if not checked and rem and rem["completed"]:
            lines[idx] = _set_checked(lines[idx])
            closed.append(rem["title"])

    new_uuids = [
        u for u, r in reminders.items() if not r["completed"] and u not in tagged
    ]
    new_lines = [format_task(u, reminders[u]) for u in new_uuids]
    if new_lines:
        lines = _insert_under_active(lines, new_lines)

    if not closed and not new_lines:
        print("✅  TASKS.md is already up to date.")
        return 0
    if new_lines:
        print(f"✅  {'Would add' if dry_run else 'Added'} {len(new_lines)} new task(s):")
        for line in new_lines:
            print(f"    {MARKER_RE.sub('', line).rstrip()}")
    if closed:
        print(f"✅  {'Would check' if dry_run else 'Checked'} off {len(closed)} task(s) completed in Reminders:")
        for title in closed:
            print(f"    - [x] {title}")
    if not dry_run:
        write_tasks(tasks_file, lines)
    return len(new_lines) + len(closed)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--pull", action="store_true")
    mode.add_argument("--push", action="store_true")
    mode.add_argument("--sync", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--tasks-file", type=Path,
                   default=Path(os.environ.get("TASKS_FILE", DEFAULT_TASKS_FILE)))
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] reminders_sync → {args.tasks_file}")
    try:
        conn = _connect()
        try:
            reminders = fetch_reminders(conn)
        finally:
            conn.close()
        if not (args.pull):
            push(args.tasks_file, reminders, args.dry_run)
        if not (args.push):
            pull(args.tasks_file, reminders, args.dry_run)
    except (SyncError, sqlite3.Error) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
