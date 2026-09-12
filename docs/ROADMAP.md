# Workflow roadmap

[Back to the project overview](../README.md)

## Portfolio and examples

- [ ] Add a fixture-based, offline walkthrough of context → synthesis → delivery, with fictional calendar and email data.
- [ ] Narrow or separately substantiate the portfolio’s model-directed terminal-tool claim. This repository now implements cross-run briefing memory, but its scheduled Python workflow still owns the tool sequence.
- [x] Implement persistent briefing memory with bounded retrieval, retention/deletion controls, explicit preferences, and historical-context instructions. See [the memory guide](MEMORY.md).
- [ ] Evaluate memory-assisted briefings against a no-memory baseline using fictional repeated, changed, stale, and adversarial inputs. Current tests verify storage and integration, not model quality.
- [ ] Consider structured, source-linked follow-ups only after that evaluation; do not infer task completion from generated briefing text.

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
