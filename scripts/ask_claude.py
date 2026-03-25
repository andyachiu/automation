#!/usr/bin/env python3
"""
Ask Claude a question with access to your Google Calendar and Gmail.
Maintains conversation history within the same day.

Usage:
  uv run ask_claude.py "What's on my calendar today?"
  uv run ask_claude.py --clear                          # reset conversation
  echo "Any urgent emails?" | uv run ask_claude.py

Called by ask_claude.sh (which handles token refresh and Keychain).
"""

import anthropic
import json
import os
import sys
from datetime import date
from pathlib import Path

GCAL_TOKEN = os.environ.get("GCAL_TOKEN", "")
GMAIL_TOKEN = os.environ.get("GMAIL_TOKEN", "")

HISTORY_FILE = Path(__file__).parent / ".conversation_history.json"

SYSTEM_PROMPT = """\
You are a concise personal assistant responding via iMessage.

Rules:
- Be terse and scannable — this is a phone notification, not a report
- Use plain text only, no markdown, no asterisks
- Max ~1000 characters
- Answer the question directly, then add relevant context if needed
- Friendly but efficient tone
"""


def load_history() -> list[dict]:
    """Load conversation history, clearing if it's from a previous day."""
    if not HISTORY_FILE.exists():
        return []

    try:
        data = json.loads(HISTORY_FILE.read_text())
    except (json.JSONDecodeError, KeyError):
        return []

    # Auto-clear if from a different day
    if data.get("date") != date.today().isoformat():
        HISTORY_FILE.unlink()
        return []

    return data.get("messages", [])


def save_history(messages: list[dict]) -> None:
    HISTORY_FILE.write_text(json.dumps({
        "date": date.today().isoformat(),
        "messages": messages,
    }, indent=2))


def clear_history() -> None:
    if HISTORY_FILE.exists():
        HISTORY_FILE.unlink()
    print("Conversation cleared.")


def ask(question: str) -> str:
    client = anthropic.Anthropic()

    messages = load_history()
    messages.append({"role": "user", "content": question})

    mcp_servers = []
    if GCAL_TOKEN:
        mcp_servers.append({
            "type": "url",
            "url": "https://gcal.mcp.claude.com/mcp",
            "name": "google-calendar",
            "authorization_token": GCAL_TOKEN,
        })
    if GMAIL_TOKEN:
        mcp_servers.append({
            "type": "url",
            "url": "https://gmail.mcp.claude.com/mcp",
            "name": "gmail",
            "authorization_token": GMAIL_TOKEN,
        })

    kwargs = dict(
        model="claude-haiku-4-5-20251001",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    if mcp_servers:
        kwargs["mcp_servers"] = mcp_servers
        kwargs["betas"] = ["mcp-client-2025-04-04"]
        response = client.beta.messages.create(**kwargs)
    else:
        response = client.messages.create(**kwargs)

    text_parts = [
        block.text
        for block in response.content
        if hasattr(block, "text") and block.text
    ]
    answer = "\n".join(text_parts).strip()

    # Save only text messages to history (not MCP tool blocks)
    messages.append({"role": "assistant", "content": answer})
    save_history(messages)

    return answer


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--clear":
        clear_history()
        return

    if len(sys.argv) > 1:
        question = " ".join(sys.argv[1:])
    elif not sys.stdin.isatty():
        question = sys.stdin.read().strip()
    else:
        print("Usage: ask_claude.py 'your question'", file=sys.stderr)
        sys.exit(1)

    if not question:
        print("No question provided.", file=sys.stderr)
        sys.exit(1)

    answer = ask(question)
    print(answer)


if __name__ == "__main__":
    main()
