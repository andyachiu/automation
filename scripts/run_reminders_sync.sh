#!/usr/bin/env bash
#
# Wrapper for reminders_sync.py, run hourly by launchd
# (plists/com.andychiu.automation.reminders-sync.plist.template).
# Posts a macOS notification if the sync fails.
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"
automation_setup_path

VENV_PY="${VENV_PY:-$SCRIPT_DIR/.venv/bin/python3}"
OSASCRIPT_BIN="${OSASCRIPT_BIN:-osascript}"
ERR_FILE="$(mktemp "${TMPDIR:-/tmp}/reminders-sync.XXXXXX")"
trap 'rm -f "$ERR_FILE"' EXIT

"$VENV_PY" "$SCRIPT_DIR/reminders_sync.py" --sync 2>"$ERR_FILE"
status=$?
cat "$ERR_FILE" >&2

if [[ $status -ne 0 ]]; then
    msg="$(grep -m1 'ERROR' "$ERR_FILE" | sed 's/^ERROR: //' | cut -c1-200)"
    msg="${msg:-exit $status — see ~/.reminders_sync.log}"
    msg="${msg//\\/\\\\}"; msg="${msg//\"/\\\"}"
    "$OSASCRIPT_BIN" -e "display notification \"$msg\" with title \"Reminders sync failed\"" 2>/dev/null || true
fi
exit $status
