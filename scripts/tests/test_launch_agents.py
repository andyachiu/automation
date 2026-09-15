"""
Tests for launchd plist rendering.
"""

from pathlib import Path
import plistlib
from types import SimpleNamespace

import pytest

import install_launch_agents


class TestInstallLaunchAgents:
    def test_install_renders_repo_and_home_paths(self, tmp_path):
        written = install_launch_agents.install_templates(tmp_path)

        assert len(written) == 5

        morning_plist = tmp_path / "com.andychiu.automation.morning-brief.plist"
        body = morning_plist.read_text()

        assert morning_plist in written
        assert "{{" not in body
        assert str(install_launch_agents.SCRIPTS_DIR) in body
        assert str(Path.home()) in body

    def test_build_launchd_path_includes_standard_dirs(self):
        path_value = install_launch_agents.build_launchd_path()

        assert "/usr/bin" in path_value
        assert "/bin" in path_value
        assert "/usr/local/bin" in path_value

    def test_aranet_alert_agent_reopens_watcher_at_login_and_interval(self, tmp_path):
        install_launch_agents.install_templates(tmp_path)
        path = tmp_path / "com.andychiu.automation.aranet-alert.plist"
        data = plistlib.loads(path.read_bytes())

        assert data["RunAtLoad"] is True
        assert data["StartInterval"] == 300
        assert data["ProgramArguments"][1].endswith("aranet-alert/ensure_aranet_alert_mac.sh")

    def test_memory_setting_survives_reinstall_and_can_be_enabled(self, tmp_path):
        for choice, expected in [(None, "1"), ("disabled", "0"), (None, "0"), ("enabled", "1")]:
            written = install_launch_agents.install_templates(tmp_path, memory=choice)
            for path in written:
                data = plistlib.loads(path.read_bytes())
                env = data["EnvironmentVariables"]
                if path.name.endswith(("morning-brief.plist", "evening-brief.plist")):
                    assert env["AUTOMATION_MEMORY_ENABLED"] == expected
                    assert data["RunAtLoad"] is False
                else:
                    assert "AUTOMATION_MEMORY_ENABLED" not in env

    def test_invalid_saved_setting_does_not_overwrite_files(self, tmp_path):
        written = install_launch_agents.install_templates(tmp_path)
        path = tmp_path / "com.andychiu.automation.morning-brief.plist"
        data = plistlib.loads(path.read_bytes())
        data["EnvironmentVariables"]["AUTOMATION_MEMORY_ENABLED"] = "invalid"
        path.write_bytes(plistlib.dumps(data))
        before = {p: p.read_bytes() for p in written}
        with pytest.raises(ValueError, match="Invalid AUTOMATION_MEMORY_ENABLED"):
            install_launch_agents.install_templates(tmp_path)
        assert {p: p.read_bytes() for p in written} == before

    def test_reload_failure_returns_nonzero(self, tmp_path, monkeypatch):
        monkeypatch.setattr("sys.argv", ["install_launch_agents.py", "--dest", str(tmp_path), "--memory", "disabled", "--reload"])
        monkeypatch.setattr(
            install_launch_agents.subprocess, "run",
            lambda *args, **kwargs: SimpleNamespace(returncode=1, stderr="load failed"),
        )
        assert install_launch_agents.main() == 1
