#!/usr/bin/env bash
#
# deploy.sh — Pull latest code from GitHub main and sync dependencies.
#
# Run this on a separate schedule BEFORE run_morning_brief.sh so that code
# updates are applied cleanly without blocking the briefing on network issues.
#
# Recommended cron (weekdays):
#   0 7 * * 1-5 /path/to/deploy.sh
#   0 8 * * 1-5 /path/to/run_morning_brief.sh
#
# Logs to: ~/.morning_brief_deploy.log
# On failure: sends iMessage if 'morning-brief-imessage-target' is in Keychain.
#
set -euo pipefail

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$HOME/.morning_brief_deploy.log"
UV_BIN="${UV_BIN:-uv}"
GIT_BIN="${GIT_BIN:-git}"
SECURITY_BIN="${SECURITY_BIN:-security}"
OSASCRIPT_BIN="${OSASCRIPT_BIN:-osascript}"

log()     { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }
log_err() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >> "$LOG_FILE"; }

on_failure() {
    local exit_code=$?
    log_err "Deploy failed with exit code $exit_code"
    # Best-effort iMessage notification — skip silently if Keychain unavailable
    IMESSAGE_TARGET="$("$SECURITY_BIN" find-generic-password -a "$USER" -s "morning-brief-imessage-target" -w 2>/dev/null)" || return 0
    local msg="Morning brief deploy failed (exit $exit_code). Check ~/.morning_brief_deploy.log"
    local escaped="${msg//\\/\\\\}"
    escaped="${escaped//\"/\\\"}"
    "$OSASCRIPT_BIN" -e "
    tell application \"Messages\"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy \"$IMESSAGE_TARGET\" of targetService
        send \"$escaped\" to targetBuddy
    end tell
    " 2>/dev/null || true
}

trap on_failure ERR

log "Starting deploy"

"$GIT_BIN" -C "$SCRIPT_DIR" pull origin main >> "$LOG_FILE" 2>&1 || {
    log_err "git pull failed"
    exit 1
}

"$UV_BIN" --project "$SCRIPT_DIR" sync >> "$LOG_FILE" 2>&1 || {
    log_err "uv sync failed"
    exit 1
}

log "Deploy complete"
