#!/usr/bin/env python3
"""
Render launchd plist templates for the current machine.

Usage:
    uv run install_launch_agents.py
"""

from __future__ import annotations

import argparse
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
    return template_path.read_text().replace("{{HOME}}", str(Path.home())).replace(
        "{{SCRIPTS_DIR}}",
        str(SCRIPTS_DIR),
    ).replace(
        "{{PATH}}",
        build_launchd_path(),
    )


def install_templates(dest_dir: Path) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    for template in sorted(PLISTS_DIR.glob("*.plist.template")):
        rendered = render_template(template)
        dest_path = dest_dir / template.name.removesuffix(".template")
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
    args = parser.parse_args()

    written = install_templates(args.dest.expanduser())
    print(f"Installed {len(written)} launchd plist(s) to {args.dest.expanduser()}:")
    for path in written:
        print(f"  - {path}")

    print("\nLoad them with:")
    for path in written:
        print(f"  launchctl load {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
