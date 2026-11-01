"""End-to-end tests against the local sample app (real HTTP, real Chromium for the UI test)."""
import datetime as dt
import threading
import pytest
from app import core, automation, recorder


@pytest.fixture
def world(sample_app):
    project = core.create_project('E2E')
    pid = project['id']
    env = core.save('environments', {'name': 'local', 'project_id': pid, 'base_url': sample_app.url, 'auth': {'type': 'none'}, 'variables': {}})

    def api_case(name, method, path, assertions, **extra):
        return core.save('cases', {'name': name, 'type': 'api', 'project_id': pid, 'method': method, 'path': path,
                                   'assertions': assertions, **extra})
    return {'app': sample_app, 'pid': pid, 'env': env, 'api_case': api_case}


def test_api_positive_and_negative(world):
    ok = world['api_case']('health', 'GET', '/health', [{'type': 'status', 'expected': 200}, {'type': 'json_equals', 'path': '$.status', 'expected': 'ok'}])
    assert core.execute_api(ok, world['env'])['status'] == 'passed'
    # negative: server answers 401, case expects the failure -> passes; wrong expectation -> fails
    unauthorized = world['api_case']('no auth', 'GET', '/api/items', [{'type': 'status', 'expected': 401}, {'type': 'json_exists', 'path': '$.error'}])
    assert core.execute_api(unauthorized, world['env'])['status'] == 'passed'
    wrong = world['api_case']('wrong', 'GET', '/api/items', [{'type': 'status', 'expected': 200}])
    failed = core.execute_api(wrong, world['env'])
    assert failed['status'] == 'failed' and failed['http_status'] == 401
    invalid = world['api_case']('422', 'POST', '/api/login', [{'type': 'status', 'expected': 401}], body={'user': 'x', 'password': 'y'})
    assert core.execute_api(invalid, world['env'])['status'] == 'passed'
    # connection error is recorded, not raised
    dead = dict(world['env'], base_url='http://127.0.0.1:1')
    assert core.execute_api(ok, dead)['status'] == 'error'


def test_chained_suite_shares_variables_between_cases(world):
    login = world['api_case']('login', 'POST', '/api/login',
                              [{'type': 'status', 'expected': 200}], body={'user': 'qa', 'password': 'qa-pass'},
                              extract=[{'name': 'token', 'path': '$.token'}, {'name': 'user', 'path': '$.user.name'}])
    create = world['api_case']('create', 'POST', '/api/items', [{'type': 'status', 'expected': 201}, {'type': 'json_equals', 'path': '$.name', 'expected': 'item-qa'}],
                               headers={'Authorization': 'Bearer {{token}}'}, body={'name': 'item-{{user}}'},
                               extract=[{'name': 'item_id', 'path': '$.id'}])
    read = world['api_case']('read', 'GET', '/api/items/{{item_id}}', [{'type': 'status', 'expected': 200}, {'type': 'json_equals', 'path': '$.name', 'expected': 'item-qa'}],
                             headers={'Authorization': 'Bearer {{token}}'})
    suite = core.save_suite('chain', world['env']['id'], [login['id'], create['id'], read['id']], world['pid'])
    result = automation.execute_suite(suite)
    assert result['status'] == 'passed', result
    assert [r['attempts'] for r in result['case_runs']] == [1, 1, 1]
    # the token must not be shown in history of the login run? it is a response value (not a configured secret) - but the header is redacted
    run = core.get('runs', result['case_runs'][1]['run_id'])
    assert run['request']['headers']['Authorization'] == '[REDACTED]'
    # order matters: running the dependent case first fails on the unresolved variable
    broken = core.save_suite('broken', world['env']['id'], [read['id'], login['id']], world['pid'])
    outcome = automation.execute_suite(broken)
    assert outcome['status'] == 'failed' and 'Variables sin resolver' in outcome['case_runs'][0]['error']


def test_suite_failure_policy_retries_and_cancel(world):
    bad = world['api_case']('bad', 'GET', '/health', [{'type': 'status', 'expected': 500}])
    good = world['api_case']('good', 'GET', '/health', [{'type': 'status', 'expected': 200}])
    cont = core.save_suite('cont', world['env']['id'], [bad['id'], good['id']], world['pid'], on_failure='continue')
    stop = core.save_suite('stop', world['env']['id'], [bad['id'], good['id']], world['pid'], on_failure='stop', retries=2)
    r1 = automation.execute_suite(cont)
    assert [c['status'] for c in r1['case_runs']] == ['failed', 'passed'] and r1['status'] == 'failed'
    r2 = automation.execute_suite(stop)
    assert [c['status'] for c in r2['case_runs']] == ['failed', 'skipped']
    assert r2['case_runs'][0]['attempts'] == 3 and len(core.list_items('runs')) >= 2 + 3
    token = automation.new_cancel_token(); token.set()
    r3 = automation.execute_suite(cont, cancel=token)
    assert r3['status'] == 'cancelled' and all(c['status'] == 'cancelled' for c in r3['case_runs'])
    # cancel in the middle, via the progress callback
    token2 = automation.new_cancel_token()
    r4 = automation.execute_suite(cont, cancel=token2, on_progress=lambda entry: token2.set())
    assert [c['status'] for c in r4['case_runs']] == ['failed', 'cancelled'] and r4['status'] == 'cancelled'
    with pytest.raises(ValueError, match='Política'):
        core.save_suite('x', world['env']['id'], [good['id']], world['pid'], on_failure='explode')
    with pytest.raises(ValueError, match='reintentos'):
        core.save_suite('x', world['env']['id'], [good['id']], world['pid'], retries=99)


def test_ui_case_with_real_chromium(world):
    steps = [
        {'action': 'navigate', 'url': '/login'},
        {'action': 'fill', 'locator': {'by': 'label', 'value': 'Usuario'}, 'value': 'qa'},
        {'action': 'fill', 'locator': {'by': 'label', 'value': 'Contraseña'}, 'value': '{{pwd}}'},
        {'action': 'click', 'locator': {'by': 'role', 'role': 'button', 'name': 'Entrar'}},
        {'action': 'assert_text', 'locator': {'by': 'testid', 'value': 'msg'}, 'expected': 'Bienvenido qa'},
        {'action': 'navigate', 'url': '/clientes'},
        {'action': 'assert_visible', 'locator': {'by': 'role', 'role': 'heading', 'name': 'Clientes'}},
        {'action': 'assert_url', 'expected': '/clientes'},
    ]
    env = dict(world['env'], variables={'pwd': 'qa-pass'})
    case = core.save('cases', {'name': 'login ui', 'type': 'ui', 'project_id': world['pid'], 'steps': steps})
    run = automation.execute_ui(case, env)
    assert run['status'] == 'passed', run
    assert [s['passed'] for s in run['steps']] == [True] * 8
    assert core.evidence_path(run['id'], run['screenshot']).stat().st_size > 1000
    # failing step keeps screenshot + trace and reports the failing step
    failing = core.save('cases', {'name': 'ui fail', 'type': 'ui', 'timeout_ms': 800, 'steps': [
        {'action': 'navigate', 'url': '/clientes'}, {'action': 'assert_visible', 'locator': {'by': 'text', 'value': 'No existe'}}]})
    bad = automation.execute_ui(failing, env)
    assert bad['status'] == 'failed' and bad['steps'][-1]['passed'] is False
    assert core.evidence_path(bad['id'], bad['trace']).suffix == '.zip'
    # a navigation to another host is refused
    offsite = core.save('cases', {'name': 'offsite', 'type': 'ui', 'steps': [{'action': 'navigate', 'url': 'http://example.org/'}]})
    assert 'fuera del host' in automation.execute_ui(offsite, env)['error']
    # secrets typed from variables are scrubbed out of history
    assert 'qa-pass' not in str(core.get('runs', run['id']))  # not a registered secret, but the value is not echoed in steps either
    # unresolved variable is rejected before launching the browser
    unresolved = core.save('cases', {'name': 'u', 'type': 'ui', 'steps': [{'action': 'navigate', 'url': '/{{x}}'}]})
    assert 'sin resolver' in automation.execute_ui(unresolved, world['env'])['error']


def test_recorded_script_runs_as_ui_case(world):
    script = f'''
page.goto("{world["app"].url}/login")
page.get_by_label("Usuario").fill("qa")
page.get_by_label("Contraseña").fill("qa-pass")
page.get_by_role("button", name="Entrar").click()
expect(page.get_by_test_id("msg")).to_contain_text("Bienvenido qa")
'''
    imported = recorder.import_codegen(script)
    assert imported['unsupported'] == []
    assert automation.validate_steps(imported['steps']) == []
    case = core.save('cases', {'name': 'recorded', 'type': 'ui', 'steps': imported['steps']})
    assert automation.execute_ui(case, world['env'])['status'] == 'passed'


def test_step_validation():
    assert automation.validate_steps([{'action': 'navigate', 'url': '/x'}]) == []
    problems = automation.validate_steps([{'action': 'fill', 'locator': {'by': 'label'}}, {'action': 'jump'}, {'action': 'assert_text', 'locator': {'by': 'role'}}])
    assert len(problems) >= 4
    assert automation.validate_steps([])


def test_portability_end_to_end(world, tmp_path):
    case = world['api_case']('health', 'GET', '/health', [{'type': 'status', 'expected': 200}])
    suite = core.save_suite('s', world['env']['id'], [case['id']], world['pid'])
    automation.create_schedule(suite['id'], 'daily', '03:00', 'UTC')
    path = core.export_workspace(tmp_path / 'full.zip', project_id=world['pid'])
    # Fresh workspace
    core.ROOT = tmp_path / 'other'
    core.DB = core.ROOT / 'w.sqlite3'
    core.ARTIFACTS = core.ROOT / 'ev'
    core.initialize()
    preview = core.preview_import(path, 'merge')
    assert preview['summary']['suites']['new'] == 1 and core.list_items('suites') == []
    counts = core.import_workspace(path, 'merge')
    assert counts == {'projects': 1, 'module_groups': 0, 'modules': 0, 'environments': 1, 'cases': 1, 'features': 0, 'suites': 1, 'schedules': 1}
    assert core.list_items('schedules')[0]['enabled'] is False
    imported_suite = core.list_items('suites')[0]
    assert core.get('cases', imported_suite['case_ids'][0])
    assert core.import_workspace(path, 'merge') == {t: 0 for t in core.TABLES}


def test_scheduler_variants_and_missed_policy(world):
    suite = core.save_suite('s', world['env']['id'], [world['api_case']('h', 'GET', '/health', [{'type': 'status', 'expected': 200}])['id']], world['pid'])
    now = dt.datetime(2026, 11, 2, 12, 0, tzinfo=dt.timezone.utc)
    # interval
    item = {'frequency': 'interval', 'interval_minutes': 15, 'timezone': 'UTC'}
    assert automation.next_due(item, now) == '2026-11-02T12:15:00+00:00'
    with pytest.raises(ValueError):
        automation.next_due({'frequency': 'interval', 'interval_minutes': 0, 'timezone': 'UTC'}, now)
    # once: in the past is rejected, future accepted (timezone aware)
    with pytest.raises(ValueError, match='ya pasó'):
        automation.next_due({'frequency': 'once', 'run_at': '2020-01-01T10:00', 'timezone': 'UTC'}, now)
    assert automation.next_due({'frequency': 'once', 'run_at': '2026-11-02T10:00', 'timezone': 'America/Mexico_City'}, now) == '2026-11-02T16:00:00+00:00'
    with pytest.raises(ValueError, match='Zona horaria'):
        automation.next_due({'frequency': 'daily', 'time': '10:00', 'timezone': 'Mars/Base'}, now)
    # once runs a single time and disables itself
    future = (dt.datetime.now() + dt.timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')
    once = automation.create_schedule(suite['id'], 'once', timezone=dt.datetime.now().astimezone().tzname() and 'UTC', run_at=future)
    later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3)
    assert len(automation.dispatch_due(later)) == 1
    assert core.get('schedules', once['id'])['enabled'] is False
    assert automation.dispatch_due(later) == []
    # missed policies
    run_once = automation.create_schedule(suite['id'], 'interval', interval_minutes=5, missed_policy='run_once')
    skip = automation.create_schedule(suite['id'], 'interval', interval_minutes=5, missed_policy='skip')
    way_later = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=5)
    results = automation.dispatch_due(way_later)
    assert len(results) == 1  # only the run_once schedule executed
    assert core.get('schedules', skip['id'])['last_outcome'].startswith('omitida')
    assert core.get('schedules', run_once['id'])['last_outcome'] == 'ejecutada'
    assert core.get('schedules', run_once['id'])['next_run_at'] > way_later.isoformat()
    assert 'Cada 5 min' == automation.describe_schedule(core.get('schedules', skip['id']))


def test_scheduler_single_instance_lock():
    first = automation.SchedulerLock().acquire()
    try:
        assert automation.scheduler_active()
        with pytest.raises(automation.SchedulerLockError):
            automation.SchedulerLock().acquire()
        first.heartbeat()
    finally:
        first.release()
    assert not automation.scheduler_active()
    # a stale lock (old heartbeat) is recovered automatically
    (core.ROOT / 'scheduler.lock').write_text('{"pid": 1, "heartbeat": 0}')
    recovered = automation.SchedulerLock().acquire()
    recovered.release()
    # serve_scheduler loop stops on request and always releases the lock
    calls = []
    automation.serve_scheduler(interval=0, should_stop=lambda: calls.append(1) or len(calls) > 2)
    assert not (core.ROOT / 'scheduler.lock').exists()


def test_real_codegen_recording_imports_and_runs(world):
    """tests/fixtures/codegen_login_real.py.txt was produced by a real `playwright codegen` session."""
    from pathlib import Path
    script = (Path(__file__).parent / 'fixtures' / 'codegen_login_real.py.txt').read_text(encoding='utf-8')
    imported = recorder.import_codegen(script)
    assert imported['unsupported'] == []
    assert [s['action'] for s in imported['steps']] == ['navigate', 'click', 'fill', 'press', 'fill', 'press']
    steps = [dict(s) for s in imported['steps']]
    steps[0]['url'] = '/login'  # the recording used the author's host; the environment decides the host
    steps.append({'action': 'assert_text', 'locator': {'by': 'text', 'value': 'bienvenido'}, 'expected': 'Bienvenido qa'})  # substring, like Codegen
    case = core.save('cases', {'name': 'real recording', 'type': 'ui', 'steps': steps})
    run = automation.execute_ui(case, world['env'])
    assert run['status'] == 'passed', run


def test_first_and_nth_locators_avoid_strict_mode_violations(world):
    steps = [{'action': 'navigate', 'url': '/clientes'},
             {'action': 'assert_visible', 'locator': {'by': 'role', 'role': 'listitem'}}]       # 1 item in the sample app -> fine
    case = core.save('cases', {'name': 'one', 'type': 'ui', 'steps': steps, 'timeout_ms': 3000})
    assert automation.execute_ui(case, world['env'])['status'] == 'passed'
    world['app'].server.items.append({'id': 2, 'name': 'Globex'})
    ambiguous = automation.execute_ui(case, world['env'])
    assert ambiguous['status'] == 'failed' and 'strict mode' in ambiguous['error']          # two <li>: Playwright refuses to guess
    steps[1] = {'action': 'assert_text', 'locator': {'by': 'role', 'role': 'listitem', 'nth': 1}, 'expected': 'Globex'}
    case = core.save('cases', {'name': 'nth', 'type': 'ui', 'steps': steps, 'timeout_ms': 3000})
    assert automation.execute_ui(case, world['env'])['status'] == 'passed'
    steps[1] = {'action': 'assert_text', 'locator': {'by': 'role', 'role': 'listitem', 'first': True}, 'expected': 'Acme'}
    case = core.save('cases', {'name': 'first', 'type': 'ui', 'steps': steps, 'timeout_ms': 3000})
    assert automation.execute_ui(case, world['env'])['status'] == 'passed'
    spec = recorder.import_codegen('page.get_by_role("link", name="a").nth(2).click()\npage.get_by_text("z").first.click()')
    assert [s['locator'] for s in spec['steps']] == [{'by': 'role', 'role': 'link', 'name': 'a', 'nth': 2}, {'by': 'text', 'value': 'z', 'first': True}]
