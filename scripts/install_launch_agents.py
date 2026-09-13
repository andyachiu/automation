#!/usr/bin/env python3
"""
Render launchd plist templates for the current machine.

Usage:
    uv run install_launch_agents.py
"""

from __future__ import annotations

import argparse
import plistlib
import subprocess
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
PLISTS_DIR = REPO_ROOT / "plists"
DEFAULT_DEST = Path.home() / "Library" / "LaunchAgents"


def build_launchd_path() -> str:
    seen: set[str] = set()
    entries: list[str] = []

    for entry in [
        Path.home() / ".local" / "bin",
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
        Path("/usr/bin"),
        Path("/bin"),
        Path.home() / ".npm-global" / "bin",
    ]:
        value = str(entry)
        if value in seen:
            continue
        seen.add(value)
        entries.append(value)

    return ":".join(entries)


def render_template(template_path: Path) -> str:
    return (
        template_path.read_text()
        .replace("{{HOME}}", str(Path.home()))
        .replace(
            "{{SCRIPTS_DIR}}",
            str(SCRIPTS_DIR),
        )
        .replace(
            "{{PATH}}",
            build_launchd_path(),
        )
    )


def install_templates(dest_dir: Path, memory: str | None = None) -> list[Path]:
    if memory not in (None, "enabled", "disabled"):
        raise ValueError("memory must be enabled or disabled")
    dest_dir.mkdir(parents=True, exist_ok=True)
    pending: list[tuple[Path, str]] = []

    for template in sorted(PLISTS_DIR.glob("*.plist.template")):
        rendered = render_template(template)
        dest_path = dest_dir / template.name.removesuffix(".template")
        if dest_path.name in (
            "com.andychiu.automation.morning-brief.plist",
            "com.andychiu.automation.evening-brief.plist",
        ):
            value = "1"
            if memory is not None:
                value = "1" if memory == "enabled" else "0"
            elif dest_path.exists():
                existing = plistlib.loads(dest_path.read_bytes())
                value = existing.get("EnvironmentVariables", {}).get(
                    "AUTOMATION_MEMORY_ENABLED", "1"
                )
            if value not in ("0", "1"):
                raise ValueError(f"Invalid AUTOMATION_MEMORY_ENABLED in {dest_path}")
            settings = plistlib.loads(rendered.encode())
            settings.setdefault("EnvironmentVariables", {})["AUTOMATION_MEMORY_ENABLED"] = value
            rendered = plistlib.dumps(settings, sort_keys=False).decode()
        pending.append((dest_path, rendered))

    # Validate all existing settings before overwriting any installed files.
    written: list[Path] = []
    for dest_path, rendered in pending:
        dest_path.write_text(rendered)
        written.append(dest_path)

    return written


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render launchd plists for the current repo location and home directory.",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DEST,
        help="Directory to write rendered plists into (default: ~/Library/LaunchAgents).",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Automatically unload and reload the launchd agents.",
    )
    parser.add_argument(
        "--memory",
        choices=("enabled", "disabled"),
        help="Set memory for both briefings; omitted preserves destination settings (new installs: enabled).",
    )
    args = parser.parse_args()

    written = install_templates(args.dest.expanduser(), memory=args.memory)
    print(f"Installed {len(written)} launchd plist(s) to {args.dest.expanduser()}:")
    for path in written:
        print(f"  - {path}")

    if args.reload:
        failed = False
        print("\nReloading launchd agents...")
        for path in written:
            subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
            res = subprocess.run(
                ["launchctl", "load", str(path)], capture_output=True, text=True
            )
            if res.returncode == 0:
                print(f"  Reloaded {path.name}")
            else:
                failed = True
                print(f"  Failed to load {path.name}: {res.stderr.strip()}")
        if failed:
            return 1
    else:
        print("\nLoad them with:")
        for path in written:
            print(f"  launchctl load {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
