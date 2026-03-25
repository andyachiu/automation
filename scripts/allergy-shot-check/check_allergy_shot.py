#!/usr/bin/env python3
"""
check_allergy_shot.py — Check for allergy shot appointments via Claude + Google Calendar MCP.

Called by check_allergy_shot.sh, which handles token refresh and Keychain reads.
Exits 0 if appointment found or reminder sent successfully.
Exits 1 on API error.
"""

import os
import subprocess
import sys
from datetime import date, timedelta

import anthropic

GCAL_TOKEN = os.environ.get("GCAL_TOKEN", "")
IMESSAGE_TARGET = os.environ.get("IMESSAGE_TARGET", "")


def build_prompt() -> str:
    today = date.today()
    cutoff = today + timedelta(days=30)
    return f"""\
Today is {today.strftime("%B %d, %Y")}. Search my Google Calendar for allergy shot appointments \
between today and {cutoff.strftime("%B %d, %Y")}.
Look for events matching 'allergy shot' or 'allergy' (exclude blood draws and consultations).

After searching, reply with ONLY one of these two formats — no other text:
  FOUND: [event summary] on [date]
  NOT_FOUND
"""


def check_calendar() -> str:
    client = anthropic.Anthropic()

    response = client.beta.messages.create(
        model="claude-haiku-4-5",
        max_tokens=1024,
        messages=[{"role": "user", "content": build_prompt()}],
        mcp_servers=[
            {
                "type": "url",
                "url": "https://gcal.mcp.claude.com/mcp",
                "name": "google-calendar",
                "authorization_token": GCAL_TOKEN,
            },
        ],
        betas=["mcp-client-2025-04-04"],
    )

    text_parts = [
        block.text
        for block in response.content
        if hasattr(block, "text") and block.text
    ]
    return "\n".join(text_parts).strip()


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


def main():
    if not GCAL_TOKEN:
        print("ERROR: GCAL_TOKEN not set. Run oauth_setup.py and refresh tokens first.", file=sys.stderr)
        sys.exit(1)

    print("Checking Google Calendar for allergy shot appointments...")
    try:
        result = check_calendar()
    except Exception as e:
        print(f"ERROR: API call failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Result: {result}")

    if "FOUND:" in result and "NOT_FOUND" not in result:
        print("Appointment found — no reminder needed.")
    elif "NOT_FOUND" in result:
        print("No appointment found. Sending iMessage reminder...")
        from datetime import datetime
        day = datetime.now().strftime("%A")
        message = (
            f"Allergy Shot Reminder ({day})\n\n"
            "No allergy shot appointment in the next 30 days. Time to schedule one!\n\n"
            "Book at Stanford via MyHealth or call the clinic."
        )
        if IMESSAGE_TARGET:
            if send_imessage(message, IMESSAGE_TARGET):
                print("iMessage sent.")
            else:
                print("iMessage send failed.", file=sys.stderr)
                subprocess.run([
                    "osascript", "-e",
                    'display notification "No allergy shot scheduled in 30 days. Book one!" '
                    'with title "Allergy Shot Reminder" sound name "default"'
                ])
        else:
            print("No IMESSAGE_TARGET set — printing reminder:")
            print(message)
    else:
        print(f"WARNING: Unexpected response from Claude: {result!r}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
