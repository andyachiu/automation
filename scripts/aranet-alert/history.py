"""Local observation history. Times are reception times, not sensor sample times."""
import os
import sqlite3
import time
from pathlib import Path

DB_PATH = Path(os.environ.get('ARANET_DB', Path.home() / '.local/share/aranet/readings.sqlite3'))

def connect(path=DB_PATH):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    return db

def initialize(sensors, path=DB_PATH):
    with connect(path) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE IF NOT EXISTS rooms (address TEXT PRIMARY KEY, name TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS readings (address TEXT NOT NULL, ts INTEGER NOT NULL, co2 REAL NOT NULL, temperature REAL, humidity REAL, battery REAL, PRIMARY KEY(address,ts))')
        if 'pressure' not in {row['name'] for row in db.execute('PRAGMA table_info(readings)')}:
            db.execute('ALTER TABLE readings ADD COLUMN pressure REAL')
        db.execute('CREATE INDEX IF NOT EXISTS readings_time ON readings(ts)')
        db.executemany('INSERT INTO rooms VALUES (?,?) ON CONFLICT(address) DO UPDATE SET name=excluded.name', sensors.items())

def record(address, reading, path=DB_PATH, now=None):
    now = int(time.time() if now is None else now)
    with connect(path) as db:
        pressure = getattr(reading, 'pressure', None)
        if pressure is not None and pressure <= 0:
            pressure = None
        db.execute('INSERT OR REPLACE INTO readings (address,ts,co2,temperature,humidity,battery,pressure) VALUES (?,?,?,?,?,?,?)', (address, now, reading.co2, getattr(reading,'temperature',None), getattr(reading,'humidity',None), reading.battery, pressure))
        db.execute('DELETE FROM readings WHERE ts < ?', (now-90*86400,))

def snapshot(hours=24, path=DB_PATH, now=None):
    now = int(time.time() if now is None else now)
    with connect(path) as db:
        rooms=[]
        for room in db.execute('SELECT * FROM rooms ORDER BY name').fetchall():
            latest=db.execute('SELECT * FROM readings WHERE address=? ORDER BY ts DESC LIMIT 1',(room['address'],)).fetchone()
            points=[dict(r) for r in db.execute('SELECT ts,co2,temperature,humidity,battery,pressure FROM readings WHERE address=? AND ts>=? ORDER BY ts',(room['address'],now-hours*3600))]
            rooms.append(dict(name=room['name'], latest=dict(latest) if latest else None, points=points, peak=max((r['co2'] for r in points),default=None)))
        first=db.execute('SELECT MIN(ts) FROM readings').fetchone()[0]
    return dict(now=now,hours=hours,first=first,rooms=rooms)
