---
name: morning-brief
description: Run the daily morning briefing script that fetches calendar events and emails, then delivers a summary via iMessage. Use this skill whenever the user asks for their morning brief, morning briefing, daily summary, daily brief, or wants to know what's on their schedule today. Also trigger when they say things like "what do I have today", "run my morning brief", "get my briefing", or "send me my brief".
---

# Morning Brief

Generate a concise, friendly daily briefing covering calendar, email, weather, and allergy shot status — then deliver it via iMessage.

## Step 1: Gather data (do all four in parallel where possible)

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
Use the `weather_fetch` tool:
- `latitude`: `37.7749`
- `longitude`: `-122.4194`
- `location_name`: `San Francisco, CA`

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

## Step 4: Send via iMessage

The iMessage target is stored in macOS Keychain — never hardcode it. Always read it at send time:

```bash
IMESSAGE_TARGET=$(security find-generic-password -a "$USER" -s "morning-brief-imessage-target" -w 2>/dev/null)
```

If the Keychain lookup fails, report the error and skip iMessage delivery (the in-chat briefing from Step 3 is still valuable).

### Option A: Dispatch available
If `mcp__dispatch__start_code_task` is available, dispatch the iMessage send to the host Mac:
- `cwd`: `/Users/andychiu/Code/automation`
- `title`: `Send morning brief via iMessage`
- `prompt`:

  ```
  Send this exact message via iMessage. Read the target from Keychain, write the message to a temp file to avoid shell escaping issues, then use osascript:

  BRIEFING_TEXT='[INSERT THE FULL BRIEFING TEXT HERE]'

  IMESSAGE_TARGET=$(security find-generic-password -a "$USER" -s "morning-brief-imessage-target" -w 2>/dev/null)

  echo "$BRIEFING_TEXT" > /tmp/morning_brief_msg.txt

  osascript <<'EOF'
  set msgText to (do shell script "cat /tmp/morning_brief_msg.txt")
  tell application "Messages"
    set targetService to 1st service whose service type = iMessage
    set targetBuddy to buddy "$IMESSAGE_TARGET" of targetService
    send msgText to targetBuddy
  end tell
  EOF

  Report whether the send succeeded or failed.
  ```

Then wait for the Code session to complete using `read_transcript` and let the user know whether delivery succeeded.

### Option B: Running locally (no Dispatch)
If Dispatch is not available but Bash is, send directly using the same Keychain lookup + `buddy` approach:

```bash
IMESSAGE_TARGET=$(security find-generic-password -a "$USER" -s "morning-brief-imessage-target" -w 2>/dev/null)
echo "$BRIEFING_TEXT" > /tmp/morning_brief_msg.txt
MSG=$(cat /tmp/morning_brief_msg.txt | sed 's/\\/\\\\/g' | sed 's/"/\\"/g')
osascript -e "
tell application \"Messages\"
    set targetService to 1st service whose service type = iMessage
    set targetBuddy to buddy \"$IMESSAGE_TARGET\" of targetService
    send \"$MSG\" to targetBuddy
end tell
"
```

### Option C: Neither available (e.g., claude.ai)
Skip iMessage delivery silently — the in-chat briefing from Step 3 is still useful on its own.

## Error handling

- If calendar or email connectors fail, still deliver whatever data you successfully gathered. A partial briefing is better than no briefing.
- If weather fetch fails, just omit that section.
- If the allergy shot check fails, note it and move on.
- Always show the briefing in chat even if iMessage delivery fails.
