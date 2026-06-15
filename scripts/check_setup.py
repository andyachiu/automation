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

import getpass
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
    "morning-brief-google-token": "Google access token (Calendar + Gmail)",
    "morning-brief-google-refresh-token": "Google refresh token",
    "morning-brief-google-client": "Google OAuth client credentials",
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
        [
            "security",
            "find-generic-password",
            "-a",
            current_user(),
            "-s",
            service,
            "-w",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value if value else None


def keychain_set(service: str, value: str) -> None:
    user = current_user()
    result = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-a",
            user,
            "-s",
            service,
            "-w",
            value,
            "-U",
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        subprocess.run(
            [
                "security",
                "add-generic-password",
                "-a",
                user,
                "-s",
                service,
                "-w",
                value,
            ],
            check=True,
        )


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
            ok(
                f"Global skill symlink valid (~/.claude/skills/morning-brief -> {os.readlink(global_skill)})"
            )
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
    is_interactive = sys.stdin.isatty()

    for service, label in KEYCHAIN_ENTRIES.items():
        value = keychain_get(service)
        if value is None:
            if is_interactive:
                print(
                    f"  [MISSING] {label} ({service}) is not configured in your Keychain."
                )
                try:
                    choice = (
                        input("            Would you like to set it now? [y/N]: ")
                        .strip()
                        .lower()
                    )
                except (KeyboardInterrupt, EOFError):
                    choice = "n"
                if choice in ("y", "yes"):
                    if service == "morning-brief-imessage-target":
                        try:
                            new_val = input(
                                "            Enter iMessage target (phone or email): "
                            ).strip()
                        except (KeyboardInterrupt, EOFError):
                            new_val = ""
                    elif service == "morning-brief-google-client":
                        print(
                            '            Enter Google OAuth client JSON (e.g. {"client_id":"...", "client_secret":"..."}):'
                        )
                        try:
                            new_val = input("            JSON: ").strip()
                        except (KeyboardInterrupt, EOFError):
                            new_val = ""
                    else:
                        try:
                            new_val = getpass.getpass(
                                f"            Enter {label}: "
                            ).strip()
                        except (KeyboardInterrupt, EOFError):
                            new_val = ""

                    if new_val:
                        try:
                            keychain_set(service, new_val)
                            ok(f"Stored {label} in Keychain.")
                            value = new_val
                        except Exception as e:
                            fail(f"Failed to store {label}: {e}")
                            passed = False
                            continue
                    else:
                        fail(
                            f"{label} ({service}) — missing or empty.",
                            _keychain_hint(service),
                        )
                        passed = False
                        continue
                else:
                    fail(
                        f"{label} ({service}) — missing or empty.",
                        _keychain_hint(service),
                    )
                    passed = False
                    continue
            else:
                fail(
                    f"{label} ({service}) — missing or empty.", _keychain_hint(service)
                )
                passed = False

        if value is not None:
            # Extra validation for specific entries
            if service == "morning-brief-anthropic-key" and not value.startswith(
                "sk-ant-"
            ):
                fail(
                    f"{label} exists but doesn't start with 'sk-ant-'.",
                    "Store the correct Anthropic API key in Keychain.",
                )
                passed = False
            elif service == "morning-brief-google-client":
                try:
                    data = json.loads(value)
                    if "client_id" not in data or "client_secret" not in data:
                        raise ValueError("missing client_id or client_secret")
                    ok(
                        f"{label} ({service}) — valid JSON with client_id and client_secret"
                    )
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


def check_pmset_schedule() -> bool:
    section("macOS Wake Schedule")
    try:
        result = subprocess.run(
            ["pmset", "-g", "sched"], capture_output=True, text=True
        )
        if result.returncode != 0:
            warn("Could not read pmset schedule (pmset -g sched returned non-zero)")
            return True

        output = result.stdout
        repeating_lines = []
        in_repeating = False
        for line in output.splitlines():
            if "Repeating power events:" in line:
                in_repeating = True
                continue
            if "Scheduled power events:" in line:
                in_repeating = False
            if in_repeating and line.strip():
                repeating_lines.append(line.strip())

        if repeating_lines:
            ok(f"Found repeating wake events: {', '.join(repeating_lines)}")
            has_correct_time = any(
                "6:55" in line or "06:55" in line for line in repeating_lines
            )
            if not has_correct_time:
                warn(
                    "Repeating wake time is not set to 6:55 AM.\n"
                    "       Standard schedule requires Mac to wake at 6:55 AM (5 mins before 7:00 AM brief).\n"
                    "       Fix with:\n"
                    "         sudo pmset repeat wakeorpoweron MTWRFSU 06:55:00"
                )
        else:
            warn(
                "No repeating wake schedule found via pmset.\n"
                "       If your Mac is asleep, launchd scheduled briefs will not fire on time.\n"
                "       Fix with:\n"
                "         sudo pmset repeat wakeorpoweron MTWRFSU 06:55:00"
            )
    except Exception as e:
        warn(f"Failed to check pmset schedule: {e}")
    return True


def check_recent_runs() -> bool:
    section("Recent Run History")

    def get_last_run_status(log_path: Path, run_type: str) -> tuple[str, str]:
        if not log_path.exists():
            return "Never run", "No log file found."

        try:
            with open(log_path, "r", errors="replace") as f:
                lines = f.readlines()[-100:]

            start_time = None
            outcome = "Unknown"
            outcome_details = ""

            for line in reversed(lines):
                if "Briefing sent successfully" in line and outcome == "Unknown":
                    outcome = "Success"
                    outcome_details = line.strip()
                elif "Deploy complete" in line and outcome == "Unknown":
                    outcome = "Success"
                    outcome_details = line.strip()
                elif "ERROR" in line or "failed" in line.lower() or "failed" in line:
                    if outcome == "Unknown":
                        outcome = "Failure"
                        outcome_details = line.strip()

                if (
                    "Starting morning brief" in line
                    or "Starting run_morning_brief.sh" in line
                ) and run_type == "morning":
                    start_time = (
                        line.split("]")[0].strip("[ ")
                        if "]" in line
                        else line.split("INFO")[0].strip()
                    )
                    break
                if (
                    "Starting evening brief" in line
                    or "Starting run_evening_brief.sh" in line
                ) and run_type == "evening":
                    start_time = (
                        line.split("]")[0].strip("[ ")
                        if "]" in line
                        else line.split("INFO")[0].strip()
                    )
                    break
                if "Starting deploy" in line and run_type == "deploy":
                    start_time = (
                        line.split("]")[0].strip("[ ")
                        if "]" in line
                        else line.split("INFO")[0].strip()
                    )
                    break

            if not start_time:
                if lines:
                    return "Ran recently", f"Last log: {lines[-1].strip()}"
                return "Empty log", "Log file is empty."

            return f"Started {start_time}", f"{outcome} — {outcome_details}"
        except Exception as e:
            return "Error reading log", str(e)

    logs = [
        (Path.home() / ".morning_brief.log", "morning", "Morning Brief"),
        (Path.home() / ".evening_brief.log", "evening", "Evening Brief"),
        (Path.home() / ".morning_brief_deploy.log", "deploy", "Deploy Script"),
    ]

    for path, run_type, label in logs:
        time_str, status_str = get_last_run_status(path, run_type)
        if "Success" in status_str:
            ok(f"{label}: {time_str} -> {status_str}")
        elif "Failure" in status_str:
            warn(f"{label}: {time_str} -> {status_str}")
        else:
            print(f"  {label}: {time_str} -> {status_str}")

    return True


def main() -> int:
    print("automation-scripts preflight check")
    print("===================================")

    results = [
        check_platform(),
        check_binaries(),
        check_scripts(),
        check_keychain(),
    ]

    check_pmset_schedule()
    check_recent_runs()

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
