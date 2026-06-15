#!/usr/bin/env bash
#
# Wrapper that refreshes OAuth tokens and runs evening_brief.py
#
# Scheduling (add to launchd — see plists/com.andychiu.automation.evening-brief.plist):
#   9 PM daily → run_evening_brief.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"
automation_setup_path

LOG_FILE="$HOME/.evening_brief.log"
VENV_PY="${VENV_PY:-$SCRIPT_DIR/.venv/bin/python3}"
SECURITY_BIN="${SECURITY_BIN:-security}"
OSASCRIPT_BIN="${OSASCRIPT_BIN:-osascript}"
KEYCHAIN_USER="$(automation_current_user)"

if [[ -t 1 ]]; then
    log()     { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
    log_err() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" | tee -a "$LOG_FILE" >&2; }
else
    log()     { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }
    log_err() {
        local msg="[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*"
        echo "$msg" >> "$LOG_FILE"
        echo "$msg" >&2
    }
fi

# ── Failure trap ───────────────────────────────────────────────────────────────
IMESSAGE_TARGET=""

on_failure() {
    local exit_code="${1:-$?}"
    log_err "Script failed with exit code $exit_code"
    if [[ -n "$IMESSAGE_TARGET" ]]; then
        local last_err=""
        if [[ -f "$LOG_FILE" ]]; then
            last_err=$(grep "ERROR:" "$LOG_FILE" 2>/dev/null | tail -n 1 | sed 's/.*ERROR: //' || true)
        fi
        local msg
        if [[ -n "$last_err" ]]; then
            msg="Evening brief failed: $last_err"
        else
            msg="Evening brief failed (exit $exit_code). Check ~/.evening_brief.log"
        fi
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

on_exit() {
    local exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        on_failure "$exit_code"
    fi
}

trap on_exit EXIT

log "Starting run_evening_brief.sh"

if [[ ! -x "$VENV_PY" ]]; then
    log_err "Venv python missing or not executable: $VENV_PY"
    log_err "Run: (cd \"$SCRIPT_DIR\" && uv sync)"
    exit 1
fi
log "Using python: $(readlink -f "$VENV_PY")"

# Retrieve Anthropic API key
ANTHROPIC_API_KEY="$("$SECURITY_BIN" find-generic-password -a "$KEYCHAIN_USER" -s "morning-brief-anthropic-key" -w 2>/dev/null)" || {
    log_err "Could not read 'morning-brief-anthropic-key' from Keychain."
    exit 1
}

IMESSAGE_TARGET="$("$SECURITY_BIN" find-generic-password -a "$KEYCHAIN_USER" -s "morning-brief-imessage-target" -w 2>/dev/null)" || {
    log_err "Could not read 'morning-brief-imessage-target' from Keychain."
    exit 1
}

export ANTHROPIC_API_KEY
export IMESSAGE_TARGET

# Refresh OAuth tokens before running
log "Refreshing OAuth tokens..."
"$VENV_PY" "$SCRIPT_DIR/shared/refresh_tokens.py" || {
    log_err "Token refresh failed. Re-run: uv run oauth_setup.py"
    exit 1
}

# Read fresh Google access token from Keychain
GOOGLE_TOKEN="$("$SECURITY_BIN" find-generic-password -a "$KEYCHAIN_USER" -s "morning-brief-google-token" -w 2>/dev/null)" || {
    log_err "No google token after refresh. Re-run: uv run oauth_setup.py"
    exit 1
}

export GOOGLE_TOKEN

log "Running evening_brief.py..."
"$VENV_PY" "$SCRIPT_DIR/evening_brief.py" "$@"
