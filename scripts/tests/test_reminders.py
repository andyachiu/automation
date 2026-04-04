"""
Unit tests for shared/reminders.py and reminders integration in morning/evening briefs.

These tests are fully offline (all DB access is mocked).
Run with: uv run pytest tests/test_reminders.py -v
"""

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.reminders import CORE_DATA_EPOCH, _find_db, get_reminders
import morning_brief
import evening_brief


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_ts(dt: datetime) -> float:
    return dt.timestamp() - CORE_DATA_EPOCH


def _mock_db(rows: list[tuple], tmp_path: Path) -> Path:
    """Create a real SQLite DB with the expected schema and rows."""
    db_path = tmp_path / "Test.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE ZREMCDBASELIST (Z_PK INTEGER PRIMARY KEY, ZNAME VARCHAR)"
    )
    conn.execute(
        "CREATE TABLE ZREMCDREMINDER ("
        "Z_PK INTEGER PRIMARY KEY, ZTITLE VARCHAR, ZDUEDATE TIMESTAMP, "
        "ZFLAGGED INTEGER, ZPRIORITY INTEGER, ZCOMPLETED INTEGER, "
        "ZMARKEDFORDELETION INTEGER, ZLIST INTEGER)"
    )
    conn.execute("INSERT INTO ZREMCDBASELIST VALUES (1, 'Reminders')")
    conn.execute("INSERT INTO ZREMCDBASELIST VALUES (2, 'Groceries')")
    for i, (title, due_ts, list_pk, completed, deleted) in enumerate(rows, start=1):
        conn.execute(
            "INSERT INTO ZREMCDREMINDER VALUES (?, ?, ?, 0, 0, ?, ?, ?)",
            (i, title, due_ts, completed, deleted, list_pk),
        )
    conn.commit()
    conn.close()
    return db_path


# ── _find_db ─────────────────────────────────────────────────────────────────

class TestFindDb:
    def test_returns_none_when_dir_missing(self):
        with patch("shared.reminders.STORES_DIR", Path("/nonexistent")):
            assert _find_db() is None

    def test_picks_db_with_most_incomplete(self, tmp_path):
        # DB A: 1 incomplete reminder
        db_a = tmp_path / "A.sqlite"
        conn = sqlite3.connect(str(db_a))
        conn.execute("CREATE TABLE ZREMCDREMINDER (ZCOMPLETED INTEGER, ZMARKEDFORDELETION INTEGER)")
        conn.execute("INSERT INTO ZREMCDREMINDER VALUES (0, 0)")
        conn.commit()
        conn.close()

        # DB B: 3 incomplete reminders
        db_b = tmp_path / "B.sqlite"
        conn = sqlite3.connect(str(db_b))
        conn.execute("CREATE TABLE ZREMCDREMINDER (ZCOMPLETED INTEGER, ZMARKEDFORDELETION INTEGER)")
        for _ in range(3):
            conn.execute("INSERT INTO ZREMCDREMINDER VALUES (0, 0)")
        conn.commit()
        conn.close()

        with patch("shared.reminders.STORES_DIR", tmp_path):
            result = _find_db()
        assert result == db_b

    def test_skips_wal_and_shm_files(self, tmp_path):
        # Create a -wal file that looks like a sqlite file
        (tmp_path / "Data.sqlite-wal").touch()
        (tmp_path / "Data.sqlite-shm").touch()
        db = tmp_path / "Data.sqlite"
        conn = sqlite3.connect(str(db))
        conn.execute("CREATE TABLE ZREMCDREMINDER (ZCOMPLETED INTEGER, ZMARKEDFORDELETION INTEGER)")
        conn.execute("INSERT INTO ZREMCDREMINDER VALUES (0, 0)")
        conn.commit()
        conn.close()

        with patch("shared.reminders.STORES_DIR", tmp_path):
            result = _find_db()
        assert result == db


# ── get_reminders ────────────────────────────────────────────────────────────

class TestGetReminders:
    def test_returns_empty_when_no_db(self):
        with patch("shared.reminders._find_db", return_value=None):
            result = get_reminders(datetime.now())
        assert result == {"overdue": [], "due": []}

    def test_overdue_reminders(self, tmp_path):
        yesterday = datetime.now() - timedelta(days=1)
        rows = [
            ("Overdue task", _make_ts(yesterday), 1, 0, 0),
        ]
        db = _mock_db(rows, tmp_path)
        with patch("shared.reminders._find_db", return_value=db):
            result = get_reminders(datetime.now())
        assert result["overdue"] == ["Overdue task"]
        assert result["due"] == []

    def test_due_today(self, tmp_path):
        now = datetime.now()
        today_noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
        rows = [
            ("Today task", _make_ts(today_noon), 1, 0, 0),
        ]
        db = _mock_db(rows, tmp_path)
        with patch("shared.reminders._find_db", return_value=db):
            result = get_reminders(now)
        assert result["due"] == ["Today task"]
        assert result["overdue"] == []

    def test_due_tomorrow_for_evening(self, tmp_path):
        tomorrow = datetime.now() + timedelta(days=1)
        tomorrow_noon = tomorrow.replace(hour=12, minute=0, second=0, microsecond=0)
        rows = [
            ("Tomorrow task", _make_ts(tomorrow_noon), 1, 0, 0),
        ]
        db = _mock_db(rows, tmp_path)
        with patch("shared.reminders._find_db", return_value=db):
            result = get_reminders(tomorrow)
        assert result["due"] == ["Tomorrow task"]

    def test_excludes_completed_reminders(self, tmp_path):
        today_noon = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        rows = [
            ("Done task", _make_ts(today_noon), 1, 1, 0),  # completed
        ]
        db = _mock_db(rows, tmp_path)
        with patch("shared.reminders._find_db", return_value=db):
            result = get_reminders(datetime.now())
        assert result["overdue"] == []
        assert result["due"] == []

    def test_excludes_deleted_reminders(self, tmp_path):
        today_noon = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        rows = [
            ("Deleted task", _make_ts(today_noon), 1, 0, 1),  # marked for deletion
        ]
        db = _mock_db(rows, tmp_path)
        with patch("shared.reminders._find_db", return_value=db):
            result = get_reminders(datetime.now())
        assert result["overdue"] == []
        assert result["due"] == []

    def test_excludes_no_due_date(self, tmp_path):
        rows = [
            ("Undated task", None, 1, 0, 0),
        ]
        db = _mock_db(rows, tmp_path)
        with patch("shared.reminders._find_db", return_value=db):
            result = get_reminders(datetime.now())
        assert result["overdue"] == []
        assert result["due"] == []

    def test_excludes_future_reminders(self, tmp_path):
        future = datetime.now() + timedelta(days=7)
        rows = [
            ("Future task", _make_ts(future), 1, 0, 0),
        ]
        db = _mock_db(rows, tmp_path)
        with patch("shared.reminders._find_db", return_value=db):
            result = get_reminders(datetime.now())
        assert result["overdue"] == []
        assert result["due"] == []

    def test_non_default_list_shown_in_parens(self, tmp_path):
        today_noon = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        rows = [
            ("Buy milk", _make_ts(today_noon), 2, 0, 0),  # Groceries list
        ]
        db = _mock_db(rows, tmp_path)
        with patch("shared.reminders._find_db", return_value=db):
            result = get_reminders(datetime.now())
        assert result["due"] == ["Buy milk (Groceries)"]

    def test_include_overdue_false(self, tmp_path):
        yesterday = datetime.now() - timedelta(days=1)
        rows = [
            ("Overdue task", _make_ts(yesterday), 1, 0, 0),
        ]
        db = _mock_db(rows, tmp_path)
        with patch("shared.reminders._find_db", return_value=db):
            result = get_reminders(datetime.now(), include_overdue=False)
        assert result["overdue"] == []

    def test_mixed_overdue_and_due(self, tmp_path):
        yesterday = datetime.now() - timedelta(days=1)
        today_noon = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        rows = [
            ("Old task", _make_ts(yesterday), 1, 0, 0),
            ("Today task", _make_ts(today_noon), 1, 0, 0),
        ]
        db = _mock_db(rows, tmp_path)
        with patch("shared.reminders._find_db", return_value=db):
            result = get_reminders(datetime.now())
        assert result["overdue"] == ["Old task"]
        assert result["due"] == ["Today task"]

    def test_handles_db_read_error(self, tmp_path):
        bad_db = tmp_path / "bad.sqlite"
        bad_db.write_text("not a database")
        with patch("shared.reminders._find_db", return_value=bad_db):
            result = get_reminders(datetime.now())
        assert result == {"overdue": [], "due": []}


# ── Morning brief integration ───────────────────────────────────────────────

class TestMorningBriefReminders:
    def test_prompt_includes_reminders_context(self):
        ctx = "[OVERDUE] Pay bills\n[Due today] Call dentist"
        prompt = morning_brief.build_user_prompt("", ctx)
        assert "[OVERDUE] Pay bills" in prompt
        assert "[Due today] Call dentist" in prompt
        assert "do NOT use a tool call for these" in prompt
        assert '"reminders"' in prompt

    def test_prompt_no_reminders_key_when_empty(self):
        prompt = morning_brief.build_user_prompt("")
        assert '"reminders"' not in prompt
        assert "Apple Reminders" not in prompt

    def test_format_briefing_includes_reminders_section(self):
        data = {
            "summary": "1 reminder",
            "events": [],
            "urgent_emails": [],
            "email_highlights": [],
            "focus": "Handle reminders",
            "reminders": ["[OVERDUE] Pay bills", "Call dentist"],
        }
        result = morning_brief.format_briefing(json.dumps(data), "")
        assert "REMINDERS" in result
        assert "Pay bills" in result
        assert "Call dentist" in result

    def test_format_briefing_no_reminders_section_when_empty(self):
        data = {
            "summary": "quiet day",
            "events": [],
            "urgent_emails": [],
            "email_highlights": [],
            "focus": "Relax",
            "reminders": [],
        }
        result = morning_brief.format_briefing(json.dumps(data), "")
        assert "REMINDERS" not in result

    def test_format_briefing_no_reminders_key_ok(self):
        data = {
            "events": ["9 AM — Standup"],
            "urgent_emails": [],
            "email_highlights": [],
            "focus": "Ship it",
        }
        result = morning_brief.format_briefing(json.dumps(data), "")
        assert "REMINDERS" not in result
        assert "SCHEDULE" in result


# ── Evening brief integration ────────────────────────────────────────────────

class TestEveningBriefReminders:
    def test_prompt_includes_reminders_context(self):
        ctx = "[OVERDUE] Pay bills\n[Due tomorrow] Prep slides"
        prompt = evening_brief.build_user_prompt("", ctx)
        assert "[OVERDUE] Pay bills" in prompt
        assert "[Due tomorrow] Prep slides" in prompt
        assert "do NOT use a tool call for these" in prompt
        assert '"reminders"' in prompt

    def test_prompt_no_reminders_key_when_empty(self):
        prompt = evening_brief.build_user_prompt("")
        assert '"reminders"' not in prompt
        assert "Apple Reminders" not in prompt

    def test_format_briefing_includes_reminders_section(self):
        data = {
            "summary": "1 reminder",
            "tomorrow_events": [],
            "pending_replies": [],
            "email_highlights": [],
            "prep": "Review slides",
            "reminders": ["[OVERDUE] Pay bills", "Prep slides"],
        }
        result = evening_brief.format_briefing(json.dumps(data), "")
        assert "REMINDERS" in result
        assert "Pay bills" in result
        assert "Prep slides" in result

    def test_format_briefing_no_reminders_section_when_empty(self):
        data = {
            "summary": "quiet evening",
            "tomorrow_events": [],
            "pending_replies": [],
            "email_highlights": [],
            "prep": "Sleep",
            "reminders": [],
        }
        result = evening_brief.format_briefing(json.dumps(data), "")
        assert "REMINDERS" not in result

    def test_reminders_appear_before_prep(self):
        data = {
            "summary": "test",
            "tomorrow_events": [],
            "pending_replies": [],
            "email_highlights": [],
            "prep": "Do the thing",
            "reminders": ["Important task"],
        }
        result = evening_brief.format_briefing(json.dumps(data), "")
        rem_pos = result.index("REMINDERS")
        prep_pos = result.index("Tonight:")
        assert rem_pos < prep_pos
