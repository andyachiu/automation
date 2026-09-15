#!/usr/bin/env bash
# run_ntfy_imessage_relay.sh
#
# Wrapper: reads the ntfy topic and iMessage recipients from Keychain, then runs
# ntfy_imessage_relay.py via uv. launchd keeps it alive.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPTS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPTS_ROOT/lib/common.sh"
automation_setup_path

UV_BIN="${UV_BIN:-uv}"
SECURITY_BIN="${SECURITY_BIN:-security}"
KEYCHAIN_USER="$(automation_current_user)"

NTFY_TOPIC="$("$SECURITY_BIN" find-generic-password -a "$KEYCHAIN_USER" -s "aranet-alert-ntfy-topic" -w 2>/dev/null)" || {
  echo "ERROR: Keychain item 'aranet-alert-ntfy-topic' missing. See aranet-alert/README.md." >&2
  exit 1
}

IMESSAGE_TARGETS="$("$SECURITY_BIN" find-generic-password -a "$KEYCHAIN_USER" -s "aranet-alert-imessage-targets" -w 2>/dev/null)" || {
  echo "ERROR: Keychain item 'aranet-alert-imessage-targets' missing (comma-separated recipients)." >&2
  exit 1
}

export NTFY_TOPIC IMESSAGE_TARGETS

exec "$UV_BIN" run --project "$SCRIPTS_ROOT" "$SCRIPT_DIR/ntfy_imessage_relay.py"
