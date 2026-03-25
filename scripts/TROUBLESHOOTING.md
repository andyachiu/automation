# Troubleshooting

## Non-Fatal Warnings (Normal Behavior)

These warnings appear in logs but do not indicate a failure — the briefing is still delivered.

### `WARNING Weather fetch failed: The read operation timed out`

`wttr.in` is an external service with a 5-second timeout. It will occasionally time out or be unavailable. The briefing runs without weather context in that case. No action needed.

### `WARNING Response was not valid JSON, using raw text`

Claude is instructed to return a JSON object, but occasionally returns plain text instead. `format_briefing()` falls back to the raw response text with a date header prepended. The briefing is still delivered — it just won't be as cleanly structured. No action needed unless it happens consistently (which would suggest a prompt or model issue).

---


## Wrong Environment: Sandbox or Container

### Symptoms

Scripts fail with errors like:
- `security: SecKeychainSearchCopyNext: The specified item could not be found in the keychain.`
- `osascript: can't open application "Messages"`
- `ANTHROPIC_API_KEY` is empty even though Keychain is populated
- Morning brief runs but no iMessage arrives
- `uv: command not found`

### Root Cause

This project **requires a real macOS environment** with full access to:
- **macOS Keychain** (`security` binary reading from your login keychain)
- **Messages app** via `osascript`
- **Your home directory** at `/Users/<you>/`

These are unavailable in Docker containers, Linux CI environments, and Claude Code sandboxes. The `/morning-brief` Claude Code skill must shell out to your **local Mac** — if Claude Code is running in a restricted environment, the skill invocation will silently fail or error.

### How to Diagnose

```bash
# Run the preflight check — prints exactly what's missing and how to fix it
uv run check_setup.py

# Or run the integration test suite for detailed output
uv run pytest tests/test_environment.py -v
```

### How to Fix

1. Run scripts directly in your local terminal, not inside any container or remote session.
2. For the Claude Code skill: ensure the skill is symlinked globally so it runs via your local shell:
   ```bash
   ln -sf ~/Code/automation/scripts/.claude/skills/morning-brief ~/.claude/skills/morning-brief
   ```
3. Verify Claude Code has permission to run shell commands (check `.claude/settings.local.json`).

---

## MCP Server Connection Timeout with Larger Models

### Symptoms

```
Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error',
'message': 'Connection to MCP server timed out. The server may be unavailable or unresponsive.'}}
```

The request hangs for exactly ~5 minutes before failing.

### Root Cause

The remote MCP servers enforce a ~5-minute connection timeout. Larger models like Sonnet make more thorough tool calls (reading more emails, more calendar events) and consistently exceed this limit. Haiku is fast enough to complete within the window.

### Fix

Use `claude-haiku-4-5`. Do not switch to Sonnet or Opus for this script.

---

## MCP Authentication Error Misdiagnosed as Credits Issue

## MCP Authentication Error Misdiagnosed as Credits Issue

### The Problem

When running `morning_brief.py`, the API returns:

```
Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error',
'message': 'Authentication error while communicating with MCP server.
Please check your authorization token.'}}
```

This error is **misleading** — it looks like an API key or credits problem, but it's actually about **OAuth tokens for the remote MCP servers** (Google Calendar, Gmail). The Anthropic API key can be perfectly valid (confirmed by `check_api_key.py`) while the MCP servers still fail because they need separate Google OAuth tokens.

### Why It's Confusing

1. `check_api_key.py` reports "API key works and has credits" — because it tests the Anthropic API directly, not the MCP servers.
2. The error says "Authentication error" with no indication of *which* authentication failed (Anthropic vs. Google OAuth).
3. The MCP servers were originally configured without `authorization_token` fields, so the request silently sent no token and got a generic auth error back.

### Root Cause

The remote MCP servers at `gcal.mcp.claude.com` and `gmail.mcp.claude.com` act as proxies to Google APIs. They require a Google OAuth access token passed via the `authorization_token` field in the `mcp_servers` config. Without it, the server returns a 400 error that the Anthropic SDK surfaces as an `invalid_request_error`.

### How to Fix

1. **Get OAuth tokens** using the MCP Inspector:
   ```bash
   npx @modelcontextprotocol/inspector
   ```
   - Select **SSE** transport type
   - Enter the server URL (e.g., `https://gcal.mcp.claude.com/mcp`)
   - Click **Open Auth Settings** → **Quick OAuth Flow**
   - Authorize with your Google account
   - **Copy the full `access_token`** — make sure it's not truncated (watch for `...` at the end, which means the display cut it off)
   - Repeat for `https://gmail.mcp.claude.com/mcp`

2. **Store tokens in Keychain**:
   ```bash
   security add-generic-password -a "$USER" -s "morning-brief-gcal-token" -w "FULL_TOKEN_HERE"
   security add-generic-password -a "$USER" -s "morning-brief-gmail-token" -w "FULL_TOKEN_HERE"
   ```

3. Run `bash run_morning_brief.sh` — it pulls the tokens from Keychain automatically.

### How to Avoid This in the Future

- **Test what you use.** If the app calls MCP servers, the health check should test MCP connectivity too, not just the base API key. A passing `check_api_key.py` only proves the Anthropic API key works — it says nothing about MCP server auth.
- **Check all credentials.** Remote MCP servers have their own auth (OAuth tokens) that is separate from your Anthropic API key. When you see an auth error, ask: *which* service is failing?
- **Watch for truncation.** OAuth tokens are long strings. When copying from UIs, always verify you have the complete value — a trailing `...` means it was cut off.
- **Token expiry.** Google OAuth access tokens expire (typically after 1 hour). If the script worked before but stops working, the token likely expired and needs to be refreshed. Consider automating token refresh if running on a schedule.
