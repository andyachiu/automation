# Allergy Shot Reminder Automation

Smart automation that checks your Google Calendar for allergy shot appointments
and reminds you on Mon/Wed/Fri if you don't have one in the next 30 days.

## How It Works

1. **Mon/Wed/Fri at 9 AM**, macOS launchd triggers `check_allergy_shot.sh`
2. The script refreshes Google OAuth tokens via `scripts/shared/refresh_tokens.py`
3. Claude Code CLI queries Google Calendar via MCP for "allergy shot" events in the next 30 days
4. If **no appointment found** → sends an iMessage reminder (with notification fallback)
5. If **appointment found** → does nothing (just logs it)

## Test

```bash
bash ~/Code/automation/scripts/allergy-shot-check/check_allergy_shot.sh
```

## Manage

```bash
# Check if loaded
launchctl list | grep allergy

# View logs
tail -f ~/Code/automation/scripts/allergy-shot-check/allergy_shot_check.log

# Reload after editing plist
launchctl unload ~/Library/LaunchAgents/com.andychiu.allergy-shot-check.plist
launchctl load ~/Library/LaunchAgents/com.andychiu.allergy-shot-check.plist
```

## Customization

- **Reminder time**: Edit `Hour`/`Minute` in the plist
- **Reminder days**: Edit `Weekday` values in the plist (0=Sun, 1=Mon, ..., 6=Sat)
- **Search keywords**: Edit the Claude prompt in `check_allergy_shot.sh`
- **Lookahead window**: Modify "30 days" in the Claude prompt
- **Notification method**: Edit the osascript section in the script
