# Project Notes

## Overview

This is a macOS automation toolkit that integrates Claude AI with Google Calendar and Gmail to provide:

1. **Morning Briefing** (`morning_brief.py`): Scheduled daily summary of calendar events and emails, delivered via iMessage
2. **Evening Briefing** (`evening_brief.py`): Look-ahead for tomorrow's schedule and pending replies, delivered via iMessage

**Platform:** macOS only (requires Keychain, `osascript`, Messages app)
**Runtime:** Python >=3.13.6, managed with `uv`
**Model:** `claude-haiku-4-5-20251001` (Haiku — required to complete within the 5-minute MCP server timeout; on allergy shot days the prompt makes 3 tool calls)

---

## Repository Structure

```
automation/
├── plists/                 # launchd agents (copy to ~/Library/LaunchAgents/ to schedule)
│   ├── com.andychiu.automation.deploy.plist        # deploy at 7am weekdays
│   ├── com.andychiu.automation.morning-brief.plist # morning brief at 8am weekdays
│   └── com.andychiu.allergy-shot-check.plist       # allergy check Mon/Wed/Fri
└── scripts/                # Python project root (uv, pyproject.toml)
    ├── morning_brief.py        # Generates and sends daily morning briefing
    ├── evening_brief.py        # Generates and sends evening look-ahead briefing
    ├── deploy.sh               # Pulls latest code from GitHub + runs uv sync (7am launchd)
    ├── run_morning_brief.sh    # Production wrapper: token refresh + morning_brief.py (8am launchd)
    ├── run_evening_brief.sh    # Production wrapper: token refresh + evening_brief.py (9pm launchd)
    ├── check_api_key.py        # Validates Anthropic API key only (not MCP connectivity)
    ├── check_setup.py          # Preflight environment check
    ├── oauth_setup.py          # One-time OAuth authorization flow for Google services
    ├── shared/
    │   └── refresh_tokens.py   # Refreshes expired Google OAuth access tokens
    ├── allergy-shot-check/
    │   └── check_allergy_shot.sh  # Allergy appointment reminder via Claude + Calendar
    ├── .claude/skills/
    │   └── morning-brief/      # Claude Code skill: /morning-brief
    │       └── SKILL.md
    ├── tests/
    │   ├── test_morning_brief.py  # Unit tests (offline, all mocked)
    │   └── test_environment.py    # Integration tests (macOS only, real Keychain)
    ├── pyproject.toml          # Python project config (anthropic>=0.86.0)
    ├── CLAUDE.md               # This file
    ├── TROUBLESHOOTING.md      # Diagnostic guide for MCP authentication issues
    └── README.md               # Project documentation and setup guide
```

---

## Authentication Architecture

This project has **two separate authentication systems** that must both be functional:

### 1. Anthropic API Key
- Stored in Keychain: `morning-brief-anthropic-key`
- Validated by `check_api_key.py`
- Set via: `security add-generic-password -a "$USER" -s "morning-brief-anthropic-key" -w "sk-ant-..."`

### 2. Google OAuth Tokens (for MCP servers)
- MCP servers at `gcal.mcp.claude.com` and `gmail.mcp.claude.com` require **separate** Google OAuth tokens
- Tokens are passed via the `authorization_token` field in the MCP server config
- Stored in Keychain:
  - `morning-brief-gcal-token` — active Google Calendar access token
  - `morning-brief-gmail-token` — active Gmail access token
  - `morning-brief-gcal-refresh-token` — refresh token for Calendar
  - `morning-brief-gmail-refresh-token` — refresh token for Gmail
  - `morning-brief-gcal-client` — JSON with `client_id` and `client_secret`
  - `morning-brief-gmail-client` — JSON with `client_id` and `client_secret`
- Obtained via `oauth_setup.py` (one-time PKCE flow)
- Refreshed via `refresh_tokens.py` (called automatically by shell wrappers)

### 3. iMessage Target
- Stored in Keychain: `morning-brief-imessage-target` (phone number or email)
- Set via: `security add-generic-password -a "$USER" -s "morning-brief-imessage-target" -w "+15551234567"`

**Critical distinction:** A working Anthropic API key does NOT mean MCP servers are authenticated. The error `Authentication error while communicating with MCP server` always indicates a Google OAuth problem, not an API key problem. See `TROUBLESHOOTING.md` for diagnostics.

---

## Execution Flows

### Deploy (7am launchd)
```
deploy.sh
  ├── git pull origin master
  ├── uv sync (install/update dependencies)
  ├── Log everything to ~/.morning_brief_deploy.log
  └── On failure: send iMessage notification + exit 1
```

### Morning Briefing (8am launchd)
```
run_morning_brief.sh
  ├── trap on_failure ERR (sends error iMessage on any failure)
  ├── Read Anthropic API key from Keychain
  ├── Read iMessage target from Keychain
  ├── refresh_tokens.py
  │   ├── Read refresh tokens + client credentials from Keychain
  │   ├── POST to /token endpoint on each MCP server
  │   └── Write new access tokens back to Keychain
  ├── Read fresh GCAL_TOKEN and GMAIL_TOKEN from Keychain
  └── morning_brief.py
      ├── get_weather() → wttr.in (plain text, empty string on failure)
      ├── is_monday() → adds week-ahead section if True
      ├── build_user_prompt(weather) → includes weather + email urgency criteria
      ├── get_briefing(weather) → Claude Haiku with Calendar + Gmail MCP
      │   └── Returns JSON: {summary, events, urgent_emails, sent_awaiting_reply, focus}
      │                      + week_preview (Mondays only)
      ├── format_briefing(raw, weather) → plain text (falls back to raw if not valid JSON)
      ├── send_imessage() → osascript → Messages → iMessage
      └── On failure: notify_failure() sends short error iMessage
```

---

## Key Conventions

### Briefing Output Format
- Claude returns a **JSON object** (not plain text) — `format_briefing()` converts it to readable iMessage text
- Fallback to raw text if Claude doesn't return valid JSON
- Final message is truncated to 1200 chars before iMessage delivery
- Special characters are escaped before passing to `osascript`
- No markdown, no asterisks, no emoji in output

### Logging
- `morning_brief.py` logs to `~/.morning_brief.log` (configured in `main()`)
- `run_morning_brief.sh` also appends to `~/.morning_brief.log` via `tee`
- `deploy.sh` logs to `~/.morning_brief_deploy.log` (append-only)
- Both log files are persistent across reboots and should be checked first when debugging

### MCP Integration
- Uses Anthropic SDK beta header: `mcp-client-2025-04-04`
- MCP servers configured with `authorization_token` (not `api_key` or `bearer`)
- Graceful degradation: if tokens are missing, scripts continue without MCP access
- The SDK parameter is `mcp_servers` (list of dicts with `name`, `url`, `authorization_token`)

### Bash Script Conventions
- All `.sh` files use `set -euo pipefail` for strict error handling
- `run_morning_brief.sh` uses `trap on_failure ERR` to send iMessage on unexpected failures
- `deploy.sh` uses `trap on_failure ERR` similarly
- Keychain reads use: `security find-generic-password -a "$USER" -s "<key-name>" -w`
- Missing Keychain entries cause immediate exit with a descriptive error
- Token refresh always runs before reading tokens (tokens expire in ~1 hour)

---

## Setup & First-Time Configuration

```bash
# 1. Install dependencies
uv sync

# 2. Store Anthropic API key
security add-generic-password -a "$USER" -s "morning-brief-anthropic-key" -w "sk-ant-..."

# 3. Store iMessage target
security add-generic-password -a "$USER" -s "morning-brief-imessage-target" -w "+15551234567"

# 4. Authorize Google services (runs browser OAuth flow)
uv run oauth_setup.py

# 5. Test the morning brief
bash run_morning_brief.sh

# 6. Install launchd agents (weekdays: deploy at 7am, brief at 8am)
# Plist files are in automation/plists/
cp ~/Code/automation/plists/com.andychiu.automation.deploy.plist ~/Library/LaunchAgents/
cp ~/Code/automation/plists/com.andychiu.automation.morning-brief.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.andychiu.automation.deploy.plist
launchctl load ~/Library/LaunchAgents/com.andychiu.automation.morning-brief.plist
# Verify both are loaded:
# launchctl list | grep andychiu

# 7. (Optional) Enable the /morning-brief Claude Code skill globally
ln -sf ~/Code/automation/scripts/.claude/skills/morning-brief ~/.claude/skills/morning-brief
```

---

## Development Notes

- **Do not add markdown formatting** to Claude responses — they are delivered as plain iMessages
- **Model:** `claude-haiku-4-5-20251001`. MCP server enforces a ~5-minute connection timeout. Prompt is constrained to 2 tool calls max (calendar + email) to stay within it. `sent_awaiting_reply` was removed as it required extra MCP calls.
- **Deploy is separate from the briefing** — merge to `master` and `deploy.sh` picks it up at 7am
- **Token refresh** must happen before every token read — Google tokens expire in ~1 hour
- **`check_api_key.py`** only tests the Anthropic API key. Use `TROUBLESHOOTING.md` for MCP issues
- `main.py` is a placeholder and not used by any production script
- Unit tests (`test_morning_brief.py`) are fully offline and safe to run anywhere
- Integration tests (`test_environment.py`) require macOS + Keychain — will fail in CI/sandboxes

---

## MCP Server Auth vs API Key Auth

This project uses remote MCP servers (Google Calendar, Gmail) that require **separate OAuth tokens** from the Anthropic API key. When debugging:

- Do NOT assume a working API key means everything is authenticated. MCP servers have their own OAuth tokens stored in macOS Keychain (`morning-brief-gcal-token`, `morning-brief-gmail-token`).
- The error `Authentication error while communicating with MCP server` means the **Google OAuth token** is missing, expired, or invalid — not the Anthropic API key.
- Always check both: (1) Anthropic API key validity via `check_api_key.py`, and (2) MCP OAuth token presence and freshness.
- See `TROUBLESHOOTING.md` for the full diagnostic guide.
