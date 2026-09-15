#!/usr/bin/env bash
#
# ensure_aranet_alert_mac.sh — Keep the Mac Aranet watcher open in Terminal.
#
# Run by launchd at login and every 5 minutes. Opens run_aranet_alert_mac.command
# in a Terminal window unless it is already running.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCHER="$SCRIPT_DIR/run_aranet_alert_mac.command"

if pgrep -f "$LAUNCHER" >/dev/null; then
  exit 0
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Watcher not running; opening it in Terminal"
open -a Terminal "$LAUNCHER"
