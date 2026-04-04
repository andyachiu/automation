"""
Environment validation tests — verify this project is running on the local macOS
machine with all prerequisites in place.

These tests check REAL system state: Keychain access, filesystem paths, and required
binaries. They will intentionally fail if run in a Claude Code sandbox, Docker
container, or any environment that lacks macOS Keychain / osascript access.

Run with:
    uv run pytest tests/test_environment.py -v

If any test fails, run check_setup.py for a human-readable diagnostic:
    uv run check_setup.py
"""

import os
import platform
import shutil
import subprocess
import sys
import tomllib
import getpass
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).parent.parent

REQUIRED_KEYCHAIN_ENTRIES = [
    "morning-brief-anthropic-key",
    "morning-brief-gcal-token",
    "morning-brief-gmail-token",
    "morning-brief-gcal-refresh-token",
    "morning-brief-gmail-refresh-token",
    "morning-brief-gcal-client",
    "morning-brief-gmail-client",
    "morning-brief-imessage-target",
]

REQUIRED_BINARIES = ["security", "osascript", "uv", "git"]

REQUIRED_SCRIPTS = [
    "morning_brief.py",
    "evening_brief.py",
    "run_morning_brief.sh",
    "run_evening_brief.sh",
    "deploy.sh",
    "install_launch_agents.py",
    "oauth_setup.py",
    "shared/refresh_tokens.py",
    "shared/reminders.py",
    "check_setup.py",
]


# ===========================================================================
# Platform checks
# ===========================================================================


class TestPlatform:
    def test_running_on_macos(self):
        assert sys.platform == "darwin", (
            f"This project requires macOS. Current platform: {sys.platform!r}.\n"
            "Do not run these scripts from a Linux container, CI environment, or "
            "Claude Code sandbox. Run them directly on your local Mac."
        )

    def test_not_in_docker_container(self):
        assert not Path("/.dockerenv").exists(), (
            "Running inside Docker — macOS Keychain and osascript are not available.\n"
            "Run scripts directly on your local Mac, not inside a container."
        )

    def test_home_is_under_users(self):
        home = Path.home()
        assert str(home).startswith("/Users/"), (
            f"Home directory is {home}, expected /Users/<name>.\n"
            "This may indicate a sandboxed or containerized environment where "
            "the real macOS Keychain is inaccessible."
        )

    def test_macos_version(self):
        ver = platform.mac_ver()[0]
        assert ver, "Could not determine macOS version — platform.mac_ver() returned empty."
        major = int(ver.split(".")[0])
        assert major >= 13, (
            f"macOS {ver} detected. This project requires macOS 13 (Ventura) or later "
            "for reliable Keychain and Messages app integration."
        )


# ===========================================================================
# Required binaries
# ===========================================================================


class TestRequiredBinaries:
    @pytest.mark.parametrize("binary", REQUIRED_BINARIES)
    def test_binary_is_in_path(self, binary):
        path = shutil.which(binary)
        assert path is not None, (
            f"'{binary}' not found in PATH.\n"
            f"Current PATH: {os.environ.get('PATH', '(unset)')}\n"
            "Ensure you're running on your local Mac with Homebrew and uv installed."
        )

    def test_security_is_real_macos_keychain_tool(self):
        """Ensure 'security' is the real macOS binary, not a stub or mock."""
        result = subprocess.run(
            ["security", "list-keychains"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            "The 'security' binary could not list keychains.\n"
            "Are you running in a sandboxed environment where Keychain is unavailable?"
        )
        assert ".keychain" in result.stdout or "login" in result.stdout, (
            "No real keychain found. The 'security' binary may be a stub or the "
            "environment does not have access to your macOS Keychain."
        )

    def test_osascript_can_run(self):
        """Verify osascript is the real AppleScript interpreter (needed for iMessage)."""
        result = subprocess.run(
            ["osascript", "-e", "return 42"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            "osascript failed to execute a trivial script.\n"
            "iMessage delivery requires a real macOS environment with the Messages app."
        )
        assert result.stdout.strip() == "42", (
            f"osascript returned unexpected output: {result.stdout.strip()!r}\n"
            "Expected '42'. The AppleScript interpreter may not be functioning correctly."
        )


# ===========================================================================
# Script paths
# ===========================================================================


class TestScriptPaths:
    def test_running_in_correct_project(self):
        toml_path = SCRIPTS_DIR / "pyproject.toml"
        assert toml_path.exists(), (
            f"pyproject.toml not found at {toml_path}.\n"
            f"Tests should be run from {SCRIPTS_DIR}."
        )
        with open(toml_path, "rb") as f:
            config = tomllib.load(f)
        name = config.get("project", {}).get("name")
        assert name == "automation-scripts", (
            f"pyproject.toml project name is {name!r}, expected 'automation-scripts'.\n"
            f"Wrong directory — run from {SCRIPTS_DIR}."
        )

    @pytest.mark.parametrize("script", REQUIRED_SCRIPTS)
    def test_required_script_exists(self, script):
        path = SCRIPTS_DIR / script
        assert path.exists(), (
            f"Required script not found: {path}\n"
            f"Ensure you have the full repo checked out at {SCRIPTS_DIR}."
        )

    def test_skill_file_exists(self):
        skill = SCRIPTS_DIR / ".claude" / "skills" / "morning-brief" / "SKILL.md"
        assert skill.exists(), (
            f"Skill file not found: {skill}\n"
            "The /morning-brief Claude Code skill is missing."
        )

    def test_global_skill_symlink_is_valid(self):
        """If the global skill symlink exists, verify it points to the right place."""
        global_skill = Path.home() / ".claude" / "skills" / "morning-brief"
        if not global_skill.exists() and not global_skill.is_symlink():
            pytest.skip("Global skill symlink not yet created — run setup step 7 in README.")
        assert global_skill.exists(), (
            f"~/.claude/skills/morning-brief symlink is broken: {global_skill} -> {os.readlink(global_skill)}\n"
            f"Fix with: ln -sf {SCRIPTS_DIR / '.claude' / 'skills' / 'morning-brief'} ~/.claude/skills/morning-brief"
        )
        assert (global_skill / "SKILL.md").exists(), (
            "Global skill symlink exists but SKILL.md is missing at the destination."
        )


# ===========================================================================
# Keychain entries
# ===========================================================================


def _keychain_get(service: str) -> str | None:
    """Return the Keychain value for service, or None if missing/empty."""
    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-a", os.environ.get("USER") or getpass.getuser(),
            "-s", service,
            "-w",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value if value else None


class TestKeychainEntries:
    @pytest.mark.parametrize("service", REQUIRED_KEYCHAIN_ENTRIES)
    def test_keychain_entry_exists(self, service):
        value = _keychain_get(service)
        assert value is not None, (
            f"Keychain entry '{service}' is missing or empty.\n\n"
            + _keychain_setup_hint(service)
        )

    def test_anthropic_key_looks_valid(self):
        value = _keychain_get("morning-brief-anthropic-key")
        if value is None:
            pytest.skip("Keychain entry missing — caught by test_keychain_entry_exists.")
        assert value.startswith("sk-ant-"), (
            f"Anthropic API key in Keychain doesn't start with 'sk-ant-' (got: {value[:12]}...).\n"
            "Store the correct key:\n"
            "  security add-generic-password -a \"$USER\" -s \"morning-brief-anthropic-key\" -w \"sk-ant-...\""
        )

    def test_gcal_client_is_valid_json(self):
        import json
        value = _keychain_get("morning-brief-gcal-client")
        if value is None:
            pytest.skip("Keychain entry missing — caught by test_keychain_entry_exists.")
        try:
            data = json.loads(value)
        except json.JSONDecodeError as e:
            pytest.fail(
                f"'morning-brief-gcal-client' in Keychain is not valid JSON: {e}\n"
                "Re-run oauth_setup.py to regenerate client credentials."
            )
        assert "client_id" in data, "morning-brief-gcal-client JSON missing 'client_id'."
        assert "client_secret" in data, "morning-brief-gcal-client JSON missing 'client_secret'."

    def test_gmail_client_is_valid_json(self):
        import json
        value = _keychain_get("morning-brief-gmail-client")
        if value is None:
            pytest.skip("Keychain entry missing — caught by test_keychain_entry_exists.")
        try:
            data = json.loads(value)
        except json.JSONDecodeError as e:
            pytest.fail(
                f"'morning-brief-gmail-client' in Keychain is not valid JSON: {e}\n"
                "Re-run oauth_setup.py to regenerate client credentials."
            )
        assert "client_id" in data, "morning-brief-gmail-client JSON missing 'client_id'."
        assert "client_secret" in data, "morning-brief-gmail-client JSON missing 'client_secret'."


def _keychain_setup_hint(service: str) -> str:
    hints = {
        "morning-brief-anthropic-key": (
            "Set it with:\n"
            "  security add-generic-password -a \"$USER\" -s \"morning-brief-anthropic-key\" -w \"sk-ant-...\""
        ),
        "morning-brief-imessage-target": (
            "Set it with:\n"
            "  security add-generic-password -a \"$USER\" -s \"morning-brief-imessage-target\" -w \"+15551234567\""
        ),
        "morning-brief-gcal-token": (
            "Run oauth_setup.py to authorize Google Calendar:\n  uv run oauth_setup.py"
        ),
        "morning-brief-gmail-token": (
            "Run oauth_setup.py to authorize Gmail:\n  uv run oauth_setup.py"
        ),
        "morning-brief-gcal-refresh-token": (
            "Run oauth_setup.py to authorize Google Calendar:\n  uv run oauth_setup.py"
        ),
        "morning-brief-gmail-refresh-token": (
            "Run oauth_setup.py to authorize Gmail:\n  uv run oauth_setup.py"
        ),
        "morning-brief-gcal-client": (
            "Run oauth_setup.py to register the OAuth client:\n  uv run oauth_setup.py"
        ),
        "morning-brief-gmail-client": (
            "Run oauth_setup.py to register the OAuth client:\n  uv run oauth_setup.py"
        ),
    }
    return hints.get(service, f"Run the setup steps in README.md for '{service}'.")
