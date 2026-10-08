import sys
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import aranet_alert  # noqa: E402
from aranet_alert import Config, Monitor, load_config, parse_sensors  # noqa: E402


def test_scan_accepts_manufacturer_only_broadcasts_and_ignores_unrelated_devices(monkeypatch):
    stopped = []
    parsed = []
    reading = SimpleNamespace(co2=991)
    manufacturer = aranet_alert.aranet4.client.Aranet4.MANUFACTURER_ID
    service = aranet_alert.aranet4.client.Aranet4.SERVICE_SAF_TEHNIKA

    def parse(device, advertisement):
        parsed.append(device.address)
        return SimpleNamespace(device=device, readings=advertisement.reading)

    class Scanner:
        def __init__(self, detection_callback, **kwargs):
            assert not kwargs.get('service_uuids')
            self.callback = detection_callback

        async def start(self):
            for address, ids, services, value in [
                ('aa:bb', {manufacturer: b'data'}, [], reading),
                ('aa:bb', {}, [service], None),
                ('cc:dd', {}, [service], None),
                ('ee:ff', {76: b'unrelated'}, [], None),
            ]:
                self.callback(
                    SimpleNamespace(address=address, name=None),
                    SimpleNamespace(manufacturer_data=ids, service_uuids=services, reading=value),
                )

        async def stop(self):
            stopped.append(True)

    monkeypatch.setattr(aranet_alert.aranet4.client, 'BleakScanner', Scanner)
    monkeypatch.setattr(aranet_alert.aranet4.client, 'Aranet4Advertisement', parse)
    found = asyncio.run(aranet_alert._scan(0))
    assert set(found) == {'AA:BB', 'CC:DD'}
    assert found['AA:BB'].readings is reading
    assert 'ee:ff' not in parsed
    assert stopped == [True]


def _monitor(**overrides) -> Monitor:
    config = Config(sensors={"AA:BB": "Bedroom"}, topic="t", **overrides)
    return Monitor(config, "Bedroom", last_seen=0)


def _titles(alerts):
    return [title for title, _, _ in alerts]


def test_high_alert_fires_once_and_clears_with_hysteresis():
    m = _monitor()
    assert m.on_reading(990, 80, 0) == []
    assert _titles(m.on_reading(1000, 80, 1)) == ["Bedroom: CO2 high"]
    assert m.on_reading(1100, 80, 2) == []
    assert m.on_reading(950, 80, 3) == []
    assert _titles(m.on_reading(890, 80, 4)) == ["Bedroom: CO2 back to normal"]
    assert m.on_reading(950, 80, 5) == []


def test_offline_after_stale_window_then_recovers():
    m = _monitor(stale_minutes=15)
    assert m.on_missing(14 * 60) == []
    assert _titles(m.on_missing(15 * 60)) == ["Bedroom: sensor offline"]
    assert m.on_missing(30 * 60) == []
    assert _titles(m.on_reading(600, 80, 31 * 60)) == ["Bedroom: back online"]


def test_low_battery_warns_once_and_resets_after_swap():
    m = _monitor(low_battery=10)
    assert _titles(m.on_reading(600, 9, 1)) == ["Bedroom: battery low"]
    assert m.on_reading(600, 8, 2) == []
    assert m.on_reading(600, 100, 3) == []
    assert _titles(m.on_reading(600, 10, 4)) == ["Bedroom: battery low"]


def test_monitors_track_sensors_independently():
    config = Config(sensors={"AA": "Bedroom", "BB": "Living room"}, topic="t")
    bedroom = Monitor(config, "Bedroom", last_seen=0)
    living = Monitor(config, "Living room", last_seen=0)
    assert _titles(bedroom.on_reading(1500, 80, 1)) == ["Bedroom: CO2 high"]
    assert living.on_reading(700, 80, 1) == []
    assert _titles(living.on_reading(1400, 80, 2)) == ["Living room: CO2 high"]


def test_parse_sensors_names_and_normalizes_addresses():
    assert parse_sensors(
        "Bedroom=e4:5f:01:ab:cd:ef, Living room = AA:BB:CC:DD:EE:FF"
    ) == {
        "E4:5F:01:AB:CD:EF": "Bedroom",
        "AA:BB:CC:DD:EE:FF": "Living room",
    }


@pytest.mark.parametrize(
    "value,match",
    [
        ("E4:5F:01:AB:CD:EF", "must be name=address"),
        ("Bedroom=", "must be name=address"),
        ("Bedroom=AA,Office=aa", "listed twice"),
        ("Café 🌿=AA", "plain ASCII"),
    ],
)
def test_parse_sensors_rejects_bad_entries(value, match):
    with pytest.raises(SystemExit, match=match):
        parse_sensors(value)


def _reading(interval, ago):
    return SimpleNamespace(interval=interval, ago=ago)


def test_next_delay_waits_for_the_earliest_next_measurement():
    assert aranet_alert.next_delay([_reading(300, 120), _reading(300, 20)]) == 185


def test_next_delay_falls_back_without_usable_readings():
    assert aranet_alert.next_delay([]) == aranet_alert.POLL_SECONDS
    assert aranet_alert.next_delay([_reading(-1, -1)]) == aranet_alert.POLL_SECONDS


def test_next_delay_is_clamped():
    assert aranet_alert.next_delay([_reading(60, 59)]) == aranet_alert.MIN_SLEEP_SECONDS
    assert (
        aranet_alert.next_delay([_reading(3600, 0)]) == aranet_alert.MAX_SLEEP_SECONDS
    )


def test_load_config_requires_sensors_and_topic():
    with pytest.raises(SystemExit, match="ARANET_SENSORS, NTFY_TOPIC"):
        load_config({})


def test_load_config_rejects_inverted_thresholds():
    env = {
        "ARANET_SENSORS": "Bedroom=aa:bb",
        "NTFY_TOPIC": "t",
        "CO2_HIGH": "1000",
        "CO2_CLEAR": "1000",
    }
    with pytest.raises(SystemExit, match="CO2_CLEAR"):
        load_config(env)


def test_notify_posts_to_topic_with_headers(monkeypatch):
    sent = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout):
        sent["request"] = request
        return FakeResponse()

    monkeypatch.setattr(aranet_alert.urllib.request, "urlopen", fake_urlopen)
    aranet_alert.notify(
        Config(sensors={}, topic="room", server="https://ntfy.example/"),
        "CO2 high",
        "1500 ppm",
        "high",
    )

    request = sent["request"]
    assert request.full_url == "https://ntfy.example/room"
    assert request.data == b"1500 ppm"
    assert request.get_header("Title") == "CO2 high"
    assert request.get_header("Priority") == "high"
