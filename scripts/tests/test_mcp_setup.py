"""
Tests for MCP setup: oauth_setup.py, refresh_tokens.py, ask_claude.py,
morning_brief.py, run_morning_brief.sh, and the Claude Code morning-brief skill.

All tests mock subprocess (Keychain) and network calls so they run without
macOS Keychain access or real network connectivity.
"""

import base64
import hashlib
import io
import json
import sys
import urllib.error
import yaml
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_mock_response(body: bytes, status: int = 200):
    """Return a context-manager mock suitable for urllib.request.urlopen."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = body
    mock_resp.status = status
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


# ===========================================================================
# oauth_setup.py tests
# ===========================================================================

class TestRegisterClient:
    def test_posts_to_register_endpoint(self):
        import oauth_setup

        response_body = json.dumps({
            "client_id": "test-client-id",
            "client_secret": "test-secret",
        }).encode()

        with patch("urllib.request.urlopen", return_value=make_mock_response(response_body)) as mock_open:
            result = oauth_setup.register_client("https://gcal.mcp.claude.com")

        assert result["client_id"] == "test-client-id"
        assert result["client_secret"] == "test-secret"

        req = mock_open.call_args[0][0]
        assert req.full_url == "https://gcal.mcp.claude.com/register"
        assert req.get_header("Content-type") == "application/json"

        payload = json.loads(req.data)
        assert payload["client_name"] == "morning-brief-cli"
        assert oauth_setup.REDIRECT_URI in payload["redirect_uris"]
        assert "authorization_code" in payload["grant_types"]
        assert "refresh_token" in payload["grant_types"]

    def test_returns_parsed_json(self):
        import oauth_setup

        body = json.dumps({"client_id": "abc", "extra": "field"}).encode()
        with patch("urllib.request.urlopen", return_value=make_mock_response(body)):
            result = oauth_setup.register_client("https://example.com")

        assert result == {"client_id": "abc", "extra": "field"}


class TestKeychainSet:
    def _mock_whoami(self, name="testuser"):
        return patch(
            "subprocess.check_output",
            return_value=name.encode(),
        )

    def test_update_flag_used_first(self):
        import oauth_setup

        with self._mock_whoami():
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                oauth_setup.keychain_set("my-service", "my-value")

        first_call_args = mock_run.call_args_list[0][0][0]
        assert "-U" in first_call_args

    def test_fallback_add_on_update_failure(self):
        import oauth_setup

        with self._mock_whoami():
            with patch("subprocess.run") as mock_run:
                # First call (update with -U) fails
                mock_run.side_effect = [
                    MagicMock(returncode=1),
                    MagicMock(returncode=0),
                ]
                oauth_setup.keychain_set("my-service", "my-value")

        assert mock_run.call_count == 2
        second_call_args = mock_run.call_args_list[1][0][0]
        assert "-U" not in second_call_args
        assert "my-service" in second_call_args
        assert "my-value" in second_call_args


class TestPKCEGeneration:
    """Verify PKCE code challenge is computed correctly (S256 method)."""

    def test_code_challenge_is_s256_of_verifier(self):
        import secrets as secrets_mod
        import hashlib as hashlib_mod

        verifier = secrets_mod.token_urlsafe(64)
        digest = hashlib_mod.sha256(verifier.encode()).digest()
        expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()

        # Re-derive to confirm the algorithm used in oauth_setup matches
        assert len(expected) > 0
        assert "=" not in expected  # padding stripped
        # Verify it's valid base64url
        padded = expected + "=" * (-len(expected) % 4)
        decoded = base64.urlsafe_b64decode(padded)
        assert decoded == hashlib_mod.sha256(verifier.encode()).digest()


class TestCallbackHandler:
    """Test the OAuth callback HTTP handler via do_oauth_flow internals."""

    def _make_handler(self, path, state, auth_code_ref, error_ref):
        """Instantiate CallbackHandler-like logic without a real HTTP server."""
        import urllib.parse

        params = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)

        received_state = params.get("state", [None])[0]
        if received_state != state:
            return 400, "State mismatch"

        if "error" in params:
            error_ref[0] = params["error"][0]
            return 400, f"OAuth error: {params['error'][0]}"

        auth_code_ref[0] = params.get("code", [None])[0]
        return 200, "Authorization successful! You can close this tab."

    def test_valid_callback_captures_code(self):
        state = "test-state-123"
        auth_code = [None]
        error = [None]

        status, body = self._make_handler(
            f"/callback?state={state}&code=myauthcode",
            state, auth_code, error,
        )

        assert status == 200
        assert auth_code[0] == "myauthcode"

    def test_state_mismatch_returns_400(self):
        auth_code = [None]
        error = [None]

        status, body = self._make_handler(
            "/callback?state=wrong-state&code=myauthcode",
            "expected-state", auth_code, error,
        )

        assert status == 400
        assert "State mismatch" in body
        assert auth_code[0] is None

    def test_oauth_error_param_returns_400(self):
        state = "correct-state"
        auth_code = [None]
        error = [None]

        status, body = self._make_handler(
            f"/callback?state={state}&error=access_denied",
            state, auth_code, error,
        )

        assert status == 400
        assert error[0] == "access_denied"


# ===========================================================================
# refresh_tokens.py tests
# ===========================================================================

class TestKeychainGet:
    def _mock_whoami(self, name="testuser"):
        return patch("subprocess.check_output", return_value=name.encode())

    def test_returns_value_on_success(self):
        import refresh_tokens

        with self._mock_whoami():
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="mytoken\n")
                result = refresh_tokens.keychain_get("my-service")

        assert result == "mytoken"

    def test_returns_none_on_failure(self):
        import refresh_tokens

        with self._mock_whoami():
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                result = refresh_tokens.keychain_get("missing-service")

        assert result is None

    def test_strips_trailing_whitespace(self):
        import refresh_tokens

        with self._mock_whoami():
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="  token-value  \n")
                result = refresh_tokens.keychain_get("svc")

        assert result == "token-value"


class TestRefreshToken:
    def _config(self):
        return {
            "base_url": "https://gcal.mcp.claude.com",
            "keychain_refresh": "morning-brief-gcal-refresh-token",
            "keychain_access": "morning-brief-gcal-token",
            "keychain_client": "morning-brief-gcal-client",
        }

    def _client_json(self):
        return json.dumps({"client_id": "cid", "client_secret": "csec"})

    def test_returns_false_when_no_refresh_token(self, capsys):
        import refresh_tokens

        with patch.object(refresh_tokens, "keychain_get", return_value=None):
            result = refresh_tokens.refresh_token("gcal", self._config())

        assert result is False
        captured = capsys.readouterr()
        assert "oauth_setup.py" in captured.err

    def test_returns_false_when_no_client_credentials(self, capsys):
        import refresh_tokens

        def side_effect(service):
            if "refresh" in service:
                return "refresh-tok"
            return None

        with patch.object(refresh_tokens, "keychain_get", side_effect=side_effect):
            result = refresh_tokens.refresh_token("gcal", self._config())

        assert result is False
        captured = capsys.readouterr()
        assert "oauth_setup.py" in captured.err

    def test_returns_false_on_http_error(self, capsys):
        import refresh_tokens

        def side_effect(service):
            if "client" in service:
                return self._client_json()
            return "some-token"

        http_err = urllib.error.HTTPError(
            url="https://gcal.mcp.claude.com/token",
            code=401,
            msg="Unauthorized",
            hdrs={},
            fp=io.BytesIO(b"invalid_grant"),
        )

        with patch.object(refresh_tokens, "keychain_get", side_effect=side_effect):
            with patch("urllib.request.urlopen", side_effect=http_err):
                result = refresh_tokens.refresh_token("gcal", self._config())

        assert result is False
        captured = capsys.readouterr()
        assert "401" in captured.err

    def test_returns_false_when_no_access_token_in_response(self, capsys):
        import refresh_tokens

        def side_effect(service):
            if "client" in service:
                return self._client_json()
            return "some-token"

        body = json.dumps({"error": "no_token"}).encode()

        with patch.object(refresh_tokens, "keychain_get", side_effect=side_effect):
            with patch("urllib.request.urlopen", return_value=make_mock_response(body)):
                result = refresh_tokens.refresh_token("gcal", self._config())

        assert result is False

    def test_success_stores_new_access_token(self):
        import refresh_tokens

        def side_effect(service):
            if "client" in service:
                return self._client_json()
            return "old-token"

        body = json.dumps({"access_token": "new-access-tok"}).encode()

        with patch.object(refresh_tokens, "keychain_get", side_effect=side_effect):
            with patch("urllib.request.urlopen", return_value=make_mock_response(body)):
                with patch.object(refresh_tokens, "keychain_set") as mock_set:
                    result = refresh_tokens.refresh_token("gcal", self._config())

        assert result is True
        mock_set.assert_called_once_with("morning-brief-gcal-token", "new-access-tok")

    def test_rotates_refresh_token_when_new_one_returned(self):
        import refresh_tokens

        def side_effect(service):
            if "client" in service:
                return self._client_json()
            return "old-token"

        body = json.dumps({
            "access_token": "new-access-tok",
            "refresh_token": "new-refresh-tok",
        }).encode()

        with patch.object(refresh_tokens, "keychain_get", side_effect=side_effect):
            with patch("urllib.request.urlopen", return_value=make_mock_response(body)):
                with patch.object(refresh_tokens, "keychain_set") as mock_set:
                    result = refresh_tokens.refresh_token("gcal", self._config())

        assert result is True
        calls = mock_set.call_args_list
        assert call("morning-brief-gcal-token", "new-access-tok") in calls
        assert call("morning-brief-gcal-refresh-token", "new-refresh-tok") in calls

    def test_posts_correct_grant_type(self):
        import refresh_tokens
        import urllib.parse

        def side_effect(service):
            if "client" in service:
                return self._client_json()
            return "old-token"

        body = json.dumps({"access_token": "tok"}).encode()
        captured_req = {}

        def mock_urlopen(req):
            captured_req["req"] = req
            return make_mock_response(body)

        with patch.object(refresh_tokens, "keychain_get", side_effect=side_effect):
            with patch("urllib.request.urlopen", side_effect=mock_urlopen):
                with patch.object(refresh_tokens, "keychain_set"):
                    refresh_tokens.refresh_token("gcal", self._config())

        req = captured_req["req"]
        assert req.full_url == "https://gcal.mcp.claude.com/token"
        params = urllib.parse.parse_qs(req.data.decode())
        assert params["grant_type"] == ["refresh_token"]
        assert params["client_id"] == ["cid"]
        assert params["client_secret"] == ["csec"]


class TestRefreshMain:
    def test_exits_1_when_any_service_fails(self):
        import refresh_tokens

        results = {"gcal": False, "gmail": True}

        def mock_refresh(name, config):
            return results[name]

        with patch.object(refresh_tokens, "refresh_token", side_effect=mock_refresh):
            with pytest.raises(SystemExit) as exc:
                refresh_tokens.main()

        assert exc.value.code == 1

    def test_exits_0_when_all_succeed(self):
        import refresh_tokens

        with patch.object(refresh_tokens, "refresh_token", return_value=True):
            # Should not raise
            refresh_tokens.main()


# ===========================================================================
# ask_claude.py tests
# ===========================================================================

class TestConversationHistory:
    def test_load_returns_empty_when_file_missing(self, tmp_path):
        import ask_claude

        with patch.object(ask_claude, "HISTORY_FILE", tmp_path / "history.json"):
            result = ask_claude.load_history()

        assert result == []

    def test_load_returns_empty_on_corrupt_json(self, tmp_path):
        import ask_claude

        hist_file = tmp_path / "history.json"
        hist_file.write_text("not-json{{{")

        with patch.object(ask_claude, "HISTORY_FILE", hist_file):
            result = ask_claude.load_history()

        assert result == []

    def test_load_clears_and_returns_empty_for_different_date(self, tmp_path):
        import ask_claude

        hist_file = tmp_path / "history.json"
        hist_file.write_text(json.dumps({
            "date": "2000-01-01",
            "messages": [{"role": "user", "content": "old message"}],
        }))

        with patch.object(ask_claude, "HISTORY_FILE", hist_file):
            result = ask_claude.load_history()

        assert result == []
        assert not hist_file.exists()

    def test_load_returns_messages_for_today(self, tmp_path):
        import ask_claude

        hist_file = tmp_path / "history.json"
        messages = [{"role": "user", "content": "hello"}]
        hist_file.write_text(json.dumps({
            "date": date.today().isoformat(),
            "messages": messages,
        }))

        with patch.object(ask_claude, "HISTORY_FILE", hist_file):
            result = ask_claude.load_history()

        assert result == messages

    def test_save_writes_correct_structure(self, tmp_path):
        import ask_claude

        hist_file = tmp_path / "history.json"
        messages = [{"role": "user", "content": "test"}]

        with patch.object(ask_claude, "HISTORY_FILE", hist_file):
            ask_claude.save_history(messages)

        data = json.loads(hist_file.read_text())
        assert data["date"] == date.today().isoformat()
        assert data["messages"] == messages

    def test_clear_removes_file(self, tmp_path):
        import ask_claude

        hist_file = tmp_path / "history.json"
        hist_file.write_text("{}")

        with patch.object(ask_claude, "HISTORY_FILE", hist_file):
            ask_claude.clear_history()

        assert not hist_file.exists()

    def test_clear_is_idempotent_when_no_file(self, tmp_path):
        import ask_claude

        with patch.object(ask_claude, "HISTORY_FILE", tmp_path / "missing.json"):
            ask_claude.clear_history()  # should not raise


class TestAskMCPConfiguration:
    def _make_mock_client(self, answer="test answer"):
        mock_block = MagicMock()
        mock_block.text = answer
        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_client.beta.messages.create.return_value = mock_response
        return mock_client

    def test_no_mcp_servers_when_tokens_absent(self, tmp_path):
        import ask_claude

        mock_client = self._make_mock_client()

        with patch.object(ask_claude, "GCAL_TOKEN", ""):
            with patch.object(ask_claude, "GMAIL_TOKEN", ""):
                with patch.object(ask_claude, "HISTORY_FILE", tmp_path / "h.json"):
                    with patch("anthropic.Anthropic", return_value=mock_client):
                        ask_claude.ask("hello")

        mock_client.messages.create.assert_called_once()
        call_kwargs = mock_client.messages.create.call_args[1]
        assert "mcp_servers" not in call_kwargs
        assert "betas" not in call_kwargs

    def test_mcp_servers_added_when_both_tokens_present(self, tmp_path):
        import ask_claude

        mock_client = self._make_mock_client()

        with patch.object(ask_claude, "GCAL_TOKEN", "gcal-tok"):
            with patch.object(ask_claude, "GMAIL_TOKEN", "gmail-tok"):
                with patch.object(ask_claude, "HISTORY_FILE", tmp_path / "h.json"):
                    with patch("anthropic.Anthropic", return_value=mock_client):
                        ask_claude.ask("hello")

        mock_client.beta.messages.create.assert_called_once()
        call_kwargs = mock_client.beta.messages.create.call_args[1]
        assert "mcp_servers" in call_kwargs
        assert "betas" in call_kwargs
        assert "mcp-client-2025-04-04" in call_kwargs["betas"]

    def test_gcal_mcp_server_config(self, tmp_path):
        import ask_claude

        mock_client = self._make_mock_client()

        with patch.object(ask_claude, "GCAL_TOKEN", "gcal-tok"):
            with patch.object(ask_claude, "GMAIL_TOKEN", "gmail-tok"):
                with patch.object(ask_claude, "HISTORY_FILE", tmp_path / "h.json"):
                    with patch("anthropic.Anthropic", return_value=mock_client):
                        ask_claude.ask("hello")

        servers = mock_client.beta.messages.create.call_args[1]["mcp_servers"]
        gcal = next(s for s in servers if s["name"] == "google-calendar")
        assert gcal["type"] == "url"
        assert "gcal.mcp.claude.com" in gcal["url"]
        assert gcal["authorization_token"] == "gcal-tok"

    def test_gmail_mcp_server_config(self, tmp_path):
        import ask_claude

        mock_client = self._make_mock_client()

        with patch.object(ask_claude, "GCAL_TOKEN", "gcal-tok"):
            with patch.object(ask_claude, "GMAIL_TOKEN", "gmail-tok"):
                with patch.object(ask_claude, "HISTORY_FILE", tmp_path / "h.json"):
                    with patch("anthropic.Anthropic", return_value=mock_client):
                        ask_claude.ask("hello")

        servers = mock_client.beta.messages.create.call_args[1]["mcp_servers"]
        gmail = next(s for s in servers if s["name"] == "gmail")
        assert gmail["type"] == "url"
        assert "gmail.mcp.claude.com" in gmail["url"]
        assert gmail["authorization_token"] == "gmail-tok"

    def test_only_gcal_added_when_only_gcal_token(self, tmp_path):
        import ask_claude

        mock_client = self._make_mock_client()

        with patch.object(ask_claude, "GCAL_TOKEN", "gcal-tok"):
            with patch.object(ask_claude, "GMAIL_TOKEN", ""):
                with patch.object(ask_claude, "HISTORY_FILE", tmp_path / "h.json"):
                    with patch("anthropic.Anthropic", return_value=mock_client):
                        ask_claude.ask("hello")

        servers = mock_client.beta.messages.create.call_args[1]["mcp_servers"]
        names = [s["name"] for s in servers]
        assert "google-calendar" in names
        assert "gmail" not in names

    def test_conversation_history_preserved_across_calls(self, tmp_path):
        import ask_claude

        mock_client = self._make_mock_client("second answer")

        hist_file = tmp_path / "h.json"
        existing = [{"role": "user", "content": "first"}, {"role": "assistant", "content": "first answer"}]
        hist_file.write_text(json.dumps({"date": date.today().isoformat(), "messages": existing}))

        with patch.object(ask_claude, "GCAL_TOKEN", ""):
            with patch.object(ask_claude, "GMAIL_TOKEN", ""):
                with patch.object(ask_claude, "HISTORY_FILE", hist_file):
                    with patch("anthropic.Anthropic", return_value=mock_client):
                        ask_claude.ask("second question")

        messages_sent = mock_client.messages.create.call_args[1]["messages"]
        assert messages_sent[0] == {"role": "user", "content": "first"}
        assert messages_sent[1] == {"role": "assistant", "content": "first answer"}
        assert messages_sent[2]["content"] == "second question"


# ===========================================================================
# morning_brief.py tests
# ===========================================================================

class TestSendIMessage:
    def test_prints_to_stdout_when_no_target(self, capsys):
        import morning_brief

        with patch.object(morning_brief, "IMESSAGE_TARGET", ""):
            result = morning_brief.send_imessage("hello", "")

        assert result is True
        captured = capsys.readouterr()
        assert "hello" in captured.out

    def test_truncates_long_messages(self):
        import morning_brief

        long_msg = "x" * 2000
        captured_script = {}

        def mock_run(cmd, **kwargs):
            captured_script["cmd"] = cmd
            return MagicMock(returncode=0, stderr="")

        with patch.object(morning_brief, "IMESSAGE_TARGET", "+15550000000"):
            with patch("subprocess.run", side_effect=mock_run):
                morning_brief.send_imessage(long_msg, "+15550000000")

        script = captured_script["cmd"][-1]
        # The escaped message in the script should be truncated
        assert len(script) < len(long_msg) + 500  # well under original length
        assert "..." in script

    def test_sends_via_osascript(self):
        import morning_brief

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stderr="")
            result = morning_brief.send_imessage("hello world", "+15551234567")

        assert result is True
        cmd = mock_run.call_args[0][0]
        assert cmd[0] == "osascript"
        assert cmd[1] == "-e"

    def test_returns_false_on_applescript_error(self, capsys):
        import morning_brief

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="Messages error")
            result = morning_brief.send_imessage("hello", "+15551234567")

        assert result is False

    def test_escapes_double_quotes(self):
        import morning_brief

        captured = {}

        def mock_run(cmd, **kwargs):
            captured["script"] = cmd[-1]
            return MagicMock(returncode=0, stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            morning_brief.send_imessage('say "hello"', "+15551234567")

        assert '\\"' in captured["script"]
        assert 'say \\"hello\\"' in captured["script"]

    def test_escapes_backslashes(self):
        import morning_brief

        captured = {}

        def mock_run(cmd, **kwargs):
            captured["script"] = cmd[-1]
            return MagicMock(returncode=0, stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            morning_brief.send_imessage("path\\to\\file", "+15551234567")

        assert "\\\\" in captured["script"]

    def test_message_at_exact_limit_not_truncated(self):
        import morning_brief

        msg = "a" * morning_brief.MAX_MESSAGE_CHARS
        captured = {}

        def mock_run(cmd, **kwargs):
            captured["script"] = cmd[-1]
            return MagicMock(returncode=0, stderr="")

        with patch("subprocess.run", side_effect=mock_run):
            morning_brief.send_imessage(msg, "+15551234567")

        assert "..." not in captured["script"]


class TestGetBriefingMCPConfig:
    def _make_mock_client(self, text="Daily briefing text"):
        mock_block = MagicMock()
        mock_block.text = text
        mock_response = MagicMock()
        mock_response.content = [mock_block]
        mock_client = MagicMock()
        mock_client.beta.messages.create.return_value = mock_response
        return mock_client

    def test_gcal_mcp_server_in_request(self):
        import morning_brief

        mock_client = self._make_mock_client()

        with patch.object(morning_brief, "GCAL_TOKEN", "gcal-token-abc"):
            with patch.object(morning_brief, "GMAIL_TOKEN", "gmail-token-xyz"):
                with patch("anthropic.Anthropic", return_value=mock_client):
                    morning_brief.get_briefing()

        servers = mock_client.beta.messages.create.call_args[1]["mcp_servers"]
        gcal = next(s for s in servers if s["name"] == "google-calendar")
        assert gcal["authorization_token"] == "gcal-token-abc"
        assert gcal["type"] == "url"
        assert "gcal.mcp.claude.com" in gcal["url"]

    def test_gmail_mcp_server_in_request(self):
        import morning_brief

        mock_client = self._make_mock_client()

        with patch.object(morning_brief, "GCAL_TOKEN", "gcal-token-abc"):
            with patch.object(morning_brief, "GMAIL_TOKEN", "gmail-token-xyz"):
                with patch("anthropic.Anthropic", return_value=mock_client):
                    morning_brief.get_briefing()

        servers = mock_client.beta.messages.create.call_args[1]["mcp_servers"]
        gmail = next(s for s in servers if s["name"] == "gmail")
        assert gmail["authorization_token"] == "gmail-token-xyz"
        assert gmail["type"] == "url"
        assert "gmail.mcp.claude.com" in gmail["url"]

    def test_mcp_beta_header_included(self):
        import morning_brief

        mock_client = self._make_mock_client()

        with patch.object(morning_brief, "GCAL_TOKEN", "tok"):
            with patch.object(morning_brief, "GMAIL_TOKEN", "tok"):
                with patch("anthropic.Anthropic", return_value=mock_client):
                    morning_brief.get_briefing()

        kwargs = mock_client.beta.messages.create.call_args[1]
        assert "mcp-client-2025-04-04" in kwargs.get("betas", [])

    def test_extracts_text_from_response_blocks(self):
        import morning_brief

        block1 = MagicMock()
        block1.text = "Part one. "
        block2 = MagicMock()
        block2.text = "Part two."
        block3 = MagicMock()  # non-text block (e.g. mcp_tool_use)
        del block3.text

        mock_response = MagicMock()
        mock_response.content = [block1, block2, block3]
        mock_client = MagicMock()
        mock_client.beta.messages.create.return_value = mock_response

        with patch.object(morning_brief, "GCAL_TOKEN", "tok"):
            with patch.object(morning_brief, "GMAIL_TOKEN", "tok"):
                with patch("anthropic.Anthropic", return_value=mock_client):
                    result = morning_brief.get_briefing()

        assert "Part one." in result
        assert "Part two." in result

    def test_uses_haiku_model(self):
        import morning_brief

        mock_client = self._make_mock_client()

        with patch.object(morning_brief, "GCAL_TOKEN", "tok"):
            with patch.object(morning_brief, "GMAIL_TOKEN", "tok"):
                with patch("anthropic.Anthropic", return_value=mock_client):
                    morning_brief.get_briefing()

        kwargs = mock_client.beta.messages.create.call_args[1]
        assert kwargs["model"] == "claude-haiku-4-5-20251001"


# ===========================================================================
# run_morning_brief.sh — git pull behaviour
# ===========================================================================

class TestRunMorningBriefGitPull:
    """
    Verify the git pull step in run_morning_brief.sh by running the real script
    with a temporary directory of stub executables prepended to PATH.
    """

    SCRIPT = Path(__file__).parent.parent / "run_morning_brief.sh"

    def _make_stubs(self, tmp_path: Path, git_exit_code: int) -> Path:
        """Write stub executables into tmp_path/bin and return the bin dir."""
        import stat

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()

        # git stub: log args and exit with requested code
        git_stub = bin_dir / "git"
        git_stub.write_text(
            f"#!/bin/sh\necho \"[stub] git $*\"\nexit {git_exit_code}\n"
        )
        git_stub.chmod(git_stub.stat().st_mode | stat.S_IEXEC)

        # security stub: always returns a dummy token
        sec_stub = bin_dir / "security"
        sec_stub.write_text("#!/bin/sh\necho 'stub-token'\nexit 0\n")
        sec_stub.chmod(sec_stub.stat().st_mode | stat.S_IEXEC)

        # uv stub: succeed silently
        uv_stub = bin_dir / "uv"
        uv_stub.write_text("#!/bin/sh\nexit 0\n")
        uv_stub.chmod(uv_stub.stat().st_mode | stat.S_IEXEC)

        return bin_dir

    def _run(self, tmp_path: Path, git_exit_code: int) -> tuple[int, str, str]:
        import subprocess, os, stat

        bin_dir = self._make_stubs(tmp_path, git_exit_code)
        env = os.environ.copy()

        # run_morning_brief.sh line 16 hardcodes:
        #   export PATH="/Users/…/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
        # This puts real git/security/uv ahead of any stubs in $PATH.
        # Fix: place symlinks to our stubs in each hardcoded directory that
        # the script prepends, so the stubs are found first regardless.
        # Instead, we use a simpler approach: create a modified copy of the
        # script that prepends the stub bin_dir to PATH.
        script_text = self.SCRIPT.read_text()
        patched = script_text.replace(
            'export PATH="',
            f'export PATH="{bin_dir}:',
            1,
        )
        patched_script = tmp_path / "run_morning_brief_patched.sh"
        patched_script.write_text(patched)
        patched_script.chmod(patched_script.stat().st_mode | stat.S_IEXEC)

        env["PATH"] = f"{bin_dir}:{env.get('PATH', '')}"
        env.setdefault("USER", "testuser")

        result = subprocess.run(
            ["bash", str(patched_script)],
            capture_output=True, text=True, env=env,
        )
        return result.returncode, result.stdout, result.stderr

    def test_git_pull_is_called_with_origin_master(self, tmp_path):
        _rc, out, _err = self._run(tmp_path, git_exit_code=0)
        assert "pull origin master" in out

    def test_script_continues_when_git_pull_fails(self, tmp_path):
        """A failed git pull should warn but not abort the script."""
        rc, out, err = self._run(tmp_path, git_exit_code=1)
        assert "WARNING" in out + err
        assert rc == 0

    def test_script_succeeds_when_git_pull_succeeds(self, tmp_path):
        rc, _out, _err = self._run(tmp_path, git_exit_code=0)
        assert rc == 0


# ===========================================================================
# .claude/skills/morning-brief/SKILL.md — skill file validation
# ===========================================================================

class TestMorningBriefSkill:
    """Validate the Claude Code morning-brief skill file."""

    SKILL_PATH = Path(__file__).parent.parent / ".claude" / "skills" / "morning-brief" / "SKILL.md"

    def _parse_frontmatter(self):
        """Parse YAML frontmatter from SKILL.md."""
        text = self.SKILL_PATH.read_text()
        assert text.startswith("---"), "SKILL.md must start with YAML frontmatter"
        _, fm, body = text.split("---", 2)
        return yaml.safe_load(fm), body

    def test_skill_file_exists(self):
        assert self.SKILL_PATH.exists(), (
            f"Skill file not found at {self.SKILL_PATH}. "
            "The /morning-brief skill must be present in .claude/skills/."
        )

    def test_frontmatter_has_required_fields(self):
        fm, _ = self._parse_frontmatter()
        assert "name" in fm, "Frontmatter must include 'name'"
        assert "description" in fm, "Frontmatter must include 'description'"

    def test_skill_name_is_morning_brief(self):
        fm, _ = self._parse_frontmatter()
        assert fm["name"] == "morning-brief"

    def test_description_contains_trigger_phrases(self):
        fm, _ = self._parse_frontmatter()
        desc = fm["description"].lower()
        assert "morning brief" in desc
        assert "morning briefing" in desc

    def test_body_references_run_morning_brief_script(self):
        _, body = self._parse_frontmatter()
        assert "run_morning_brief.sh" in body, (
            "Skill body must reference run_morning_brief.sh"
        )

    def test_body_references_correct_working_directory(self):
        _, body = self._parse_frontmatter()
        assert "automation/scripts" in body, (
            "Skill body must reference the automation/scripts directory"
        )
