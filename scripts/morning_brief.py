#!/usr/bin/env python3
"""
morning_brief.py — Daily AI briefing sent to yourself via iMessage
"""

import json
import logging
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import anthropic

# ── Logging ───────────────────────────────────────────────────────────────────
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
IMESSAGE_TARGET = os.environ.get("IMESSAGE_TARGET", "")
GCAL_TOKEN = os.environ.get("GCAL_TOKEN", "")
GMAIL_TOKEN = os.environ.get("GMAIL_TOKEN", "")
MAX_MESSAGE_CHARS = 1200
MODEL = "claude-sonnet-4-6"

# ── Weather ───────────────────────────────────────────────────────────────────

def get_weather() -> str:
    """Fetch one-line weather summary from wttr.in. Returns empty string on failure."""
    try:
        req = urllib.request.Request(
            "https://wttr.in/?format=3&u",
            headers={"User-Agent": "morning-brief/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception as e:
        log.warning("Weather fetch failed: %s", e)
        return ""


# ── Prompt building ───────────────────────────────────────────────────────────

def is_monday() -> bool:
    return datetime.now().weekday() == 0


def build_user_prompt(weather: str) -> str:
    now = datetime.now()
    today = now.strftime("%A, %B %-d")
    today_iso = now.strftime("%Y-%m-%d")
    weather_line = f"\nCurrent weather: {weather}" if weather else ""
    week_section = (
        '\n  "week_preview": list of strings for Mon-Fri key events (Monday only)'
        if is_monday()
        else ""
    )
    monday_instruction = (
        "\n5. Since it's Monday, add a brief week-ahead section with key events Mon-Fri (2 lines max)."
        if is_monday()
        else ""
    )

    return f"""\
Today is {today} ({today_iso}).{weather_line}

Using my Google Calendar and Gmail (2 tool calls max — calendar first, then email):

1. List only today's events ({today_iso}, from midnight to 11:59 PM local time; time + title; flag anything back-to-back or needing prep). Do not include events from other days.
2. Check the 50 most recent unread emails in my inbox only (not sent, not search). \
Flag urgent ones meeting all of these criteria:
   - Addressed directly to you in the To: field (not CC or mailing list)
   - From a real person (not automated sender, newsletter, or notification)
   - Contains time-sensitive language: urgent, asap, today, deadline, reply, action required
   - Received in the last 24 hours and still unanswered
3. Close with one sentence: the #1 thing I should focus on today.{monday_instruction}

Return ONLY a valid JSON object with these keys:
  "summary": one-line overview (e.g. "3 meetings, 1 urgent email")
  "events": list of strings, one per event (e.g. ["9 AM: Standup", "2 PM: 1:1 (prep needed)"])
  "urgent_emails": list of strings, one per urgent email (empty list if none)
  "focus": one sentence, the #1 priority{week_section}

Return only valid JSON, no other text.
"""


SYSTEM_PROMPT = """\
You are a concise personal assistant writing a morning briefing delivered as an iMessage.
Return only a valid JSON object — no markdown, no preamble, no explanation, no surrounding text.
Be terse and factual. All string values must be plain text (no asterisks, no bullet symbols).
Use at most 2 tool calls: one to fetch today's calendar events, one to fetch recent emails. \
Do not make additional calls. Fetch all data first, then compose your response entirely from what you retrieved.
"""


# ── Claude call ───────────────────────────────────────────────────────────────

def get_briefing(weather: str) -> str:
    """Call Claude with MCP servers and return raw response text."""
    client = anthropic.Anthropic()

    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(weather)}],
        mcp_servers=[
            {
                "type": "url",
                "url": "https://gcal.mcp.claude.com/mcp",
                "name": "google-calendar",
                "authorization_token": GCAL_TOKEN,
            },
            {
                "type": "url",
                "url": "https://gmail.mcp.claude.com/mcp",
                "name": "gmail",
                "authorization_token": GMAIL_TOKEN,
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


# ── Format briefing ───────────────────────────────────────────────────────────

def format_briefing(raw: str, weather: str) -> str:
    """Parse JSON briefing and format as plain text. Falls back to raw text."""
    header_parts = [datetime.now().strftime("%a %b %-d")]
    if weather:
        header_parts.append(weather)
    header = " | ".join(header_parts)

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # Model sometimes prepends reasoning prose before the JSON block — try to extract it.
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            try:
                data = json.loads(raw[start:end])
                log.warning("Extracted JSON from mixed-content response")
            except (json.JSONDecodeError, ValueError):
                log.warning("Response was not valid JSON, using raw text")
                return f"{header}\n\n{raw}"
        else:
            log.warning("Response was not valid JSON, using raw text")
            return f"{header}\n\n{raw}"

    lines = [header, data.get("summary", "")]

    events = data.get("events", [])
    if events:
        lines.append("")
        lines.extend(events)

    week_preview = data.get("week_preview", [])
    if week_preview:
        lines.append("")
        lines.append("Week ahead:")
        lines.extend(week_preview)

    urgent = data.get("urgent_emails", [])
    if urgent:
        lines.append("")
        lines.append("Emails:")
        lines.extend(urgent)

    focus = data.get("focus", "")
    if focus:
        lines.append("")
        lines.append(f"Focus: {focus}")

    return "\n".join(lines)


# ── iMessage ──────────────────────────────────────────────────────────────────

def send_imessage(message: str, target: str) -> bool:
    if not target:
        log.warning("No IMESSAGE_TARGET set — printing to stdout")
        print(message)
        return True

    if len(message) > MAX_MESSAGE_CHARS:
        message = message[: MAX_MESSAGE_CHARS - 3] + "..."

    escaped = message.replace("\\", "\\\\").replace('"', '\\"')

    script = f'''
    tell application "Messages"
        set targetService to 1st service whose service type = iMessage
        set targetBuddy to buddy "{target}" of targetService
        send "{escaped}" to targetBuddy
    end tell
    '''

    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        log.error("AppleScript error: %s", result.stderr.strip())
        return False

    return True


def notify_failure(target: str, error: str) -> None:
    """Send a short failure notice via iMessage. Does nothing if no target."""
    if not target:
        return
    short = f"Morning brief failed: {error}"[:200]
    send_imessage(short, target)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log_file = Path.home() / ".morning_brief.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )

    log.info("Starting morning brief")
    target = IMESSAGE_TARGET

    weather = get_weather()
    if weather:
        log.info("Weather: %s", weather)

    try:
        raw = get_briefing(weather)
        log.info("Received briefing (%d chars raw)", len(raw))
    except Exception as e:
        log.error("API error: %s", e)
        notify_failure(target, str(e)[:100])
        sys.exit(1)

    message = format_briefing(raw, weather)
    log.info("Formatted briefing (%d chars)", len(message))

    success = send_imessage(message, target)
    if success:
        log.info("Briefing sent successfully")
    else:
        log.error("Failed to send briefing via iMessage")
        notify_failure(target, "iMessage send failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
