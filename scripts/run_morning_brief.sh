#!/usr/bin/env bash
#
# Wrapper that refreshes OAuth tokens and runs morning_brief.py
# Code updates are handled separately by deploy.sh (runs at 7am).
#
# First-time setup:
#   1. Store your Anthropic key and iMessage target:
#        security add-generic-password -a "$USER" -s "morning-brief-anthropic-key" -w "sk-ant-..."
#        security add-generic-password -a "$USER" -s "morning-brief-imessage-target" -w "+15551234567"
#   2. Run OAuth setup to authorize Google Calendar & Gmail:
#        uv run oauth_setup.py
#   3. Schedule (see README for both cron entries):
#        0 7 * * 1-5 /path/to/deploy.sh
#        0 8 * * 1-5 /path/to/run_morning_brief.sh
#
set -euo pipefail

export PATH="/Users/andychiu/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$HOME/.morning_brief.log"

log()     { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
log_err() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" | tee -a "$LOG_FILE" >&2; }

# ── Failure trap ───────────────────────────────────────────────────────────────
# Runs on any unhandled error; sends iMessage if target is known.
IMESSAGE_TARGET=""

on_failure() {
    local exit_code=$?
    log_err "Script failed with exit code $exit_code"
    if [[ -n "$IMESSAGE_TARGET" ]]; then
        local msg="Morning brief failed (exit $exit_code). Check ~/.morning_brief.log"
        local escaped="${msg//\\/\\\\}"
        escaped="${escaped//\"/\\\"}"
        osascript -e "
        tell application \"Messages\"
            set targetService to 1st service whose service type = iMessage
            set targetBuddy to buddy \"$IMESSAGE_TARGET\" of targetService
            send \"$escaped\" to targetBuddy
        end tell
        " 2>/dev/null || true
    fi
}

trap on_failure ERR

log "Starting run_morning_brief.sh"

# Retrieve Anthropic API key
ANTHROPIC_API_KEY="$(security find-generic-password -a "$USER" -s "morning-brief-anthropic-key" -w 2>/dev/null)" || {
    log_err "Could not read 'morning-brief-anthropic-key' from Keychain."
    log_err "Run: security add-generic-password -a \"\$USER\" -s \"morning-brief-anthropic-key\" -w \"sk-ant-...\""
    exit 1
}

IMESSAGE_TARGET="$(security find-generic-password -a "$USER" -s "morning-brief-imessage-target" -w 2>/dev/null)" || {
    log_err "Could not read 'morning-brief-imessage-target' from Keychain."
    log_err "Run: security add-generic-password -a \"\$USER\" -s \"morning-brief-imessage-target\" -w \"+15551234567\""
    exit 1
}

export ANTHROPIC_API_KEY
export IMESSAGE_TARGET

# Refresh OAuth tokens before running
log "Refreshing OAuth tokens..."
uv run "$SCRIPT_DIR/shared/refresh_tokens.py" || {
    log_err "Token refresh failed. Re-run: uv run oauth_setup.py"
    exit 1
}

# Read fresh tokens from Keychain (shared/refresh_tokens.py just updated them)
GCAL_TOKEN="$(security find-generic-password -a "$USER" -s "morning-brief-gcal-token" -w 2>/dev/null)" || {
    log_err "No gcal token after refresh. Re-run: uv run oauth_setup.py"
    exit 1
}

GMAIL_TOKEN="$(security find-generic-password -a "$USER" -s "morning-brief-gmail-token" -w 2>/dev/null)" || {
    log_err "No gmail token after refresh. Re-run: uv run oauth_setup.py"
    exit 1
}

export GCAL_TOKEN
export GMAIL_TOKEN

log "Running morning_brief.py..."
exec uv run "$SCRIPT_DIR/morning_brief.py" "$@"
