#!/usr/bin/env python3
"""
morning_brief.py — Daily AI briefing sent to yourself via iMessage
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

SYSTEM_PROMPT = """\
You are a concise personal assistant writing a morning briefing delivered as an iMessage.
Return only a valid JSON object. Do not include any text before or after the JSON object — \
no preamble, no explanation, no markdown, no code fences.
Be terse and factual. All string values must be plain text (no asterisks, no bullet symbols).
Do not call any tools. The calendar and email data is provided inline — compose your response \
entirely from what is given.
"""


def build_user_prompt(weather: str, reminders_ctx: str = "") -> str:
    now = datetime.now()
    today = now.strftime("%A, %B %-d")
    today_iso = now.strftime("%Y-%m-%d")
    weather_line = f"\nCurrent weather: {weather}" if weather else ""

    allergy_day = is_allergy_shot_day()

    steps = []
    n = 1
    steps.append(
        f"{n}. From the calendar events, list only today's events ({today_iso}; "
        "format each as 'TIME — TITLE'; flag anything back-to-back or needing prep in the title). "
        "Skip events from other days."
    )
    n += 1

    if allergy_day:
        steps.append(
            f"{n}. From the same calendar events, identify the next allergy shot appointment "
            "(events matching 'allergy' or 'allergy shot') in the next 30 days. "
            "Exclude blood draws and consultations."
        )
        n += 1

    if is_weekend():
        steps.append(
            f"{n}. From the unread emails, separate into two groups:\n"
            "   URGENT: directly addressed to me, from a real person, time-sensitive language, received today.\n"
            "   HIGHLIGHTS: notable non-urgent items — substantive newsletters, shipping/order updates, anything worth knowing. Skip promos and automated noise."
        )
    else:
        steps.append(
            f"{n}. From the unread emails, separate into two groups:\n"
            "   URGENT: directly addressed to me, from a real person, time-sensitive language "
            "(urgent, asap, today, deadline, reply, action required), received in the last 24 hours.\n"
            "   HIGHLIGHTS: notable non-urgent items — substantive newsletters (VC/tech digests, news), "
            "shipping/order updates, anything worth a quick note. Skip promos and automated noise."
        )
    n += 1

    steps.append(f"{n}. Close with one sentence: the #1 thing I should focus on today.")
    n += 1

    if is_monday():
        steps.append(
            f"{n}. Since it's Monday, add a brief week-ahead section with key events Mon-Fri "
            "(2 lines max, drawn only from events in the provided calendar data)."
        )
        n += 1

    if is_friday():
        steps.append(
            f"{n}. Since it's Friday, add a next-week kickoff: first Monday meeting "
            "and any notable upcoming events (2 items max, drawn only from events in the provided calendar data)."
        )
        n += 1

    json_fields = [
        '  "summary": one-line overview (e.g. "3 meetings, 1 urgent email")',
        '  "events": list of strings formatted as "TIME — TITLE"; empty list if no events',
        '  "urgent_emails": list of strings formatted as "Sender: one-line summary"; empty list if none',
        '  "email_highlights": list of strings formatted as "Sender: one-line summary"; empty list if nothing worth noting',
        '  "focus": one sentence, the #1 priority for today',
    ]
    if allergy_day:
        json_fields.append(
            '  "allergy_shot": "Next shot: [Weekday Mon DD]" or "Next shot: [Weekday Mon DD] at [location]" '
            "only if a location is actually set in the event; "
            'or "No allergy shot in next 30 days — book one at Stanford MyHealth" if none found'
        )
    if is_monday():
        json_fields.append(
            '  "week_preview": list of strings formatted as "DAY — EVENT" for Mon-Fri key events (Monday only)'
        )
    if is_friday():
        json_fields.append(
            '  "week_kickoff": list of strings formatted as "DAY — EVENT" for key upcoming events (Friday only)'
        )

    reminders_block = ""
    if reminders_ctx:
        json_fields.append(
            '  "reminders": list of strings — copy from the reminders provided below (overdue first, then due today); empty list if none'
        )
        reminders_block = f"\n\nApple Reminders (already fetched):\n{reminders_ctx}"

    steps_text = "\n".join(steps)
    fields_text = "\n".join(json_fields)

    return f"""\
Today is {today} ({today_iso}).{weather_line}

Calendar events and unread emails are provided below — do NOT call any tools.

{steps_text}

Return ONLY a valid JSON object with these keys:
{fields_text}

Return only valid JSON, no other text.{reminders_block}
"""


# ── Claude call ───────────────────────────────────────────────────────────────


def get_briefing(weather: str, reminders_ctx: str = "") -> str:
    """Fetch calendar/email directly via Google APIs, then call Claude without tools."""
    now = datetime.now()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    # Pull 30 days for allergy-shot lookup; harmless on non-allergy days
    end = start + timedelta(days=30)
    time_min = start.astimezone().isoformat()
    time_max = end.astimezone().isoformat()

    events = list_calendar_events(GOOGLE_TOKEN, time_min, time_max)
    max_emails = 20 if is_weekend() else 50
    emails = list_unread_messages(GOOGLE_TOKEN, max_results=max_emails)
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
    date_str = datetime.now().strftime("%a %b %-d")
    header = f"☀️ {date_str} | {weather}" if weather else f"☀️ {date_str}"

    data, fallback = parse_json_response(raw, header=header, log=log)
    if fallback:
        return fallback

    # Extract all components
    events = data.get("events", [])
    urgent = data.get("urgent_emails", [])
    emails = data.get("email_highlights", [])
    reminders = data.get("reminders", [])
    allergy = data.get("allergy_shot", data.get("allergy_shot_reminder", ""))
    week_preview = data.get("week_preview", [])
    week_kickoff = data.get("week_kickoff", [])
    focus = data.get("focus", "")

    # Helper function to assemble components into a single message
    def assemble(evs, urg, higs, rems, allg, wp, wk, foc) -> str:
        lines = [header]

        # Schedule
        sched = ["", "📅 SCHEDULE"]
        sched += (
            [f"• {e}" for e in evs]
            if evs
            else ["Nothing on the calendar today — enjoy the open day!"]
        )
        lines.extend(sched)

        # Urgent emails
        if urg:
            lines.extend(["", "🚨 URGENT"] + [f"• {e}" for e in urg])

        # Highlights
        h_sec = ["", "📧 HIGHLIGHTS"]
        h_sec += (
            [f"• {e}" for e in higs] if higs else ["Inbox is quiet — nothing notable."]
        )
        lines.extend(h_sec)

        # Reminders
        if rems:
            lines.extend(["", "✅ REMINDERS"] + [f"• {r}" for r in rems])

        # Allergy
        if allg:
            lines.extend(["", "🩹 ALLERGY SHOT", allg])

        # Week preview (Monday)
        if wp:
            lines.extend(["", "📅 WEEK AHEAD"] + [f"• {e}" for e in wp])

        # Week kickoff (Friday)
        if wk:
            lines.extend(["", "📅 NEXT WEEK"] + [f"• {e}" for e in wk])

        # Focus
        if foc:
            lines.extend(["", "🎯 FOCUS", foc])

        return "\n".join(lines)

    # Clone components for pruning
    evs_p = list(events)
    urg_p = list(urgent)
    higs_p = list(emails)
    rems_p = list(reminders)
    wp_p = list(week_preview)
    wk_p = list(week_kickoff)

    # Initial assembly
    msg = assemble(evs_p, urg_p, higs_p, rems_p, allergy, wp_p, wk_p, focus)

    # Pruning Loop: if message exceeds MAX_MESSAGE_CHARS, we prune from least important to most important.
    # Prune Highlights
    while len(msg) > MAX_MESSAGE_CHARS and higs_p:
        higs_p.pop()
        msg = assemble(evs_p, urg_p, higs_p, rems_p, allergy, wp_p, wk_p, focus)

    # Prune Week Preview / Kickoff
    if len(msg) > MAX_MESSAGE_CHARS and wp_p:
        wp_p = []
        msg = assemble(evs_p, urg_p, higs_p, rems_p, allergy, wp_p, wk_p, focus)
    if len(msg) > MAX_MESSAGE_CHARS and wk_p:
        wk_p = []
        msg = assemble(evs_p, urg_p, higs_p, rems_p, allergy, wp_p, wk_p, focus)

    # Prune Schedule (events) - down to 1 event if it was not empty
    while len(msg) > MAX_MESSAGE_CHARS and len(evs_p) > 1:
        evs_p.pop()
        msg = assemble(evs_p, urg_p, higs_p, rems_p, allergy, wp_p, wk_p, focus)

    # Prune Reminders
    while len(msg) > MAX_MESSAGE_CHARS and rems_p:
        rems_p.pop()
        msg = assemble(evs_p, urg_p, higs_p, rems_p, allergy, wp_p, wk_p, focus)

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
    short = f"Morning brief failed: {error}"[:200]
    send_imessage(short, target)


# ── Main ──────────────────────────────────────────────────────────────────────


def main():
    log_file = Path.home() / ".morning_brief.log"
    handlers = [logging.StreamHandler(sys.stdout)]
    if sys.stdout.isatty():
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
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
        log.info(
            "Reminders: %d overdue, %d due today",
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
