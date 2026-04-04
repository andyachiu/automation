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

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/lib/common.sh"
automation_setup_path

LOG_FILE="$HOME/.morning_brief_deploy.log"
UV_BIN="${UV_BIN:-uv}"
GIT_BIN="${GIT_BIN:-git}"
SECURITY_BIN="${SECURITY_BIN:-security}"
OSASCRIPT_BIN="${OSASCRIPT_BIN:-osascript}"
AUTOMATION_GIT_BRANCH="${AUTOMATION_GIT_BRANCH:-main}"
KEYCHAIN_USER="$(automation_current_user)"

log()     { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }
log_err() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >> "$LOG_FILE"; }

on_failure() {
    local exit_code=$?
    log_err "Deploy failed with exit code $exit_code"
    # Best-effort iMessage notification — skip silently if Keychain unavailable
    IMESSAGE_TARGET="$("$SECURITY_BIN" find-generic-password -a "$KEYCHAIN_USER" -s "morning-brief-imessage-target" -w 2>/dev/null)" || return 0
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

current_branch="$("$GIT_BIN" -C "$REPO_ROOT" branch --show-current)"
if [[ "$current_branch" != "$AUTOMATION_GIT_BRANCH" ]]; then
    log_err "Refusing deploy: current branch is '$current_branch', expected '$AUTOMATION_GIT_BRANCH'"
    exit 1
fi

if [[ -n "$("$GIT_BIN" -C "$REPO_ROOT" status --porcelain)" ]]; then
    log_err "Refusing deploy: repo has uncommitted changes"
    exit 1
fi

"$GIT_BIN" -C "$REPO_ROOT" fetch origin "$AUTOMATION_GIT_BRANCH" >> "$LOG_FILE" 2>&1 || {
    log_err "git fetch failed"
    exit 1
}

"$GIT_BIN" -C "$REPO_ROOT" merge --ff-only "origin/$AUTOMATION_GIT_BRANCH" >> "$LOG_FILE" 2>&1 || {
    log_err "fast-forward merge failed"
    exit 1
}

"$UV_BIN" --project "$SCRIPT_DIR" sync >> "$LOG_FILE" 2>&1 || {
    log_err "uv sync failed"
    exit 1
}

log "Deploy complete"
