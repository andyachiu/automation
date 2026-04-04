#!/usr/bin/env python3
"""
evening_brief.py — Evening look-ahead briefing sent via iMessage
"""

import json
import logging
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import anthropic

from shared.reminders import get_reminders

# ── Logging ───────────────────────────────────────────────────────────────────
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
IMESSAGE_TARGET = os.environ.get("IMESSAGE_TARGET", "")
GCAL_TOKEN = os.environ.get("GCAL_TOKEN", "")
GMAIL_TOKEN = os.environ.get("GMAIL_TOKEN", "")
MAX_MESSAGE_CHARS = 1200
MODEL = "claude-haiku-4-5-20251001"

# ── Weather ───────────────────────────────────────────────────────────────────

def get_weather() -> str:
    """Fetch one-line weather summary from wttr.in. Returns empty string on failure."""
    try:
        req = urllib.request.Request(
            "https://wttr.in/?format=3&u",
            headers={"User-Agent": "evening-brief/1.0"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception as e:
        log.warning("Weather fetch failed: %s", e)
        return ""


# ── Prompt building ───────────────────────────────────────────────────────────

def build_user_prompt(weather: str, reminders_ctx: str = "") -> str:
    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    tomorrow_label = tomorrow.strftime("%A, %B %-d")
    tomorrow_iso = tomorrow.strftime("%Y-%m-%d")
    weather_line = f"\nCurrent weather: {weather}" if weather else ""

    reminders_key = ""
    reminders_block = ""
    if reminders_ctx:
        reminders_key = '\n  "reminders": list of strings — copy from the reminders provided below (overdue first, then due tomorrow); empty list if none'
        reminders_block = f"\n\nApple Reminders (already fetched, do NOT use a tool call for these):\n{reminders_ctx}"

    return f"""\
Today is {now.strftime("%A, %B %-d")} ({now.strftime("%Y-%m-%d")}).{weather_line}
Tomorrow is {tomorrow_label} ({tomorrow_iso}).

Using my Google Calendar and Gmail (2 tool calls max — calendar first, then email):

1. List all events on {tomorrow_iso} (from midnight to 11:59 PM local time; format each as \
"TIME — TITLE"; flag anything back-to-back or needing prep in the title). Do not include events from other days.
2. Check the 50 most recent unread emails in my inbox (not sent, not search). Separate into two groups:
   PENDING REPLIES: directly addressed in To: (not CC/mailing list), from a real person, \
received today, unanswered, and requires a response (contains a question, request, or ask).
   HIGHLIGHTS: notable non-urgent items — substantive newsletters (VC/tech digests, news), \
shipping/order updates, anything worth a quick note. Skip promos and automated noise.
3. Close with one sentence: the single most important thing to prepare or do tonight.

Return ONLY a valid JSON object with these keys:
  "summary": one-line overview (e.g. "3 meetings tomorrow, 1 pending reply")
  "tomorrow_events": list of strings formatted as "TIME — TITLE" (e.g. ["9:00 AM — Standup", "2:00 PM — 1:1 (prep needed)"]); empty list if no events
  "pending_replies": list of strings formatted as "Sender: one-line summary" for emails needing a reply; empty list if none
  "email_highlights": list of strings formatted as "Sender: one-line summary" for notable non-urgent emails; empty list if nothing worth noting
  "prep": one sentence, the #1 thing to prepare or handle tonight{reminders_key}

Return only valid JSON, no other text.{reminders_block}
"""


SYSTEM_PROMPT = """\
You are a concise personal assistant writing an evening look-ahead briefing delivered as an iMessage.
Return only a valid JSON object. Do not include any text before or after the JSON object — \
no preamble, no explanation, no markdown, no code fences.
Be terse and factual. All string values must be plain text (no asterisks, no bullet symbols).
Use at most 2 tool calls: one to fetch tomorrow's calendar events, one to fetch recent emails. \
Do not make additional calls. Fetch all data first, then compose your response entirely from what you retrieved.
"""


# ── Claude call ───────────────────────────────────────────────────────────────

def get_briefing(weather: str, reminders_ctx: str = "") -> str:
    """Call Claude with MCP servers and return raw response text."""
    client = anthropic.Anthropic()

    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": build_user_prompt(weather, reminders_ctx)}],
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

def _try_append(lines: list[str], candidate: list[str]) -> bool:
    """Append candidate lines if they fit within MAX_MESSAGE_CHARS. Returns True if added."""
    if len("\n".join(lines + candidate)) <= MAX_MESSAGE_CHARS:
        lines.extend(candidate)
        return True
    return False


def format_briefing(raw: str, weather: str) -> str:
    """Parse JSON briefing and format as plain text with emoji sections. Falls back to raw text."""
    tomorrow = datetime.now() + timedelta(days=1)
    date_str = tomorrow.strftime("%a %b %-d")
    header = f"🌙 Tomorrow, {date_str} | {weather}" if weather else f"🌙 Tomorrow, {date_str}"

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
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

    lines: list[str] = [header]

    # Tomorrow's schedule
    events = data.get("tomorrow_events", [])
    sched = ["", "📅 TOMORROW"]
    sched += [f"• {e}" for e in events] if events else ["Nothing scheduled — enjoy the open day!"]
    if not _try_append(lines, sched):
        _try_append(lines, ["", "📅 TOMORROW"])
        for e in events:
            if not _try_append(lines, [f"• {e}"]):
                break

    # Pending replies — only shown if present
    pending = data.get("pending_replies", [])
    if pending:
        pending_sec = ["", "📬 PENDING REPLIES"] + [f"• {e}" for e in pending]
        if not _try_append(lines, pending_sec):
            if _try_append(lines, ["", "📬 PENDING REPLIES"]):
                for e in pending:
                    if not _try_append(lines, [f"• {e}"]):
                        break

    # Email highlights
    emails = data.get("email_highlights", [])
    email_sec = ["", "📧 HIGHLIGHTS"]
    email_sec += [f"• {e}" for e in emails] if emails else ["Inbox is quiet — nothing notable."]
    if not _try_append(lines, email_sec):
        if _try_append(lines, ["", "📧 HIGHLIGHTS"]):
            for e in emails:
                if not _try_append(lines, [f"• {e}"]):
                    break

    # Reminders
    reminders = data.get("reminders", [])
    if reminders:
        rem_sec = ["", "✅ REMINDERS"] + [f"• {r}" for r in reminders]
        if not _try_append(lines, rem_sec):
            if _try_append(lines, ["", "✅ REMINDERS"]):
                for r in reminders:
                    if not _try_append(lines, [f"• {r}"]):
                        break

    # Tonight's prep — lowest priority
    prep = data.get("prep", "")
    if prep:
        _try_append(lines, ["", f"Tonight: {prep}"])

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
    short = f"Evening brief failed: {error}"[:200]
    send_imessage(short, target)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log_file = Path.home() / ".evening_brief.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout),
        ],
    )

    log.info("Starting evening brief")
    target = IMESSAGE_TARGET

    weather = get_weather()
    if weather:
        log.info("Weather: %s", weather)

    tomorrow = datetime.now() + timedelta(days=1)
    reminders_data = get_reminders(tomorrow)
    reminders_lines = []
    for r in reminders_data["overdue"]:
        reminders_lines.append(f"[OVERDUE] {r}")
    for r in reminders_data["due"]:
        reminders_lines.append(f"[Due tomorrow] {r}")
    reminders_ctx = "\n".join(reminders_lines) if reminders_lines else ""
    if reminders_ctx:
        log.info("Reminders: %d overdue, %d due tomorrow", len(reminders_data["overdue"]), len(reminders_data["due"]))

    try:
        raw = get_briefing(weather, reminders_ctx)
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
