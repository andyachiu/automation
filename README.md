# automation

macOS automation scripts using Claude AI, Google Calendar, and Gmail.

## TODO / Ideas

Running list of capabilities to build out next. Newest at the top.

- [ ] **Obsidian note-taking integration**
  - [ ] Vault path + config: resolve vault location from env (`OBSIDIAN_VAULT`) with sane macOS default; store in `scripts/config.py` alongside other paths
  - [ ] Decide access layer: direct filesystem read/write (simpler, no daemon) vs. Obsidian Local REST API plugin (richer: open note, run commands) — start with filesystem, revisit if we need live UI actions
  - [ ] Daily-note helpers: locate/create today's daily note from the vault's daily-note template, append-section primitive (`append_to_section(note, heading, body)`) that respects existing headings
  - [ ] Brief → daily note: morning + evening briefs append a dated block to today's daily note in addition to iMessage delivery
  - [ ] Search + read: wrap `ripgrep` over the vault for full-text search; expose `read_note(path)` and `list_notes(folder)` helpers
  - [ ] Frontmatter + tags: parse/write YAML frontmatter so generated notes get consistent tags (`#brief/morning`, `#source/automation`)
  - [ ] Link graph queries: resolve `[[wikilinks]]` and backlinks; helper to list notes linking to a given note (for context gathering)
  - [ ] Note drafting from chat: capture-style script that takes a transcript or prompt and writes a new note under `Inbox/` with frontmatter + a link back to the source
  - [ ] Tests: fixture vault under `scripts/tests/fixtures/vault/` so all of the above can run without touching the real vault
- [ ]

## What's Here

- **Morning brief** — Daily calendar + email summary delivered via iMessage at 7 AM on weekdays
- **Evening brief** — Next-day look-ahead with pending email reminders, delivered at 9 PM daily
- **Allergy shot check** — Mon/Wed/Fri reminder via iMessage if no allergy shot appointment is on the calendar within 30 days

## Latest Updates

- **Migrated off the retired Anthropic hosted MCP proxy → direct Google OAuth** — `gcal.mcp.claude.com` / `gmail.mcp.claude.com` started returning 404 on every path. `oauth_setup.py` and `shared/refresh_tokens.py` now go straight to `accounts.google.com` / `oauth2.googleapis.com` using your own Google Cloud OAuth client (`morning-brief-google-client` in Keychain). Single token covers both Calendar and Gmail. MCP-only code paths (`call_briefing_model` MCP variant, `BRIEFING_USE_MCP` env var, `tests/test_mcp_setup.py`, `probe_mcp.py`) removed. Allergy shot check switched to direct Calendar fetch + local regex match (no LLM call).
- **`/morning-brief` skill: BlastDoor vs TCC probes before iMessage send** — Step 4 now runs a Finder AppleEvent probe (tests Automation permission) and a Messages probe (tests BlastDoor health) so a `-1712` timeout points at the right fix instead of guessing. Also reads the iMessage target from `~/.config/morning-brief/target` first, Keychain as fallback.
- **Morning brief: 🎯 FOCUS section header** — `format_briefing` now renders the focus line with its own emoji header (matching SCHEDULE / HIGHLIGHTS / REMINDERS) instead of inline `Focus: …` so it stands out at the bottom of the brief
- **Switch FDA target from `uv` to the venv's python** — `run_morning_brief.sh` / `run_evening_brief.sh` now invoke `<repo>/scripts/.venv/bin/python3` directly. `uv` is no longer in the responsible-process chain, so `uv self update` / brew upgrades stop invalidating the FDA grant. Re-grant is now only needed on Python *version* upgrades. Wrappers also log the resolved python path on every run for post-mortem clarity.
- **TROUBLESHOOTING: clarified uv FDA re-grant** — toggling the FDA switch off/on is not sufficient after a uv upgrade; the entry must be removed (`−`) and re-added so TCC captures the new code signature
- **Shared Claude Code settings tracked** (#9) — project `.claude/settings.json` is checked in; local overrides and worktrees stay ignored

## Structure

```
automation/
├── plists/          # launchd agents for scheduling
└── scripts/         # Python project (uv)
```

See [`scripts/README.md`](scripts/README.md) for setup instructions, authentication, and usage.

## Scheduling

Render machine-local launchd plists, then load them:

```bash
cd scripts
uv run install_launch_agents.py

launchctl load ~/Library/LaunchAgents/com.andychiu.automation.deploy.plist
launchctl load ~/Library/LaunchAgents/com.andychiu.automation.morning-brief.plist
launchctl load ~/Library/LaunchAgents/com.andychiu.automation.evening-brief.plist
launchctl load ~/Library/LaunchAgents/com.andychiu.allergy-shot-check.plist
```

| Agent | Schedule | What it does |
|-------|----------|--------------|
| `deploy` | 6 AM weekdays | Fast-forward `main` + `uv sync` |
| `morning-brief` | 7 AM weekdays, 9 AM weekends | Today's events + urgent emails |
| `evening-brief` | 9 PM daily | Tomorrow's events + pending replies |
| `allergy-shot-check` | 9 AM Mon/Wed/Fri | Reminds if no allergy shot scheduled in next 30 days |
