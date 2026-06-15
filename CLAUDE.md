# automation — Agent Guidelines

These guidelines define repository rules, architecture, and conventions for all AI assistants (Gemini, Claude, Cursor, etc.) working in this workspace.

---

## 📌 Repository Rules

### 1. README maintenance (required)
Any non-trivial change to this repo must be reflected in `README.md` before the work is considered done:
- **Latest Updates** section — prepend a one-line bullet for the change. Trim entries older than the most recent ~5.
- **TODO / Ideas** section — check off or remove completed items. Add new follow-ups.
- **What's Here** / **Scheduling** table — update if a user-visible feature, agent, or schedule changed.

Skip README updates *only* for: formatting, typo fixes, or changes confined to `BUG_REPORT.md` / internal notes. When in doubt, update it. Stage README edits in the same commit as the code changes.

### 2. Fail loud
launchd-driven briefs must exit non-zero on permission, auth, or delivery failures — never swallow them into a "succeeded but empty" run. If you add a new failure path, surface it (raise / non-zero exit / loud log) rather than fall back.

### 3. Don't hand-edit plists
`plists/*.plist` and `~/Library/LaunchAgents/com.andychiu.automation.*.plist` are rendered by `scripts/install_launch_agents.py`. Change the renderer, re-run `uv run install_launch_agents.py`, then reload the affected agent. Hand-edits will be clobbered on the next install.

---

## 📁 Repository Structure

```
automation/
├── plists/                 # launchd agents (copy to ~/Library/LaunchAgents/ to schedule)
├── .claude/
│   └── skills/
│       └── morning-brief/  # Custom agent skill definitions
│           └── SKILL.md
└── scripts/                # Python project root (uv, pyproject.toml)
    ├── morning_brief.py        # Generates and sends daily morning briefing
    ├── evening_brief.py        # Generates and sends evening look-ahead briefing
    ├── deploy.sh               # Pulls latest code from GitHub + runs uv sync
    ├── run_morning_brief.sh    # Production wrapper: token refresh + morning_brief.py
    ├── run_evening_brief.sh    # Production wrapper: token refresh + evening_brief.py
    ├── check_api_key.py        # Validates Anthropic API key only
    ├── check_setup.py          # Preflight environment check
    ├── oauth_setup.py          # One-time OAuth authorization flow for Google services
    ├── shared/
    │   ├── briefing_common.py  # Common API call, formatting, and iMessage utils
    │   ├── reminders.py        # Reads incomplete reminders from macOS Reminders SQLite DB
    │   ├── refresh_tokens.py   # Refreshes expired Google OAuth access tokens
    │   ├── google_api.py       # REST client for Google Calendar & Gmail
    │   └── system.py           # Core OS/user helper utilities
    ├── allergy-shot-check/     # Standalone allergy shot cron check
    ├── tests/                  # Pytest unit and integration test suite
    └── pyproject.toml          # uv python project configuration
```

---

## 🔐 Authentication Architecture

Three systems must be functional for run-time executions:

### 1. API Keys (Stored in Keychain)
- Anthropic key: `morning-brief-anthropic-key` (value starts with `sk-ant-`)
- Gemini key (optional): `morning-brief-gemini-key`

### 2. Google OAuth (Direct REST)
- Secure token storage in Keychain:
  - `morning-brief-google-client` — JSON `{client_id, client_secret}`
  - `morning-brief-google-refresh-token` — Long-lived refresh token
  - `morning-brief-google-token` — Short-lived access token (~1h)
- Token refreshing is managed by `scripts/shared/refresh_tokens.py` before wrapper executions.

### 3. iMessage Target
- Stored in Keychain: `morning-brief-imessage-target` (phone number or email)

---

## 💻 Execution & Setup

All python operations must be executed from the `scripts/` directory:

```bash
cd scripts

# 1. Install dependencies
uv sync

# 2. Preflight checks
uv run check_setup.py

# 3. Running tests
uv run pytest
```

---

## 🛠️ Key Conventions

### 1. Briefing Output Format
- LLMs return a **JSON object** (not plain text) — `format_briefing()` converts it to readable iMessage text.
- Plain text fallbacks are handled gracefully.
- Final messages are truncated to 1200 characters before delivery to prevent iMessage XPC hangs.
- No markdown, no asterisks, and no emoji inside values returned by the LLM prompt.

### 2. Google API Calls
- All Google integrations are direct REST calls against `googleapis.com` (Calendar v3, Gmail v1).
- Direct token parsing is managed in `scripts/shared/google_api.py`.

### 3. Logging
- Morning Brief: `~/.morning_brief.log`
- Evening Brief: `~/.evening_brief.log`
- Deploy: `~/.morning_brief_deploy.log`
