# Persistent briefing memory

[Project overview](../README.md) · [Setup and operations](../scripts/README.md)

Morning and evening briefings now share local memory across process restarts. Each run reads the recipient's recent delivered briefings before calling Claude, then saves its final formatted message only after the send function reports success. This lets the model connect today's context to earlier preparation and use explicitly saved presentation preferences.

For example, a morning briefing might mention preparing notes for a project review. If the evening's fresh calendar and email inputs support a follow-up, the model can connect it to that preparation. An old mention alone cannot establish that the notes are complete or a request is still open. This is an illustrative behavior, not a measured quality result.

## What persists

| Data | Storage and retrieval |
|---|---|
| Delivered briefing | Final message, capped at 1,200 characters; morning/evening kind; timestamp; hashed recipient identifier |
| Recent history | At most 14 messages across the store; entries older than seven days are deleted on the next read or write |
| Context for a run | Latest three messages for that recipient, presented chronologically with UTC timestamps; future-dated records excluded |
| Explicit preferences | Up to five presentation preferences, each up to 240 characters; shared across this local user's briefing runs until edited or removed |

The store does not copy raw email, calendar responses, credentials, or general chat history. Briefing text itself can contain personal information drawn from those sources. Retrieved history and preferences are sent to Anthropic as part of the subsequent briefing request. Recipient hashes separate histories; they are not encryption or anonymization of the briefing content.

The default location is `~/.local/share/automation/briefing-memory.sqlite3`. The final directory must be owned by the current user with private permissions (0700); the database is created with 0600 permissions. The database is not encrypted. It lives outside the repository, and SQLite memory files are also ignored by Git as a precaution.

## Local controls

Run these commands from `scripts/`. They require no credentials and make no network requests or message deliveries.

```bash
# Counts and retention only; does not print personal content
uv run briefing_memory.py status

# Intentionally display stored text and preferences in your terminal
uv run briefing_memory.py show

# Save or replace a presentation preference
uv run briefing_memory.py set-preference style "Use short sentences and spell out acronyms."
uv run briefing_memory.py forget-preference style

# Remove all remembered briefings and preferences
uv run briefing_memory.py clear --yes
```

Preferences influence phrasing and presentation. They cannot authorize new actions, change the required output format, or override current inputs. The system does not learn preferences automatically from generated output.

Deleting memory removes rows from this SQLite store with SQLite secure deletion enabled. It does not erase existing application logs, sent messages, backups, or data already sent to the model provider. The next successful briefing begins a new history. Retention runs on access, so an unused database can retain old entries until it is next opened by a memory operation.

## Configuration and rollout

- `AUTOMATION_MEMORY_ENABLED=1` is the default. Set it to `0` to bypass memory reads and writes; this does not delete stored data. Other values fail visibly.
- `AUTOMATION_MEMORY_PATH` overrides the database path. Use a dedicated private directory, not a shared folder. Both entrypoints and management commands must receive the same setting to share a store.
- No recipient means the existing stdout preview behavior, with no memory read or write. The separate assistant-invoked skill and appointment checker do not use this store.

Once this code is deployed, the next scheduled briefing with a recipient creates the empty database automatically. No migration of old logs or previous conversations occurs. Setting variables in an interactive terminal affects only processes launched from that environment; it does not reconfigure an already loaded launchd job. Follow the repository's renderer-based scheduling conventions for persistent launchd configuration.

## Failure behavior and limits

Unreadable, corrupt, insecure, or unsupported databases stop briefing preparation with a visible error rather than silently dropping memory. A failed model request or failed delivery adds no history. If delivery succeeds but the subsequent memory write fails, the process exits non-zero and logs that the message was already sent; do not resend merely to repair memory. Inspect the storage problem first. A process crash between delivery and saving can likewise leave a sent briefing unrecorded. Successful send means the delivery helper reported success, not proof that the recipient read it.

Model instructions label history as untrusted historical data and require fresh inputs to support current claims. These are instructions, not a guarantee against model errors or prompt injection. There is no automatic task-status inference, semantic search, autonomous tool loop, or note comparison. Offline tests verify persistence, bounded retrieval, recipient separation, prompt wiring, and failure handling; improvement in generated briefing quality still needs evaluation.

See [the offline tests](../scripts/tests/test_memory.py) and [remaining work](ROADMAP.md).
