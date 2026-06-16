#!/usr/bin/env python3
"""
One-time OAuth setup against Google directly (Calendar + Gmail).

Stores the Google OAuth client credentials and the resulting refresh +
access tokens in macOS Keychain. A single client + single refresh token
covers both Calendar and Gmail scopes.

First-time setup:
    1. Create a "Desktop app" OAuth client in Google Cloud Console with the
       Calendar API and Gmail API enabled, and the consent screen published
       to "In production" (avoids the 7-day refresh-token expiry that
       Testing mode imposes on sensitive scopes).
    2. Export the credentials and run this script:
           export GOOGLE_OAUTH_CLIENT_ID="<client_id>.apps.googleusercontent.com"
           export GOOGLE_OAUTH_CLIENT_SECRET="<client_secret>"
           uv run oauth_setup.py
       (Subsequent runs read the client from Keychain — no env vars needed.)

Usage: uv run oauth_setup.py
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import subprocess
import sys
import urllib.parse
import urllib.request
import webbrowser

from shared.system import current_user

# ── Keychain service names ────────────────────────────────────────────────────
KC_CLIENT = "morning-brief-google-client"  # JSON {client_id, client_secret}
KC_REFRESH = "morning-brief-google-refresh-token"
KC_ACCESS = "morning-brief-google-token"

# ── Google OAuth endpoints ────────────────────────────────────────────────────
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/documents.readonly",
]

REDIRECT_PORT = 18329
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"


def keychain_get(service: str) -> str | None:
    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-a",
            current_user(),
            "-s",
            service,
            "-w",
        ],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def keychain_set(service: str, value: str) -> None:
    user = current_user()
    result = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-a",
            user,
            "-s",
            service,
            "-w",
            value,
            "-U",
        ],
        capture_output=True,
    )
    if result.returncode != 0:
        subprocess.run(
            [
                "security",
                "add-generic-password",
                "-a",
                user,
                "-s",
                service,
                "-w",
                value,
            ],
            check=True,
        )


def load_client() -> tuple[str, str]:
    """Load OAuth client from env vars (first run) or Keychain (subsequent runs)."""
    env_id = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    env_secret = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if env_id and env_secret:
        keychain_set(
            KC_CLIENT, json.dumps({"client_id": env_id, "client_secret": env_secret})
        )
        print("Stored Google OAuth client in Keychain.")
        return env_id, env_secret

    stored = keychain_get(KC_CLIENT)
    if not stored:
        print(
            "ERROR: No Google OAuth client found.\n"
            "First run: set GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET "
            "in your environment and re-run this script.",
            file=sys.stderr,
        )
        sys.exit(1)

    client = json.loads(stored)
    return client["client_id"], client["client_secret"]


def b64url_no_pad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def capture_auth_code(state: str) -> str:
    """Run a one-shot localhost server, return the authorization code."""
    captured: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

            if params.get("state", [None])[0] != state:
                captured["error"] = "state_mismatch"
                body = b"State mismatch. Close this tab and re-run oauth_setup.py."
            elif "error" in params:
                captured["error"] = params["error"][0]
                body = f"OAuth error: {captured['error']}".encode()
            elif "code" in params:
                captured["code"] = params["code"][0]
                body = b"Authorization successful! You can close this tab."
            else:
                captured["error"] = "no_code"
                body = b"No code in callback."

            self.send_response(200 if "code" in captured else 400)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):  # silence default logging
            pass

    server = http.server.HTTPServer(("localhost", REDIRECT_PORT), Handler)
    server.handle_request()
    server.server_close()

    if "error" in captured:
        print(f"ERROR: {captured['error']}", file=sys.stderr)
        sys.exit(1)
    return captured["code"]


def exchange_code(
    client_id: str, client_secret: str, code: str, code_verifier: str
) -> dict:
    payload = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": code_verifier,
        }
    ).encode()

    req = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"ERROR: token exchange failed ({e.code}): {body}", file=sys.stderr)
        sys.exit(1)


def main() -> int:
    print("Morning Brief — Google OAuth setup")
    client_id, client_secret = load_client()

    code_verifier = secrets.token_urlsafe(64)
    code_challenge = b64url_no_pad(hashlib.sha256(code_verifier.encode()).digest())
    state = secrets.token_urlsafe(32)

    auth_url = (
        AUTH_ENDPOINT
        + "?"
        + urllib.parse.urlencode(
            {
                "client_id": client_id,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "scope": " ".join(SCOPES),
                "access_type": "offline",  # required to get a refresh_token
                "prompt": "consent",  # forces refresh_token issuance on re-auth
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
    )

    print("\nOpening browser for Google authorization...")
    print(f"If it doesn't open automatically: {auth_url}\n")
    webbrowser.open(auth_url)

    code = capture_auth_code(state)
    print("Authorization code received. Exchanging for tokens...")

    tokens = exchange_code(client_id, client_secret, code, code_verifier)

    access = tokens.get("access_token")
    refresh = tokens.get("refresh_token")

    if not access:
        print(f"ERROR: no access_token in response: {tokens}", file=sys.stderr)
        return 1
    if not refresh:
        print(
            "ERROR: no refresh_token in response. This usually means a prior "
            "authorization is still valid and Google declined to mint a new one. "
            "Revoke at https://myaccount.google.com/permissions and re-run.",
            file=sys.stderr,
        )
        return 1

    keychain_set(KC_ACCESS, access)
    keychain_set(KC_REFRESH, refresh)

    print("\nDone. Stored:")
    print(f"  - {KC_ACCESS}")
    print(f"  - {KC_REFRESH}")
    print("\nVerify with:  uv run shared/refresh_tokens.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
