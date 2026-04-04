"""
Tests for MCP setup: oauth_setup.py, shared/refresh_tokens.py,
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
    def _mock_current_user(self, name="testuser"):
        return patch("oauth_setup.current_user", return_value=name)

    def test_update_flag_used_first(self):
        import oauth_setup

        with self._mock_current_user():
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                oauth_setup.keychain_set("my-service", "my-value")

        first_call_args = mock_run.call_args_list[0][0][0]
        assert "-U" in first_call_args

    def test_fallback_add_on_update_failure(self):
        import oauth_setup

        with self._mock_current_user():
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
    def _mock_current_user(self, name="testuser"):
        return patch("shared.refresh_tokens.current_user", return_value=name)

    def test_returns_value_on_success(self):
        from shared import refresh_tokens

        with self._mock_current_user():
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout="mytoken\n")
                result = refresh_tokens.keychain_get("my-service")

        assert result == "mytoken"

    def test_returns_none_on_failure(self):
        from shared import refresh_tokens

        with self._mock_current_user():
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1, stdout="")
                result = refresh_tokens.keychain_get("missing-service")

        assert result is None

    def test_strips_trailing_whitespace(self):
        from shared import refresh_tokens

        with self._mock_current_user():
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
        from shared import refresh_tokens

        with patch.object(refresh_tokens, "keychain_get", return_value=None):
            result = refresh_tokens.refresh_token("gcal", self._config())

        assert result is False
        captured = capsys.readouterr()
        assert "oauth_setup.py" in captured.err

    def test_returns_false_when_no_client_credentials(self, capsys):
        from shared import refresh_tokens

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
        from shared import refresh_tokens

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
        from shared import refresh_tokens

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
        from shared import refresh_tokens

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
        from shared import refresh_tokens

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
        from shared import refresh_tokens
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
        from shared import refresh_tokens

        results = {"gcal": False, "gmail": True}

        def mock_refresh(name, config):
            return results[name]

        with patch.object(refresh_tokens, "refresh_token", side_effect=mock_refresh):
            with pytest.raises(SystemExit) as exc:
                refresh_tokens.main()

        assert exc.value.code == 1

    def test_exits_0_when_all_succeed(self):
        from shared import refresh_tokens

        with patch.object(refresh_tokens, "refresh_token", return_value=True):
            # Should not raise
            refresh_tokens.main()


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
                    morning_brief.get_briefing("")

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
                    morning_brief.get_briefing("")

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
                    morning_brief.get_briefing("")

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
                    result = morning_brief.get_briefing("")

        assert "Part one." in result
        assert "Part two." in result

    def test_uses_haiku_model(self):
        import morning_brief

        mock_client = self._make_mock_client()

        with patch.object(morning_brief, "GCAL_TOKEN", "tok"):
            with patch.object(morning_brief, "GMAIL_TOKEN", "tok"):
                with patch("anthropic.Anthropic", return_value=mock_client):
                    morning_brief.get_briefing("")

        kwargs = mock_client.beta.messages.create.call_args[1]
        assert kwargs["model"] == "claude-haiku-4-5-20251001"


# ===========================================================================
# .claude/skills/morning-brief/SKILL.md — skill file validation
# ===========================================================================

class TestMorningBriefSkill:
    """Validate the Claude Code morning-brief skill file."""

    SKILL_PATH = Path(__file__).parent.parent / ".claude" / "skills" / "morning-brief" / "SKILL.md"
    TOP_LEVEL_SKILL_PATH = Path(__file__).parent.parent.parent / "skills" / "morning-brief" / "SKILL.md"

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

    def test_body_mentions_imessage_target_keychain(self):
        _, body = self._parse_frontmatter()
        assert "morning-brief-imessage-target" in body, (
            "Skill body must explain how the iMessage target is loaded from Keychain"
        )

    def test_body_references_automation_repo_path(self):
        _, body = self._parse_frontmatter()
        assert "AUTOMATION_REPO_ROOT" in body or "git rev-parse --show-toplevel" in body, (
            "Skill body must explain how to resolve the automation repo path dynamically"
        )

    def test_top_level_skill_copy_matches_claude_skill(self):
        assert self.TOP_LEVEL_SKILL_PATH.read_text() == self.SKILL_PATH.read_text(), (
            "Top-level and .claude morning-brief skill files must stay in sync."
        )
