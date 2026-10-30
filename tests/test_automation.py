import datetime as dt
from app import core, automation

def test_scheduler_daily(monkeypatch,tmp_path):
    monkeypatch.setattr(core,'ROOT',tmp_path)
    monkeypatch.setattr(core,'DB',tmp_path/'db.sqlite3')
    monkeypatch.setattr(core,'ARTIFACTS',tmp_path/'evidence')
    env=core.save('environments',{'name':'QA','base_url':'http://127.0.0.1:8000','auth':{'type':'none'}})
    case=core.save('cases',{'name':'check','type':'api','method':'GET','path':'/health','assertions':[{'type':'status','expected':200}]})
    suite=core.save('suites',{'name':'smoke','environment_id':env['id'],'case_ids':[case['id']]})
    schedule=automation.create_schedule(suite['id'],'daily','10:00','UTC')
    assert dt.datetime.fromisoformat(schedule['next_run_at']).tzinfo is not None
    assert automation.next_due({'frequency':'weekdays','time':'10:00','timezone':'UTC'},dt.datetime(2026,10,30,12,tzinfo=dt.timezone.utc)).startswith('2026-11-02')
    assert core.get('schedules',schedule['id'])['enabled']

def test_ui_missing_playwright_is_recorded(monkeypatch,tmp_path):
    monkeypatch.setattr(core,'ROOT',tmp_path)
    monkeypatch.setattr(core,'DB',tmp_path/'db.sqlite3')
    monkeypatch.setattr(core,'ARTIFACTS',tmp_path/'evidence')
    core.initialize()
    case={'id':'ui-1','name':'UI','type':'ui','steps':[{'action':'navigate','url':'/'}]}
    env={'id':'env-1','base_url':'http://127.0.0.1:8765'}
    result=automation.execute_ui(case,env)
    assert result['status'] in ('failed','passed')
    assert core.get('runs',result['id'])
