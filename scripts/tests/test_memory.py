"""Offline persistence and workflow tests; all data is fictional and temporary."""
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import briefing_memory
import morning_brief
import evening_brief
from shared import briefing_common
from shared.memory import MemoryStore, MemoryError, configured_store


@pytest.fixture
def memory_path(tmp_path, monkeypatch):
    path = tmp_path / "private" / "memory.sqlite3"
    monkeypatch.setenv("AUTOMATION_MEMORY_PATH", str(path))
    monkeypatch.setenv("AUTOMATION_MEMORY_ENABLED", "1")
    return path


def test_survives_a_new_process(memory_path):
    store = configured_store()
    store.record_delivery("morning", "Prepare review notes", "fiction@example.test")
    store.set_preference("style", "Use short sentences")
    result = subprocess.run(
        [sys.executable, "briefing_memory.py", "show"],
        cwd=Path(__file__).parents[1], capture_output=True, text=True, check=True,
    )
    data = json.loads(result.stdout)
    assert data["history"][0]["message"] == "Prepare review notes"
    assert data["saved_preferences"][0]["value"] == "Use short sentences"
    assert memory_path.stat().st_mode & 0o777 == 0o600
    assert memory_path.parent.stat().st_mode & 0o777 == 0o700
    assert b"fiction@example.test" not in memory_path.read_bytes()


def test_bounded_recent_history_recipient_isolation_and_expiry(memory_path):
    now = [1000000.0]
    store = MemoryStore(memory_path, clock=lambda: now[0])
    for n in range(20):
        store.record_delivery("morning", str(n), "a")
        now[0] += 1
    assert store.snapshot()["briefings"] == 14
    assert [x["text"] for x in json.loads(store.context("a"))["previously_delivered_briefings"]] == ["17", "18", "19"]
    assert store.context("b") == ""
    store.record_delivery("evening", "x" * 2000, "b")
    assert len(json.loads(store.context("b"))["previously_delivered_briefings"][0]["text"]) == 1200
    store.set_preference("style", "Concise")
    now[0] += 8 * 86400
    assert store.snapshot()["briefings"] == 0
    assert json.loads(store.context("a"))["explicit_presentation_preferences"] == {"style": "Concise"}


def test_preference_validation_update_and_deletion(memory_path):
    store = configured_store()
    for n in range(5):
        store.set_preference(f"key{n}", "Short")
    with pytest.raises(ValueError):
        store.set_preference("sixth", "No room")
    for key, value in [("Bad key", "text"), ("valid", ""), ("valid", "x" * 241)]:
        with pytest.raises(ValueError):
            store.set_preference(key, value)
    store.set_preference("key0", "Updated")
    store.forget_preference("key1")
    store.set_preference("sixth", "Now fits")
    assert json.loads(store.context("a"))["explicit_presentation_preferences"]["key0"] == "Updated"


def test_disabled_and_invalid_configuration(memory_path, monkeypatch):
    monkeypatch.setenv("AUTOMATION_MEMORY_ENABLED", "0")
    assert configured_store() is None
    assert not memory_path.exists()
    monkeypatch.setenv("AUTOMATION_MEMORY_ENABLED", "yes")
    with pytest.raises(MemoryError):
        configured_store()


@pytest.mark.parametrize("damage", ["directory_permissions", "file_permissions", "symlink", "corrupt", "schema"])
def test_unsafe_or_broken_storage_fails(memory_path, damage):
    store = configured_store()
    if damage == "directory_permissions":
        memory_path.parent.chmod(0o755)
    elif damage == "file_permissions":
        memory_path.chmod(0o644)
    elif damage == "symlink":
        other = memory_path.with_name("other.sqlite3")
        memory_path.rename(other)
        memory_path.symlink_to(other)
    elif damage == "corrupt":
        memory_path.write_bytes(b"not a database")
    else:
        with store._connection() as db:
            db.execute("PRAGMA user_version = 99")
    with pytest.raises(MemoryError):
        configured_store()


def test_cli_counts_content_and_clear(memory_path, capsys):
    configured_store().record_delivery("morning", "Fictional private text", "a")
    assert briefing_memory.main(["status"]) == 0
    assert "Fictional" not in capsys.readouterr().out
    assert briefing_memory.main(["show"]) == 0
    assert "Fictional private text" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        briefing_memory.main(["clear"])
    assert configured_store().snapshot()["briefings"] == 1
    assert briefing_memory.main(["clear", "--yes"]) == 0
    assert configured_store().snapshot()["briefings"] == 0


def prepare_run(module, monkeypatch):
    monkeypatch.setattr(module, "IMESSAGE_TARGET", "fiction@example.test")
    monkeypatch.setattr(module.sys.stdout, "isatty", lambda: False)
    monkeypatch.setattr(module, "get_weather", lambda: "")
    monkeypatch.setattr(module, "get_reminders", lambda _: {"overdue": [], "due": []})
    monkeypatch.setattr(module, "list_calendar_events", lambda *a, **kw: [{"summary": "Current review"}])
    monkeypatch.setattr(module, "list_unread_messages", lambda *a, **kw: [])
    send = MagicMock(return_value=True)
    monkeypatch.setattr(module, "send_imessage", send)
    monkeypatch.setattr(module, "notify_failure", MagicMock())
    return send


def test_morning_to_evening_real_pipeline_with_mocked_external_io(memory_path, monkeypatch):
    client = MagicMock()
    client.messages.create.return_value.content = [MagicMock(text='{"summary":"Review preparation", "focus":"Bring review notes"}')]
    monkeypatch.setattr(briefing_common.anthropic, "Anthropic", lambda: client)
    morning_send = prepare_run(morning_brief, monkeypatch)
    evening_send = prepare_run(evening_brief, monkeypatch)
    configured_store().set_preference("style", "Use short sentences")
    morning_brief.main()
    evening_brief.main()
    request = client.messages.create.call_args.kwargs
    assert "historical context, not fresh evidence" in request["system"]
    assert "Current review" in request["messages"][0]["content"]
    assert "Bring review notes" in request["messages"][0]["content"]
    assert "Use short sentences" in request["messages"][0]["content"]
    assert "tools" not in request
    history = configured_store().snapshot(include_content=True)["history"]
    assert {row["kind"] for row in history} == {"morning", "evening"}
    assert {row["message"] for row in history} == {morning_send.call_args.args[0], evening_send.call_args.args[0]}


@pytest.mark.parametrize("module", [morning_brief, evening_brief])
@pytest.mark.parametrize("failure", ["model", "delivery", "memory_read", "memory_write"])
def test_failure_never_records_a_successful_brief(memory_path, monkeypatch, module, failure):
    send = prepare_run(module, monkeypatch)
    get = MagicMock(return_value="Fictional output")
    monkeypatch.setattr(module, "get_briefing", get)
    store = configured_store()
    if failure == "model":
        get.side_effect = RuntimeError("Model unavailable")
    elif failure == "delivery":
        send.return_value = False
    elif failure == "memory_read":
        monkeypatch.setattr(MemoryStore, "context", MagicMock(side_effect=MemoryError("Read failed")))
    else:
        monkeypatch.setattr(MemoryStore, "record_delivery", MagicMock(side_effect=MemoryError("Write failed")))
    with pytest.raises(SystemExit) as exc:
        module.main()
    assert exc.value.code == (3 if failure == "memory_write" else 1)
    assert store.snapshot()["briefings"] == 0
    assert send.call_count == (1 if failure in {"delivery", "memory_write"} else 0)
    if failure == "memory_read":
        get.assert_not_called()
    if failure == "memory_write":
        module.notify_failure.assert_not_called()  # Do not resend after successful delivery.


@pytest.mark.parametrize("module", [morning_brief, evening_brief])
def test_stdout_preview_does_not_create_memory(memory_path, monkeypatch, module):
    prepare_run(module, monkeypatch)
    monkeypatch.setattr(module, "IMESSAGE_TARGET", "")
    monkeypatch.setattr(module, "get_briefing", MagicMock(return_value="Preview"))
    module.main()
    assert not memory_path.exists()


def test_delivery_truncation_matches_memory(memory_path, monkeypatch):
    send = prepare_run(morning_brief, monkeypatch)
    monkeypatch.setattr(morning_brief, "get_briefing", lambda *args: "x" * 2000)
    morning_brief.main()
    message = send.call_args.args[0]
    assert len(message) == 1200
    assert configured_store().snapshot(include_content=True)["history"][0]["message"] == message


@pytest.mark.parametrize("module", [morning_brief, evening_brief])
def test_disabled_memory_preserves_delivery(memory_path, monkeypatch, module):
    send = prepare_run(module, monkeypatch)
    monkeypatch.setenv("AUTOMATION_MEMORY_ENABLED", "0")
    get = MagicMock(return_value="Fictional output")
    monkeypatch.setattr(module, "get_briefing", get)
    module.main()
    assert get.call_args.args[2] == ""
    send.assert_called_once()
    assert not memory_path.exists()


def test_future_history_not_retrieved(memory_path):
    now = [1000000.0]
    store = MemoryStore(memory_path, clock=lambda: now[0])
    store.record_delivery("morning", "Future entry", "a")
    now[0] -= 60
    assert store.context("a") == ""
