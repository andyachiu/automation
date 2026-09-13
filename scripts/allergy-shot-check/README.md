# Allergy Shot Reminder Automation

Automation that checks your Google Calendar for allergy shot appointments
and reminds you on Mon/Wed/Fri if you don't have one in the next 30 days.

## How It Works

1. **Mon/Wed/Fri at 9 AM**, macOS launchd triggers `check_allergy_shot.sh`
2. The script refreshes Google OAuth tokens via `scripts/shared/refresh_tokens.py`
3. `check_allergy_shot.py` queries the primary Google Calendar directly, from the start of today through the end of the day 30 days ahead. It matches event titles containing the word "allergy" (case-insensitive), excluding blood draws and consultations. No model or MCP is used.
4. If **no appointment found** → sends an iMessage reminder. If delivery fails, it attempts a local notification and exits non-zero.
5. If **appointment found** → does nothing (just logs it)

## Test

From `scripts/`, run the wrapper below. This uses your configured Google account and can send a real iMessage to the Keychain-configured recipient.

```bash
bash allergy-shot-check/check_allergy_shot.sh
```

## Manage

Run from `scripts/`:

```bash
# Check if loaded
launchctl list | grep allergy

# View logs
tail -f allergy-shot-check/allergy_shot_check.log

# Render and reload the repository's schedules after changing a template
uv run install_launch_agents.py --reload
```

## Customization

- **Reminder time and days**: Update `Hour`/`Minute` and `Weekday` in the [schedule template](../../plists/com.andychiu.allergy-shot-check.plist.template) (0=Sun, 1=Mon, ..., 6=Sat), then run the installer above. Do not hand-edit generated plists.
- **Search keywords**: Edit `ALLERGY_RE` and `EXCLUDE_RE` in `check_allergy_shot.py`.
- **Lookahead window**: Update `timedelta(days=30)` and the corresponding reminder text in `check_allergy_shot.py`.
- **Notification method**: Edit `send_imessage()` and the fallback notification in `check_allergy_shot.py`.
