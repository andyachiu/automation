#!/usr/bin/env bash
# check_allergy_shot.sh
#
# Wrapper: refreshes OAuth tokens, then runs check_allergy_shot.py via uv.
# Runs Mon/Wed/Fri via launchd. Sends iMessage reminder if no allergy shot
# is scheduled in the next 30 days.

set -euo pipefail

export PATH="/Users/andychiu/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_FILE="${SCRIPT_DIR}/allergy_shot_check.log"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

log "=== Allergy Shot Check Starting ==="

# Read credentials from Keychain
ANTHROPIC_API_KEY="$(security find-generic-password -a "$USER" -s "morning-brief-anthropic-key" -w 2>/dev/null)" || {
  log "ERROR: Could not read 'morning-brief-anthropic-key' from Keychain."
  exit 1
}

IMESSAGE_TARGET="$(security find-generic-password -a "$USER" -s "morning-brief-imessage-target" -w 2>/dev/null)" || {
  log "ERROR: Could not read 'morning-brief-imessage-target' from Keychain."
  exit 1
}

export ANTHROPIC_API_KEY IMESSAGE_TARGET

# Refresh OAuth tokens
log "Refreshing OAuth tokens..."
uv run --project "$SCRIPTS_ROOT" "$SCRIPTS_ROOT/shared/refresh_tokens.py" 2>&1 | tee -a "$LOG_FILE" || {
  log "WARNING: Token refresh failed, proceeding anyway (tokens may still be valid)"
}

# Read fresh token from Keychain
GCAL_TOKEN="$(security find-generic-password -a "$USER" -s "morning-brief-gcal-token" -w 2>/dev/null)" || {
  log "ERROR: No gcal token. Run: uv run oauth_setup.py"
  exit 1
}
export GCAL_TOKEN

# Run calendar check
log "Running Claude calendar check..."
uv run --project "$SCRIPTS_ROOT" "$SCRIPT_DIR/check_allergy_shot.py" 2>&1 | tee -a "$LOG_FILE"

log "=== Allergy Shot Check Complete ==="
