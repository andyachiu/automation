#!/usr/bin/env python3
"""
Throwaway probe — runs the same MCP-backed call as evening_brief.py
and dumps every content block (text, mcp_tool_use, mcp_tool_result)
to stdout and a timestamped log file. No iMessage send.

Usage: uv run probe_mcp.py
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import anthropic

from evening_brief import MODEL, SYSTEM_PROMPT, build_user_prompt
from shared.system import current_user


def keychain_get(service: str) -> str:
    r = subprocess.run(
        ["security", "find-generic-password", "-a", current_user(), "-s", service, "-w"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        sys.exit(f"keychain miss: {service}")
    return r.stdout.strip()


def block_to_dict(block) -> dict:
    """Convert any response content block to a JSON-serializable dict."""
    if hasattr(block, "model_dump"):
        return block.model_dump()
    return {"type": getattr(block, "type", "unknown"), "repr": repr(block)}


def main() -> None:
    log_dir = Path.home() / "Code" / "automation" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_path = log_dir / f"mcp_probe_{stamp}.json"

    # Refresh tokens first (same as production wrapper)
    script_dir = Path(__file__).parent
    refresh = subprocess.run(
        ["uv", "run", str(script_dir / "shared" / "refresh_tokens.py")],
        capture_output=True, text=True, cwd=script_dir,
    )
    if refresh.returncode != 0:
        sys.exit(f"token refresh failed: {refresh.stderr}")

    os.environ["ANTHROPIC_API_KEY"] = keychain_get("morning-brief-anthropic-key")
    gcal_token = keychain_get("morning-brief-gcal-token")
    gmail_token = keychain_get("morning-brief-gmail-token")

    user_prompt = build_user_prompt(weather="", reminders_ctx="")

    client = anthropic.Anthropic()
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        mcp_servers=[
            {"type": "url", "url": "https://gcal.mcp.claude.com/mcp",
             "name": "google-calendar", "authorization_token": gcal_token},
            {"type": "url", "url": "https://gmail.mcp.claude.com/mcp",
             "name": "gmail", "authorization_token": gmail_token},
        ],
        tools=[
            {"type": "mcp_toolset", "mcp_server_name": "google-calendar"},
            {"type": "mcp_toolset", "mcp_server_name": "gmail"},
        ],
        betas=["mcp-client-2025-11-20"],
    )

    dump = {
        "id": response.id,
        "model": response.model,
        "stop_reason": response.stop_reason,
        "usage": response.usage.model_dump() if hasattr(response.usage, "model_dump") else None,
        "anthropic_sdk_version": anthropic.__version__,
        "blocks": [block_to_dict(b) for b in response.content],
    }

    out_path.write_text(json.dumps(dump, indent=2, default=str))
    print(f"wrote {out_path}")
    print(f"stop_reason: {response.stop_reason}")
    print(f"block types: {[getattr(b, 'type', '?') for b in response.content]}")
    print()
    for i, b in enumerate(response.content):
        print(f"--- block {i} ({getattr(b, 'type', '?')}) ---")
        print(json.dumps(block_to_dict(b), indent=2, default=str)[:2000])
        print()


if __name__ == "__main__":
    main()
