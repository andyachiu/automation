from types import SimpleNamespace
from history import initialize,record,connect
from nest_fan import initialize as init_fan,qualifying_room,reserve_run,tick

def setup(tmp_path,points):
    p=tmp_path/'test.sqlite3';initialize({'A':'Room'},p);init_fan(p)
    for ts,co2 in points:record('A',SimpleNamespace(co2=co2,battery=90),p,ts)
    return p

def test_requires_sustained_high_and_fresh_readings(tmp_path):
    p=setup(tmp_path,[(1000,1100),(1300,1100)])
    with connect(p) as db:
        assert qualifying_room(db,1301)=='Room'
        assert qualifying_room(db,2000) is None
    record('A',SimpleNamespace(co2=850,battery=90),p,1350)
    with connect(p) as db:assert qualifying_room(db,1351) is None

def test_short_duplicates_do_not_trigger(tmp_path):
    p=setup(tmp_path,[(1000,1100),(1030,1100)])
    with connect(p) as db:assert qualifying_room(db,1031) is None

def test_reservation_survives_failure_and_limits_daily_runtime(tmp_path):
    p=setup(tmp_path,[])
    assert reserve_run(p,10000,'test')
    assert reserve_run(p,10001,'test') is None
    for now in [13600,17200,20800]:assert reserve_run(p,now,'test')
    assert reserve_run(p,24400,'test') is None

def test_dry_run_never_needs_credentials(tmp_path):
    p=setup(tmp_path,[(1000,1100),(1300,1100)])
    assert tick('/does-not-exist',p,now=1301)=='Dry run: Room'

def test_existing_fan_timer_is_not_overridden(tmp_path,monkeypatch):
    import nest_fan
    p=setup(tmp_path,[(1000,1100),(1300,1100)])
    monkeypatch.setattr(nest_fan,'token_from_file',lambda p:('token','enterprises/p/devices/d'))
    calls=[]
    def api(url,payload=None,**kw):
        calls.append(payload)
        return {'traits':{'sdm.devices.traits.Fan':{'timerMode':'ON'}}}
    monkeypatch.setattr(nest_fan,'request_json',api)
    assert tick('unused',p,live=True,now=1301)=='Existing fan timer left unchanged'
    assert calls==[None]

def test_command_is_bounded_and_logged(tmp_path,monkeypatch):
    import nest_fan
    p=setup(tmp_path,[(1000,1100),(1300,1100)])
    monkeypatch.setattr(nest_fan,'token_from_file',lambda p:('token','enterprises/p/devices/d'))
    calls=[]
    notifications=[]
    monkeypatch.setattr(nest_fan,'notify_fan',lambda reason:notifications.append(reason))
    def api(url,payload=None,**kw):
        calls.append(payload)
        return {'traits':{'sdm.devices.traits.Fan':{'timerMode':'OFF'}}} if payload is None else {}
    monkeypatch.setattr(nest_fan,'request_json',api)
    assert tick('unused',p,live=True,now=1301)=='Fan timer accepted for 15 minutes'
    assert calls[-1]['params']=={'timerMode':'ON','duration':'900s'}
    with connect(p) as db:assert db.execute('SELECT status FROM fan_runs').fetchone()[0]=='accepted'
    assert notifications==['Room']
    assert tick('unused',p,live=True,now=1302)=='Cooldown or daily limit reached'
    assert notifications==['Room']

def test_notification_failure_does_not_repeat_fan_command(tmp_path,monkeypatch):
    import nest_fan
    import pytest
    p=setup(tmp_path,[(1000,1100),(1300,1100)])
    monkeypatch.setattr(nest_fan,'token_from_file',lambda p:('token','enterprises/p/devices/d'))
    commands=[]
    def api(url,payload=None,**kw):
        if payload is not None:commands.append(payload)
        return {'traits':{'sdm.devices.traits.Fan':{'timerMode':'OFF'}}}
    def failed(reason):raise RuntimeError('delivery failed')
    monkeypatch.setattr(nest_fan,'request_json',api)
    monkeypatch.setattr(nest_fan,'notify_fan',failed)
    with pytest.raises(RuntimeError):tick('unused',p,live=True,now=1301)
    assert tick('unused',p,live=True,now=1302)=='Cooldown or daily limit reached'
    assert len(commands)==1
    with connect(p) as db:assert db.execute('SELECT status FROM fan_runs').fetchone()[0]=='accepted'

def test_ntfy_payload_is_not_an_imessage_alert(monkeypatch):
    import nest_fan
    from ntfy_imessage_relay import should_text
    monkeypatch.setenv('NEST_NOTIFY','1')
    monkeypatch.setenv('NTFY_TOPIC','test-topic')
    requests=[]
    from contextlib import nullcontext
    monkeypatch.setattr(nest_fan.urllib.request,'urlopen',lambda req,**kw:requests.append(req) or nullcontext())
    nest_fan.notify_fan('Room')
    req=requests[0]
    assert b'15-minute' in req.data and b'Room' in req.data
    assert not should_text({'event':'message','title':req.get_header('Title')})
