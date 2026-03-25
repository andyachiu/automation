---
name: morning-brief
description: Run the daily morning briefing script that fetches calendar events and emails, then delivers a summary via iMessage. Use this skill whenever the user asks for their morning brief, morning briefing, daily summary, daily brief, or wants to know what's on their schedule today. Also trigger when they say things like "what do I have today", "run my morning brief", "get my briefing", or "send me my brief".
---

Run the morning briefing by executing:

```bash
cd /Users/andychiu/Code/automation/scripts && bash run_morning_brief.sh
```

This script will:
1. Pull latest code from GitHub
2. Refresh Google OAuth tokens
3. Query calendar and email via Claude + MCP servers
4. Send the briefing summary via iMessage

Show the user the full output so they can see the status of each step.
