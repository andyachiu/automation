"""
Shared helpers for briefing scripts.
"""

import json
import logging
import os
import subprocess
import urllib.request

import anthropic


def fetch_weather(user_agent: str, log: logging.Logger) -> str:
    """Fetch one-line weather summary from wttr.in. Returns empty string on failure."""
    timeout = int(os.environ.get("WEATHER_TIMEOUT", "5"))
    try:
        req = urllib.request.Request(
            "https://wttr.in/?format=3&u",
            headers={"User-Agent": user_agent},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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


def send_imessage(
    message: str,
    target: str,
    *,
    max_message_chars: int,
    log: logging.Logger,
) -> bool:
    """Send an iMessage. If no target is configured, print to stdout instead and return False."""
    if not target:
        log.warning("No IMESSAGE_TARGET set — printing to stdout")
        print(message)
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
