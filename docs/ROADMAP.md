# Workflow roadmap

[Back to the project overview](../README.md)

## Portfolio and examples

- [ ] Add a fixture-based, offline walkthrough of context → synthesis → delivery, with fictional calendar and email data.
- [ ] Reconcile the portfolio’s cross-session memory and autonomous terminal-tool claims with the public implementation, or link a separate implementation that supports those claims. This repository currently provides neither.
- [ ] If persistent memory is introduced, define what is stored, how it is retrieved, retention/deletion controls, and how stale context is handled before presenting it as an implemented capability.

## Obsidian integration

Planned capabilities. These are not implemented in the current scheduled briefing pipeline.

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
