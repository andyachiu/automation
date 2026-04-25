"""
Shared helpers for briefing scripts.
"""

import json
import logging
import subprocess
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
    gcal_token: str,
    gmail_token: str,
) -> str:
    """Call Claude with MCP servers and return raw response text."""
    client = anthropic.Anthropic()

    response = client.beta.messages.create(
        model=model,
        max_tokens=2048,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        mcp_servers=[
            {
                "type": "url",
                "url": "https://gcal.mcp.claude.com/mcp",
                "name": "google-calendar",
                "authorization_token": gcal_token,
            },
            {
                "type": "url",
                "url": "https://gmail.mcp.claude.com/mcp",
                "name": "gmail",
                "authorization_token": gmail_token,
            },
        ],
        betas=["mcp-client-2025-04-04"],
    )

    failed = [
        b for b in response.content
        if getattr(b, "type", "") == "mcp_tool_result" and getattr(b, "is_error", False)
    ]
    if failed:
        first = failed[0]
        detail = " ".join(
            getattr(c, "text", "") for c in getattr(first, "content", []) if getattr(c, "text", "")
        ).strip()
        raise RuntimeError(f"{len(failed)} MCP tool call(s) returned is_error; first: {detail}")

    text_parts = [
        block.text
        for block in response.content
        if hasattr(block, "text") and block.text
    ]
    return "\n".join(text_parts).strip()


def call_briefing_model_direct(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    calendar_data: list[dict],
    email_data: list[dict],
) -> str:
    """Call Claude with prefetched data appended to the prompt — no MCP, no tools."""
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


def _blastdoor_pid_count() -> int:
    """Return the number of running MessagesBlastDoorService instances.

    Healthy state on macOS Tahoe is 0 or 1. On macOS 26.x there is a regression
    where workers from prior Messages sessions don't get reaped, and once they
    pile up Messages.app stops servicing AppleEvents (osascript hangs with -1712).
    Returns -1 if the probe itself fails.
    """
    try:
        result = subprocess.run(
            ["pgrep", "-f", "MessagesBlastDoorService"],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return -1
    if result.returncode not in (0, 1):  # 1 = no matches, valid
        return -1
    return len([line for line in result.stdout.splitlines() if line.strip()])


def send_imessage(
    message: str,
    target: str,
    *,
    max_message_chars: int,
    log: logging.Logger,
) -> bool:
    """Send an iMessage. If no target is configured, print to stdout instead."""
    if not target:
        log.warning("No IMESSAGE_TARGET set — printing to stdout")
        print(message)
        return True

    pid_count = _blastdoor_pid_count()
    if pid_count > 1:
        log.error(
            "Skipping iMessage send: %d MessagesBlastDoorService instances detected (healthy is ≤1). "
            "Messages.app is wedged and the AppleEvent will time out with -1712. "
            "Recovery: force-quit Messages.app via Activity Monitor (killall fails under SIP because "
            "MessagesBlastDoorService is an Apple-signed XPC service), then relaunch Messages.app. "
            "Verify with: pgrep -lf MessagesBlastDoorService (should show 0–1 PIDs).",
            pid_count,
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
