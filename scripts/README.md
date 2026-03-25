# Morning Brief - macOS Automation Toolkit

A macOS automation toolkit that uses Claude AI with Google Calendar and Gmail to deliver daily briefings and interactive chat via iMessage.

## What It Does

- **Morning Briefing** — Scheduled daily summary of your calendar events and emails, delivered straight to iMessage
- **Interactive Chat** — Ask Claude questions with full calendar/email context from the command line

Features:
- Weather via wttr.in injected as context
- Monday mode: adds a week-at-a-glance section on Mondays
- Structured JSON output formatted into clean, scannable plain text
- Smarter email urgency filtering (direct recipients, time-sensitive language, 24h window)
- Failure notifications via iMessage if the briefing or deploy fails
- Persistent logging to `~/.morning_brief.log` and `~/.morning_brief_deploy.log`
- Separate deploy cron so code updates never block the 8am briefing

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

> **Note:** The `/morning-brief` Claude Code skill runs `run_morning_brief.sh` on your **local Mac**. It requires Keychain access and the Messages app. If invoked from a sandboxed environment, Keychain reads will fail and no iMessage will be sent.

## Schedule Daily Briefings

Two cron jobs: one to deploy at 7am, one to run the brief at 8am.

```bash
crontab -e
# Add these two lines (adjust the path):
0 7 * * 1-5 /Users/andychiu/Code/automation/scripts/deploy.sh
0 8 * * 1-5 /Users/andychiu/Code/automation/scripts/run_morning_brief.sh
```

Logs:
- `~/.morning_brief.log` — briefing run logs (token refresh, Claude API, iMessage delivery)
- `~/.morning_brief_deploy.log` — deploy logs (git pull, uv sync)

## Auto-Deploy from GitHub

`deploy.sh` handles code updates independently from the briefing run:

```
deploy.sh (7am cron)
  ├── git pull origin master
  ├── uv sync (install/update dependencies)
  ├── Log to ~/.morning_brief_deploy.log
  └── On failure: send iMessage notification
```

Separating deploy from the briefing means a git network error at 7am won't prevent your 8am brief. The briefing always runs on whatever code is currently on disk.

To run a deploy manually:

```bash
bash deploy.sh
```

## Interactive Chat

```bash
# Ask a question (uses calendar/email context)
bash ask_claude.sh "What meetings do I have today?"

# Ask and send the response via iMessage
bash ask_claude.sh --send "Summarize my unread emails"
```

Conversation history resets daily and is stored locally in `.conversation_history.json`.

## Claude Code Skill

This repo includes a `/morning-brief` skill for Claude Code. To make it available globally:

```bash
ln -sf ~/Code/automation/scripts/.claude/skills/morning-brief ~/.claude/skills/morning-brief
```

Then you can say "get my morning brief" in any Claude Code session.

## How It Works

```
deploy.sh (7am)                    run_morning_brief.sh (8am)
  ├── git pull origin master         ├── Read API key + iMessage target from Keychain
  ├── uv sync                        ├── Refresh Google OAuth tokens
  └── log / notify on failure        ├── Read fresh tokens from Keychain
                                     └── morning_brief.py
                                         ├── Fetch weather from wttr.in
                                         ├── Build prompt (Monday mode if applicable)
                                         ├── Call Claude (Haiku) with Calendar + Gmail MCP
                                         ├── Parse JSON response → format as plain text
                                         ├── Send via iMessage
                                         └── On any failure: send error iMessage
```

## Output Format

Briefings are structured plain text, e.g.:

```
Sat Mar 21 | San Francisco: Sunny +68F
2 meetings, 1 urgent email

9 AM: Standup
2 PM: 1:1 with advisor (prep needed)

Emails:
Reply ASAP: grant deadline from Prof. Lee

Focus: send thesis chapter before 2 PM
```

On Mondays, a "Week ahead:" section is added after the events.

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
├── morning_brief.py        # Generates and sends daily briefing
├── deploy.sh               # Pulls latest code and syncs dependencies (7am cron)
├── run_morning_brief.sh    # Production wrapper: token refresh + briefing (8am cron)
├── ask_claude.py           # Interactive chat with conversation history
├── ask_claude.sh           # Bash wrapper for ask_claude.py
├── oauth_setup.py          # One-time Google OAuth setup
├── shared/
│   └── refresh_tokens.py   # Refreshes expired Google OAuth tokens
├── check_setup.py          # Preflight environment check
├── check_api_key.py        # Validates Anthropic API key
├── allergy-shot-check/
│   └── check_allergy_shot.sh  # Allergy appointment reminder
├── tests/
│   ├── test_morning_brief.py  # Unit tests (offline, fully mocked)
│   └── test_environment.py    # Environment/integration tests (macOS only)
├── .claude/skills/
│   └── morning-brief/      # /morning-brief Claude Code skill
├── CLAUDE.md               # Development notes and conventions
└── TROUBLESHOOTING.md      # Auth diagnostic guide
```
