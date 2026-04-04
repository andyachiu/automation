# Morning Brief - macOS Automation Toolkit

A macOS automation toolkit that uses Claude AI with Google Calendar and Gmail to deliver daily briefings via iMessage.

## What It Does

- **Morning Briefing** — Daily summary of today's calendar, emails, reminders, weather, and allergy shot status, delivered to iMessage
- **Evening Briefing** — Look-ahead for tomorrow's schedule, reminders, pending replies, and what to prepare tonight

Features:
- Apple Reminders integration: overdue + due-today/tomorrow items read directly from macOS Reminders SQLite DB
- Weather via wttr.in injected as context
- Monday/Friday modes: week-ahead preview on Mondays, next-week kickoff on Fridays
- Allergy shot check on Mon/Wed/Fri: next appointment or reminder to book
- Two email sections: `🚨 URGENT` (direct + time-sensitive) and `📧 HIGHLIGHTS` (newsletters, shipping, notable items)
- Emoji-sectioned output optimized for iMessage readability
- Failure notifications via iMessage if a briefing or deploy fails
- Persistent logging to `~/.morning_brief.log`, `~/.evening_brief.log`, `~/.morning_brief_deploy.log`
- Separate deploy agent so code updates never block the morning briefing

## Requirements

- macOS (uses Keychain, `osascript`, Messages app)
- Python >= 3.13.6 with [`uv`](https://docs.astral.sh/uv/)
- [Anthropic API key](https://console.anthropic.com/)
- Google account (for Calendar and Gmail access)

## Quick Start

```bash
# 1. Install dependencies
uv sync

# 2. Store your Anthropic API key in Keychain
security add-generic-password -a "$USER" -s "morning-brief-anthropic-key" -w "sk-ant-..."

# 3. Store your iMessage target (phone number or email)
security add-generic-password -a "$USER" -s "morning-brief-imessage-target" -w "+15551234567"

# 4. Authorize Google Calendar and Gmail (opens browser for OAuth)
uv run oauth_setup.py

# 5. Test it
bash run_morning_brief.sh
```

## Verify Your Setup

Before scheduling, confirm everything is configured correctly on your **local Mac**:

```bash
# Human-readable preflight check (shows what's missing and how to fix it)
uv run check_setup.py

# Full test suite: environment validation + unit tests
uv run pytest tests/ -v
```

The environment tests check:
- Running on macOS (not a sandbox or container)
- `security`, `osascript`, `uv`, and `git` are available
- All required scripts are present
- All Keychain entries exist and are non-empty
- Google OAuth client credentials are valid JSON

> **Note:** The `/morning-brief` Claude Code skill uses Claude Code's own MCP auth (separate from the Python SDK OAuth tokens). It requires Keychain access and the Messages app for iMessage delivery. If invoked from a sandboxed environment, iMessage delivery will be skipped.

## Schedule Daily Briefings

Scheduling is handled via launchd. Render machine-local plist files into `~/Library/LaunchAgents/` and then load them:

```bash
uv run install_launch_agents.py

launchctl load ~/Library/LaunchAgents/com.andychiu.automation.deploy.plist
launchctl load ~/Library/LaunchAgents/com.andychiu.automation.morning-brief.plist
launchctl load ~/Library/LaunchAgents/com.andychiu.automation.evening-brief.plist
# Verify:
launchctl list | grep andychiu
```

Default schedule: deploy at 6am, morning brief at 7am weekdays / 9am weekends, evening brief at 9pm daily.

Logs:
- `~/.morning_brief.log` — morning briefing run logs
- `~/.evening_brief.log` — evening briefing run logs
- `~/.morning_brief_deploy.log` — deploy logs (git pull, uv sync)

## Auto-Deploy from GitHub

`deploy.sh` handles code updates independently from the briefing run:

```
deploy.sh (6am launchd)
  ├── git fetch origin main
  ├── fast-forward local main only
  ├── uv sync (install/update dependencies)
  ├── Log to ~/.morning_brief_deploy.log
  └── On failure: send iMessage notification
```

Separating deploy from the briefing means a git network error at 6am won't prevent your 7am brief. The briefing always runs on whatever code is currently on disk.

To run a deploy manually:

```bash
bash deploy.sh
```

## Claude Code Skill

This repo includes a `/morning-brief` skill for Claude Code. To make it available globally:

```bash
ln -sf "$(pwd)/.claude/skills/morning-brief" ~/.claude/skills/morning-brief
```

Then you can say "get my morning brief" in any Claude Code session.

## How It Works

```
deploy.sh (6am)                    run_morning_brief.sh (7am)         run_evening_brief.sh (9pm)
  ├── git fetch + ff-only merge      ├── Read keys from Keychain           ├── Read keys from Keychain
  ├── uv sync                        ├── Refresh Google OAuth tokens        ├── Refresh Google OAuth tokens
  └── log / notify on failure        ├── Read fresh tokens                  ├── Read fresh tokens
                                     └── morning_brief.py                   └── evening_brief.py
                                         ├── Fetch weather (wttr.in)            ├── Fetch weather (wttr.in)
                                         ├── Fetch reminders (SQLite DB)        ├── Fetch reminders (SQLite DB)
                                         ├── Build prompt (Mon/Fri/allergy)     ├── Build prompt
                                         ├── Call Haiku + Calendar/Gmail MCP    ├── Call Haiku + Calendar/Gmail MCP
                                         ├── Parse JSON → emoji sections        ├── Parse JSON → emoji sections
                                         ├── Send via iMessage                  ├── Send via iMessage
                                         └── On failure: send error iMessage    └── On failure: send error iMessage
```

## Output Format

**Morning brief:**
```
☀️ Wed Mar 26 | san francisco: ⛅  +62°F

📅 SCHEDULE
• 9:00 AM — Allergy Shot
• 2:00 PM — 1:1 with advisor (prep needed)

🚨 URGENT
• Prof. Lee: grant deadline — reply needed today

📧 HIGHLIGHTS
• Necessary Ventures: AI shift from academia; SPACs making a comeback
• Target: package from order #912003 has arrived

✅ REMINDERS
• [OVERDUE] File expense report
• Call Center to reschedule appointment

🩹 ALLERGY SHOT
Next shot: Thu Mar 26 at 9:00 AM

Focus: reply to Prof. Lee before your 2 PM.
```

On Mondays a `📅 WEEK AHEAD` section is added; on Fridays a `📅 NEXT WEEK` section.

**Evening brief:**
```
🌙 Tomorrow, Thu Mar 27 | san francisco: 🌧  +58°F

📅 TOMORROW
• 9:00 AM — Allergy Shot
• 2:00 PM — 1:1 with advisor (prep needed)

📬 PENDING REPLIES
• Prof. Lee: grant deadline — needs response

📧 HIGHLIGHTS
• Necessary Ventures: weekly VC digest

✅ REMINDERS
• [OVERDUE] File expense report

Tonight: prep talking points for the 2 PM 1:1.
```

## Authentication

The project uses two independent auth systems:

| System | Purpose | Keychain Entry |
|--------|---------|----------------|
| Anthropic API Key | Claude API access | `morning-brief-anthropic-key` |
| Google OAuth (Calendar) | Calendar MCP server | `morning-brief-gcal-token` |
| Google OAuth (Gmail) | Gmail MCP server | `morning-brief-gmail-token` |
| iMessage Target | Delivery address | `morning-brief-imessage-target` |

Google tokens expire hourly and are refreshed automatically. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for auth issues.

## Project Structure

```
├── morning_brief.py        # Morning briefing (today's schedule, emails, reminders, weather, allergy shot)
├── evening_brief.py        # Evening look-ahead (tomorrow's schedule, reminders, pending replies)
├── deploy.sh               # Pulls latest code and syncs dependencies (6am launchd)
├── run_morning_brief.sh    # Production wrapper: token refresh + morning brief
├── run_evening_brief.sh    # Production wrapper: token refresh + evening brief
├── oauth_setup.py          # One-time Google OAuth setup
├── shared/
│   ├── __init__.py
│   ├── reminders.py        # Reads incomplete reminders from macOS Reminders SQLite DB
│   └── refresh_tokens.py   # Refreshes expired Google OAuth tokens
├── check_setup.py          # Preflight environment check
├── check_api_key.py        # Validates Anthropic API key
├── allergy-shot-check/
│   ├── check_allergy_shot.sh   # Standalone allergy appointment reminder
│   ├── check_allergy_shot.py   # Python helper for allergy shot check
│   └── README.md
├── tests/
│   ├── __init__.py
│   ├── test_morning_brief.py  # Unit tests for morning brief (offline, fully mocked)
│   ├── test_reminders.py      # Unit tests for reminders module + brief integration
│   ├── test_mcp_setup.py      # Tests for OAuth, token refresh, MCP config, skill
│   └── test_environment.py    # Environment/integration tests (macOS only)
├── .claude/skills/
│   └── morning-brief/      # /morning-brief Claude Code skill
│       └── SKILL.md
├── pyproject.toml          # Python project config (anthropic>=0.86.0)
├── CLAUDE.md               # Development notes and conventions
└── TROUBLESHOOTING.md      # Diagnostic guide for MCP and iMessage issues
```
