#!/usr/bin/env python3
"""
morning_brief.py — Daily AI briefing sent to yourself via iMessage
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from shared.briefing_common import call_briefing_model, fetch_weather, parse_json_response
from shared.briefing_common import send_imessage as _send_imessage
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
    return fetch_weather("morning-brief/1.0", log)


# ── Day helpers ───────────────────────────────────────────────────────────────

def is_monday() -> bool:
    return datetime.now().weekday() == 0

def is_friday() -> bool:
    return datetime.now().weekday() == 4

def is_weekend() -> bool:
    return datetime.now().weekday() >= 5

def is_allergy_shot_day() -> bool:
    return datetime.now().weekday() in (0, 2, 4)  # Mon, Wed, Fri


# ── Prompt building ───────────────────────────────────────────────────────────

def build_user_prompt(weather: str, reminders_ctx: str = "") -> str:
    now = datetime.now()
    today = now.strftime("%A, %B %-d")
    today_iso = now.strftime("%Y-%m-%d")
    weather_line = f"\nCurrent weather: {weather}" if weather else ""

    allergy_day = is_allergy_shot_day()
    max_calls = 3 if allergy_day else 2

    # Build numbered steps
    steps = []
    n = 1

    steps.append(
        f"{n}. List only today's events ({today_iso}, midnight to 11:59 PM local time; "
        "format each as 'TIME — TITLE'; flag anything back-to-back or needing prep in the title. "
        "Do not include events from other days."
    )
    n += 1

    if allergy_day:
        steps.append(
            f"{n}. Search my calendar for allergy shot appointments (events matching "
            "'allergy' or 'allergy shot') in the next 30 days. Exclude blood draws and consultations."
        )
        n += 1

    if is_weekend():
        steps.append(
            f"{n}. Check the 20 most recent emails. Separate into two groups:\n"
            "   URGENT: directly addressed to you in To:, from a real person, time-sensitive language, received today.\n"
            "   HIGHLIGHTS: notable non-urgent items — substantive newsletters, shipping/order updates, anything worth knowing. Skip promos and automated noise."
        )
    else:
        steps.append(
            f"{n}. Check the 50 most recent unread emails in my inbox (not sent, not search). Separate into two groups:\n"
            "   URGENT: all must be true — directly addressed in To: (not CC/mailing list), "
            "from a real person (not newsletter or automated sender), "
            "time-sensitive language (urgent, asap, today, deadline, reply, action required), "
            "received in the last 24 hours and unanswered.\n"
            "   HIGHLIGHTS: notable non-urgent items — substantive newsletters (VC/tech digests, news), "
            "shipping/order updates, anything worth a quick note. Skip promos and automated noise."
        )
    n += 1

    steps.append(f"{n}. Close with one sentence: the #1 thing I should focus on today.")
    n += 1

    if is_monday():
        steps.append(
            f"{n}. Since it's Monday, add a brief week-ahead section with key events Mon-Fri (2 lines max)."
        )
        n += 1

    if is_friday():
        steps.append(
            f"{n}. Since it's Friday, add a next-week kickoff: first Monday meeting "
            "and any notable upcoming events (2 items max)."
        )
        n += 1

    # JSON schema
    json_fields = [
        '  "summary": one-line overview (e.g. "3 meetings, 1 urgent email")',
        '  "events": list of strings formatted as "TIME — TITLE" (e.g. ["9:00 AM — Standup", "2:00 PM — 1:1 (prep needed)"]); empty list if no events',
        '  "urgent_emails": list of strings formatted as "Sender: one-line summary" for urgent emails only; empty list if none',
        '  "email_highlights": list of strings formatted as "Sender: one-line summary" for notable non-urgent emails; empty list if nothing worth noting',
        '  "focus": one sentence, the #1 priority for today',
    ]
    if allergy_day:
        json_fields.append(
            '  "allergy_shot": "Next shot: [Weekday Mon DD]" or "Next shot: [Weekday Mon DD] at [location]" '
            'only if a location is actually set in the event; '
            'or "No allergy shot in next 30 days — book one at Stanford MyHealth" if none found'
        )
    if is_monday():
        json_fields.append('  "week_preview": list of strings formatted as "DAY — EVENT" for Mon-Fri key events (Monday only)')
    if is_friday():
        json_fields.append('  "week_kickoff": list of strings formatted as "DAY — EVENT" for key upcoming events (Friday only)')

    steps_text = "\n".join(steps)
    fields_text = "\n".join(json_fields)

    reminders_block = ""
    if reminders_ctx:
        json_fields.append('  "reminders": list of strings — copy from the reminders provided below (overdue first, then due today); empty list if none')
        fields_text = "\n".join(json_fields)
        reminders_block = f"\n\nApple Reminders (already fetched, do NOT use a tool call for these):\n{reminders_ctx}"

    return f"""\
Today is {today} ({today_iso}).{weather_line}

Using my Google Calendar and Gmail ({max_calls} tool calls max):

{steps_text}

Return ONLY a valid JSON object with these keys:
{fields_text}

Return only valid JSON, no other text.{reminders_block}
"""


SYSTEM_PROMPT = """\
You are a concise personal assistant writing a morning briefing delivered as an iMessage.
Return only a valid JSON object. Do not include any text before or after the JSON object — \
no preamble, no explanation, no markdown, no code fences.
Be terse and factual. All string values must be plain text (no asterisks, no bullet symbols).
Use exactly the number of tool calls specified — no more. Fetch all data first, then compose \
your response entirely from what you retrieved.
"""


# ── Claude call ───────────────────────────────────────────────────────────────

def get_briefing(weather: str, reminders_ctx: str = "") -> str:
    """Call Claude with MCP servers and return raw response text."""
    return call_briefing_model(
        model=MODEL,
        system_prompt=SYSTEM_PROMPT,
        user_prompt=build_user_prompt(weather, reminders_ctx),
        gcal_token=GCAL_TOKEN,
        gmail_token=GMAIL_TOKEN,
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
    date_str = datetime.now().strftime("%a %b %-d")
    header = f"☀️ {date_str} | {weather}" if weather else f"☀️ {date_str}"

    data, fallback = parse_json_response(raw, header=header, log=log)
    if fallback:
        return fallback

    lines: list[str] = [header]

    # Schedule
    events = data.get("events", [])
    sched = ["", "📅 SCHEDULE"]
    sched += [f"• {e}" for e in events] if events else ["Nothing on the calendar today — enjoy the open day!"]
    if not _try_append(lines, sched):
        _try_append(lines, ["", "📅 SCHEDULE"])
        for e in events:
            if not _try_append(lines, [f"• {e}"]):
                break

    # Urgent emails — only shown if present
    urgent = data.get("urgent_emails", [])
    if urgent:
        urgent_sec = ["", "🚨 URGENT"] + [f"• {e}" for e in urgent]
        if not _try_append(lines, urgent_sec):
            if _try_append(lines, ["", "🚨 URGENT"]):
                for e in urgent:
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

    # Allergy shot
    allergy = data.get("allergy_shot", data.get("allergy_shot_reminder", ""))
    if allergy:
        _try_append(lines, ["", "🩹 ALLERGY SHOT", allergy])

    # Week preview (Monday)
    week_preview = data.get("week_preview", [])
    if week_preview:
        wp = ["", "📅 WEEK AHEAD"] + [f"• {e}" for e in week_preview]
        if not _try_append(lines, wp):
            if _try_append(lines, ["", "📅 WEEK AHEAD"]):
                for e in week_preview:
                    if not _try_append(lines, [f"• {e}"]):
                        break

    # Week kickoff (Friday)
    week_kickoff = data.get("week_kickoff", [])
    if week_kickoff:
        wk = ["", "📅 NEXT WEEK"] + [f"• {e}" for e in week_kickoff]
        if not _try_append(lines, wk):
            if _try_append(lines, ["", "📅 NEXT WEEK"]):
                for e in week_kickoff:
                    if not _try_append(lines, [f"• {e}"]):
                        break

    # Focus — lowest priority
    focus = data.get("focus", "")
    if focus:
        _try_append(lines, ["", f"Focus: {focus}"])

    return "\n".join(lines)


# ── iMessage ──────────────────────────────────────────────────────────────────

def send_imessage(message: str, target: str) -> bool:
    return _send_imessage(message, target, max_message_chars=MAX_MESSAGE_CHARS, log=log)


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

    reminders_data = get_reminders(datetime.now())
    reminders_lines = []
    for r in reminders_data["overdue"]:
        reminders_lines.append(f"[OVERDUE] {r}")
    for r in reminders_data["due"]:
        reminders_lines.append(f"[Due today] {r}")
    reminders_ctx = "\n".join(reminders_lines) if reminders_lines else ""
    if reminders_ctx:
        log.info("Reminders: %d overdue, %d due today", len(reminders_data["overdue"]), len(reminders_data["due"]))

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
