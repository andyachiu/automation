#!/usr/bin/env python3
"""
evening_brief.py — Evening look-ahead briefing sent via iMessage
"""

import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from shared.briefing_common import (
    call_briefing_model,
    fetch_weather,
    parse_json_response,
)
from shared.briefing_common import send_imessage as _send_imessage
from shared.google_api import list_calendar_events, list_unread_messages
from shared.reminders import get_reminders

# ── Logging ───────────────────────────────────────────────────────────────────
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
IMESSAGE_TARGET = os.environ.get("IMESSAGE_TARGET", "")
GOOGLE_TOKEN = os.environ.get("GOOGLE_TOKEN", "")
MAX_MESSAGE_CHARS = 1200
MODEL = "claude-haiku-4-5-20251001"

# ── Weather ───────────────────────────────────────────────────────────────────


def get_weather() -> str:
    """Fetch one-line weather summary from wttr.in. Returns empty string on failure."""
    return fetch_weather("evening-brief/1.0", log)


# ── Prompt building ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a concise personal assistant writing an evening look-ahead briefing delivered as an iMessage.
Return only a valid JSON object. Do not include any text before or after the JSON object — \
no preamble, no explanation, no markdown, no code fences.
Be terse and factual. All string values must be plain text (no asterisks, no bullet symbols).
Do not call any tools. The calendar and email data is provided inline — compose your response \
entirely from what is given.
"""


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
        reminders_block = f"\n\nApple Reminders (already fetched):\n{reminders_ctx}"

    return f"""\
Today is {now.strftime("%A, %B %-d")} ({now.strftime("%Y-%m-%d")}).{weather_line}
Tomorrow is {tomorrow_label} ({tomorrow_iso}).

Calendar events and unread emails are provided below — do NOT call any tools.

1. From the calendar events, list all events on {tomorrow_iso} (format each as "TIME — TITLE"; \
flag anything back-to-back or needing prep in the title). Skip events from other days.
2. From the unread emails, separate into two groups:
   PENDING REPLIES: directly addressed to me, from a real person, received today, requires a response \
(contains a question, request, or ask).
   HIGHLIGHTS: notable non-urgent items — substantive newsletters (VC/tech digests, news), \
shipping/order updates, anything worth a quick note. Skip promos and automated noise.
3. Close with one sentence: the single most important thing to prepare or do tonight.

Return ONLY a valid JSON object with these keys:
  "summary": one-line overview (e.g. "3 meetings tomorrow, 1 pending reply")
  "tomorrow_events": list of strings formatted as "TIME — TITLE"; empty list if no events
  "pending_replies": list of strings formatted as "Sender: one-line summary"; empty list if none
  "email_highlights": list of strings formatted as "Sender: one-line summary"; empty list if nothing worth noting
  "prep": one sentence, the #1 thing to prepare or handle tonight{reminders_key}

Return only valid JSON, no other text.{reminders_block}
"""


# ── Claude call ───────────────────────────────────────────────────────────────


def get_briefing(weather: str, reminders_ctx: str = "") -> str:
    """Fetch calendar/email directly via Google APIs, then call Claude without tools."""
    tomorrow = datetime.now() + timedelta(days=1)
    start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    time_min = start.astimezone().isoformat()
    time_max = end.astimezone().isoformat()

    events = list_calendar_events(GOOGLE_TOKEN, time_min, time_max)
    emails = list_unread_messages(GOOGLE_TOKEN, max_results=50)
    log.info("Direct fetch: %d events, %d unread emails", len(events), len(emails))

    return call_briefing_model(
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=build_user_prompt(weather, reminders_ctx),
        calendar_data=events,
        email_data=emails,
    )


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
    header = (
        f"🌙 Tomorrow, {date_str} | {weather}"
        if weather
        else f"🌙 Tomorrow, {date_str}"
    )

    data, fallback = parse_json_response(raw, header=header, log=log)
    if fallback:
        return fallback

    # Extract all components
    events = data.get("tomorrow_events", [])
    pending = data.get("pending_replies", [])
    emails = data.get("email_highlights", [])
    reminders = data.get("reminders", [])
    prep = data.get("prep", "")

    # Helper function to assemble components into a single message
    def assemble(evs, pend, higs, rems, prp) -> str:
        lines = [header]

        # Tomorrow's schedule
        sched = ["", "📅 TOMORROW"]
        sched += (
            [f"• {e}" for e in evs]
            if evs
            else ["Nothing scheduled — enjoy the open day!"]
        )
        lines.extend(sched)

        # Pending replies
        if pend:
            lines.extend(["", "📬 PENDING REPLIES"] + [f"• {e}" for e in pend])

        # Highlights
        h_sec = ["", "📧 HIGHLIGHTS"]
        h_sec += (
            [f"• {e}" for e in higs] if higs else ["Inbox is quiet — nothing notable."]
        )
        lines.extend(h_sec)

        # Reminders
        if rems:
            lines.extend(["", "✅ REMINDERS"] + [f"• {r}" for r in rems])

        # Prep
        if prp:
            lines.extend(["", f"Tonight: {prp}"])

        return "\n".join(lines)

    # Clone components for pruning
    evs_p = list(events)
    pend_p = list(pending)
    higs_p = list(emails)
    rems_p = list(reminders)

    # Initial assembly
    msg = assemble(evs_p, pend_p, higs_p, rems_p, prep)

    # Pruning Loop: if message exceeds MAX_MESSAGE_CHARS, we prune from least important to most important.
    # Prune Highlights
    while len(msg) > MAX_MESSAGE_CHARS and higs_p:
        higs_p.pop()
        msg = assemble(evs_p, pend_p, higs_p, rems_p, prep)

    # Prune Schedule (events) - down to 1 event if it was not empty
    while len(msg) > MAX_MESSAGE_CHARS and len(evs_p) > 1:
        evs_p.pop()
        msg = assemble(evs_p, pend_p, higs_p, rems_p, prep)

    # Prune Reminders
    while len(msg) > MAX_MESSAGE_CHARS and rems_p:
        rems_p.pop()
        msg = assemble(evs_p, pend_p, higs_p, rems_p, prep)

    # Last resort: absolute truncation
    if len(msg) > MAX_MESSAGE_CHARS:
        msg = msg[: MAX_MESSAGE_CHARS - 3] + "..."

    return msg


# ── iMessage ──────────────────────────────────────────────────────────────────


def send_imessage(message: str, target: str) -> bool:
    return _send_imessage(message, target, max_message_chars=MAX_MESSAGE_CHARS, log=log)


def notify_failure(target: str, error: str) -> None:
    """Send a short failure notice via iMessage. Does nothing if no target."""
    if not target:
        return
    short = f"Evening brief failed: {error}"[:200]
    send_imessage(short, target)


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    log_file = Path.home() / ".evening_brief.log"
    handlers = [logging.StreamHandler(sys.stdout)]
    if sys.stdout.isatty():
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
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
        log.info(
            "Reminders: %d overdue, %d due tomorrow",
            len(reminders_data["overdue"]),
            len(reminders_data["due"]),
        )

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
