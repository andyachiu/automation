#!/usr/bin/env python3
"""
Refresh the Google OAuth access token using the stored refresh token.

Called by run_morning_brief.sh / run_evening_brief.sh / check_allergy_shot.sh
before each run. Writes the new access token to macOS Keychain. A single
token covers both Calendar and Gmail since both scopes were granted in
oauth_setup.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

try:
    from shared.system import current_user
except ModuleNotFoundError:
    # Supports `uv run shared/refresh_tokens.py` from the scripts/ dir.
    from system import current_user

KC_CLIENT  = "morning-brief-google-client"
KC_REFRESH = "morning-brief-google-refresh-token"
KC_ACCESS  = "morning-brief-google-token"

TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"


def keychain_get(service: str) -> str | None:
    result = subprocess.run(
        ["security", "find-generic-password", "-a", current_user(), "-s", service, "-w"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


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


def main() -> int:
    refresh = keychain_get(KC_REFRESH)
    if not refresh:
        print(f"  No refresh token in Keychain ({KC_REFRESH}). Re-run oauth_setup.py.", file=sys.stderr)
        return 1

    client_json = keychain_get(KC_CLIENT)
    if not client_json:
        print(f"  No client credentials in Keychain ({KC_CLIENT}). Re-run oauth_setup.py.", file=sys.stderr)
        return 1
    client = json.loads(client_json)

    payload = urllib.parse.urlencode({
        "grant_type":    "refresh_token",
        "refresh_token": refresh,
        "client_id":     client["client_id"],
        "client_secret": client["client_secret"],
    }).encode()

    req = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with urllib.request.urlopen(req) as resp:
            tokens = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  Refresh failed ({e.code}): {body}", file=sys.stderr)
        return 1

    access = tokens.get("access_token")
    if not access:
        print(f"  No access_token in refresh response: {tokens}", file=sys.stderr)
        return 1

    keychain_set(KC_ACCESS, access)

    # Google rotates refresh tokens rarely, but honor it if it happens.
    new_refresh = tokens.get("refresh_token")
    if new_refresh and new_refresh != refresh:
        keychain_set(KC_REFRESH, new_refresh)
        print("  Refresh token rotated.")

    print("  Access token refreshed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
