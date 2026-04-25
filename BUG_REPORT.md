# Bug: hosted Google Calendar + Gmail MCP servers advertise tool names that `tools/call` then rejects as "no longer exist"

## File at

1. **Primary:** [anthropics/claude-ai-mcp issues](https://github.com/anthropics/claude-ai-mcp/issues/new/choose) — this repo is Anthropic's stated channel for bugs in Claude.ai-hosted MCP servers (covers `*.mcp.claude.com`, OAuth, tool discovery).
2. **Secondary:** [support.anthropic.com](https://support.anthropic.com) — for tracking impact on a paid API account.

Do **not** file at `anthropics/anthropic-sdk-python` or `anthropics/claude-code` — this is a server-side bug, reproducible across SDK versions and outside Claude Code.

---

## Summary

The hosted Google Calendar (`gcal.mcp.claude.com`) and Gmail (`gmail.mcp.claude.com`) MCP servers are internally inconsistent: their `tools/list` endpoint advertises tool names (`gcal_list_events`, `gmail_search_messages`) that the same servers' `tools/call` endpoint then rejects with "the tool you tried to call no longer exists." The error tells the caller to "reload the page or start a new session," which is meaningless for direct API callers — every API call is already a fresh session.

## Impact

- Both Calendar and Gmail hosted MCP servers are **unusable from the Anthropic Messages API** (`client.beta.messages.create` with `mcp_servers`).
- Breaks any non-interactive / scheduled / automation workflow built on the MCP connector beta — there is no "session" to reload.
- First failure in our logs: **2026-04-23**. Last successful run: **2026-04-22 18:00 PT**. Broken every day since. The bug rolled out in the 2026-04-22 → 2026-04-23 window.

## Reproduction

Standalone reproducer: `/Users/andychiu/Code/automation/scripts/probe_mcp.py`. Minimal shape:

```python
import anthropic

client = anthropic.Anthropic()  # ANTHROPIC_API_KEY in env
response = client.beta.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=2048,
    system="...",
    messages=[{"role": "user", "content": "Summarize today's calendar and unread email."}],
    mcp_servers=[
        {"type": "url", "url": "https://gcal.mcp.claude.com/mcp",
         "name": "google-calendar", "authorization_token": GCAL_OAUTH_TOKEN},
        {"type": "url", "url": "https://gmail.mcp.claude.com/mcp",
         "name": "gmail", "authorization_token": GMAIL_OAUTH_TOKEN},
    ],
    tools=[
        {"type": "mcp_toolset", "mcp_server_name": "google-calendar"},
        {"type": "mcp_toolset", "mcp_server_name": "gmail"},
    ],
    betas=["mcp-client-2025-11-20"],
)
```

The model emits `mcp_tool_use` blocks with the names the server itself advertised; every resulting `mcp_tool_result` has `is_error: true` with the reload-session text.

## Expected vs actual

- **Expected:** `tools/call` accepts the tool names that `tools/list` just advertised; results return successfully.
- **Actual:** every call returns `mcp_tool_result` with `is_error: true` and the "tool no longer exists / reload your session" message.

## Evidence

From `/Users/andychiu/Code/automation/logs/mcp_probe_20260424-224504.json` (response `msg_01XP9BFex617ocbn38z48v65`, model `claude-haiku-4-5-20251001`, SDK `0.97.0`, beta `mcp-client-2025-11-20`):

Request block (one of two; the Gmail one is identical in shape):

```json
{
  "id": "mcptoolu_01GKMXFXVdNckSjsfLdJzcHV",
  "input": {
    "calendarId": "primary",
    "timeMin": "2026-04-25T00:00:00",
    "timeMax": "2026-04-25T23:59:59"
  },
  "name": "gcal_list_events",
  "server_name": "google-calendar",
  "type": "mcp_tool_use"
}
```

Matching response block:

```json
{
  "content": [
    {
      "citations": null,
      "text": "This Google Workspace integration was just upgraded and the tool you tried to call no longer exists. Your tool definitions are stale. Tell the user to reload them (e.g. refresh the page on web, or start a new session in Claude Code) and do not retry this tool call.",
      "type": "text"
    }
  ],
  "is_error": true,
  "tool_use_id": "mcptoolu_01GKMXFXVdNckSjsfLdJzcHV",
  "type": "mcp_tool_result"
}
```

The Gmail call (`gmail_search_messages`, `tool_use_id: mcptoolu_018TrfUKmScQBjkCHbb8bZXW`) returns the identical error.

The model picked these tool names because the server advertised them in this same exchange — they are not cached on the client side.

## Variants tried — all fail identically

| anthropic SDK | beta header                | tools shape                                | Result                       |
| ------------- | -------------------------- | ------------------------------------------ | ---------------------------- |
| 0.86.0        | `mcp-client-2025-04-04`    | `mcp_servers` only                         | stale names, rejected        |
| 0.97.0        | `mcp-client-2025-04-04`    | `mcp_servers` only                         | stale names, rejected        |
| 0.97.0        | `mcp-client-2025-11-20`    | `mcp_servers` + `mcp_toolset` in `tools`   | stale names, rejected        |

Reproducible across two SDK versions, both currently-documented MCP beta headers, and both old and new `mcp_toolset` config shapes. Not a client misconfig.

Three full request/response dumps available:

- `/Users/andychiu/Code/automation/logs/mcp_probe_20260424-224320.json`
- `/Users/andychiu/Code/automation/logs/mcp_probe_20260424-224407.json`
- `/Users/andychiu/Code/automation/logs/mcp_probe_20260424-224504.json`

## Suspected cause

The MCP server's `tools/list` is serving stale tool definitions while `tools/call` validates against a newer schema — the upgrade rolled out atomically on the call path but not on the discovery path (or vice versa). The "reload your session" guidance in the error message does not apply to direct API callers: each Messages API request is a fresh session, with `tools/list` re-fetched on every invocation. There is no client-side cache to invalidate. Until the discovery and call paths agree, the API connector is unusable.

## Environment

- Python 3.13
- `anthropic` 0.97.0 (also reproduced on 0.86.0)
- macOS (Darwin 25.4.0)
- Auth: Google OAuth via PKCE flow; access tokens refreshed successfully via the per-server `/token` endpoint immediately before each failed call (Google OAuth side is healthy — `Authentication error while communicating with MCP server` is **not** what we see; we see the `is_error: true` payload above, which only the MCP server itself can produce).
