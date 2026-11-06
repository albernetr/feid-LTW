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

def test_dispatch_due_skips_schedules_of_a_disabled_project(monkeypatch,tmp_path):
    monkeypatch.setattr(core,'ROOT',tmp_path)
    monkeypatch.setattr(core,'DB',tmp_path/'db.sqlite3')
    monkeypatch.setattr(core,'ARTIFACTS',tmp_path/'evidence')
    project=core.create_project('P')
    env=core.save('environments',{'name':'QA','project_id':project['id'],'base_url':'http://127.0.0.1:8000','auth':{'type':'none'}})
    case=core.save('cases',{'name':'check','type':'api','project_id':project['id'],'method':'GET','path':'/health','assertions':[{'type':'status','expected':200}]})
    suite=core.save_suite('smoke',env['id'],[case['id']],project['id'])
    schedule=automation.create_schedule(suite['id'],'daily','10:00','UTC')
    core.set_project_enabled(project['id'],False)
    due=dt.datetime.fromisoformat(schedule['next_run_at'])+dt.timedelta(seconds=1)
    completed=automation.dispatch_due(due)
    assert completed==[]
    assert core.get('schedules',schedule['id'])['last_outcome']=='omitida (proyecto deshabilitado)'


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


class _FakePage:
    """Lo mínimo que automation.execute_ui toca de una Page — sin steps, nunca navega de verdad."""
    def __init__(self):
        self.closed = False
    def set_default_timeout(self, value): pass
    def route(self, pattern, handler): pass
    def goto(self, url, wait_until=None): pass
    def screenshot(self, path, full_page=True): pass
    def close(self): self.closed = True


class _FakeContext:
    def __init__(self, page):
        self._page = page
        self.closed = False
    def new_page(self): return self._page
    def close(self): self.closed = True


class _FakeBrowser:
    def __init__(self, context):
        self.contexts = [context]
        self.closed = False
    def close(self): self.closed = True


class _FakeSyncPlaywright:
    """Sustituye `with sync_playwright() as p:` — p.chromium.connect_over_cdp(url) es lo único que usa el
    modo «en vivo» de execute_ui."""
    def __init__(self, chromium):
        self.chromium = chromium
    def __enter__(self): return self
    def __exit__(self, *a): return False


def test_execute_ui_live_mode_reuses_the_existing_context_and_only_closes_its_own_page(monkeypatch, tmp_path):
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    monkeypatch.setattr(core, 'DB', tmp_path / 'db.sqlite3')
    monkeypatch.setattr(core, 'ARTIFACTS', tmp_path / 'evidence')
    core.initialize()
    page, context = _FakePage(), None
    context = _FakeContext(page)
    browser = _FakeBrowser(context)
    requested_urls = []

    class FakeChromium:
        def connect_over_cdp(self, url):
            requested_urls.append(url)
            return browser
    monkeypatch.setattr('playwright.sync_api.sync_playwright', lambda: _FakeSyncPlaywright(FakeChromium()))
    case = {'id': 'ui-1', 'name': 'UI', 'type': 'ui', 'steps': [{'action': 'navigate', 'url': '/'}]}
    env = {'id': 'env-1', 'base_url': 'http://127.0.0.1:8765', 'ui_session_mode': 'live', 'ui_live_port': 9333}
    result = automation.execute_ui(case, env)
    assert result['status'] == 'passed', result
    assert requested_urls == ['http://127.0.0.1:9333']   # se conectó al puerto configurado para este ambiente
    assert page.closed is True          # la pestaña que abrió se cierra...
    assert context.closed is False      # ...pero el contexto (y sus otras pestañas) quedan como estaban
    assert browser.closed is False      # ...y el navegador del usuario nunca se cierra


def test_execute_ui_live_mode_gives_a_clear_error_when_no_live_browser_is_listening(monkeypatch, tmp_path):
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    monkeypatch.setattr(core, 'DB', tmp_path / 'db.sqlite3')
    monkeypatch.setattr(core, 'ARTIFACTS', tmp_path / 'evidence')
    core.initialize()

    class RefusingChromium:
        def connect_over_cdp(self, url):
            raise RuntimeError('connection refused')
    monkeypatch.setattr('playwright.sync_api.sync_playwright', lambda: _FakeSyncPlaywright(RefusingChromium()))
    case = {'id': 'ui-1', 'name': 'UI', 'type': 'ui', 'steps': [{'action': 'navigate', 'url': '/'}]}
    env = {'id': 'env-1', 'base_url': 'http://127.0.0.1:8765', 'ui_session_mode': 'live', 'ui_live_port': 9333}
    result = automation.execute_ui(case, env)
    assert result['status'] == 'failed'
    assert 'Navegador en vivo' in result['error']
