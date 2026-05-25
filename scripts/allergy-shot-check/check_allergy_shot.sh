#!/usr/bin/env bash
# check_allergy_shot.sh
#
# Wrapper: refreshes OAuth tokens, then runs check_allergy_shot.py via uv.
# Runs Mon/Wed/Fri via launchd. Sends iMessage reminder if no allergy shot
# is scheduled in the next 30 days.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPTS_ROOT/lib/common.sh"
automation_setup_path

LOG_FILE="${SCRIPT_DIR}/allergy_shot_check.log"
UV_BIN="${UV_BIN:-uv}"
SECURITY_BIN="${SECURITY_BIN:-security}"
KEYCHAIN_USER="$(automation_current_user)"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "=== Allergy Shot Check Starting ==="

IMESSAGE_TARGET="$("$SECURITY_BIN" find-generic-password -a "$KEYCHAIN_USER" -s "morning-brief-imessage-target" -w 2>/dev/null)" || {
  log "ERROR: Could not read 'morning-brief-imessage-target' from Keychain."
  exit 1
}

export IMESSAGE_TARGET

# Refresh OAuth tokens (fail loud — never proceed on a stale token)
log "Refreshing OAuth tokens..."
"$UV_BIN" run --project "$SCRIPTS_ROOT" "$SCRIPTS_ROOT/shared/refresh_tokens.py" 2>&1 | tee -a "$LOG_FILE" || {
  log "ERROR: Token refresh failed. Re-run: uv run oauth_setup.py"
  exit 1
}

# Read fresh Google access token from Keychain
GOOGLE_TOKEN="$("$SECURITY_BIN" find-generic-password -a "$KEYCHAIN_USER" -s "morning-brief-google-token" -w 2>/dev/null)" || {
  log "ERROR: No google token. Run: uv run oauth_setup.py"
  exit 1
}
export GOOGLE_TOKEN

# Run calendar check
log "Running calendar check..."
"$UV_BIN" run --project "$SCRIPTS_ROOT" "$SCRIPT_DIR/check_allergy_shot.py" 2>&1 | tee -a "$LOG_FILE"

log "=== Allergy Shot Check Complete ==="
