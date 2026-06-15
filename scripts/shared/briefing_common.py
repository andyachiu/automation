"""
Shared helpers for briefing scripts.
"""

import json
import logging
import os
import signal
import subprocess
import time
import urllib.request

import anthropic


def fetch_weather(user_agent: str, log: logging.Logger) -> str:
    """Fetch one-line weather summary from wttr.in. Returns empty string on failure."""
    try:
        req = urllib.request.Request(
            "https://wttr.in/?format=3&u",
            headers={"User-Agent": user_agent},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception as exc:
        log.warning("Weather fetch failed: %s", exc)
        return ""


def call_briefing_model(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    calendar_data: list[dict],
    email_data: list[dict],
) -> str:
    """Call Claude with prefetched calendar + email data appended to the prompt. No tools."""
    client = anthropic.Anthropic()

    context = (
        "\n\nCalendar events (already fetched, do NOT call any tools):\n"
        f"{json.dumps(calendar_data, indent=2, default=str)}\n\n"
        "Recent unread emails (already fetched, do NOT call any tools):\n"
        f"{json.dumps(email_data, indent=2, default=str)}\n"
    )
    full_prompt = user_prompt + context

    response = client.messages.create(
        model=model,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": full_prompt}],
    )

    text_parts = [
        block.text
        for block in response.content
        if hasattr(block, "text") and block.text
    ]
    return "\n".join(text_parts).strip()


def parse_json_response(
    raw: str,
    *,
    header: str,
    log: logging.Logger,
) -> tuple[dict | None, str | None]:
    """Parse a JSON response, falling back to raw text when parsing fails."""
    try:
        return json.loads(raw), None
    except (json.JSONDecodeError, ValueError):
        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start != -1 and end > start:
            try:
                data = json.loads(raw[start:end])
                log.warning("Extracted JSON from mixed-content response")
                return data, None
            except (json.JSONDecodeError, ValueError):
                log.warning("Response was not valid JSON, using raw text")
                return None, f"{header}\n\n{raw}"

        log.warning("Response was not valid JSON, using raw text")
        return None, f"{header}\n\n{raw}"


def _blastdoor_pids() -> list[int] | None:
    """Return the list of MessagesBlastDoorService PIDs, or None if the probe failed.

    Healthy state on macOS Tahoe is 0 or 1 PID. On macOS 26.x there is a regression
    where workers from prior Messages sessions don't get reaped, and once they pile
    up Messages.app stops servicing AppleEvents (osascript hangs with -1712).
    """
    try:
        result = subprocess.run(
            ["pgrep", "-f", "MessagesBlastDoorService"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if result.returncode not in (0, 1):  # 1 = no matches, valid
        return None
    return [int(p) for p in result.stdout.split() if p.strip().isdigit()]


def _reap_blastdoor_orphans(pids: list[int], log: logging.Logger) -> int:
    """SIGKILL every BlastDoor worker except the newest (highest PID). Returns count killed.

    Verified 2026-05-25 (macOS 26.x): `kill -9 <PID>` succeeds on these workers even
    though `killall MessagesBlastDoorService` fails. SIP blocks `killall`-by-name on
    Apple-signed XPC services but does NOT block explicit-PID SIGKILL when the worker
    is user-owned. Outgoing iMessage sends via osascript do not appear to depend on
    BlastDoor (it's the inbound-parse sandbox); Messages.app spawns a fresh worker
    on demand for any send that follows.
    """
    if len(pids) <= 1:
        return 0

    # Keep the highest PID — most-recently-spawned, most likely to be a healthy
    # current-session worker. Kill the rest.
    pids_sorted = sorted(pids)
    to_kill = pids_sorted[:-1]
    keep = pids_sorted[-1]

    killed = 0
    for pid in to_kill:
        try:
            os.kill(pid, signal.SIGKILL)
            killed += 1
        except ProcessLookupError:
            pass  # already gone
        except OSError as e:
            log.warning("Could not SIGKILL BlastDoor PID %d: %s", pid, e)
    log.info("BlastDoor auto-recovery: killed %d orphan(s), kept PID %d", killed, keep)
    return killed


def send_imessage(
    message: str,
    target: str,
    *,
    max_message_chars: int,
    log: logging.Logger,
) -> bool:
    """Send an iMessage. If no target is configured, print to stdout instead.

    On BlastDoor pile-up (>1 worker, Tahoe regression), attempts auto-recovery
    via SIGKILL of orphan workers before sending. Falls back to fail-loud if
    recovery doesn't bring the count down to ≤1.
    """
    if not target:
        log.warning("No IMESSAGE_TARGET set — printing to stdout")
        print(message)
        return True

    pids = _blastdoor_pids()
    if pids is None:
        log.warning("BlastDoor probe failed — proceeding without pre-flight check")
    elif len(pids) > 1:
        log.warning(
            "BlastDoor pile-up detected: %d workers (PIDs %s). Attempting auto-recovery.",
            len(pids),
            pids,
        )
        _reap_blastdoor_orphans(pids, log)
        time.sleep(1.5)  # give launchd a beat to settle
        pids = _blastdoor_pids() or []
        if len(pids) > 1:
            log.error(
                "Skipping iMessage send: BlastDoor still wedged after auto-recovery "
                "(%d workers remain: %s). Manual fix: force-quit Messages.app via "
                "Activity Monitor or `kill -9 <PID>` on the orphans, then relaunch Messages.",
                len(pids),
                pids,
            )
            return False

    if len(message) > max_message_chars:
        message = message[: max_message_chars - 3] + "..."

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
