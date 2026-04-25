# automation

macOS automation scripts using Claude AI, Google Calendar, and Gmail.

## TODO / Ideas

Running list of capabilities to build out next. Newest at the top.

- [ ] **De-risk the uv → TCC Full Disk Access dependency**
  - **Background:** launchd agents in this repo run `uv run python <script>` via shell wrappers. macOS TCC's responsible-process model attributes Reminders DB reads (and any other TCC-gated access) to `uv` itself, so FDA must be granted to `/Users/<you>/.local/bin/uv`. TCC keys grants by code signature, so every `uv self update` / brew upgrade silently invalidates the existing grant — and the user has to fully `−` and re-add the entry in System Settings (toggling off/on does not capture the new signature). Most recent breakage: 2026-04-25, ~8 months after the prior uv upgrade. Loud-failure surface lives in `shared/reminders.py::_find_db()` (PR #7) and is documented in `scripts/TROUBLESHOOTING.md` under "Reminders DB read silently returns empty".
  - [ ] **Switch FDA target from `uv` to the venv's python.** Change `run_morning_brief.sh` / `run_evening_brief.sh` to invoke `<repo>/scripts/.venv/bin/python3 morning_brief.py` directly instead of `uv run python morning_brief.py`. `deploy.sh` already runs `uv sync` so the venv is provisioned. The venv's python interpreter only changes when the Python version changes (rare), not on every uv update — granting FDA to it should be a one-time setup. Also update `TROUBLESHOOTING.md` to document the new FDA target and remove the uv-upgrade-staleness section (or downgrade it to "legacy"). Verify by running the wrapper once after re-granting FDA, then `uv self update` and confirming the brief still reads reminders without re-granting.
  - [ ] **Detect uv binary changes and warn early.** Add a preflight in the wrapper (or `shared/reminders.py`) that caches `uv`'s sha256 (or `stat -f %m %z`) on the last successful FDA-passing run (e.g. in `~/.cache/automation/uv-fingerprint`) and emits a loud log line + non-zero exit when the fingerprint differs. Even after fix #1 lands, this catches any residual TCC-attribution surprises and turns "what broke 8 months later" into "uv changed, re-verify FDA now." Cheap insurance; no behavior change when nothing has shifted.
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

## Latest Updates

- **TROUBLESHOOTING: clarified uv FDA re-grant** — toggling the FDA switch off/on is not sufficient after a uv upgrade; the entry must be removed (`−`) and re-added so TCC captures the new code signature
- **Shared Claude Code settings tracked** (#9) — project `.claude/settings.json` is checked in; local overrides and worktrees stay ignored
- **Loud-failure paths documented** (#8) — troubleshooting guide for the failure modes surfaced in #7
- **Fail loud on stale TCC + wedged BlastDoor** (#7) — launchd agents now exit non-zero instead of silently dropping briefs when macOS permissions or iMessage delivery are broken
- **Direct Google API path** (#6) — briefs can hit Calendar/Gmail directly via OAuth; remote MCP servers are now opt-in

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
```

| Agent | Schedule | What it does |
|-------|----------|--------------|
| `deploy` | 6 AM weekdays | Fast-forward `main` + `uv sync` |
| `morning-brief` | 7 AM weekdays, 9 AM weekends | Today's events + urgent emails |
| `evening-brief` | 9 PM daily | Tomorrow's events + pending replies |
