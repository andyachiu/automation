import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).parent.parent))
from history import initialize, record, snapshot

def test_history_window_latest_and_empty_room(tmp_path):
    path=tmp_path/'history.sqlite3'
    initialize({'A':'Ethan','B':'Master'},path)
    r=SimpleNamespace(co2=800,temperature=21.5,humidity=45,battery=90)
    record('A',r,path,100000)
    r.co2=1200
    record('A',r,path,200000)
    data=snapshot(24,path,200100)
    assert len(data['rooms'])==2
    a,b=data['rooms']
    assert a['latest']['co2']==1200
    assert len(a['points'])==1
    assert a['peak']==1200
    assert data['first']==100000
    assert b['latest'] is None and b['peak'] is None and b['points']==[]

def test_retention_and_duplicate_observation(tmp_path):
    path=tmp_path/'history.sqlite3'
    initialize({'A':'Room'},path)
    r=SimpleNamespace(co2=850,battery=90)
    record('A',r,path,1)
    record('A',r,path,10000000)
    record('A',r,path,10000000)
    d=snapshot(24,path,10000001)
    assert d['first']==10000000
    assert len(d['rooms'][0]['points'])==1
    assert d['rooms'][0]['points'][0]['temperature'] is None

def test_migrate_existing_history_and_record_pressure(tmp_path):
    import sqlite3
    path=tmp_path/'old.sqlite3'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE readings (address TEXT, ts INTEGER, co2 REAL, temperature REAL, humidity REAL, battery REAL, PRIMARY KEY(address,ts))')
        db.execute("INSERT INTO readings VALUES ('A',1000,800,21,45,90)")
    initialize({'A':'Room'},path)
    initialize({'A':'Room'},path)
    record('A',SimpleNamespace(co2=850,temperature=22,pressure=1012.3,battery=90),path,1300)
    points=snapshot(24,path,1400)['rooms'][0]['points']
    assert points[0]['pressure'] is None
    assert points[0]['temperature']==21
    assert points[1]['pressure']==1012.3
    record('A',SimpleNamespace(co2=850,pressure=-1,battery=90),path,1400)
    assert snapshot(24,path,1401)['rooms'][0]['latest']['pressure'] is None
