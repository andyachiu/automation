"""
Tests for the ntfy -> iMessage relay for CO2 alerts.
"""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SCRIPTS_DIR / "aranet-alert"))

import ntfy_imessage_relay as relay_module  # noqa: E402


def _message(title: str, body: str = "1100 ppm (alert at 1000). Ventilate.") -> str:
    return f'{{"event": "message", "title": "{title}", "message": "{body}"}}'


class TestShouldText:
    def test_only_co2_high_messages_qualify(self):
        assert relay_module.should_text(
            {"event": "message", "title": "Master Bedroom: CO2 high"}
        )
        assert not relay_module.should_text(
            {"event": "message", "title": "Master Bedroom: CO2 back to normal"}
        )
        assert not relay_module.should_text(
            {"event": "message", "title": "Master Bedroom: sensor offline"}
        )
        assert not relay_module.should_text(
            {"event": "keepalive", "title": "Master Bedroom: CO2 high"}
        )
        assert not relay_module.should_text({"event": "open"})


class TestLoadTargets:
    def test_splits_and_trims(self):
        assert relay_module.load_targets(
            {"IMESSAGE_TARGETS": "+15551234567, a@b.com "}
        ) == [
            "+15551234567",
            "a@b.com",
        ]

    def test_missing_is_empty(self):
        assert relay_module.load_targets({}) == []


class TestRelay:
    def test_texts_every_recipient_once_per_alert(self, monkeypatch):
        sent = []
        monkeypatch.setattr(
            relay_module,
            "send_imessage",
            lambda text, target, **kwargs: sent.append((target, text)) or True,
        )
        stream = [
            '{"event": "open"}',
            '{"event": "keepalive"}',
            _message("Master Bedroom: CO2 high"),
            _message("Ethan Room: CO2 back to normal"),
        ]

        assert relay_module.relay(stream, ["+1555", "+1666"]) == 1  # stream ended
        assert sent == [
            (
                "+1555",
                "Master Bedroom: CO2 high — 1100 ppm (alert at 1000). Ventilate.",
            ),
            (
                "+1666",
                "Master Bedroom: CO2 high — 1100 ppm (alert at 1000). Ventilate.",
            ),
        ]

    def test_send_failure_exits_nonzero(self, monkeypatch):
        monkeypatch.setattr(
            relay_module, "send_imessage", lambda *args, **kwargs: False
        )

        assert (
            relay_module.relay([_message("Master Bedroom: CO2 high")], ["+1555"]) == 1
        )

    def test_unparsable_lines_are_skipped(self, monkeypatch):
        sent = []
        monkeypatch.setattr(
            relay_module,
            "send_imessage",
            lambda text, target, **kwargs: sent.append(target) or True,
        )

        assert (
            relay_module.relay(
                ["not json", "", _message("Office: CO2 high")], ["+1555"]
            )
            == 1
        )
        assert sent == ["+1555"]


class TestMain:
    def test_missing_config_fails_loud(self, monkeypatch, capsys):
        monkeypatch.setattr(relay_module.os, "environ", {"NTFY_TOPIC": "t"})

        assert relay_module.main() == 1
        assert "IMESSAGE_TARGETS" in capsys.readouterr().err
