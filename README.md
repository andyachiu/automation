# automation

macOS automation scripts using Claude AI, Google Calendar, and Gmail.

## What's Here

- **Morning brief** — Daily calendar + email summary delivered via iMessage at 8 AM on weekdays
- **Evening brief** — Next-day look-ahead with pending email reminders, delivered at 9 PM daily
- **Interactive chat** — Ask Claude questions with live calendar/email context from the command line

## Structure

```
automation/
├── plists/          # launchd agents for scheduling
└── scripts/         # Python project (uv)
```

See [`scripts/README.md`](scripts/README.md) for setup instructions, authentication, and usage.

## Scheduling

Copy the relevant plists from `plists/` to `~/Library/LaunchAgents/` and load them:

```bash
cp plists/com.andychiu.automation.deploy.plist ~/Library/LaunchAgents/
cp plists/com.andychiu.automation.morning-brief.plist ~/Library/LaunchAgents/
cp plists/com.andychiu.automation.evening-brief.plist ~/Library/LaunchAgents/

launchctl load ~/Library/LaunchAgents/com.andychiu.automation.deploy.plist
launchctl load ~/Library/LaunchAgents/com.andychiu.automation.morning-brief.plist
launchctl load ~/Library/LaunchAgents/com.andychiu.automation.evening-brief.plist
```

| Agent | Schedule | What it does |
|-------|----------|--------------|
| `deploy` | 6 AM weekdays | `git pull` + `uv sync` |
| `morning-brief` | 7 AM weekdays, 9 AM weekends | Today's events + urgent emails |
| `evening-brief` | 9 PM daily | Tomorrow's events + pending replies |
