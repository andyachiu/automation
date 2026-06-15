---
name: morning-brief
description: Run the daily morning briefing script that fetches calendar events and emails, then delivers a summary via iMessage. Use this skill whenever the user asks for their morning brief, morning briefing, daily summary, daily brief, or wants to know what's on their schedule today. Also trigger when they say things like "what do I have today", "run my morning brief", "get my briefing", or "send me my brief".
---

# Morning Brief

Generate a concise, friendly daily briefing covering calendar, email, weather, reminders, and allergy shot status — then deliver it via iMessage.

## Step 1: Gather data (do all in parallel where possible)

### Apple Reminders
Run this bash command to fetch overdue and due-today reminders directly from the macOS Reminders sqlite DB via the project's `shared/reminders.py` module:

```bash
AUTOMATION_REPO_ROOT=\$(git rev-parse --show-toplevel 2>/dev/null || printf '%s\n' \"\${AUTOMATION_REPO_ROOT:-\$HOME/Code/automation}\")
cd \"\$AUTOMATION_REPO_ROOT/scripts\" && uv run python -c "
from datetime import datetime
from shared.reminders import get_reminders
r = get_reminders(datetime.now())
for x in r['overdue']: print('OVERDUE|||' + x)
for x in r['due']:     print('DUE|||'     + x)
"
```

**Do NOT use `osascript tell application "Reminders"`** — it hangs indefinitely under Claude Code (AppleEvents + TCC prompt that never gets answered). The sqlite approach is instant and already works from launchd once Full Disk Access is granted to the `uv` binary you use locally.

Parse the output: lines beginning with `OVERDUE|||` are overdue reminders, `DUE|||` are due today. The module only returns reminders that have a due date — reminders without due dates are intentionally excluded. Prefix overdue items with `[OVERDUE]` in the brief. Omit the REMINDERS section entirely if both lists are empty.

### Calendar
Use `gcal_list_events` to pull today's events:
- `calendarId`: `primary`
- `timeMin`: today at 00:00:00 (local time)
- `timeMax`: today at 23:59:59 (local time)
- `timeZone`: `America/Los_Angeles`
- `condenseEventDetails`: `false` (so you get attendee lists and locations)

### Email
Use `gmail_search_messages` to find emails from the last 24 hours:
- `q`: `newer_than:1d`
- `maxResults`: `15`

Triage from the search results (snippets, subjects, senders, and label IDs) without reading full message bodies. This is fast and usually gives you enough to work with:
- **Skip**: anything labeled `CATEGORY_PROMOTIONS`, marketing emails, automated notifications, duplicate threads
- **Highlight**: personal emails, work-related threads, newsletters the user subscribes to that have substantive content (VC/tech newsletters, news digests), order/shipping updates
- Only call `gmail_read_message` if a subject/snippet is too ambiguous to summarize confidently — don't read every message

### Weather
Fetch weather via curl:
```bash
curl -s "https://wttr.in/San+Francisco?format=%l:+%c+%t,+High+%h,+%w+wind"
```
If it fails, omit the weather section.

### Allergy shot check
Use `gcal_list_events` to search for allergy shot appointments in the next 30 days:
- `q`: `allergy shot`
- `timeMin`: today at 00:00:00
- `timeMax`: 30 days from today at 23:59:59
- `timeZone`: `America/Los_Angeles`

Also search with `q`: `allergy` to catch variant names. Exclude "allergy blood draw" — that's a separate thing. You're looking specifically for allergy shot/injection appointments.

## Step 2: Compose the briefing

Write a concise, scannable briefing in this format. Keep it tight — this gets delivered via iMessage so it needs to be readable on a phone screen.

```
☀️ Good morning! Here's your brief for [Day, Month Date]:

📅 SCHEDULE
• [Time] — [Event name] ([location or video link if present])
• [Time] — [Event name]
(or "Nothing on the calendar today — enjoy the open day!")

📧 EMAIL HIGHLIGHTS
• [Sender]: [One-line summary of what it's about]
• [Sender]: [One-line summary]
(Group by importance. Skip noise. If nothing notable: "Inbox is quiet — nothing urgent.")

✅ REMINDERS
• [OVERDUE] [Reminder title]
• [Reminder title]
(Overdue first, then due today. Omit this entire section if there are no overdue or due-today reminders.)

🌤️ WEATHER
[Current temp], [conditions]. High of [X]°F, low of [Y]°F.
(Add a note if rain is expected or if it's notably hot/cold.)

🩹 ALLERGY SHOT
[If appointment found]: "Next allergy shot: [date] at [location]"
[If NOT found]: "⚠️ No allergy shot scheduled in the next 30 days — time to book one! Check Stanford MyHealth."
```

Don't be robotic — a little warmth is good. But keep it brief. The whole thing should fit comfortably in an iMessage without scrolling forever.

## Step 3: Show the briefing in chat

Display the composed briefing to the user in the conversation so they can see it immediately.

## Step 4: Pre-flight — diagnose AppleEvent path before sending

`osascript`-driven sends can fail with `AppleEvent timed out (-1712)` for **two different reasons** that look identical: (a) Messages BlastDoor pile-up on Tahoe, or (b) TCC Automation denial against the parent process running Claude Code. Run **two probes in order** before composing the send. Save time by stopping at the first signal.

**Probe 1 — Finder (tests AppleEvent permission, not Messages):**
```bash
osascript -e 'with timeout of 3 seconds' \
          -e 'tell application "Finder" to get name of startup disk' \
          -e 'end timeout' 2>&1
```
- Returns a disk name → AppleEvents work, proceed to Probe 2.
- Returns `-1712` → **TCC Automation is denied** for this shell. Stop. Tell the user:
  > ⚠️ This Claude Code session has no Automation permission to send AppleEvents (Finder probe failed with -1712, masking a silent TCC denial). Open System Settings → Privacy & Security → Automation, grant the parent app (kitty/Terminal/Claude) access to Messages. To trigger the TCC prompt: run `osascript -e 'tell application "Messages" to count services'` from a regular terminal once and approve. Then re-run /morning-brief.
  Do NOT kill Messages or BlastDoor — that won't fix TCC.

**Probe 2 — Messages (tests BlastDoor):**
```bash
osascript -e 'with timeout of 3 seconds' \
          -e 'tell application "Messages" to count services' \
          -e 'end timeout' 2>&1
```
- Returns a number → Messages is healthy, proceed.
- Returns `-1712` (and Probe 1 passed) → **BlastDoor pile-up**. Stop. Tell the user:
  > ⚠️ Messages.app is wedged (BlastDoor). Force-quit Messages.app via Activity Monitor or `kill -9 <pid>` of the user-owned Messages.app process. (`killall` fails under SIP for Apple-signed apps.) Then re-run /morning-brief.

The in-chat briefing from Step 3 is still useful even when delivery fails.

## Step 5: Read the iMessage target

The target (phone or email) lives in `~/.config/morning-brief/target` (mode 600). Read it with:

```bash
cat ~/.config/morning-brief/target 2>/dev/null
```

If that file is missing, fall back to Keychain for backward compat:

```bash
security find-generic-password -a "$USER" -s "morning-brief-imessage-target" -w 2>/dev/null
```

If both fail, report the error and skip iMessage delivery (the in-chat briefing from Step 3 is still valuable).

## Step 6: Send via iMessage

### Option A: Dispatch available
If `mcp__dispatch__start_code_task` is available, dispatch the iMessage send to the host Mac:
- `cwd`: the automation repo root resolved from `AUTOMATION_REPO_ROOT`
- `title`: `Send morning brief via iMessage`
- `prompt`:

  ```
  Send this exact message via iMessage. Write the briefing to a temp file using a heredoc (to preserve newlines), read the target from ~/.config/morning-brief/target (Keychain fallback), then use osascript:

  cat > /tmp/morning_brief_msg.txt << 'BRIEFEOF'
  [INSERT THE FULL BRIEFING TEXT HERE — keep actual line breaks, do not escape them]
  BRIEFEOF

  IMESSAGE_TARGET=$(cat ~/.config/morning-brief/target 2>/dev/null \
    || security find-generic-password -a "$USER" -s "morning-brief-imessage-target" -w 2>/dev/null)

  osascript -e 'set msgText to (do shell script "cat /tmp/morning_brief_msg.txt")' \
            -e 'tell application "Messages"' \
            -e 'set targetService to 1st service whose service type = iMessage' \
            -e "set targetBuddy to buddy \"$IMESSAGE_TARGET\" of targetService" \
            -e 'send msgText to targetBuddy' \
            -e 'end tell'

  Report whether the send succeeded or failed.
  ```

**Critical:** the briefing text must be inserted into the heredoc with real newlines, not `\n` escape sequences. If you paste the briefing as a single line, iMessage will receive it as a single line.

Then wait for the Code session to complete using `read_transcript` and let the user know whether delivery succeeded.

### Option B: Running locally (no Dispatch)
If Dispatch is not available but Bash is, send using **three separate Bash calls** (important — do NOT combine into one compound command, because each must match a permission pattern):

**Call 1** — Read the iMessage target (file first, Keychain fallback):
```bash
cat ~/.config/morning-brief/target 2>/dev/null \
  || security find-generic-password -a "$USER" -s "morning-brief-imessage-target" -w 2>/dev/null
```
Save the output as `IMESSAGE_TARGET` for use in Call 3.

**Call 2** — Write the briefing to a temp file (use a heredoc):
```bash
cat > /tmp/morning_brief_msg.txt << 'BRIEFEOF'
[PASTE THE FULL BRIEFING TEXT HERE]
BRIEFEOF
```

**Critical:** paste the briefing with real line breaks between sections, not `\n` escape sequences or as a single joined line. The single-quoted heredoc (`<< 'BRIEFEOF'`) preserves content literally, so whatever layout you pass is what iMessage receives.

**Call 3** — Send via osascript (substitute IMESSAGE_TARGET from Call 1):
```bash
osascript -e 'set msgText to (do shell script "cat /tmp/morning_brief_msg.txt")' -e 'tell application "Messages"' -e 'set targetService to 1st service whose service type = iMessage' -e 'set targetBuddy to buddy "IMESSAGE_TARGET" of targetService' -e 'send msgText to targetBuddy' -e 'end tell'
```

### Option C: Neither available (e.g., claude.ai)
Skip iMessage delivery silently — the in-chat briefing from Step 3 is still useful on its own.

## Error handling

- If calendar or email connectors fail, still deliver whatever data you successfully gathered. A partial briefing is better than no briefing.
- If weather fetch fails, just omit that section.
- If the allergy shot check fails, note it and move on.
- Always show the briefing in chat even if iMessage delivery fails.
