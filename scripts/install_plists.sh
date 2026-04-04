#!/usr/bin/env bash
#
# install_plists.sh — Generate and install launchd plist files for this user.
#
# Usage:
#   cd /path/to/automation/scripts
#   bash install_plists.sh
#
# This replaces the placeholder paths in the plist templates with your actual
# $HOME and repo paths, then copies them to ~/Library/LaunchAgents/.
#
# After running, load each agent with:
#   launchctl load ~/Library/LaunchAgents/com.andychiu.automation.morning-brief.plist
#   launchctl load ~/Library/LaunchAgents/com.andychiu.automation.evening-brief.plist
#   launchctl load ~/Library/LaunchAgents/com.andychiu.automation.deploy.plist
#   launchctl load ~/Library/LaunchAgents/com.andychiu.allergy-shot-check.plist
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_DIR="$(cd "$SCRIPT_DIR/../plists" && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
PLACEHOLDER="/Users/andychiu"

mkdir -p "$LAUNCH_AGENTS"

installed=0

for src in "$PLIST_DIR"/*.plist; do
    name="$(basename "$src")"
    dest="$LAUNCH_AGENTS/$name"

    # Replace placeholder home path with actual $HOME and script dir
    sed \
        -e "s|${PLACEHOLDER}/Code/automation/scripts|${SCRIPT_DIR}|g" \
        -e "s|${PLACEHOLDER}|${HOME}|g" \
        "$src" > "$dest"

    echo "Installed: $dest"
    installed=$((installed + 1))
done

echo ""
echo "$installed plist(s) installed to $LAUNCH_AGENTS"
echo ""
echo "Load them with:"
for src in "$PLIST_DIR"/*.plist; do
    name="$(basename "$src" .plist)"
    echo "  launchctl load $LAUNCH_AGENTS/${name}.plist"
done
