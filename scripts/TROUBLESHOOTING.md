# Troubleshooting

## Non-Fatal Warnings (Normal Behavior)

These warnings appear in logs but do not indicate a failure — the briefing is still delivered.

### `WARNING Weather fetch failed: The read operation timed out`

`wttr.in` is an external service with a 5-second timeout. It will occasionally time out or be unavailable. The briefing runs without weather context in that case. No action needed.

### `WARNING Response was not valid JSON, using raw text`

Claude is instructed to return a JSON object, but occasionally returns plain text instead. `format_briefing()` falls back to the raw response text with a date header prepended. The briefing is still delivered — it just won't be as cleanly structured. No action needed unless it happens consistently (which would suggest a prompt or model issue).

---


## Wrong Environment: Sandbox or Container

### Symptoms

Scripts fail with errors like:
- `security: SecKeychainSearchCopyNext: The specified item could not be found in the keychain.`
- `osascript: can't open application "Messages"`
- `ANTHROPIC_API_KEY` is empty even though Keychain is populated
- Morning brief runs but no iMessage arrives
- `uv: command not found`

### Root Cause

This project **requires a real macOS environment** with full access to:
- **macOS Keychain** (`security` binary reading from your login keychain)
- **Messages app** via `osascript`
- **Your home directory** at `/Users/<you>/`

These are unavailable in Docker containers, Linux CI environments, and Claude Code sandboxes. The `/morning-brief` Claude Code skill must shell out to your **local Mac** — if Claude Code is running in a restricted environment, the skill invocation will silently fail or error.

### How to Diagnose

```bash
# Run the preflight check — prints exactly what's missing and how to fix it
uv run check_setup.py

# Or run the integration test suite for detailed output
uv run pytest tests/test_environment.py -v
```

### How to Fix

1. Run scripts directly in your local terminal, not inside any container or remote session.
2. For the Claude Code skill: ensure the skill is symlinked globally so it runs via your local shell:
   ```bash
   ln -sf "$(pwd)/.claude/skills/morning-brief" ~/.claude/skills/morning-brief
   ```
3. Verify Claude Code has permission to run shell commands (check `.claude/settings.local.json`).

---

## Google OAuth Token Refresh Fails

### Symptoms

`run_morning_brief.sh` / `run_evening_brief.sh` / `check_allergy_shot.sh` fail at the refresh step:

```
ERROR: Token refresh failed. Re-run: uv run oauth_setup.py
```

And `shared/refresh_tokens.py` logs one of:

- `Refresh failed (400): {"error": "invalid_grant", ...}` — refresh token was revoked, expired, or never minted with `access_type=offline`.
- `Refresh failed (401): {"error": "invalid_client", ...}` — client_id / client_secret in Keychain doesn't match the Google Cloud Console project.
- `Refresh failed (403)` — the OAuth client or API was disabled in the Console.
- Connection error — network issue or `oauth2.googleapis.com` unreachable.

### Root Cause

`refresh_tokens.py` POSTs to `https://oauth2.googleapis.com/token` with `grant_type=refresh_token`. Common failures:

- **Testing-mode consent screen + sensitive scopes** → Google expires refresh tokens after 7 days. Publish the consent screen to "In production" in the Cloud Console to remove this constraint.
- **User revoked the grant** at <https://myaccount.google.com/permissions>.
- **6 months of inactivity** — Google invalidates idle refresh tokens.
- **Client credentials rotated** in the Console but Keychain still has the old `client_id`/`client_secret`.

### How to Diagnose

```bash
# Confirm Google's endpoint is reachable
curl -sS -o /dev/null -w "%{http_code}\n" https://oauth2.googleapis.com/token   # expect 405 (POST-only)

# Inspect the stored client (don't print this in shared logs)
security find-generic-password -a "$USER" -s "morning-brief-google-client" -w | python3 -m json.tool

# Try the refresh manually
uv run shared/refresh_tokens.py
```

### How to Fix

1. **Confirm consent screen is "In production"** — Cloud Console → APIs & Services → OAuth consent screen → Publishing status. Publish without verification (single-user CLI, ~100-user cap is fine).
2. **Re-run setup**:
   ```bash
   export GOOGLE_OAUTH_CLIENT_ID="<client_id>.apps.googleusercontent.com"
   export GOOGLE_OAUTH_CLIENT_SECRET="<client_secret>"
   uv run oauth_setup.py
   ```
   This re-runs the PKCE flow with `prompt=consent` (forces a fresh refresh token) and overwrites the Keychain entries.
3. If Google says the grant was revoked, also revoke any leftover authorization at <https://myaccount.google.com/permissions> before re-running setup — otherwise the new grant may inherit the old revoked state.

### Historical context

Pre-2026-05, this project used Anthropic's hosted OAuth proxies at `gcal.mcp.claude.com` / `gmail.mcp.claude.com`. Those endpoints were retired and now return 404, which is why the project was migrated to direct Google OAuth. `BUG_REPORT.md` documents the related MCP server bug filed before the migration; that report is now historical.

---

## iMessage Permission Requests Sent to Wrong Chat (Wife Spam)

### Symptoms

A non-allowlisted contact (e.g., spouse) starts receiving automated iMessage permission request blobs like:

```
🔐 Permission request [xxxxxx]
Bash: Check plugins subcommands
{"command":"claude plugins --help 2>&1","description":"Check plugins subcommands"}
Reply "yes xxxxxx" to allow or "no xxxxxx" to deny.
```

These messages appear as sent-by-you ("me:") in their chat thread, not as inbound messages from Claude. The contact's DMs get flooded every time Claude performs a multi-step task.

### Root Cause

The iMessage channel's permission approval system sends approval prompts to **all chats Claude has recently seen**, not just the self-chat. If a contact's number appeared in the allowlisted chats (either directly in `allowFrom`, or via a previous access grant), Claude routes permission requests to their thread as well as the self-chat. The result is that every tool call requiring approval fires a message into every visible chat.

The config lives at `~/.claude/channels/imessage/access.json`.

### How to Fix

1. Open `~/.claude/channels/imessage/access.json`
2. Remove the contact's number from `allowFrom` (or clear the array entirely if only self-chat is needed):

```json
{
  "dmPolicy": "allowlist",
  "allowFrom": [],
  "groups": {},
  "pending": {}
}
```

With `dmPolicy: "allowlist"` and an empty `allowFrom`, no inbound DMs can trigger Claude and permission requests are only routed to your self-chat.

### How to Verify the Fix

Check `~/.claude/channels/imessage/access.json` — `allowFrom` should be empty (or contain only your own number if self-chat approval is desired). After the fix, no new permission request messages should appear in any third-party chat threads.

### Prevention

Only add numbers to `allowFrom` that you explicitly want to be able to send commands to Claude. Keep your spouse's (or anyone else's) number out of this list unless they are an intended user of the iMessage channel.

---

## Deploy Pulls Wrong Branch (`fatal: couldn't find remote ref master`)

### Symptoms

`~/.morning_brief_deploy.log` shows:

```
fatal: couldn't find remote ref master
ERROR: git pull failed
```

Deploy fails silently every day. New commits (features, bug fixes) are never pulled into production. The morning/evening briefs keep running on stale code.

### Root Cause

`deploy.sh` was hardcoded to `git pull origin master`, but the remote branch was renamed to `main`. The `git pull` fails immediately and the trap sends an iMessage notification, but since the brief itself still runs (on old code), the failure is easy to miss.

### How to Diagnose

```bash
# Check deploy log
tail -20 ~/.morning_brief_deploy.log

# Check the actual branch name
git -C "$(git rev-parse --show-toplevel)" branch -vv
```

### How to Fix

Update `deploy.sh` to fetch and fast-forward the actual branch name:

```bash
# In deploy.sh, change:
git -C "$REPO_ROOT" fetch origin master
git -C "$REPO_ROOT" merge --ff-only origin/master
# To:
git -C "$REPO_ROOT" fetch origin main
git -C "$REPO_ROOT" merge --ff-only origin/main
```

Then run `bash deploy.sh` manually to catch up on missed commits.

### Prevention

After renaming a branch on GitHub, grep the repo for the old name:

```bash
grep -r "master" scripts/*.sh plists/
```

---

## Reminders Section Missing from Launchd-Scheduled Briefings

### Symptoms

Manually running `bash run_morning_brief.sh` from a terminal pulls reminders fine — the `✅ REMINDERS` section appears in the brief. But the scheduled launchd run (7am via `com.andychiu.automation.morning-brief.plist`) delivers a brief with no reminders section, and `~/.morning_brief.log` shows:

```
WARNING Reminders database not found
```

No Python exception, no TCC prompt, no obvious error — just silently missing.

### Root Cause

macOS TCC blocks the launchd-spawned process from reading `~/Library/Group Containers/group.com.apple.reminders/`. Two things make this hard to diagnose:

1. **Loud error since the iterdir() switch (was silent).** As of [PR #7](https://github.com/andyachiu/automation/pull/7), `_find_db()` in `shared/reminders.py` calls `STORES_DIR.iterdir()` instead of `glob()` so `PermissionError` surfaces with an actionable error pointing at the responsible binary and the System Settings fix. **Older versions silently returned `[]`** because `Path.glob()` swallowed the `PermissionError`, leaving `_find_db()` to return `None` and emit the generic "database not found" warning while `STORES_DIR.exists()` still returned `True`. If you see the old warning, your code is on an older revision.

2. **Wrong binary gets blamed.** The obvious instinct is to grant Full Disk Access to `/bin/bash` (the launchd `ProgramArguments[0]`). That doesn't work — TCC uses the "responsible process" model: it attributes access to whatever binary directly spawned the python that called `sqlite3.connect()`. The wrappers print `Using python: <realpath>` at startup so `~/.morning_brief.log` always shows the binary that needs FDA.

### Which binary needs FDA

The production wrappers now invoke `<repo>/scripts/.venv/bin/python3` directly. That symlink resolves to the uv-managed interpreter, e.g. `~/.local/share/uv/python/cpython-3.13.6-macos-aarch64-none/bin/python3.13`. **TCC attributes the grant to the resolved binary's signature**, so:

- macOS shows the resolved path in the FDA picker even if you select the venv symlink — that's expected.
- The grant survives `uv self update` and brew upgrades (uv is no longer in the responsible-process chain).
- The grant goes stale only on a **Python version upgrade** (e.g., `uv` swapping in cpython-3.13.7 during a future `uv sync`). When that happens, repeat the remove-and-re-add fix on the new path.

Historical: prior to this change, the wrappers ran `uv run python ...`, which made `~/.local/bin/uv` the responsible process. Confirmed 2026-04-25: reminders fetch broke ~8 months after a 2025-08-14 uv upgrade because TCC keys grants by binary signature and `uv self update` had silently invalidated the entry. The wrapper change removes that failure mode.

Confirmed via TCC logs (pre-fix):

```
AttributionChain:
  responsible={responsible_path=$HOME/.local/bin/uv}
  accessing={binary_path=.../cpython-3.13.6/bin/python3.13}
  ReqResult(Auth Right: Denied (Service Policy))
```

Post-fix, `responsible_path` and `binary_path` are the same — both point at the resolved venv python.

### How to Diagnose

```bash
# Trigger the launchd job in its real sandbox (not your terminal's context)
launchctl kickstart -k "gui/$(id -u)/com.andychiu.automation.morning-brief"

# Watch TCC decisions in real time — look for responsible_path and Denied (Service Policy)
/usr/bin/log show --predicate 'subsystem == "com.apple.TCC"' --debug --info --last 5m \
  | grep -E "responsible_path|AllFiles|Denied"
```

The `responsible_path=` field tells you exactly which binary TCC is checking. That's the binary that needs FDA.

### How to Fix

1. Find the resolved python path: `readlink -f <repo>/scripts/.venv/bin/python3` (or grep `~/.morning_brief.log` for the `Using python:` line).
2. System Settings → Privacy & Security → Full Disk Access.
3. **If a stale entry for this binary already exists, fully remove it with the `−` button** — do **not** just toggle the switch off and back on. TCC keys grants by binary signature; toggling only flips the active flag on the same record. Only `−` then re-adding causes TCC to capture the current binary's signature.
4. Click `+`, press `Cmd+Shift+G`, paste the resolved path from step 1 (e.g., `$HOME/.local/share/uv/python/cpython-3.13.6-macos-aarch64-none/bin/python3.13`). You can also pick the venv symlink at `<repo>/scripts/.venv/bin/python3` — macOS will resolve it.
5. Confirm the new entry's switch is on.
6. Re-trigger: `launchctl kickstart -k "gui/$(id -u)/com.andychiu.automation.morning-brief"`.
7. Verify `~/.morning_brief.log` shows `Reminders: N overdue, M due today`.

### Applies To

Any launchd agent in this project (morning brief, evening brief) that reads TCC-protected resources (Reminders DB, etc.) via the venv python. The FDA grant on the resolved python binary covers all of them. The allergy shot check still uses `uv run` and does not currently touch TCC-protected paths; if that changes, port it to the venv-python pattern.

### Running briefs manually from a terminal needs a separate FDA grant

The grant on the venv python only covers the **launchd-spawned** path. When you run `bash run_morning_brief.sh` directly from a terminal (Kitty, Terminal.app, iTerm, etc.), TCC walks a different responsible-process chain and lands on the **terminal app**, not the venv python.

Symptom: launchd-driven briefs deliver reminders fine, but `bash run_morning_brief.sh` from your terminal logs `Permission denied reading ... Stores`.

Fix: grant FDA to the terminal app itself.

1. System Settings → Privacy & Security → Full Disk Access → `+`
2. `Cmd+Shift+G`, paste `/Applications/kitty.app` (or `/Applications/Utilities/Terminal.app`, `/Applications/iTerm.app`, etc.)
3. **Cmd-Q the terminal completely and relaunch** — TCC grants only apply to processes spawned after the grant.
4. Verify: `ls ~/Library/Group\ Containers/group.com.apple.reminders/Container_v1/Stores/` from a fresh terminal window should list `.sqlite` files instead of erroring.

Tradeoff: granting FDA to a terminal means *anything* run from any window of that terminal gets FDA. For a single-user personal machine this is the standard tradeoff; if multi-user or shared-machine, prefer the Terminal-app-only grant and use Terminal.app for brief runs.

### Recurrence

Only on Python version upgrades (e.g., uv-managed interpreter bumps from 3.13.6 → 3.13.7). `uv self update` no longer invalidates the grant. There is no automatic detection — the symptom is the loud error above in `~/.morning_brief.log`, and the `Using python:` log line will show a new path on the day it breaks.

---

## Brief Did Not Fire at Scheduled Time

### Symptoms

The scheduled morning brief at 7am (or evening brief at 9pm, etc.) didn't deliver. No iMessage arrived; nothing in `~/.morning_brief.log` for the expected time.

### Root Cause

launchd `StartCalendarInterval` jobs only fire when the Mac is awake. If the Mac was sleeping at the scheduled time, the job fires on next wake — which could be minutes or hours later depending on lid state and activity.

### How to Diagnose

```bash
# Check what's actually loaded
launchctl list | grep andychiu

# Check scheduled wakes (look for "wakepoweron at H:MM... every day")
pmset -g sched

# Power assertions — anything currently keeping the Mac awake?
pmset -g assertions | grep -E "PreventUserIdleSystemSleep|NoDisplaySleepAssertion"
```

### How to Fix

Schedule a system wake five minutes before the earliest daily brief:

```bash
sudo pmset repeat wakeorpoweron MTWRFSU 06:55:00
```

Verify with `pmset -g sched` (expect `wakepoweron at 6:55AM every day`). Cancel with `sudo pmset repeat cancel`.

### Limitations

- `pmset` only allows one repeating wake. A single 6:55am wake covers the 7am weekday brief; weekend (9am) briefs fire best-effort — the Mac wakes early and may go back to sleep before 9am.
- `wakeorpoweron` wakes the Mac from sleep but does **not** boot it from a clean shutdown. If the laptop is fully powered off, the brief misses entirely and fires on next login.
- On battery: macOS may refuse to wake at low battery levels. Plug in for reliability on travel.

For full decoupling from laptop state, run the brief on an always-on host (Mac mini at home, etc.) and have it dispatch iMessage from there. Not currently implemented.

---

## iMessage Send Hangs on macOS Tahoe (BlastDoor Pile-Up)

### Symptoms

`run_morning_brief.sh` (or any script calling `send_imessage`) hangs for ~30 seconds during the AppleScript dispatch and fails with:

```
AppleScript error: Messages got an error: AppleEvent timed out. (-1712)
```

Or, since [PR #7](https://github.com/andyachiu/automation/pull/7) added a pre-flight, you may instead see this in `~/.morning_brief.log`:

```
ERROR Skipping iMessage send: 5 MessagesBlastDoorService instances detected (healthy is ≤1).
Messages.app is wedged and the AppleEvent will time out with -1712.
Recovery: force-quit Messages.app via Activity Monitor (killall fails under SIP because
MessagesBlastDoorService is an Apple-signed XPC service), then relaunch Messages.app.
Verify with: pgrep -lf MessagesBlastDoorService (should show 0–1 PIDs).
```

The pre-flight short-circuits the send — the brief never reaches `osascript`, so you don't waste 30s on the timeout.

### Root Cause

macOS 26.x (Tahoe) has a regression where `MessagesBlastDoorService` XPC workers don't get reaped between Messages.app sessions or after the Apple Intelligence Messages Assistant Extension runs. Workers pile up — a single Mac can accumulate 5+ instances over a few days, with the oldest running for the better part of a week. Once BlastDoor is wedged, Messages.app stops servicing AppleEvents entirely, so `osascript` to Messages times out with `-1712` regardless of the script content. Even read-only AppleEvents (`get name of every service`) hang.

Confirmed 2026-04-25 on macOS 26.4.1 with 5 concurrent `MessagesBlastDoorService` PIDs (one running 5+ days).

### How to Diagnose

```bash
# Count BlastDoor workers — healthy is 0 or 1
pgrep -lf MessagesBlastDoorService

# Optional: confirm the AppleEvent path is wedged (will hang or return -1712)
osascript -e 'with timeout of 5 seconds' \
          -e 'tell application "Messages" to get name of every service' \
          -e 'end timeout'
```

If `pgrep` shows >1 PID, BlastDoor is wedged. The pre-flight in `send_imessage()` (in `shared/briefing_common.py`) runs this same check before every send.

### How to Fix

**The reliable recovery is force-quit Messages.app via Activity Monitor.** Other approaches do not work:

- ❌ `killall MessagesBlastDoorService` (and `sudo killall ...`) — silently fails. `MessagesBlastDoorService` is an Apple-signed XPC service protected by SIP; even root cannot terminate it.
- ❌ `sudo launchctl kickstart -k system/com.apple.MessagesBlastDoorService` — wrong domain (returns "Could not find service ... in domain for system").
- ❌ `osascript -e 'tell application "Messages" to quit'` — relies on AppleEvents, which are exactly what's wedged.
- ❌ `pkill -x Messages` — also fails when Messages.app itself is unresponsive.
- ✅ **Activity Monitor → search "Messages" → select Messages.app → click the X (Force Quit).** When Messages.app dies, launchd reaps its BlastDoor workers within a few seconds. Then relaunch Messages.app normally.

After force-quitting, verify:

```bash
pgrep -lf MessagesBlastDoorService    # should show 0 (will respawn to 1 on Messages activity)
```

If workers still accumulate after relaunch, also force-quit "Messages Assistant Extension" via Activity Monitor (it's a separate, non-SIP-protected process — `killall "Messages Assistant Extension"` does work). Last resort: reboot, or disable Apple Intelligence Message Summaries to stop the Assistant Extension from spawning orphaned workers.

### Recurrence

Expect to re-apply the force-quit after macOS point updates or extended uptime. There is no fix in this codebase — the bug is Apple-side. The pre-flight in `send_imessage` only ensures the failure mode is loud and immediate instead of a 30-second hang followed by a misleading `-1712` error.

---

## iMessage Plugin Sends Triple Permission Prompts

### Symptoms

Every permission request from Claude Code sends 3 identical `🔐 Permission request` messages to your self-chat. Approving one sends 3 `✅` confirmations back.

### Root Cause

The iMessage plugin's permission request handler (`server.ts`, `notifications/claude/channel/permission_request`) iterates all self-addresses in the `SELF` set and sends to every matching chat GUID:

```typescript
for (const h of SELF) {
  for (const { guid } of qChatsForHandle.all(h)) targets.add(guid)
}
for (const guid of targets) sendText(guid, text)
```

`SELF` is populated from `SELECT DISTINCT account FROM message WHERE is_from_me = 1` — a typical iCloud user has 3+ addresses (phone number, iCloud email, alias). Each resolves to a different self-chat GUID, so the same message is sent 3 times.

### How to Fix

Edit `~/.claude/plugins/cache/claude-plugins-official/imessage/0.1.0/server.ts`. Replace the multi-target loop with a single-target send — find the first valid self-chat GUID and send only to that one:

```typescript
let targetGuid: string | undefined
for (const h of SELF) {
  for (const { guid } of qChatsForHandle.all(h)) {
    targetGuid = guid
    break
  }
  if (targetGuid) break
}
```

### Caveats

This file is in the plugin cache. A plugin update will overwrite the fix. The upstream fix belongs in `anthropics/claude-plugins-official`.
