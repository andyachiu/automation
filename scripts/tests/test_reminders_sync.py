"""
Offline tests for reminders_sync.py (real SQLite fixture, AppleScript mocked).
Run with: uv run pytest tests/test_reminders_sync.py -v
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import reminders_sync as rs
from shared.reminders import CORE_DATA_EPOCH

U1 = "11111111-1111-1111-1111-111111111111"
U2 = "22222222-2222-2222-2222-222222222222"
U3 = "33333333-3333-3333-3333-333333333333"


def _db(tmp_path: Path, rows: list[tuple]) -> sqlite3.Connection:
    conn = sqlite3.connect(str(tmp_path / "R.sqlite"))
    conn.execute("CREATE TABLE ZREMCDBASELIST (Z_PK INTEGER PRIMARY KEY, ZNAME VARCHAR)")
    conn.execute(
        "CREATE TABLE ZREMCDREMINDER (Z_PK INTEGER PRIMARY KEY, ZCKIDENTIFIER VARCHAR, "
        "ZTITLE VARCHAR, ZDUEDATE TIMESTAMP, ZCOMPLETED INTEGER, "
        "ZMARKEDFORDELETION INTEGER, ZLIST INTEGER)"
    )
    conn.execute("INSERT INTO ZREMCDBASELIST VALUES (1, 'Reminders'), (2, 'Groceries')")
    for i, (uuid, title, due, completed, deleted, lst) in enumerate(rows, 1):
        ts = due.timestamp() - CORE_DATA_EPOCH if due else None
        conn.execute(
            "INSERT INTO ZREMCDREMINDER VALUES (?,?,?,?,?,?,?)",
            (i, uuid, title, ts, completed, deleted, lst),
        )
    conn.commit()
    return conn


def _reminders(tmp_path, rows):
    conn = _db(tmp_path, rows)
    try:
        return rs.fetch_reminders(conn)
    finally:
        conn.close()


def test_fetch_skips_deleted_and_keys_by_upper_uuid(tmp_path):
    rems = _reminders(tmp_path, [
        (U1.lower(), "Buy milk", None, 0, 0, 2),
        (U2, "Gone", None, 0, 1, 1),
    ])
    assert list(rems) == [U1]
    assert rems[U1]["list"] == "Groceries"


def test_pull_creates_file_and_adds_under_active(tmp_path):
    f = tmp_path / "TASKS.md"
    rems = _reminders(tmp_path, [
        (U1, "Call dentist", datetime(2026, 10, 7, 9, 0), 0, 0, 1),
        (U2, "Already done", None, 1, 0, 1),
    ])
    assert rs.pull(f, rems, dry_run=False) == 1
    text = f.read_text()
    assert f"- [ ] **Call dentist** - due Wed Oct 7, 2026 9:00 AM <!-- rem:{U1} -->" in text
    assert "Already done" not in text
    assert text.index("Call dentist") < text.index("## Waiting On")


def test_pull_is_idempotent_and_leaves_untagged_tasks(tmp_path):
    f = tmp_path / "TASKS.md"
    f.write_text("# Tasks\n\n## Active\n- [ ] my own thing\n\n## Done\n")
    rems = _reminders(tmp_path, [(U1, "A", None, 0, 0, 1)])
    rs.pull(f, rems, dry_run=False)
    first = f.read_text()
    assert rs.pull(f, rems, dry_run=False) == 0
    assert f.read_text() == first
    assert "- [ ] my own thing" in first


def test_pull_checks_off_tasks_completed_in_reminders(tmp_path):
    f = tmp_path / "TASKS.md"
    f.write_text(f"## Active\n- [ ] **A** <!-- rem:{U1} -->\n")
    rems = _reminders(tmp_path, [(U1, "A", None, 1, 0, 1)])
    assert rs.pull(f, rems, dry_run=False) == 1
    assert f"- [x] **A** <!-- rem:{U1} -->" in f.read_text()


def test_push_completes_checked_tasks_only(tmp_path):
    f = tmp_path / "TASKS.md"
    f.write_text(
        f"## Active\n- [x] **A** <!-- rem:{U1} -->\n"
        f"- [ ] **B** <!-- rem:{U2} -->\n- [x] **C** <!-- rem:{U3} -->\n"
    )
    rems = _reminders(tmp_path, [
        (U1, "A", None, 0, 0, 1),
        (U2, "B", None, 0, 0, 1),
        (U3, "C", None, 1, 0, 1),  # already complete in Reminders
    ])
    with patch.object(rs, "complete_in_reminders") as done:
        assert rs.push(f, rems, dry_run=False) == 1
    done.assert_called_once_with(U1)
    assert rems[U1]["completed"]


def test_dry_run_writes_nothing(tmp_path):
    f = tmp_path / "TASKS.md"
    f.write_text(f"## Active\n- [x] **A** <!-- rem:{U1} -->\n")
    before = f.read_text()
    rems = _reminders(tmp_path, [(U1, "A", None, 0, 0, 1), (U2, "New", None, 0, 0, 1)])
    with patch.object(rs, "complete_in_reminders") as done:
        rs.push(f, rems, dry_run=True)
        rs.pull(f, rems, dry_run=True)
    done.assert_not_called()
    assert f.read_text() == before


def test_main_fails_loud_when_db_unreadable(tmp_path, capsys):
    with patch.object(rs, "_find_db", return_value=None):
        assert rs.main(["--sync", "--tasks-file", str(tmp_path / "T.md")]) == 1
    assert "ERROR" in capsys.readouterr().err


def test_main_fails_loud_on_applescript_error(tmp_path):
    f = tmp_path / "TASKS.md"
    f.write_text(f"## Active\n- [x] **A** <!-- rem:{U1} -->\n")
    conn = _db(tmp_path, [(U1, "A", None, 0, 0, 1)])
    conn.close()
    with patch.object(rs, "_find_db", return_value=tmp_path / "R.sqlite"), \
         patch.object(rs, "complete_in_reminders", side_effect=rs.SyncError("boom")):
        assert rs.main(["--sync", "--tasks-file", str(f)]) == 1
