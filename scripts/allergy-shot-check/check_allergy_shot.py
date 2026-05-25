#!/usr/bin/env python3
"""
check_allergy_shot.py — Reminder iMessage if no allergy shot is scheduled
in the next 30 days.

Reads tomorrow's calendar via the direct Google Calendar API (no MCP,
no LLM), matches event titles locally, sends an iMessage if nothing matches.

Called by check_allergy_shot.sh, which handles token refresh.
Exits 0 on success (whether or not a reminder was needed).
Exits 1 on configuration or API error.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Make `shared/` (in the scripts/ root) importable when run from this subdir.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from shared.google_api import list_calendar_events  # noqa: E402

GOOGLE_TOKEN = os.environ.get("GOOGLE_TOKEN", "")
IMESSAGE_TARGET = os.environ.get("IMESSAGE_TARGET", "")

# Match "allergy" / "allergy shot" but skip blood draws and consultations.
ALLERGY_RE = re.compile(r"\ballergy\b", re.IGNORECASE)
EXCLUDE_RE = re.compile(r"\b(blood\s*draw|consult(ation)?)\b", re.IGNORECASE)


def find_upcoming_shot(events: list[dict]) -> dict | None:
    for ev in events:
        title = ev.get("summary", "")
        if ALLERGY_RE.search(title) and not EXCLUDE_RE.search(title):
            return ev
    return None


def send_imessage(message: str, target: str) -> bool:
    escaped = message.replace("\\", "\\\\").replace('"', '\\"')
    script = f'''
    tell application "Messages"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy "{target}" of targetService
        send "{escaped}" to targetBuddy
    end tell
    '''
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return result.returncode == 0


def main() -> int:
    if not GOOGLE_TOKEN:
        print("ERROR: GOOGLE_TOKEN not set. Run oauth_setup.py and refresh tokens first.",
              file=sys.stderr)
        return 1

    today = date.today()
    cutoff = today + timedelta(days=30)

    start = datetime.combine(today, datetime.min.time()).astimezone()
    end = datetime.combine(cutoff, datetime.max.time()).astimezone()

    print(f"Checking calendar {today} → {cutoff} for allergy shot appointments...")
    try:
        events = list_calendar_events(GOOGLE_TOKEN, start.isoformat(), end.isoformat())
    except Exception as e:
        print(f"ERROR: Calendar fetch failed: {e}", file=sys.stderr)
        return 1

    shot = find_upcoming_shot(events)
    if shot:
        when = shot.get("start", "")
        print(f"FOUND: {shot.get('summary')} on {when} — no reminder needed.")
        return 0

    print("NOT_FOUND. Sending iMessage reminder...")
    day = datetime.now().strftime("%A")
    message = (
        f"Allergy Shot Reminder ({day})\n\n"
        "No allergy shot appointment in the next 30 days. Time to schedule one!\n\n"
        "Book at Stanford via MyHealth or call the clinic."
    )

    if not IMESSAGE_TARGET:
        print("No IMESSAGE_TARGET set — printing reminder:")
        print(message)
        return 0

    if send_imessage(message, IMESSAGE_TARGET):
        print("iMessage sent.")
        return 0

    print("iMessage send failed.", file=sys.stderr)
    subprocess.run([
        "osascript", "-e",
        'display notification "No allergy shot scheduled in 30 days. Book one!" '
        'with title "Allergy Shot Reminder" sound name "default"',
    ])
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
