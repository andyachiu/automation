"""Nest fan controller. Explicit opt-in; credentials are never logged."""
import argparse
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from history import DB_PATH, connect

DURATION = 900
COOLDOWN = 3600
MAX_DAILY_RUNS = 4

def notify_fan(reason, test=False):
    if os.environ.get('NEST_NOTIFY') != '1':
        return
    topic = os.environ.get('NTFY_TOPIC', '')
    if not topic:
        raise RuntimeError('Fan notification requires NTFY_TOPIC')
    title = 'CasaPi fan alert test' if test else 'CasaPi fan timer accepted'
    message = ('Notification delivery test; no fan command was sent.' if test else
               f'Google accepted a {DURATION // 60}-minute fan timer. Trigger: {reason}.')
    request = urllib.request.Request(
        os.environ.get('NTFY_SERVER', 'https://ntfy.sh').rstrip('/') + '/' + topic,
        data=message.encode(), headers={'Title': title, 'Priority': 'default'})
    try:
        with urllib.request.urlopen(request, timeout=15):
            pass
    except Exception:
        raise RuntimeError('Fan notification delivery failed; fan reservation remains in place.') from None

def initialize(path=DB_PATH):
    with connect(path) as db:
        db.execute('CREATE TABLE IF NOT EXISTS fan_runs (id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, duration INTEGER NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL)')

def qualifying_room(db, now, threshold=1000):
    # At least five minutes of consecutive high observations, with no gaps
    # over ten minutes. Conservative fallback while history stores receive times.
    for room in db.execute('SELECT * FROM rooms').fetchall():
        rows=db.execute('SELECT ts,co2 FROM readings WHERE address=? AND ts>=? ORDER BY ts DESC',(room['address'],now-900)).fetchall()
        if not rows or now-rows[0]['ts']>600: continue
        latest=previous=rows[0]['ts']
        for row in rows:
            if row['co2']<threshold or previous-row['ts']>600: break
            if latest-row['ts']>=300: return room['name']
            previous=row['ts']
    return None

def reserve_run(path, now, reason):
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        recent=db.execute('SELECT MAX(ts) FROM fan_runs').fetchone()[0]
        count=db.execute('SELECT COUNT(*) FROM fan_runs WHERE ts>?',(now-86400,)).fetchone()[0]
        if (recent is not None and now-recent<COOLDOWN) or count>=MAX_DAILY_RUNS:
            return None
        return db.execute('INSERT INTO fan_runs(ts,duration,reason,status) VALUES (?,?,?,?)',(now,DURATION,reason,'pending')).lastrowid

def request_json(url, payload=None, token=None, form=False):
    headers={}
    if token: headers['Authorization']='Bearer '+token
    body=None
    if payload is not None:
        body=(urllib.parse.urlencode(payload) if form else json.dumps(payload)).encode()
        headers['Content-Type']='application/x-www-form-urlencoded' if form else 'application/json'
    try:
        with urllib.request.urlopen(urllib.request.Request(url,data=body,headers=headers),timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f'Nest API request failed (HTTP {exc.code}); credentials and response body withheld.') from None

def token_from_file(path):
    path=Path(path)
    if path.stat().st_mode & 0o077: raise RuntimeError('Nest credentials file must have mode 600.')
    c=json.loads(path.read_text())
    token=request_json('https://oauth2.googleapis.com/token',dict(client_id=c['client_id'],client_secret=c['client_secret'],refresh_token=c['refresh_token'],grant_type='refresh_token'),form=True)['access_token']
    device=c['device_name']
    parts=device.split('/')
    if len(parts)!=4 or parts[0]!='enterprises' or parts[2]!='devices' or not all(parts):
        raise ValueError('Invalid Nest device resource name')
    return token, device

def tick(credentials, path=DB_PATH, test=False, live=False, now=None):
    now=int(time.time() if now is None else now)
    initialize(path)
    with connect(path) as db:
        reason='Manual 15-minute evaluation' if test else qualifying_room(db,now,int(os.environ.get('CO2_HIGH','1000')))
        # A test also needs recent readings for both rooms to evaluate its effect.
        if test:
            rows=db.execute('SELECT rooms.address,MAX(readings.ts) AS latest FROM rooms LEFT JOIN readings USING(address) GROUP BY rooms.address').fetchall()
            if not rows or any(r['latest'] is None or now-r['latest']>600 for r in rows):
                raise RuntimeError('Test requires fresh readings from every room.')
    if not reason: return 'No sustained high CO2'
    if not live: return 'Dry run: '+reason
    token,device=token_from_file(credentials)
    url='https://smartdevicemanagement.googleapis.com/v1/'+device
    state=request_json(url,token=token)
    fan=state.get('traits',{}).get('sdm.devices.traits.Fan')
    if not fan: raise RuntimeError('Selected thermostat does not expose fan control')
    if fan.get('timerMode')=='ON': return 'Existing fan timer left unchanged'
    run_id=reserve_run(path,now,reason)
    if run_id is None: return 'Cooldown or daily limit reached'
    try:
        request_json(url+':executeCommand',dict(command='sdm.devices.commands.Fan.SetTimer',params=dict(timerMode='ON',duration=f'{DURATION}s')),token=token)
        status='accepted'
    except Exception:
        with connect(path) as db: db.execute('UPDATE fan_runs SET status=? WHERE id=?',('unknown_or_failed',run_id))
        raise
    with connect(path) as db: db.execute('UPDATE fan_runs SET status=? WHERE id=?',(status,run_id))
    notify_fan(reason)
    # Unknown outcomes are not automatically retried; the reservation persists.
    return 'Fan timer accepted for 15 minutes'

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--credentials',default=os.environ.get('NEST_CREDENTIALS',''))
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--test',action='store_true')
    parser.add_argument('--notify-test',action='store_true',help='Send only a labeled notification test; no thermostat commands')
    args=parser.parse_args()
    if args.notify_test:
        if os.environ.get('NEST_NOTIFY') != '1':
            parser.error('--notify-test requires NEST_NOTIFY=1')
        notify_fan('', test=True)
        print('Fan notification test accepted by ntfy; no fan command sent')
    else:
        print(tick(args.credentials,test=args.test,live=args.live))
