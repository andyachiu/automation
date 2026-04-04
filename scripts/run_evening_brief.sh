#!/usr/bin/env bash
#
# Wrapper that refreshes OAuth tokens and runs evening_brief.py
#
# Scheduling (add to launchd — see plists/com.andychiu.automation.evening-brief.plist):
#   9 PM daily → run_evening_brief.sh
#
set -euo pipefail

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$HOME/.evening_brief.log"
UV_BIN="${UV_BIN:-uv}"
SECURITY_BIN="${SECURITY_BIN:-security}"
OSASCRIPT_BIN="${OSASCRIPT_BIN:-osascript}"

log()     { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
log_err() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" | tee -a "$LOG_FILE" >&2; }

# ── Failure trap ───────────────────────────────────────────────────────────────
IMESSAGE_TARGET=""

on_failure() {
    local exit_code=$?
    log_err "Script failed with exit code $exit_code"
    if [[ -n "$IMESSAGE_TARGET" ]]; then
        local msg="Evening brief failed (exit $exit_code). Check ~/.evening_brief.log"
        local escaped="${msg//\\/\\\\}"
        escaped="${escaped//\"/\\\"}"
        "$OSASCRIPT_BIN" -e "
        tell application \"Messages\"
            set targetService to 1st service whose service type = iMessage
            set targetBuddy to buddy \"$IMESSAGE_TARGET\" of targetService
            send \"$escaped\" to targetBuddy
        end tell
        " 2>/dev/null || true
    fi
}

trap on_failure ERR

log "Starting run_evening_brief.sh"

# Retrieve Anthropic API key
ANTHROPIC_API_KEY="$("$SECURITY_BIN" find-generic-password -a "$USER" -s "morning-brief-anthropic-key" -w 2>/dev/null)" || {
    log_err "Could not read 'morning-brief-anthropic-key' from Keychain."
    exit 1
}

IMESSAGE_TARGET="$("$SECURITY_BIN" find-generic-password -a "$USER" -s "morning-brief-imessage-target" -w 2>/dev/null)" || {
    log_err "Could not read 'morning-brief-imessage-target' from Keychain."
    exit 1
}

export ANTHROPIC_API_KEY
export IMESSAGE_TARGET

# Refresh OAuth tokens before running
log "Refreshing OAuth tokens..."
"$UV_BIN" run "$SCRIPT_DIR/shared/refresh_tokens.py" || {
    log_err "Token refresh failed. Re-run: uv run oauth_setup.py"
    exit 1
}

# Read fresh tokens from Keychain
GCAL_TOKEN="$("$SECURITY_BIN" find-generic-password -a "$USER" -s "morning-brief-gcal-token" -w 2>/dev/null)" || {
    log_err "No gcal token after refresh. Re-run: uv run oauth_setup.py"
    exit 1
}

GMAIL_TOKEN="$("$SECURITY_BIN" find-generic-password -a "$USER" -s "morning-brief-gmail-token" -w 2>/dev/null)" || {
    log_err "No gmail token after refresh. Re-run: uv run oauth_setup.py"
    exit 1
}

export GCAL_TOKEN
export GMAIL_TOKEN

run_brief() {
    "$UV_BIN" run "$SCRIPT_DIR/evening_brief.py" "$@"
}

log "Running evening_brief.py..."
trap - ERR
if run_brief "$@"; then
    exit 0
fi
trap on_failure ERR

log "evening_brief.py failed — retrying in 10 minutes..."
sleep 600

# Refresh tokens again before retry (they may have expired or been invalidated)
log "Refreshing OAuth tokens (retry)..."
"$UV_BIN" run "$SCRIPT_DIR/shared/refresh_tokens.py" || {
    log_err "Token refresh failed on retry. Re-run: uv run oauth_setup.py"
    exit 1
}

GCAL_TOKEN="$("$SECURITY_BIN" find-generic-password -a "$USER" -s "morning-brief-gcal-token" -w 2>/dev/null)" || {
    log_err "No gcal token after retry refresh."
    exit 1
}
GMAIL_TOKEN="$("$SECURITY_BIN" find-generic-password -a "$USER" -s "morning-brief-gmail-token" -w 2>/dev/null)" || {
    log_err "No gmail token after retry refresh."
    exit 1
}
export GCAL_TOKEN GMAIL_TOKEN

log "Running evening_brief.py (retry)..."
run_brief "$@"
