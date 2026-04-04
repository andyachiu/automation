"""
Tests for launchd plist rendering.
"""

from pathlib import Path

import install_launch_agents


class TestInstallLaunchAgents:
    def test_install_renders_repo_and_home_paths(self, tmp_path):
        written = install_launch_agents.install_templates(tmp_path)

        assert len(written) == 4

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
