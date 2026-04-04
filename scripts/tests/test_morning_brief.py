"""
Unit tests for morning_brief.py — covers all new features:
  - get_weather()
  - is_monday()
  - build_user_prompt()
  - format_briefing()
  - send_imessage()
  - notify_failure()

These tests are fully offline (all network/subprocess calls are mocked).
Run with: uv run pytest tests/test_morning_brief.py -v
"""

import json
import logging
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# Silence morning_brief logging during tests
logging.getLogger("morning_brief").addHandler(logging.NullHandler())
logging.getLogger("morning_brief").propagate = False

sys.path.insert(0, str(Path(__file__).parent.parent))

import morning_brief


# ── get_weather ───────────────────────────────────────────────────────────────

class TestGetWeather:
    def _mock_urlopen(self, body: bytes):
        resp = MagicMock()
        resp.read.return_value = body
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def test_returns_weather_on_success(self):
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(b"San Francisco: Sunny +62F\n")):
            assert morning_brief.get_weather() == "San Francisco: Sunny +62F"

    def test_strips_trailing_whitespace(self):
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen(b"City: Rain\n\n")):
            assert morning_brief.get_weather() == "City: Rain"

    def test_returns_empty_on_url_error(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            assert morning_brief.get_weather() == ""

    def test_returns_empty_on_timeout(self):
        with patch("urllib.request.urlopen", side_effect=TimeoutError()):
            assert morning_brief.get_weather() == ""

    def test_returns_empty_on_generic_exception(self):
        with patch("urllib.request.urlopen", side_effect=OSError("no network")):
            assert morning_brief.get_weather() == ""


# ── is_monday ─────────────────────────────────────────────────────────────────

class TestIsMonday:
    def _patch_weekday(self, weekday: int):
        mock_now = MagicMock()
        mock_now.weekday.return_value = weekday
        return patch("morning_brief.datetime") , mock_now

    def test_true_on_monday(self):
        mock_now = MagicMock()
        mock_now.weekday.return_value = 0
        with patch("morning_brief.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            assert morning_brief.is_monday() is True

    @pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5, 6])
    def test_false_on_non_monday(self, weekday):
        mock_now = MagicMock()
        mock_now.weekday.return_value = weekday
        with patch("morning_brief.datetime") as mock_dt:
            mock_dt.now.return_value = mock_now
            assert morning_brief.is_monday() is False


# ── build_user_prompt ─────────────────────────────────────────────────────────

class TestBuildUserPrompt:
    def test_includes_weather_when_provided(self):
        with patch("morning_brief.is_monday", return_value=False), patch("morning_brief.is_weekend", return_value=False):
            prompt = morning_brief.build_user_prompt("City: 72F sunny")
        assert "City: 72F sunny" in prompt

    def test_no_weather_line_when_empty(self):
        with patch("morning_brief.is_monday", return_value=False), patch("morning_brief.is_weekend", return_value=False):
            prompt = morning_brief.build_user_prompt("")
        assert "Current weather:" not in prompt

    def test_monday_includes_week_preview_json_key(self):
        with patch("morning_brief.is_monday", return_value=True), patch("morning_brief.is_weekend", return_value=False):
            prompt = morning_brief.build_user_prompt("")
        assert "week_preview" in prompt

    def test_non_monday_no_week_preview_json_key(self):
        with patch("morning_brief.is_monday", return_value=False), patch("morning_brief.is_weekend", return_value=False):
            prompt = morning_brief.build_user_prompt("")
        assert "week_preview" not in prompt

    def test_monday_includes_week_ahead_instruction(self):
        with patch("morning_brief.is_monday", return_value=True), patch("morning_brief.is_weekend", return_value=False):
            prompt = morning_brief.build_user_prompt("")
        assert "Monday" in prompt or "week-ahead" in prompt or "Mon-Fri" in prompt

    def test_email_criteria_direct_recipient(self):
        with patch("morning_brief.is_monday", return_value=False), patch("morning_brief.is_weekend", return_value=False):
            prompt = morning_brief.build_user_prompt("")
        assert "To:" in prompt or "directly to you" in prompt

    def test_weekday_email_criteria_timeframe(self):
        with patch("morning_brief.is_monday", return_value=False), patch("morning_brief.is_weekend", return_value=False):
            prompt = morning_brief.build_user_prompt("")
        assert "24 hours" in prompt

    def test_weekend_prompt_uses_recent_emails_instead_of_unread_timeframe(self):
        with patch("morning_brief.is_monday", return_value=False), patch("morning_brief.is_weekend", return_value=True):
            prompt = morning_brief.build_user_prompt("")
        assert "20 most recent emails" in prompt
        assert "24 hours" not in prompt

    def test_email_criteria_excludes_newsletters(self):
        with patch("morning_brief.is_monday", return_value=False), patch("morning_brief.is_weekend", return_value=False):
            prompt = morning_brief.build_user_prompt("")
        assert "newsletter" in prompt or "mailing list" in prompt or "automated" in prompt

    def test_requests_json_output(self):
        with patch("morning_brief.is_monday", return_value=False), patch("morning_brief.is_weekend", return_value=False):
            prompt = morning_brief.build_user_prompt("")
        assert "JSON" in prompt

    def test_json_keys_documented(self):
        with patch("morning_brief.is_monday", return_value=False), patch("morning_brief.is_weekend", return_value=False):
            prompt = morning_brief.build_user_prompt("")
        for key in ("summary", "events", "urgent_emails", "email_highlights", "focus"):
            assert key in prompt


# ── format_briefing ───────────────────────────────────────────────────────────

SAMPLE_DATA = {
    "summary": "2 meetings, 1 urgent email",
    "events": ["9 AM: Standup", "2 PM: 1:1 (prep needed)"],
    "urgent_emails": ["Reply ASAP: budget approval from manager"],
    "email_highlights": [],
    "focus": "Finish chapter draft before 2 PM",
}


class TestFormatBriefing:
    def test_schedule_section_rendered(self):
        result = morning_brief.format_briefing(json.dumps(SAMPLE_DATA), "")
        assert "SCHEDULE" in result

    def test_events_rendered(self):
        result = morning_brief.format_briefing(json.dumps(SAMPLE_DATA), "")
        assert "9 AM: Standup" in result
        assert "2 PM: 1:1" in result

    def test_urgent_emails_rendered(self):
        result = morning_brief.format_briefing(json.dumps(SAMPLE_DATA), "")
        assert "URGENT" in result
        assert "budget approval" in result

    def test_focus_rendered(self):
        result = morning_brief.format_briefing(json.dumps(SAMPLE_DATA), "")
        assert "Focus:" in result
        assert "chapter draft" in result

    def test_weather_in_header(self):
        result = morning_brief.format_briefing(json.dumps(SAMPLE_DATA), "SF: 62F sunny")
        assert "SF: 62F sunny" in result

    def test_no_weather_in_header_when_empty(self):
        result = morning_brief.format_briefing(json.dumps(SAMPLE_DATA), "")
        assert " | " not in result  # no separator without weather

    def test_header_has_day_name(self):
        result = morning_brief.format_briefing(json.dumps(SAMPLE_DATA), "")
        day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        assert any(d in result for d in day_names)

    def test_week_preview_rendered(self):
        data = {**SAMPLE_DATA, "week_preview": ["Mon: Offsite", "Wed: Presentation"]}
        result = morning_brief.format_briefing(json.dumps(data), "")
        assert "WEEK AHEAD" in result
        assert "Mon: Offsite" in result
        assert "Wed: Presentation" in result

    def test_empty_week_preview_not_rendered(self):
        data = {**SAMPLE_DATA, "week_preview": []}
        result = morning_brief.format_briefing(json.dumps(data), "")
        assert "WEEK AHEAD" not in result

    def test_empty_urgent_section_skipped(self):
        data = {**SAMPLE_DATA, "urgent_emails": []}
        result = morning_brief.format_briefing(json.dumps(data), "")
        assert "URGENT" not in result

    def test_fallback_on_invalid_json(self):
        raw = "Plain text briefing from Claude"
        result = morning_brief.format_briefing(raw, "")
        assert "Plain text briefing from Claude" in result

    def test_fallback_still_includes_header(self):
        result = morning_brief.format_briefing("not json {{", "SF: 50F")
        assert "SF: 50F" in result

    def test_empty_focus_not_rendered(self):
        data = {**SAMPLE_DATA, "focus": ""}
        result = morning_brief.format_briefing(json.dumps(data), "")
        assert "Focus:" not in result

    def test_missing_optional_keys_dont_crash(self):
        result = morning_brief.format_briefing('{"summary": "quiet day"}', "")
        assert "SCHEDULE" in result


# ── send_imessage ─────────────────────────────────────────────────────────────

class TestSendImessage:
    def test_returns_true_on_success(self):
        with patch("subprocess.run", return_value=MagicMock(returncode=0)):
            assert morning_brief.send_imessage("Hello", "+15551234567") is True

    def test_returns_false_on_applescript_error(self):
        with patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="error")):
            assert morning_brief.send_imessage("Hello", "+15551234567") is False

    def test_prints_to_stdout_when_no_target(self, capsys):
        with patch("subprocess.run"):
            result = morning_brief.send_imessage("Hello world", "")
        assert result is True
        assert "Hello world" in capsys.readouterr().out

    def test_no_subprocess_call_when_no_target(self):
        with patch("subprocess.run") as mock_run:
            morning_brief.send_imessage("Hello", "")
        mock_run.assert_not_called()

    def test_truncates_to_max_chars(self):
        long_msg = "x" * 2000
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            morning_brief.send_imessage(long_msg, "+15551234567")

        script = calls[0][-1]
        assert "..." in script
        assert "x" * 2000 not in script

    def test_escapes_backslashes(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            morning_brief.send_imessage("path\\to\\file", "+15551234567")

        assert "\\\\" in calls[0][-1]

    def test_escapes_double_quotes(self):
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=fake_run):
            morning_brief.send_imessage('say "hello"', "+15551234567")

        assert '\\"' in calls[0][-1]

    def test_uses_osascript(self):
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            morning_brief.send_imessage("Hi", "+15551234567")
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "osascript"


# ── notify_failure ────────────────────────────────────────────────────────────

class TestNotifyFailure:
    def test_sends_message_containing_failed(self):
        with patch("morning_brief.send_imessage") as mock_send:
            morning_brief.notify_failure("+15551234567", "API timeout")
        mock_send.assert_called_once()
        msg = mock_send.call_args[0][0]
        assert "failed" in msg.lower()

    def test_includes_error_in_message(self):
        with patch("morning_brief.send_imessage") as mock_send:
            morning_brief.notify_failure("+15551234567", "token expired")
        msg = mock_send.call_args[0][0]
        assert "token expired" in msg

    def test_sends_to_correct_target(self):
        with patch("morning_brief.send_imessage") as mock_send:
            morning_brief.notify_failure("+15559998888", "error")
        assert mock_send.call_args[0][1] == "+15559998888"

    def test_noop_when_no_target(self):
        with patch("morning_brief.send_imessage") as mock_send:
            morning_brief.notify_failure("", "some error")
        mock_send.assert_not_called()

    def test_message_truncated_to_200_chars(self):
        with patch("morning_brief.send_imessage") as mock_send:
            morning_brief.notify_failure("+15551234567", "e" * 500)
        msg = mock_send.call_args[0][0]
        assert len(msg) <= 200
