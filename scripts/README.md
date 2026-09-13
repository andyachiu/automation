# AI workflow tooling — setup and operations

This guide covers running the scheduled briefing workflows. For the project narrative, architecture, implementation map, and capability boundaries, start with the [repository overview](../README.md).

Commands below assume you are in the repository’s `scripts/` directory. Briefing entrypoints deliver real messages; setup checks inspect the local environment and credentials.

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
- Python 3.13.6 (the exact version pinned in `pyproject.toml`) with [`uv`](https://docs.astral.sh/uv/)
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

# 4. One-time: create a Google Cloud OAuth client (Desktop app type) with
#    Calendar API + Gmail API enabled and the consent screen published to
#    "In production" (avoids 7-day refresh-token expiry in Testing mode).
#    Then authorize:
export GOOGLE_OAUTH_CLIENT_ID="<client_id>.apps.googleusercontent.com"
export GOOGLE_OAUTH_CLIENT_SECRET="<client_secret>"
uv run oauth_setup.py

# 5. Run a briefing (sends a real iMessage)
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

To disable memory for both scheduled briefings, run `uv run install_launch_agents.py --memory disabled --reload` from `scripts/`. Use `--memory enabled --reload` to enable it again. Omitting `--memory` preserves the destination's saved setting (new installs default to enabled). Reload failures exit non-zero. Briefings continue to run, and stored history is retained. See [memory controls](../docs/MEMORY.md#enable-or-disable-memory-for-scheduled-briefings) for manual-run differences and deletion.

### Mac state requirements

launchd's `StartCalendarInterval` only fires when the Mac is awake. If the Mac is sleeping at the scheduled time, the job fires on next wake (which may be much later). To guarantee on-time delivery — including from sleep or lid-closed travel scenarios — schedule a system wake five minutes before the earliest daily brief:

```bash
sudo pmset repeat wakeorpoweron MTWRFSU 06:55:00
```

Verify with `pmset -g sched`. Cancel with `sudo pmset repeat cancel`.

| Mac state at brief time | Brief fires? |
|---|---|
| Awake (lid open or display sleep, system awake) | ✓ |
| Sleeping, on power, `pmset` wake set | ✓ (Mac wakes, brief runs, iMessage delivers to iPhone via iCloud) |
| Sleeping, on battery | Usually ✓, but macOS may refuse to wake at low battery |
| **Fully shut down** | ✗ — `wakeorpoweron` won't boot a powered-off Mac. Brief fires only after next login. |

Limitation: `pmset` allows only one repeating wake event, so a single wake time has to cover both the 7am weekday and 9am weekend brief. Setting it to `06:55:00` works for weekdays; on weekends the Mac wakes 2h early and may go back to sleep before the 9am fire. Weekend reliability is best-effort.

For decoupled-from-laptop reliability (works even when laptop is off), the brief would need to run on a separate always-on host (Mac mini, home server) — not implemented.

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

The [repository-level `/morning-brief` skill](../.claude/skills/morning-brief/SKILL.md) describes an assistant-invoked workflow using host-provided connectors. It is separate from the scheduled Python pipeline and depends on a compatible, configured host. To make it available globally from `scripts/`:

```bash
mkdir -p ~/.claude/skills
ln -sfn "$(cd .. && pwd)/.claude/skills/morning-brief" ~/.claude/skills/morning-brief
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
                                         ├── Fetch calendar + email (Google)    ├── Fetch calendar + email (Google)
                                         ├── Build prompt (Mon/Fri/allergy)     ├── Build prompt
                                         ├── Call Haiku with data inlined       ├── Call Haiku with data inlined
                                         ├── Parse JSON → emoji sections        ├── Parse JSON → emoji sections
                                         ├── Send via iMessage                  ├── Send via iMessage
                                         └── On failure: send error iMessage    └── On failure: send error iMessage
```

## Output Format

**Morning brief** (illustrative format):
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

**Evening brief** (illustrative format):
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
| Google OAuth Client | Your Cloud OAuth client (id + secret) | `morning-brief-google-client` |
| Google Access Token | Calendar + Gmail (refreshed hourly) | `morning-brief-google-token` |
| Google Refresh Token | Used to mint new access tokens | `morning-brief-google-refresh-token` |
| iMessage Target | Delivery address | `morning-brief-imessage-target` |

Google access tokens expire hourly and are refreshed automatically by `shared/refresh_tokens.py` against `oauth2.googleapis.com/token`. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) for auth issues.

## Project Structure

```
├── morning_brief.py        # Morning briefing (today's schedule, emails, reminders, weather, allergy shot)
├── briefing_memory.py      # Local history/preference inspection and management
├── evening_brief.py        # Evening look-ahead (tomorrow's schedule, reminders, pending replies)
├── deploy.sh               # Pulls latest code and syncs dependencies (6am launchd)
├── run_morning_brief.sh    # Production wrapper: token refresh + morning brief
├── run_evening_brief.sh    # Production wrapper: token refresh + evening brief
├── oauth_setup.py          # One-time Google OAuth setup
├── shared/
│   ├── __init__.py
│   ├── briefing_common.py  # Claude call (no tools, data inlined) + iMessage send + JSON parse
│   ├── google_api.py       # Direct REST against googleapis.com (Calendar + Gmail)
│   ├── memory.py           # Private SQLite history + explicit preferences
│   ├── reminders.py        # Reads incomplete reminders from macOS Reminders SQLite DB
│   ├── refresh_tokens.py   # Refreshes the Google access token
│   └── system.py           # Tiny helpers (e.g. current_user)
├── check_setup.py          # Preflight environment check
├── check_api_key.py        # Validates Anthropic API key
├── allergy-shot-check/
│   ├── check_allergy_shot.sh   # Standalone allergy appointment reminder
│   ├── check_allergy_shot.py   # Direct Calendar fetch + local regex match (no LLM)
│   └── README.md
├── tests/
│   ├── __init__.py
│   ├── test_morning_brief.py     # Unit tests for morning brief (offline, fully mocked)
│   ├── test_memory.py            # Persistence, retention, and briefing memory failure paths
│   ├── test_google_api.py        # Calendar pagination and later-page failures
│   ├── test_reminders.py         # Unit tests for reminders module + brief integration
│   ├── test_launch_agents.py     # plist render correctness
│   ├── test_operational_scripts.py  # Wrapper failure-notification behavior
│   └── test_environment.py       # Environment/integration tests (macOS only)
├── pyproject.toml          # Python project config (anthropic>=0.86.0)
└── TROUBLESHOOTING.md      # Diagnostic guide for OAuth and iMessage issues
```

## Persistent briefing memory

Morning and evening entrypoints share recent delivered briefings and explicitly saved presentation preferences. Memory is enabled by default when a recipient is configured. It is stored outside the checkout, survives process restarts and code updates, and is supplied as historical context in subsequent model requests. The separate Claude Code skill does not use this store.

From this directory, inspect counts without displaying personal text:

```bash
uv run briefing_memory.py status
uv run briefing_memory.py set-preference style "Use short sentences and spell out acronyms."
```

See [the memory guide](../docs/MEMORY.md) for retention, deletion, configuration, failure recovery, and the distinction between stored history and current facts. These management commands do not contact external services or send messages.
