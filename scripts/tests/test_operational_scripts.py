"""
Regression tests for operational wrapper and setup scripts.
"""

import os
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import check_setup


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body)
    path.chmod(0o755)


class TestCheckSetup:
    def test_check_scripts_matches_current_repo_layout(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr(check_setup.Path, "home", classmethod(lambda cls: tmp_path))

        assert check_setup.check_scripts() is True

        output = capsys.readouterr().out
        assert "ask_claude.py" not in output
        assert "ask_claude.sh" not in output

    def test_main_success_message_references_current_entrypoints(self, monkeypatch, capsys):
        monkeypatch.setattr(check_setup, "check_platform", lambda: True)
        monkeypatch.setattr(check_setup, "check_binaries", lambda: True)
        monkeypatch.setattr(check_setup, "check_scripts", lambda: True)
        monkeypatch.setattr(check_setup, "check_keychain", lambda: True)

        assert check_setup.main() == 0

        output = capsys.readouterr().out
        assert "run_morning_brief.sh" in output
        assert "run_evening_brief.sh" in output
        assert "ask_claude.sh" not in output


class TestRunEveningBrief:
    def test_wrapper_notifies_on_brief_failure(self, tmp_path):
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        osascript_log = tmp_path / "osascript.log"
        uv_log = tmp_path / "uv.log"

        _write_executable(
            bin_dir / "security",
            """#!/bin/sh
service=""
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-s" ]; then
    service="$2"
    break
  fi
  shift
done
case "$service" in
  morning-brief-anthropic-key) printf '%s\\n' 'sk-ant-test' ;;
  morning-brief-imessage-target) printf '%s\\n' '+15550001111' ;;
  morning-brief-gcal-token) printf '%s\\n' 'gcal-token' ;;
  morning-brief-gmail-token) printf '%s\\n' 'gmail-token' ;;
  *) exit 1 ;;
esac
""",
        )
        _write_executable(
            bin_dir / "uv",
            """#!/bin/sh
printf '%s\\n' "$*" >> "$TEST_UV_LOG"
case "$*" in
  *shared/refresh_tokens.py*) exit 0 ;;
  *evening_brief.py*) exit 42 ;;
  *) exit 0 ;;
esac
""",
        )
        _write_executable(
            bin_dir / "osascript",
            """#!/bin/sh
printf '%s\\n' "$*" >> "$TEST_OSASCRIPT_LOG"
exit 0
""",
        )

        env = os.environ.copy()
        env["HOME"] = str(tmp_path)
        env["USER"] = "testuser"
        env["PATH"] = f"{bin_dir}:/usr/bin:/bin"
        env["TEST_OSASCRIPT_LOG"] = str(osascript_log)
        env["TEST_UV_LOG"] = str(uv_log)
        env["UV_BIN"] = str(bin_dir / "uv")
        env["SECURITY_BIN"] = str(bin_dir / "security")
        env["OSASCRIPT_BIN"] = str(bin_dir / "osascript")

        result = subprocess.run(
            ["/bin/bash", str(SCRIPTS_DIR / "run_evening_brief.sh")],
            cwd=SCRIPTS_DIR,
            env=env,
            capture_output=True,
            text=True,
        )

        assert result.returncode != 0
        assert "shared/refresh_tokens.py" in uv_log.read_text()
        assert "evening_brief.py" in uv_log.read_text()
        assert "Evening brief failed" in osascript_log.read_text()
        assert "Script failed with exit code" in (tmp_path / ".evening_brief.log").read_text()
