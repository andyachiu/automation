#!/usr/bin/env python3
"""
One-time OAuth setup for MCP servers (Google Calendar & Gmail).

Registers an OAuth client, opens the browser for authorization,
and stores the refresh token in macOS Keychain.

Usage: uv run oauth_setup.py
"""

import hashlib
import http.server
import json
import secrets
import subprocess
import sys
import urllib.parse
import urllib.request
import webbrowser

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

REDIRECT_PORT = 18329
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"


def keychain_set(service: str, value: str) -> None:
    # Try update first, then add
    result = subprocess.run(
        ["security", "add-generic-password", "-a", subprocess.check_output(
            ["whoami"]).decode().strip(), "-s", service, "-w", value, "-U"],
        capture_output=True,
    )
    if result.returncode != 0:
        subprocess.run(
            ["security", "add-generic-password", "-a", subprocess.check_output(
                ["whoami"]).decode().strip(), "-s", service, "-w", value],
            check=True,
        )


def register_client(base_url: str) -> dict:
    """Register a dynamic OAuth client with the MCP server."""
    data = json.dumps({
        "client_name": "morning-brief-cli",
        "redirect_uris": [REDIRECT_URI],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "client_secret_post",
    }).encode()

    req = urllib.request.Request(
        f"{base_url}/register",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def do_oauth_flow(name: str, config: dict) -> None:
    base_url = config["base_url"]

    print(f"\n{'='*50}")
    print(f"Setting up {name.upper()}...")
    print(f"{'='*50}")

    # Step 1: Register client
    print("Registering OAuth client...")
    client = register_client(base_url)
    client_id = client["client_id"]
    client_secret = client.get("client_secret", "")

    # Save client credentials for future refresh
    keychain_set(config["keychain_client"], json.dumps({
        "client_id": client_id,
        "client_secret": client_secret,
    }))
    print(f"  Client ID: {client_id[:20]}...")

    # Step 2: Build authorization URL with PKCE
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = hashlib.sha256(code_verifier.encode()).digest()
    import base64
    code_challenge_b64 = base64.urlsafe_b64encode(code_challenge).rstrip(b"=").decode()

    state = secrets.token_urlsafe(32)

    auth_params = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "code_challenge": code_challenge_b64,
        "code_challenge_method": "S256",
    })
    auth_url = f"{base_url}/authorize?{auth_params}"

    # Step 3: Start local callback server
    auth_code = None
    server_error = None

    class CallbackHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal auth_code, server_error
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

            if params.get("state", [None])[0] != state:
                server_error = "State mismatch"
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"State mismatch. Please try again.")
                return

            if "error" in params:
                server_error = params["error"][0]
                self.send_response(400)
                self.end_headers()
                self.wfile.write(f"OAuth error: {server_error}".encode())
                return

            auth_code = params.get("code", [None])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Authorization successful! You can close this tab.")

        def log_message(self, format, *args):
            pass  # Suppress server logs

    server = http.server.HTTPServer(("localhost", REDIRECT_PORT), CallbackHandler)

    print(f"Opening browser for {name} authorization...")
    webbrowser.open(auth_url)
    print("Waiting for authorization callback...")

    server.handle_request()
    server.server_close()

    if server_error:
        print(f"  ERROR: {server_error}")
        sys.exit(1)
    if not auth_code:
        print("  ERROR: No authorization code received")
        sys.exit(1)

    # Step 4: Exchange code for tokens
    print("Exchanging code for tokens...")
    token_data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
        "client_id": client_id,
        "client_secret": client_secret,
        "code_verifier": code_verifier,
    }).encode()

    req = urllib.request.Request(
        f"{base_url}/token",
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as resp:
        tokens = json.loads(resp.read())

    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")

    if not access_token:
        print(f"  ERROR: No access token in response: {tokens}")
        sys.exit(1)

    keychain_set(config["keychain_access"], access_token)
    print(f"  Access token saved.")

    if refresh_token:
        keychain_set(config["keychain_refresh"], refresh_token)
        print(f"  Refresh token saved.")
    else:
        print(f"  WARNING: No refresh token returned. Token refresh won't work.")

    print(f"  {name.upper()} setup complete!")


def main():
    print("Morning Brief — OAuth Setup")
    print("This will open your browser twice (once for Calendar, once for Gmail).")

    for name, config in MCP_SERVERS.items():
        do_oauth_flow(name, config)

    print(f"\n{'='*50}")
    print("All done! Tokens are stored in macOS Keychain.")
    print("Run `bash run_morning_brief.sh` to test.")
    print(f"{'='*50}")


if __name__ == "__main__":
    main()
