#!/usr/bin/env python3
"""
Preflight check — verify this project is configured to run on your local Mac.

Run with:
    uv run check_setup.py

Checks:
  - macOS platform (not a sandbox or container)
  - Required binaries (security, osascript, uv, git)
  - Required scripts and skill file
  - All Keychain entries present and non-empty
  - Anthropic API key format
  - Google OAuth client credentials (valid JSON)
  - Global skill symlink (if created)

Exit code 0 = all checks pass. Non-zero = one or more checks failed.
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from shared.system import current_user

SCRIPTS_DIR = Path(__file__).parent

KEYCHAIN_ENTRIES = {
    "morning-brief-anthropic-key": "Anthropic API key",
    "morning-brief-gcal-token": "Google Calendar access token",
    "morning-brief-gmail-token": "Gmail access token",
    "morning-brief-gcal-refresh-token": "Google Calendar refresh token",
    "morning-brief-gmail-refresh-token": "Gmail refresh token",
    "morning-brief-gcal-client": "Google Calendar OAuth client credentials",
    "morning-brief-gmail-client": "Gmail OAuth client credentials",
    "morning-brief-imessage-target": "iMessage delivery address",
}

REQUIRED_BINARIES = ["security", "osascript", "uv", "git"]

REQUIRED_SCRIPTS = [
    "morning_brief.py",
    "evening_brief.py",
    "run_morning_brief.sh",
    "run_evening_brief.sh",
    "deploy.sh",
    "install_launch_agents.py",
    "oauth_setup.py",
    "check_setup.py",
    "shared/refresh_tokens.py",
    "shared/reminders.py",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PASS = "[OK]"
_FAIL = "[FAIL]"
_WARN = "[WARN]"
_SKIP = "[SKIP]"


def ok(msg: str) -> None:
    print(f"  {_PASS} {msg}")


def fail(msg: str, hint: str = "") -> None:
    print(f"  {_FAIL} {msg}")
    if hint:
        for line in hint.splitlines():
            print(f"       {line}")


def warn(msg: str) -> None:
    print(f"  {_WARN} {msg}")


def skip(msg: str) -> None:
    print(f"  {_SKIP} {msg}")


def section(title: str) -> None:
    print(f"\n{title}")
    print("-" * len(title))


def keychain_get(service: str) -> str | None:
    result = subprocess.run(
        ["security", "find-generic-password", "-a", current_user(), "-s", service, "-w"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value if value else None


# ---------------------------------------------------------------------------
# Check functions — each returns True if passed, False if failed
# ---------------------------------------------------------------------------

def check_platform() -> bool:
    section("Platform")
    passed = True

    if sys.platform != "darwin":
        fail(
            f"Not running on macOS (platform={sys.platform!r}).",
            "This project requires macOS for Keychain and iMessage support.\n"
            "Do not run from a Linux sandbox, CI, or Claude Code container.",
        )
        passed = False
    else:
        ok(f"macOS detected ({platform.mac_ver()[0]})")

    if Path("/.dockerenv").exists():
        fail(
            "Running inside Docker.",
            "Keychain and osascript are unavailable in containers.\n"
            "Run scripts directly on your local Mac.",
        )
        passed = False
    else:
        ok("Not running in Docker")

    home = Path.home()
    if not str(home).startswith("/Users/"):
        fail(
            f"Home directory is {home} (expected /Users/<name>).",
            "This may be a sandboxed environment. Keychain access requires your real home.",
        )
        passed = False
    else:
        ok(f"Home directory: {home}")

    return passed


def check_binaries() -> bool:
    section("Required Binaries")
    passed = True

    for binary in REQUIRED_BINARIES:
        path = shutil.which(binary)
        if path:
            ok(f"{binary} ({path})")
        else:
            fail(
                f"{binary} not found in PATH.",
                f"Install it or ensure your PATH includes its location.\n"
                f"Current PATH: {os.environ.get('PATH', '(unset)')}",
            )
            passed = False

    # Verify security can actually access the Keychain
    if shutil.which("security"):
        result = subprocess.run(
            ["security", "list-keychains"], capture_output=True, text=True
        )
        keychain_output = result.stdout.lower() + result.stderr.lower()
        if result.returncode != 0 or "keychain" not in keychain_output:
            fail(
                "security binary exists but cannot list keychains.",
                "Keychain may be locked or unavailable in this environment.",
            )
            passed = False
        else:
            ok("Keychain is accessible")

    # Verify osascript works
    if shutil.which("osascript"):
        result = subprocess.run(
            ["osascript", "-e", "return 42"], capture_output=True, text=True
        )
        if result.returncode != 0 or result.stdout.strip() != "42":
            fail(
                "osascript is present but failed to execute.",
                "iMessage delivery requires a working AppleScript interpreter.",
            )
            passed = False
        else:
            ok("osascript works")

    return passed


def check_scripts() -> bool:
    section("Script Files")
    passed = True

    # Verify we're in the right project
    toml_path = SCRIPTS_DIR / "pyproject.toml"
    if toml_path.exists():
        with open(toml_path, "rb") as f:
            config = tomllib.load(f)
        name = config.get("project", {}).get("name")
        if name == "automation-scripts":
            ok(f"Correct project (automation-scripts) at {SCRIPTS_DIR}")
        else:
            fail(
                f"pyproject.toml project name is {name!r} (expected 'automation-scripts').",
                f"Wrong directory. Run from {SCRIPTS_DIR}.",
            )
            passed = False
    else:
        fail(f"pyproject.toml not found at {SCRIPTS_DIR}.", "Wrong directory?")
        passed = False

    for script in REQUIRED_SCRIPTS:
        path = SCRIPTS_DIR / script
        if path.exists():
            ok(script)
        else:
            fail(f"{script} not found at {path}.")
            passed = False

    # Skill file
    skill = SCRIPTS_DIR / ".claude" / "skills" / "morning-brief" / "SKILL.md"
    if skill.exists():
        ok(".claude/skills/morning-brief/SKILL.md")
    else:
        fail("Skill file missing: .claude/skills/morning-brief/SKILL.md")
        passed = False

    # Global symlink (optional)
    global_skill = Path.home() / ".claude" / "skills" / "morning-brief"
    skill_source = SCRIPTS_DIR / ".claude" / "skills" / "morning-brief"
    if global_skill.is_symlink():
        if global_skill.exists():
            ok(f"Global skill symlink valid (~/.claude/skills/morning-brief -> {os.readlink(global_skill)})")
        else:
            fail(
                f"Global skill symlink is broken: ~/.claude/skills/morning-brief -> {os.readlink(global_skill)}",
                f"Fix with:\n  ln -sf {skill_source} ~/.claude/skills/morning-brief",
            )
            passed = False
    else:
        warn(
            "Global skill symlink not created yet (skill only works inside this project dir).\n"
            "       To enable /morning-brief from any Claude Code session:\n"
            f"         ln -sf {skill_source} ~/.claude/skills/morning-brief"
        )

    return passed


def check_keychain() -> bool:
    section("Keychain Entries")

    if shutil.which("security") is None:
        fail("'security' binary not found — skipping Keychain checks.")
        return False

    passed = True

    for service, label in KEYCHAIN_ENTRIES.items():
        value = keychain_get(service)
        if value is None:
            fail(f"{label} ({service}) — missing or empty.", _keychain_hint(service))
            passed = False
        else:
            # Extra validation for specific entries
            if service == "morning-brief-anthropic-key" and not value.startswith("sk-ant-"):
                fail(
                    f"{label} exists but doesn't start with 'sk-ant-'.",
                    "Store the correct Anthropic API key in Keychain.",
                )
                passed = False
            elif service in ("morning-brief-gcal-client", "morning-brief-gmail-client"):
                try:
                    data = json.loads(value)
                    if "client_id" not in data or "client_secret" not in data:
                        raise ValueError("missing client_id or client_secret")
                    ok(f"{label} ({service}) — valid JSON with client_id and client_secret")
                except (json.JSONDecodeError, ValueError) as e:
                    fail(
                        f"{label} ({service}) — invalid JSON: {e}",
                        "Re-run oauth_setup.py to regenerate client credentials.",
                    )
                    passed = False
            else:
                ok(f"{label} ({service})")

    return passed


def _keychain_hint(service: str) -> str:
    hints = {
        "morning-brief-anthropic-key": (
            'security add-generic-password -a "$USER" -s "morning-brief-anthropic-key" -w "sk-ant-..."'
        ),
        "morning-brief-imessage-target": (
            'security add-generic-password -a "$USER" -s "morning-brief-imessage-target" -w "+15551234567"'
        ),
    }
    if service in hints:
        return f"Set with:\n  {hints[service]}"
    if "gcal" in service or "gmail" in service:
        return "Run: uv run oauth_setup.py"
    return "See README.md for setup instructions."


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("automation-scripts preflight check")
    print("===================================")

    results = [
        check_platform(),
        check_binaries(),
        check_scripts(),
        check_keychain(),
    ]

    passed = all(results)

    print()
    if passed:
        print("All checks passed. You're good to go.")
        print("  bash run_morning_brief.sh   # test the morning brief")
        print("  bash run_evening_brief.sh   # test the evening brief")
    else:
        print("Some checks failed. Fix the issues above before running the scripts.")
        print("See README.md and TROUBLESHOOTING.md for help.")

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
