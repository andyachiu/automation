# Aranet4 CO2 Alerts

Push notifications to your phone when indoor CO2 gets high, even when you're away from home.

The Aranet4 only speaks Bluetooth, so a Raspberry Pi within range of your sensors reads them and forwards alerts through [ntfy](https://ntfy.sh). No pairing is needed: the Pi reads the readings the sensor broadcasts.

## How It Works

1. A systemd service on the Pi scans for the sensors' Bluetooth broadcasts every 60 seconds.
2. `aranet_alert.py` tracks each sensor separately and puts its room name in the alert title (for example "Bedroom: CO2 high"). It compares CO2 against two thresholds. It alerts once when CO2 reaches `CO2_HIGH` (1000 ppm, where the Aranet4 display turns amber) and sends an all-clear once it drops below `CO2_CLEAR` (900 ppm). The gap keeps readings near a threshold from flapping.
3. It also alerts once when the sensor hasn't been seen for `STALE_MINUTES` (15) and when the battery reaches `LOW_BATTERY` (10%).
4. Alerts are an HTTP POST to your ntfy topic. The ntfy app on your phone and iPad shows them as push notifications.
5. Bluetooth and delivery failures crash the process. systemd restarts it after 30 seconds and the journal records why. After a restart the service alerts again if CO2 is still high.

## What to Buy

| Item | Notes |
|---|---|
| Raspberry Pi 4 Model B, 2 GB | Better onboard antenna than the Zero 2 W, and 5 GHz Wi-Fi keeps the 2.4 GHz band free for Bluetooth. Full-size USB leaves room for an external-antenna Bluetooth adapter if range falls short. A Zero 2 W works for a single nearby sensor. |
| microSD card, 16 GB or larger | A1/A2-rated (for example SanDisk Endurance or High Endurance) |
| Official Raspberry Pi 15 W USB-C power supply | Phone chargers cause undervoltage resets. |
| Plastic case with passive heatsink | Avoid metal cases; they block Bluetooth. |

Place the Pi within about 10 m of every sensor, ideally midway between them. Walls cut that range.

## One-Time Setup

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

## Manage

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

## Run on a Mac Instead

A Mac that stays on can stand in for the Pi. launchd can't run the watcher directly: macOS only allows Bluetooth for a process that an app with Bluetooth permission is responsible for. Instead, a launchd agent opens `run_aranet_alert_mac.command` in a Terminal window at login, and again within 5 minutes if it stops. The launcher restarts the watcher 30 seconds after any exit. It sends an "Aranet watcher restarting" push on the first exit after a healthy run, so a crash loop doesn't push every 30 seconds.

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

3. A Terminal window opens and runs the watcher. If macOS asks whether Terminal can use Bluetooth, click Allow. Leave the window open.

Logs from both the agent and the watcher go to `~/.aranet_alert.log`:

```bash
tail -f ~/.aranet_alert.log
```

Limits compared with the Pi:

- **Sleep:** the watcher holds `caffeinate -i`, which prevents idle sleep. Closing a laptop lid without an external display still sleeps the Mac and stops scanning.
- **Restarts:** after a reboot, alerts resume only once you log in.
- **Thresholds:** the launcher doesn't read `/etc/aranet-alert.env`. To change thresholds on the Mac, edit the defaults in `Config`.

When the Pi takes over, stop the Mac watcher, then delete `plists/com.andychiu.automation.aranet-alert.plist.template` so the installer doesn't bring it back:

```bash
launchctl unload ~/Library/LaunchAgents/com.andychiu.automation.aranet-alert.plist && pkill -f run_aranet_alert_mac.command
```

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

- **Thresholds, stale window, battery level**: set the optional variables in `/etc/aranet-alert.env`, then restart the service.
- **Scan cadence**: `POLL_SECONDS` in `aranet_alert.py`. The sensor itself measures every 1–10 minutes (set in the Aranet Home app), so polling faster than that interval gains nothing.
- **Notification method**: edit `notify()` in `aranet_alert.py`.

## Test

The unit tests don't need a sensor or network access:

```bash
uv run pytest
```

`--scan` also works on a Mac, but macOS shows CoreBluetooth UUIDs instead of MAC addresses. Use the address `--scan` prints on the Pi itself.
