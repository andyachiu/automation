# automation

macOS automation scripts using Claude AI, Google Calendar, and Gmail.

## What's Here

- **Morning brief** — Daily calendar + email summary delivered via iMessage at 7 AM on weekdays
- **Evening brief** — Next-day look-ahead with pending email reminders, delivered at 9 PM daily

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
