# Project Notes

## Overview

This is a macOS automation toolkit that integrates Claude AI with Google Calendar and Gmail to provide:

1. **Morning Briefing** (`morning_brief.py`): Scheduled daily summary of calendar events and emails, delivered via iMessage
2. **Evening Briefing** (`evening_brief.py`): Look-ahead for tomorrow's schedule and pending replies, delivered via iMessage

**Platform:** macOS only (requires Keychain, `osascript`, Messages app)
**Runtime:** Python >=3.13.6, managed with `uv`
**Model:** `claude-haiku-4-5-20251001` (Haiku — fast/cheap is sufficient now that all data is fetched in-process and passed inline; Claude does formatting only, no tool calls)

---

## Repository Structure

```
automation/
├── plists/                 # launchd agents (copy to ~/Library/LaunchAgents/ to schedule)
│   ├── com.andychiu.automation.deploy.plist          # deploy at 6am
│   ├── com.andychiu.automation.morning-brief.plist   # morning brief at 7am weekdays / 9am weekends
│   ├── com.andychiu.automation.evening-brief.plist   # evening brief at 9pm daily
│   └── com.andychiu.allergy-shot-check.plist         # allergy check Mon/Wed/Fri
└── scripts/                # Python project root (uv, pyproject.toml)
    ├── morning_brief.py        # Generates and sends daily morning briefing
    ├── evening_brief.py        # Generates and sends evening look-ahead briefing
    ├── deploy.sh               # Pulls latest code from GitHub + runs uv sync
    ├── run_morning_brief.sh    # Production wrapper: token refresh + morning_brief.py
    ├── run_evening_brief.sh    # Production wrapper: token refresh + evening_brief.py
    ├── check_api_key.py        # Validates Anthropic API key only (not MCP connectivity)
    ├── check_setup.py          # Preflight environment check
    ├── oauth_setup.py          # One-time OAuth authorization flow for Google services
    ├── shared/
    │   ├── __init__.py
    │   ├── reminders.py        # Reads incomplete reminders from macOS Reminders SQLite DB
    │   └── refresh_tokens.py   # Refreshes expired Google OAuth access tokens
    ├── allergy-shot-check/
    │   ├── check_allergy_shot.sh   # Allergy appointment reminder via Claude + Calendar
    │   ├── check_allergy_shot.py   # Python helper for allergy shot check
    │   └── README.md
    ├── .claude/skills/
    │   └── morning-brief/      # Claude Code skill: /morning-brief
    │       └── SKILL.md
    ├── tests/
    │   ├── __init__.py
    │   ├── test_morning_brief.py  # Unit tests for morning brief (offline, all mocked)
    │   ├── test_reminders.py      # Unit tests for reminders module + brief integration
    │   ├── test_mcp_setup.py      # Tests for OAuth, token refresh, MCP config, skill
    │   └── test_environment.py    # Integration tests (macOS only, real Keychain)
    ├── pyproject.toml          # Python project config (anthropic>=0.86.0)
    ├── CLAUDE.md               # This file
    ├── TROUBLESHOOTING.md      # Diagnostic guide for MCP and iMessage issues
    └── README.md               # Project documentation and setup guide
```

---

## Authentication Architecture

Two independent auth systems must both be functional:

### 1. Anthropic API Key
- Stored in Keychain: `morning-brief-anthropic-key`
- Validated by `check_api_key.py`
- Set via: `security add-generic-password -a "$USER" -s "morning-brief-anthropic-key" -w "sk-ant-..."`

### 2. Google OAuth (direct against Google, no proxy)
- Single Google Cloud Console "Desktop app" OAuth client. Calendar API + Gmail API enabled. Consent screen published to "In production" so refresh tokens don't expire weekly.
- One PKCE authorization covers both scopes (`calendar.readonly` + `gmail.modify`). One refresh token for both.
- Keychain entries:
  - `morning-brief-google-client` — JSON `{client_id, client_secret}` (your Cloud Console credentials)
  - `morning-brief-google-refresh-token` — long-lived, used to mint access tokens
  - `morning-brief-google-token` — short-lived access token (~1h)
- `oauth_setup.py` runs the one-time PKCE flow against `accounts.google.com/o/oauth2/v2/auth` and `oauth2.googleapis.com/token`. First run reads client from `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` env vars and stores in Keychain; subsequent runs read from Keychain.
- `shared/refresh_tokens.py` refreshes against `oauth2.googleapis.com/token` and writes the new access token to Keychain. Called by every wrapper script.

### 3. iMessage Target
- Stored in Keychain: `morning-brief-imessage-target` (phone number or email)
- Set via: `security add-generic-password -a "$USER" -s "morning-brief-imessage-target" -w "+15551234567"`

**Historical:** Prior to 2026-05-24, this project routed OAuth through Anthropic-hosted proxies at `gcal.mcp.claude.com` / `gmail.mcp.claude.com`. Those endpoints (`/token`, `/register`, `/mcp`) were retired and now return 404, which is why everything is now direct against Google. `BUG_REPORT.md` documents the related MCP server bug filed before the migration.

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

### Morning Briefing (7am weekdays / 9am weekends launchd)
```
run_morning_brief.sh
  ├── trap on_failure ERR (sends error iMessage on any failure)
  ├── Read Anthropic API key from Keychain
  ├── Read iMessage target from Keychain
  ├── shared/refresh_tokens.py
  │   ├── Read morning-brief-google-client (client_id + client_secret) from Keychain
  │   ├── Read morning-brief-google-refresh-token from Keychain
  │   ├── POST to oauth2.googleapis.com/token (grant_type=refresh_token)
  │   └── Write new access token to morning-brief-google-token
  ├── Read fresh GOOGLE_TOKEN from Keychain
  └── morning_brief.py
      ├── get_weather() → wttr.in (plain text, empty string on failure)
      ├── get_reminders(today) → reads macOS Reminders SQLite DB (overdue + due today)
      ├── is_monday() → adds week-ahead section if True
      ├── get_briefing(weather, reminders_ctx)
      │   ├── list_calendar_events(GOOGLE_TOKEN, today, +30d) — direct REST against googleapis.com
      │   ├── list_unread_messages(GOOGLE_TOKEN, 20 or 50) — direct REST against gmail.googleapis.com
      │   └── call_briefing_model(...) → Claude Haiku, no tools, data inlined in the prompt
      ├── format_briefing(raw, weather) → plain text (falls back to raw if not valid JSON)
      ├── send_imessage() → BlastDoor pre-flight (pgrep) → osascript → Messages → iMessage
      │   └── If >1 MessagesBlastDoorService instances detected, fails fast with recovery
      │       instructions instead of waiting on a 30s AppleEvent timeout (Tahoe regression).
      │       See [TROUBLESHOOTING.md "iMessage Send Hangs on macOS Tahoe (BlastDoor Pile-Up)"](TROUBLESHOOTING.md#imessage-send-hangs-on-macos-tahoe-blastdoor-pile-up).
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

### Google API Calls
- All Google calls are direct REST against `googleapis.com` (Calendar v3, Gmail v1) — no MCP, no proxy.
- The `Authorization: Bearer <token>` header carries the access token from Keychain.
- `shared/google_api.py` is the only thing that talks to Google; bumps to scope or endpoint go there.

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

# 4. Authorize Google services (runs browser OAuth flow against Google directly)
#    First run needs the OAuth client from your Google Cloud Console project:
export GOOGLE_OAUTH_CLIENT_ID="<id>.apps.googleusercontent.com"
export GOOGLE_OAUTH_CLIENT_SECRET="<secret>"
uv run oauth_setup.py

# 5. Test the morning brief
bash run_morning_brief.sh

# 6. Install launchd agents (weekdays: deploy at 6am, brief at 7am)
uv run install_launch_agents.py
launchctl load ~/Library/LaunchAgents/com.andychiu.automation.deploy.plist
launchctl load ~/Library/LaunchAgents/com.andychiu.automation.morning-brief.plist
# Verify both are loaded:
# launchctl list | grep andychiu

# 7. (Optional) Enable the /morning-brief Claude Code skill globally
ln -sf "$(pwd)/.claude/skills/morning-brief" ~/.claude/skills/morning-brief
```

---

## Development Notes

- **Do not add markdown formatting** to Claude responses — they are delivered as plain iMessages
- **Model:** `claude-haiku-4-5-20251001`. No tool calls happen — calendar + email are fetched in Python and inlined in the prompt, so Claude only formats the output.
- **Deploy is separate from the briefing** — merge to `main` and `deploy.sh` picks it up at 6am
- **Token refresh** must happen before every token read — Google access tokens expire in ~1 hour
- **`check_api_key.py`** only tests the Anthropic API key. For OAuth issues, see `TROUBLESHOOTING.md` → "Google OAuth Token Refresh Fails"
- `main.py` is a placeholder and not used by any production script
- Unit tests (`test_morning_brief.py`, `test_reminders.py`, `test_launch_agents.py`, `test_operational_scripts.py`) are fully offline and safe to run anywhere
- Integration tests (`test_environment.py`) require macOS + Keychain — will fail in CI/sandboxes
