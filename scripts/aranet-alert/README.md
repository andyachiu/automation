# Aranet4 CO2 Alerts

Push notifications to your phone when indoor CO2 gets high, even when you're away from home.

The Aranet4 only speaks Bluetooth, so an always-on computer within range of your sensors reads them and forwards alerts through [ntfy](https://ntfy.sh). No pairing is needed: it reads the readings the sensors broadcast. The host is either a Raspberry Pi (systemd) or a Mac (launchd plus a Terminal window). On a Mac, a second agent also texts the CO2 alerts over iMessage.

**Running it today on the Mac?** Jump to [Start and Stop on the Mac](#start-and-stop-on-the-mac). Setting up from scratch: [Raspberry Pi](#raspberry-pi-setup-one-time) or [Mac](#mac-setup-one-time).

## Start and Stop on the Mac

Everything below runs from `~/Code/automation/scripts`. One-time setup, including the Keychain items these commands depend on, is in [Mac Setup](#mac-setup-one-time).

**Start both agents** (the watcher and the texting relay). Safe to re-run; already-loaded agents report "service already loaded":

```bash
cd ~/Code/automation/scripts && launchctl load ~/Library/LaunchAgents/com.andychiu.automation.aranet-alert.plist && launchctl load ~/Library/LaunchAgents/com.andychiu.automation.aranet-imessage-relay.plist
```

The watcher agent opens a Terminal window running `run_aranet_alert_mac.command`. Leave that window open. If macOS asks whether Terminal can use Bluetooth, click Allow, or scanning fails.

**Start the watcher right now** instead of waiting up to 5 minutes for the next check:

```bash
launchctl kickstart -k gui/$(id -u)/com.andychiu.automation.aranet-alert
```

**Check what's running.** The first command lists loaded agents, the second confirms the watcher and relay processes:

```bash
launchctl list | grep aranet && pgrep -fl "run_aranet_alert_mac.command|ntfy_imessage_relay"
```

**Watch the logs.** The watcher prints one line per room per measurement:

```bash
tail -f ~/.aranet_alert.log ~/.aranet_relay.log
```

**Stop everything,** including the supervisor that would otherwise reopen the watcher:

```bash
launchctl unload ~/Library/LaunchAgents/com.andychiu.automation.aranet-alert.plist ~/Library/LaunchAgents/com.andychiu.automation.aranet-imessage-relay.plist && pkill -f run_aranet_alert_mac.command
```

**Apply code changes.** Restarting the watcher is a kill: the supervisor reopens it within 5 minutes, or use the kickstart command above to skip the wait:

```bash
pkill -f run_aranet_alert_mac.command && launchctl kickstart -k gui/$(id -u)/com.andychiu.automation.aranet-imessage-relay
```

**Send a test alert** to confirm pushes and texts both work end to end. This texts everyone in `aranet-alert-imessage-targets`:

```bash
curl -fsS -H "Title: Test Room: CO2 high" -d "Test alert, please ignore." "https://ntfy.sh/$(security find-generic-password -a "$USER" -s aranet-alert-ntfy-topic -w)"
```

## How It Works

### Nest fan controller (enabled; Production OAuth verified)

`nest_fan.py` defaults to dry-run; `--live` is required to issue commands. It uses Google's SDM Fan.SetTimer API. No heating/cooling mode or temperature settings are changed. The variants in `systemd-user/` are installed in `~/.config/systemd/user/` on the Pi. The timer is enabled and active, with existing `Linger=yes` allowing operation after logout and at boot. The original system-level templates remain uninstalled; do not enable both.

Policy: at least five minutes of consecutive observations at or above `CO2_HIGH` in one room, latest observation at most ten minutes old, and no gap over ten minutes. These are received observations, not guaranteed distinct sensor samples. Each command requests a 15-minute timer, with at least one hour between requests and at most four attempts in a rolling 24 hours. Existing ON fan timers are preserved. Reservations are recorded before sending; failed or ambiguous commands count toward cooldown and limits to prevent retry loops. Errors exit nonzero.

Credentials must be a mode-600 JSON file containing `client_id`, `client_secret`, `refresh_token`, and `device_name` (`enterprises/PROJECT/devices/DEVICE`), outside the repo. The service expects `/home/andychiu/.config/aranet/nest.json`. Setup requires Google Device Access registration, an SDM-enabled Cloud project and OAuth authorization. Do not reuse the morning briefing's OAuth credentials or persist authorization codes in documentation.

The authorized evaluation will pause the recurring timer, require fresh readings from both rooms, record a 15-minute pre-run baseline, issue one `--test --live` timed command, verify the thermostat reports its timer ON, and observe CO2 during the run and for 15 minutes afterward. Compare per-room observations with timestamps and missing-coverage caveats; a single uncontrolled trial does not establish causality. Resume automatic operation only after confirming the command behavior. The HVAC has no fresh-air intake, so this tests redistribution of indoor CO2, not removal from the home.

On October 7, live timer control was verified: Google reported ON after a bounded test and OFF after its timeout. This verifies API timer control, not independently measured airflow or CO2 removal. One sensor lacked a stable pre-test baseline, so observations do not establish causality. Production OAuth refresh and read-only Fan access passed. The persistent user timer was enabled with a 1000 ppm threshold. Check with `systemctl --user status aranet-nest-fan.timer`; stop with `systemctl --user disable --now aranet-nest-fan.timer`. Logs are at `~/.local/share/aranet/nest-fan.log`; requests are audited in SQLite. Credentials and household-specific deployment details are kept outside the public repository.

### Air-quality dashboard

Configure `DASHBOARD_BIND` with your Pi's private Tailscale address, then open `http://<pi-tailscale-ip>:8080` with Tailscale connected. The checked-in template defaults to localhost; access follows your tailnet's network policy. It has no separate dashboard password. There are no external JavaScript/CDN dependencies.

The watcher stores each received observation in `~/.local/share/aranet/readings.sqlite3` (override with `ARANET_DB`). SQLite WAL allows the dashboard to read while the watcher writes. Records older than 90 days are pruned when observations arrive. History starts at installation; old log lines are not backfilled. Storage failures exit loudly and systemd restarts the watcher.

The 2h/6h/24h/7d chart shows both rooms on the same scale, with the configured alert threshold. Cards show the latest received observation, temperature in Fahrenheit, humidity, pressure, battery, and the selected period's observed peak. Observations may repeat a sensor measurement; timestamps are reception times, not reconstructed measurement times. Gaps exceeding the configured stale interval are disconnected. Missing rooms remain visible; stale readings are labeled. The browser refreshes every minute and reports refresh failures.

```bash
systemctl status aranet-dashboard
journalctl -u aranet-dashboard -f
```

`aranet-dashboard.service` defaults to localhost; adapt the username, paths, and private bind address when installing it. Deploy `history.py`, `dashboard.py`, and `dashboard.html` alongside `aranet_alert.py`, install the unit, restart the watcher, and enable the dashboard. Back up the SQLite database using SQLite's backup API, rather than copying only its main file during writes.

1. The watcher scans for 60 seconds for the sensors' Bluetooth broadcasts, started by systemd on the Pi or by the Terminal launcher on the Mac. It accepts Aranet manufacturer data even without service UUIDs. Each broadcast reports the sensor's measurement interval and how long ago it measured, so the watcher sleeps until the next reading is due instead of re-reading the same value. Scanning costs the sensor nothing: it broadcasts whether or not anything listens.
2. `aranet_alert.py` tracks each sensor separately and puts its room name in the alert title (for example "Bedroom: CO2 high"). It compares CO2 against two thresholds. It alerts once when CO2 reaches `CO2_HIGH` (1000 ppm, where the Aranet4 display turns amber) and sends an all-clear once it drops below `CO2_CLEAR` (900 ppm). The gap keeps readings near a threshold from flapping.
3. It also alerts once when the sensor hasn't been seen for `STALE_MINUTES` (15) and when the battery reaches `LOW_BATTERY` (10%).
4. Alerts are an HTTP POST to your ntfy topic. The ntfy app on your phone and iPad shows them as push notifications.
5. Bluetooth and delivery failures crash the process. systemd on the Pi, or the Terminal launcher on the Mac, restarts it after 30 seconds and logs why. After a restart it alerts again if CO2 is still high.
6. On a Mac, `ntfy_imessage_relay.py` also texts each "CO2 high" alert. See [Text Alerts](#text-alerts-mac).

## What to Buy

| Item | Notes |
|---|---|
| Raspberry Pi 4 Model B, 2 GB | Better onboard antenna than the Zero 2 W, and 5 GHz Wi-Fi keeps the 2.4 GHz band free for Bluetooth. Full-size USB leaves room for an external-antenna Bluetooth adapter if range falls short. A Zero 2 W works for a single nearby sensor. |
| microSD card, 16 GB or larger | A1/A2-rated (for example SanDisk Endurance or High Endurance) |
| Official Raspberry Pi 15 W USB-C power supply | Phone chargers cause undervoltage resets. |
| Plastic case with passive heatsink | Avoid metal cases; they block Bluetooth. |

Place the Pi within about 10 m of every sensor, ideally midway between them. Walls cut that range.

## Raspberry Pi Setup (one-time)

### Current Pi deployment (2026-10-06)

- Raspberry Pi OS / Debian 13, arm64. Project files are deployed as files rather than a Git clone; `git pull` does not update the running installation.
- The Pi watcher runs under systemd, while the Mac watcher is disabled and the Mac iMessage relay remains active.
- Private configuration resides in `/etc/aranet-alert.env` with mode 600. Keep sensor addresses, notification topics, network addresses, and SSH fingerprints outside this public repository.
- Manufacturer-data discovery and a 60-second scan window improve sensor discovery. Validate sustained coverage in final sensor locations.
- Tailscale and SSH were validated from an iPhone. Resolve the current private address with `tailscale status` and verify host keys through your trusted device setup.

Useful checks on the Pi:

```bash
cd ~/automation/scripts/aranet-alert
~/.local/bin/uv run --frozen --no-dev aranet_alert.py --scan
systemctl status aranet-alert
tailscale status
```

### 1. Sensor and phone

1. In the Aranet Home app, open each sensor's settings and turn on **Smart Home integration**. Update the firmware if the option is missing (it needs 1.2.0 or newer).
2. Install the **ntfy** app on your phone and iPad. Subscribe both to the same hard-to-guess topic, for example the output of `echo aranet-$(openssl rand -hex 8)`. Anyone who knows the topic name can read and send to it.

### 2. Pi OS

With [Raspberry Pi Imager](https://www.raspberrypi.com/software/), flash **Raspberry Pi OS Lite (64-bit)**. In the Imager's settings, set the username to `pi`, your Wi-Fi network, and SSH with your public key. The service file assumes the username `pi`; if you choose another, edit `User=` and the paths in `aranet-alert.service`.

Then SSH in:

```bash
ssh pi@raspberrypi.local
```

```bash
sudo apt update && sudo apt full-upgrade -y && sudo apt install -y git bluez
```

```bash
sudo usermod -aG bluetooth pi
```

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Log out and back in so the group and `uv` path apply.

### 3. Code

The repository is private, so the Pi needs GitHub access. A read-only [deploy key](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys) is the narrowest option.

```bash
git clone git@github.com:andyachiu/automation.git ~/automation
```

```bash
cd ~/automation/scripts/aranet-alert && uv sync --frozen --no-dev
```

### 4. Find the sensors

```bash
uv run --frozen --no-dev aranet_alert.py --scan
```

Run it with the Pi in its final spot: every sensor should appear. Copy each address (for example `E4:5F:01:AB:CD:EF`). To tell the sensors apart, match the name column to the sensor names in the Aranet Home app, or the CO2 value to each sensor's screen. A "no readings" line means Smart Home integration is off for that sensor. A sensor that doesn't appear is out of range.

### 5. Configure

Create `/etc/aranet-alert.env`. The file is root-owned and not world-readable because the topic acts as a password.

```bash
sudo install -m 600 /dev/null /etc/aranet-alert.env && sudo nano /etc/aranet-alert.env
```

```ini
# Comma-separated room=address pairs; quote the value if a name has spaces
ARANET_SENSORS="Bedroom=E4:5F:01:AB:CD:EF,Living room=E4:5F:01:12:34:56"
NTFY_TOPIC=aranet-your-random-suffix
# Optional overrides (defaults shown)
# NTFY_SERVER=https://ntfy.sh
# CO2_HIGH=1000
# CO2_CLEAR=900
# STALE_MINUTES=15
# LOW_BATTERY=10
```

Send a test push:

```bash
set -a; source <(sudo cat /etc/aranet-alert.env); set +a; uv run --frozen --no-dev aranet_alert.py --test-notify
```

### 6. Run as a service

```bash
sudo cp aranet-alert.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now aranet-alert
```

## Start and Stop on the Pi

```bash
sudo systemctl start aranet-alert
```

```bash
sudo systemctl stop aranet-alert
```

```bash
systemctl status aranet-alert
```

```bash
journalctl -u aranet-alert -f
```

To update after pushing changes:

```bash
cd ~/automation && git pull --ff-only && cd scripts/aranet-alert && uv sync --frozen --no-dev && sudo systemctl restart aranet-alert
```

## Mac Setup (one-time)

A Mac that stays on can stand in for the Pi. launchd can't run the watcher directly: macOS only allows Bluetooth for a process that an app with Bluetooth permission is responsible for. Instead, a launchd agent opens `run_aranet_alert_mac.command` in a Terminal window at login, and again within 5 minutes if it stops. The launcher restarts the watcher 30 seconds after any exit. It sends an "Aranet watcher restarting" push on the first exit after a healthy run, so a crash loop doesn't push every 30 seconds. Closing the Terminal window, or killing the launcher, stops the watcher with it; leaving orphans behind would let the supervisor start a second watcher and double every alert.

1. Store the settings in Keychain. On a Mac, `--scan` prints CoreBluetooth IDs instead of MAC addresses; use those IDs.

   ```bash
   security add-generic-password -a "$USER" -s aranet-alert-ntfy-topic -w aranet-your-random-suffix
   ```

   ```bash
   security add-generic-password -a "$USER" -s aranet-alert-sensors -w "Bedroom=<id>,Living room=<id>"
   ```

2. From `scripts/`, render and load the agent:

   ```bash
   uv run install_launch_agents.py && launchctl load ~/Library/LaunchAgents/com.andychiu.automation.aranet-alert.plist
   ```

3. A Terminal window opens and runs the watcher. If macOS asks whether Terminal can use Bluetooth, click Allow. Leave the window open. Confirm it's working with the commands in [Start and Stop on the Mac](#start-and-stop-on-the-mac); logs from both the agent and the watcher go to `~/.aranet_alert.log`.

Limits compared with the Pi:

- **Sleep:** the watcher holds `caffeinate -i`, which prevents idle sleep. Closing a laptop lid without an external display still sleeps the Mac and stops scanning.
- **Restarts:** after a reboot, alerts resume only once you log in.
- **Thresholds:** the launcher doesn't read `/etc/aranet-alert.env`. To change thresholds on the Mac, edit the defaults in `Config`.

When the Pi takes over, persistently disable and stop the Mac watcher. Retain its template for rollback and leave the iMessage relay running:

```bash
launchctl disable gui/$(id -u)/com.andychiu.automation.aranet-alert
launchctl bootout gui/$(id -u)/com.andychiu.automation.aranet-alert
pkill -TERM -f '^bash .*/aranet-alert/run_aranet_alert_mac.command'
```

To roll back, first stop the Pi service, then run `launchctl enable gui/$(id -u)/com.andychiu.automation.aranet-alert` before loading the Mac agent again.

## Text Alerts (Mac)

`ntfy_imessage_relay.py` subscribes to the ntfy topic and sends an iMessage for every "CO2 high" alert, reusing the briefings' `send_imessage`. Only the Mac can send iMessage, so this runs here whether the watcher runs on the Mac or on the Pi. All-clear, offline, and battery alerts stay push-only.

1. Store the recipients in Keychain, comma-separated:

   ```bash
   security add-generic-password -a "$USER" -s aranet-alert-imessage-targets -w "+15551234567,+15557654321"
   ```

2. From `scripts/`, render and load the agent:

   ```bash
   uv run install_launch_agents.py && launchctl load ~/Library/LaunchAgents/com.andychiu.automation.aranet-imessage-relay.plist
   ```

launchd restarts the relay whenever it exits, which it does on a dropped stream or a failed send. It subscribes from the current moment, so a restart never re-texts cached alerts. Logs go to `~/.aranet_relay.log`:

```bash
tail -f ~/.aranet_relay.log
```

## Customization

- **Thresholds, stale window, battery level**: on the Pi, set the optional variables in `/etc/aranet-alert.env` and restart the service. On the Mac, edit the defaults in `Config` in `aranet_alert.py` and restart the watcher.
- **Scan cadence**: set the measurement interval in the Aranet Home app (1–10 minutes) and the watcher follows it. `next_delay()` in `aranet_alert.py` clamps the wait between `MIN_SLEEP_SECONDS` and `MAX_SLEEP_SECONDS`, and falls back to `POLL_SECONDS` when no sensor is heard.
- **Notification method**: edit `notify()` in `aranet_alert.py`.

## Test

The unit tests don't need a sensor or network access:

```bash
uv run pytest
```

`--scan` also works on a Mac, but macOS shows CoreBluetooth UUIDs instead of MAC addresses. Use the address `--scan` prints on the Pi itself.

### Fan-run notifications

The deployed user service enables `NEST_NOTIFY=1` and loads the existing ntfy topic from private mode-600 `~/.config/aranet/fan-alert.env`. Each accepted fan command produces one normal-priority notification with its triggering room and 15-minute duration. Routine checks, existing timers, cooldowns, and rejected commands do not send fan-start notifications. Titles do not match the iMessage relay filter, so no extra iMessages are sent. Notification failures exit nonzero after recording the accepted fan command; the reservation still prevents duplicate fan commands. Notification delivery is not automatically retried.

A labeled `--notify-test` was run via the Pi user systemd manager on October 7 and accepted by ntfy without issuing a thermostat command. Server acceptance does not independently confirm phone display. The eight controller/notification behavior tests passed.

### Temperature, pressure, and theme (October 8, 2026)

The dashboard measurement selector charts CO2, temperature (degrees Fahrenheit; stored sensor data remains Celsius), relative humidity (% RH, using a 0–100% chart scale), or sensor pressure (hPa, not sea-level adjusted) for both rooms over 2h/6h/24h/7d. Current pressure appears in each room card. Temperature uses existing recorded history; a non-destructive SQLite migration adds nullable pressure to old rows, and new broadcasts supply pressure. Missing values are not backfilled or connected through null points. The separate top-right light/dark toggle initially follows the system preference and saves an override in this browser. Existing 90-day retention and stale/gap handling apply.
