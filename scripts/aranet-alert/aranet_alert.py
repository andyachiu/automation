#!/usr/bin/env python3
"""
aranet_alert.py — Push ntfy alerts when any watched Aranet4 reports high CO2.

Runs continuously on an always-on Linux host (Raspberry Pi) within Bluetooth
range of the sensors. Reads Bluetooth advertisements, so no pairing or
connection is needed, but "Smart Home integration" must be enabled for each
sensor in the Aranet Home app.

Exits non-zero on configuration, Bluetooth, or delivery failure so systemd
restarts it and the journal records why.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
import urllib.request
from dataclasses import dataclass

import aranet4

POLL_SECONDS = 60
SCAN_SECONDS = 10

Alert = tuple[str, str, str]  # (title, message, ntfy priority)


@dataclass
class Config:
    sensors: dict[str, str]  # address -> room name
    topic: str
    server: str = "https://ntfy.sh"
    co2_high: int = 1000
    co2_clear: int = 900
    stale_minutes: int = 15
    low_battery: int = 10


def parse_sensors(value: str) -> dict[str, str]:
    sensors = {}
    for entry in value.split(","):
        name, _, address = (part.strip() for part in entry.rpartition("="))
        if not name or not address:
            raise SystemExit(
                f"ERROR: ARANET_SENSORS entry {entry.strip()!r} must be name=address."
            )
        # Names go into ntfy's Title header, which only carries ASCII reliably.
        if not name.isascii():
            raise SystemExit(f"ERROR: sensor name {name!r} must be plain ASCII.")
        if address.upper() in sensors:
            raise SystemExit(f"ERROR: sensor address {address} is listed twice.")
        sensors[address.upper()] = name
    return sensors


def load_config(env: dict[str, str] = os.environ) -> Config:
    missing = [name for name in ("ARANET_SENSORS", "NTFY_TOPIC") if not env.get(name)]
    if missing:
        raise SystemExit(
            f"ERROR: {', '.join(missing)} not set. See aranet-alert/README.md."
        )
    config = Config(
        sensors=parse_sensors(env["ARANET_SENSORS"]),
        topic=env["NTFY_TOPIC"],
        server=env.get("NTFY_SERVER", Config.server),
        co2_high=int(env.get("CO2_HIGH", Config.co2_high)),
        co2_clear=int(env.get("CO2_CLEAR", Config.co2_clear)),
        stale_minutes=int(env.get("STALE_MINUTES", Config.stale_minutes)),
        low_battery=int(env.get("LOW_BATTERY", Config.low_battery)),
    )
    if config.co2_clear >= config.co2_high:
        raise SystemExit("ERROR: CO2_CLEAR must be below CO2_HIGH.")
    return config


@dataclass
class Monitor:
    config: Config
    name: str
    last_seen: float
    co2_high: bool = False
    offline: bool = False
    battery_warned: bool = False

    def on_reading(self, co2: int, battery: int, now: float) -> list[Alert]:
        alerts = []
        self.last_seen = now
        if self.offline:
            self.offline = False
            alerts.append((f"{self.name}: back online", f"CO2 {co2} ppm.", "default"))

        # Hysteresis: alert at CO2_HIGH, clear only below CO2_CLEAR, so readings
        # hovering around one threshold don't flap.
        if not self.co2_high and co2 >= self.config.co2_high:
            self.co2_high = True
            alerts.append(
                (
                    f"{self.name}: CO2 high",
                    f"{co2} ppm (alert at {self.config.co2_high}). Ventilate.",
                    "high",
                )
            )
        elif self.co2_high and co2 < self.config.co2_clear:
            self.co2_high = False
            alerts.append(
                (f"{self.name}: CO2 back to normal", f"{co2} ppm.", "default")
            )

        if not self.battery_warned and battery <= self.config.low_battery:
            self.battery_warned = True
            alerts.append(
                (f"{self.name}: battery low", f"Battery at {battery}%.", "default")
            )
        elif battery > self.config.low_battery:
            self.battery_warned = False
        return alerts

    def on_missing(self, now: float) -> list[Alert]:
        if self.offline or now - self.last_seen < self.config.stale_minutes * 60:
            return []
        self.offline = True
        return [
            (
                f"{self.name}: sensor offline",
                f"No reading for {self.config.stale_minutes} minutes. Check range, battery, "
                "and Smart Home integration in the Aranet Home app.",
                "default",
            )
        ]


def notify(config: Config, title: str, message: str, priority: str = "default") -> None:
    request = urllib.request.Request(
        f"{config.server.rstrip('/')}/{config.topic}",
        data=message.encode(),
        headers={"Title": title, "Priority": priority},
    )
    with urllib.request.urlopen(request, timeout=15):
        pass


async def _scan(duration: int) -> dict:
    found = {}

    def on_scan(adv):
        address = adv.device.address.upper()
        if getattr(adv, "readings", None) or address not in found:
            found[address] = adv

    scanner = aranet4.client.Aranet4Scanner(on_scan)
    await scanner.start()
    await asyncio.sleep(duration)
    await scanner.stop()
    return found


def scan(duration: int = SCAN_SECONDS) -> dict:
    return asyncio.run(_scan(duration))


def list_nearby() -> int:
    found = scan()
    if not found:
        print(
            "No Aranet devices found. Check Bluetooth is on and the sensors are in range."
        )
        return 1
    for address, adv in found.items():
        name = adv.device.name or "(no name)"
        readings = getattr(adv, "readings", None)
        if readings:
            print(
                f"{address}  {name}  CO2 {readings.co2} ppm, battery {readings.battery}%"
            )
        else:
            print(
                f"{address}  {name}  no readings: enable Smart Home integration in the Aranet Home app"
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Push ntfy alerts for Aranet4 CO2 readings."
    )
    parser.add_argument(
        "--scan", action="store_true", help="list nearby Aranet devices and exit"
    )
    parser.add_argument(
        "--test-notify", action="store_true", help="send a test push and exit"
    )
    args = parser.parse_args(argv)

    if args.scan:
        return list_nearby()

    config = load_config()
    if args.test_notify:
        notify(config, "Aranet alert test", "ntfy delivery works.")
        print("Test notification sent.")
        return 0

    started = time.monotonic()
    monitors = {
        address: Monitor(config, name, last_seen=started)
        for address, name in config.sensors.items()
    }
    for address, name in config.sensors.items():
        print(f"Watching {name} ({address})")
    print(f"Alert at {config.co2_high} ppm, clear below {config.co2_clear} ppm")
    while True:
        now = time.monotonic()
        found = scan()
        for address, monitor in monitors.items():
            readings = getattr(found.get(address), "readings", None)
            if readings and readings.co2 > 0:
                print(
                    f"{monitor.name}: CO2 {readings.co2} ppm, battery {readings.battery}%"
                )
                alerts = monitor.on_reading(readings.co2, readings.battery, now)
            else:
                alerts = monitor.on_missing(now)
            for title, message, priority in alerts:
                print(f"ALERT: {title} — {message}", file=sys.stderr)
                notify(config, title, message, priority)
        time.sleep(POLL_SECONDS - SCAN_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
