#!/usr/bin/env python3
"""
ntfy_imessage_relay.py — Text the CO2 alerts that aranet_alert.py pushes.

Subscribes to the ntfy topic and sends an iMessage for every "CO2 high" alert,
so texts stay in sync with the push notifications whether the watcher runs on
this Mac or on the Pi. iMessage needs Messages, so this always runs on the Mac.

Exits non-zero when the stream ends or a send fails; launchd restarts it.

Logs to: ~/.aranet_relay.log
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.request
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_ROOT))

from shared.briefing_common import send_imessage  # noqa: E402

MAX_MESSAGE_CHARS = 1200
READ_TIMEOUT = 120  # ntfy sends a keepalive roughly every 45 seconds
ALERT_SUFFIX = ": CO2 high"

log = logging.getLogger("aranet_relay")


def load_targets(env: dict[str, str] = os.environ) -> list[str]:
    return [
        target.strip()
        for target in env.get("IMESSAGE_TARGETS", "").split(",")
        if target.strip()
    ]


def should_text(event: dict) -> bool:
    return event.get("event") == "message" and str(event.get("title", "")).endswith(
        ALERT_SUFFIX
    )


def format_text(event: dict) -> str:
    return f"{event.get('title', '')} — {event.get('message', '')}".strip(" —")


def relay(stream, recipients: list[str]) -> int:
    for raw in stream:
        line = raw.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            log.warning("Ignoring unparsable line: %s", line[:200])
            continue
        if not should_text(event):
            continue

        text = format_text(event)
        for recipient in recipients:
            if not send_imessage(
                text, recipient, max_message_chars=MAX_MESSAGE_CHARS, log=log
            ):
                log.error("iMessage send to %s failed", recipient)
                return 1
            log.info("Texted %s: %s", recipient, text)

    log.error("ntfy stream ended")
    return 1


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    env = os.environ
    topic = env.get("NTFY_TOPIC", "")
    recipients = load_targets(env)
    if not topic or not recipients:
        print(
            "ERROR: NTFY_TOPIC and IMESSAGE_TARGETS are required. See aranet-alert/README.md.",
            file=sys.stderr,
        )
        return 1

    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    # since=0s: start from now, so a restart never re-texts cached alerts.
    url = f"{server}/{topic}/json?since=0s"
    log.info("Relaying CO2 alerts to %s", ", ".join(recipients))
    with urllib.request.urlopen(url, timeout=READ_TIMEOUT) as stream:
        return relay(stream, recipients)


if __name__ == "__main__":
    raise SystemExit(main())
