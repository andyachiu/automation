#!/usr/bin/env bash
#
# run_aranet_alert_mac.command — Mac stand-in for the Pi's systemd service.
#
# ensure_aranet_alert_mac.sh opens this in Terminal. macOS only lets a process
# use Bluetooth when an app with Bluetooth permission (Terminal) is responsible
# for it, so launchd cannot run the watcher directly.
#
# Restarts the watcher 30 seconds after any exit. The first exit after a
# healthy run also sends an ntfy push, so a dying watcher isn't silent.
#
# Logs to: ~/.aranet_alert.log

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"
automation_setup_path

LOG_FILE="$HOME/.aranet_alert.log"
UV_BIN="${UV_BIN:-uv}"
SECURITY_BIN="${SECURITY_BIN:-security}"
KEYCHAIN_USER="$(automation_current_user)"
HEALTHY_SECONDS=300
export PYTHONUNBUFFERED=1

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }

keychain() { "$SECURITY_BIN" find-generic-password -a "$KEYCHAIN_USER" -s "$1" -w 2>/dev/null; }

notified=0
while true; do
  if ! NTFY_TOPIC="$(keychain aranet-alert-ntfy-topic)" || ! ARANET_SENSORS="$(keychain aranet-alert-sensors)"; then
    log "ERROR: Keychain items 'aranet-alert-ntfy-topic' and 'aranet-alert-sensors' are required. See aranet-alert/README.md."
  else
    export NTFY_TOPIC ARANET_SENSORS
    log "Starting watcher"
    started=$SECONDS
    caffeinate -i "$UV_BIN" run --project "$SCRIPT_DIR" --frozen --no-dev "$SCRIPT_DIR/aranet_alert.py" 2>&1 | tee -a "$LOG_FILE"
    status=${PIPESTATUS[0]}
    log "ERROR: Watcher exited with status $status; restarting in 30 seconds"

    # Notify once per failure burst: a crash loop shouldn't push every 30 seconds.
    if (( SECONDS - started >= HEALTHY_SECONDS )); then
      notified=0
    fi
    if (( notified == 0 )); then
      notified=1
      curl -fsS -m 15 -H "Title: Aranet watcher restarting" \
        -d "Mac watcher exited with status $status. See ~/.aranet_alert.log." \
        "${NTFY_SERVER:-https://ntfy.sh}/$NTFY_TOPIC" >/dev/null \
        || log "ERROR: Could not send restart notification"
    fi
  fi
  sleep 30
done
