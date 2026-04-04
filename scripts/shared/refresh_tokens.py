#!/usr/bin/env python3
"""
Refresh OAuth tokens for MCP servers using stored refresh tokens.

Called by run_morning_brief.sh before fetching the briefing.
Updates access tokens in macOS Keychain.
"""

import json
import subprocess
import sys
import urllib.parse
import urllib.request

try:
    from shared.system import current_user
except ModuleNotFoundError:
    # Supports direct execution via `uv run shared/refresh_tokens.py`.
    from system import current_user

MCP_SERVERS = {
    "gcal": {
        "base_url": "https://gcal.mcp.claude.com",
        "keychain_refresh": "morning-brief-gcal-refresh-token",
        "keychain_access": "morning-brief-gcal-token",
        "keychain_client": "morning-brief-gcal-client",
    },
    "gmail": {
        "base_url": "https://gmail.mcp.claude.com",
        "keychain_refresh": "morning-brief-gmail-refresh-token",
        "keychain_access": "morning-brief-gmail-token",
        "keychain_client": "morning-brief-gmail-client",
    },
}


def keychain_get(service: str) -> str | None:
    result = subprocess.run(
        ["security", "find-generic-password", "-a",
         current_user(),
         "-s", service, "-w"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def keychain_set(service: str, value: str) -> None:
    user = current_user()
    result = subprocess.run(
        ["security", "add-generic-password", "-a", user, "-s", service, "-w", value, "-U"],
        capture_output=True,
    )
    if result.returncode != 0:
        subprocess.run(
            ["security", "add-generic-password", "-a", user, "-s", service, "-w", value],
            check=True,
        )


def refresh_token(name: str, config: dict) -> bool:
    refresh = keychain_get(config["keychain_refresh"])
    if not refresh:
        print(f"  {name}: No refresh token found. Run oauth_setup.py first.", file=sys.stderr)
        return False

    client_json = keychain_get(config["keychain_client"])
    if not client_json:
        print(f"  {name}: No client credentials found. Run oauth_setup.py first.", file=sys.stderr)
        return False

    client = json.loads(client_json)

    token_data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": refresh,
        "client_id": client["client_id"],
        "client_secret": client.get("client_secret", ""),
    }).encode()

    req = urllib.request.Request(
        f"{config['base_url']}/token",
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with urllib.request.urlopen(req) as resp:
            tokens = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  {name}: Refresh failed ({e.code}): {body}", file=sys.stderr)
        return False

    access_token = tokens.get("access_token")
    if not access_token:
        print(f"  {name}: No access token in refresh response", file=sys.stderr)
        return False

    keychain_set(config["keychain_access"], access_token)

    # Update refresh token if a new one was issued
    new_refresh = tokens.get("refresh_token")
    if new_refresh:
        keychain_set(config["keychain_refresh"], new_refresh)

    print(f"  {name}: Token refreshed.")
    return True


def main():
    all_ok = True
    for name, config in MCP_SERVERS.items():
        if not refresh_token(name, config):
            all_ok = False

    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
