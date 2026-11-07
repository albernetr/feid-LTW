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


def test_dynamic_variables_are_resolved_fresh_and_yield_to_user_ones(world):
    """{{now_date}}/{{now_time}}/{{uuid}}/{{seq}} need no setup, resolve on every send, and a case/environment
    variable of the same name still wins (dynamic ones are the lowest-priority layer)."""
    case = world['api_case']('crear con dinamicas', 'POST', '/api/items', [{'type': 'status', 'expected': 201}],
                             headers={'Authorization': 'Bearer tok-abc123'}, body={'name': 'item-{{seq}}', 'nota': '{{now_date}} {{now_time}} {{uuid}}'})
    env = {**world['env'], 'variables': {}}
    first = core.execute_api(case, env)
    second = core.execute_api(case, env)
    assert first['status'] == 'passed' and second['status'] == 'passed'
    assert first['request']['body']['name'] != second['request']['body']['name']   # {{seq}} advanced
    assert dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d') in first['request']['body']['nota']
    assert len(first['request']['body']['nota'].split()[-1]) == 36                 # a uuid4, freshly generated
    overridden = core.execute_api({**case, 'variables': {'seq': 'fijo'}}, env)
    assert overridden['request']['body']['name'] == 'item-fijo'                    # a same-named variable wins


def test_named_sequence_keeps_going_across_standalone_cases_and_a_suite(world):
    """{{seq:nombre}} is its own counter, independent from the plain {{seq}} and from a suite's own `seq_start` —
    persisted by name, so a case run on its own (outside any suite) and the same case run later as a suite step
    share and advance the very same counter, picking up exactly where the other left off."""
    case = world['api_case']('crear con consecutivo propio', 'POST', '/api/items', [{'type': 'status', 'expected': 201}],
                             headers={'Authorization': 'Bearer tok-abc123'}, body={'name': 'conv-{{seq:conversacion}}'})
    standalone = core.execute_api(case, world['env'])
    assert standalone['request']['body']['name'] == 'conv-1'                       # first use anywhere: starts at 1
    suite = core.save_suite('Retoma el consecutivo', world['env']['id'], [case['id']], world['pid'])
    result = automation.execute_suite(suite)
    assert result['status'] == 'passed', result
    run = core.get('runs', result['case_runs'][0]['run_id'])
    assert run['request']['body']['name'] == 'conv-2'                              # continues from the standalone run, not from 1
    other = world['api_case']('otro consecutivo', 'POST', '/api/items', [{'type': 'status', 'expected': 201}],
                              headers={'Authorization': 'Bearer tok-abc123'}, body={'name': 'ticket-{{seq:ticket}}'})
    unrelated = core.execute_api(other, world['env'])
    assert unrelated['request']['body']['name'] == 'ticket-1'                      # a different name starts its own count at 1


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


def test_trusted_hosts_allows_navigating_to_an_additional_host(world):
    """`localhost` y `127.0.0.1` son hosts DISTINTOS para el chequeo (aunque el mismo servidor responda a los
    dos) — sirve para probar `trusted_hosts` (SSO/MFA como PingID) sin levantar un segundo dominio real."""
    alt_url = world['app'].url.replace('127.0.0.1', 'localhost') + '/clientes'
    case = core.save('cases', {'name': 'cross-host', 'type': 'ui', 'steps': [
        {'action': 'navigate', 'url': alt_url}, {'action': 'assert_url', 'expected': '/clientes'}]})
    assert 'fuera del host' in automation.execute_ui(case, world['env'])['error']   # sin listarlo, sigue bloqueado
    trusting_env = dict(world['env'], trusted_hosts=['localhost'])
    result = automation.execute_ui(case, trusting_env)
    assert result['status'] == 'passed', result


def test_ui_session_lets_a_case_start_already_logged_in(world):
    """Una sesión guardada (core.save_ui_session, ver recorder.capture_session) se carga en el contexto ANTES
    del primer paso: un caso que nunca pasa por el formulario de login puede llegar ya autenticado, igual que
    un login real de SSO/MFA capturado a mano una sola vez."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        context.new_page().goto(world['app'].url + '/set-cookie')
        state = context.storage_state()
        browser.close()
    case = core.save('cases', {'name': 'whoami', 'type': 'ui', 'steps': [
        {'action': 'navigate', 'url': '/whoami'},
        {'action': 'assert_text', 'locator': {'by': 'testid', 'value': 'cookie'}, 'expected': 'session=qa-token'}]})
    before = automation.execute_ui(case, world['env'])
    assert before['status'] == 'failed'   # sin sesión guardada todavía: no hay cookie que mandar
    core.save_ui_session(world['env']['id'], state)
    after = automation.execute_ui(case, world['env'])
    assert after['status'] == 'passed', after


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
    assert counts == {'projects': 1, 'module_groups': 0, 'modules': 0, 'environments': 1, 'cases': 1, 'features': 0, 'suites': 1, 'schedules': 1, 'datasets': 0, 'suite_groups': 0, 'integrations': 0}
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


def test_locator_needs_the_frame_selector_to_reach_inside_an_iframe(world):
    """Playwright no busca adentro de un <iframe> por defecto: un locator normal no lo encuentra aunque esté
    visible en pantalla. `locator.frame` (selector CSS del <iframe>) lo hace entrar con `page.frame_locator(...)`
    antes de resolver el resto del locator (ver automation._base_locator)."""
    without_frame = [{'action': 'navigate', 'url': '/con-iframe'},
                      {'action': 'assert_visible', 'locator': {'by': 'testid', 'value': 'campo-interno'}}]
    case = core.save('cases', {'name': 'sin frame', 'type': 'ui', 'steps': without_frame, 'timeout_ms': 800})
    missing = automation.execute_ui(case, world['env'])
    assert missing['status'] == 'failed'                                           # no cruza al iframe solo

    with_frame = [{'action': 'navigate', 'url': '/con-iframe'},
                  {'action': 'fill', 'locator': {'by': 'testid', 'value': 'campo-interno', 'frame': '#caja'}, 'value': 'hola'},
                  {'action': 'click', 'locator': {'by': 'testid', 'value': 'boton-interno', 'frame': '#caja'}},
                  {'action': 'assert_value', 'locator': {'by': 'testid', 'value': 'campo-interno', 'frame': '#caja'}, 'expected': 'hola'}]
    case = core.save('cases', {'name': 'con frame', 'type': 'ui', 'steps': with_frame, 'timeout_ms': 3000})
    result = automation.execute_ui(case, world['env'])
    assert result['status'] == 'passed', result
    assert [s['passed'] for s in result['steps']] == [True] * 4


def test_random_variable_picks_from_an_uploaded_dataset(world):
    """{{random:conjunto.columna}} sortea una fila del conjunto subido en cada envío. Si el conjunto no existe,
    el nombre exacto queda sin resolver — el mismo mecanismo (y el mismo mensaje) que cualquier otra variable
    faltante, sin un camino de error aparte que mantener."""
    core.save_dataset('leads', world['pid'], ['nombre', 'rfc'], [{'nombre': 'Ana', 'rfc': 'AAA'}, {'nombre': 'Beto', 'rfc': 'BBB'}, {'nombre': 'Caro', 'rfc': 'CCC'}])
    case = world['api_case']('crear con random', 'POST', '/api/items', [{'type': 'status', 'expected': 201}],
                             headers={'Authorization': 'Bearer tok-abc123'}, body={'name': '{{random:leads.nombre}}'})
    result = core.execute_api(case, world['env'])
    assert result['status'] == 'passed', result
    assert result['request']['body']['name'] in ('Ana', 'Beto', 'Caro')

    missing = world['api_case']('conjunto inexistente', 'POST', '/api/items', [{'type': 'status', 'expected': 201}],
                                headers={'Authorization': 'Bearer tok-abc123'}, body={'name': '{{random:no_existe}}'})
    outcome = core.execute_api(missing, world['env'])
    assert outcome['status'] == 'error' and 'Variables sin resolver' in outcome['error']


def test_suite_draw_keeps_the_same_row_across_all_steps(world):
    """Un Sorteo se resuelve UNA vez por corrida y lo comparten todos los pasos — a diferencia de {{random:...}}
    suelto, que sortea de nuevo en cada request — así el nombre y el RFC de "la misma persona" no se desalinean
    entre el paso 1 y el paso 2 de una misma conversación."""
    core.save_dataset('leads', world['pid'], ['nombre', 'rfc'], [{'nombre': 'Ana', 'rfc': 'AAA'}, {'nombre': 'Beto', 'rfc': 'BBB'}])
    step1 = world['api_case']('paso1', 'POST', '/api/items', [{'type': 'status', 'expected': 201}],
                              headers={'Authorization': 'Bearer tok-abc123'}, body={'name': 'n={{draw:lead.nombre}}'})
    step2 = world['api_case']('paso2', 'POST', '/api/items', [{'type': 'status', 'expected': 201}],
                              headers={'Authorization': 'Bearer tok-abc123'}, body={'name': 'r={{draw:lead.rfc}}'})
    suite = core.save_suite('con sorteo', world['env']['id'], [step1['id'], step2['id']], world['pid'],
                            draws=[{'alias': 'lead', 'dataset': 'leads'}])
    result = automation.execute_suite(suite)
    assert result['status'] == 'passed', result
    run1 = core.get('runs', result['case_runs'][0]['run_id'])
    run2 = core.get('runs', result['case_runs'][1]['run_id'])
    nombre, rfc = run1['request']['body']['name'][2:], run2['request']['body']['name'][2:]
    assert rfc == {'Ana': 'AAA', 'Beto': 'BBB'}[nombre]   # el paso 2 usó la misma fila que el paso 1, no una nueva


def test_materialize_suite_variants_freezes_the_draw(world):
    """Generar N copias congela el sorteo a un valor fijo por copia (no vuelve a sortear en cada corrida de ESA
    copia) — a diferencia de correr la misma suite N veces, que vuelve a sortear en cada una."""
    core.save_dataset('leads', world['pid'], ['nombre'], [{'nombre': 'Ana'}, {'nombre': 'Beto'}, {'nombre': 'Caro'}])
    case = world['api_case']('paso', 'POST', '/api/items', [{'type': 'status', 'expected': 201}],
                             headers={'Authorization': 'Bearer tok-abc123'}, body={'name': '{{draw:lead.nombre}}'})
    suite = core.save_suite('plantilla', world['env']['id'], [case['id']], world['pid'], draws=[{'alias': 'lead', 'dataset': 'leads'}])
    created = core.materialize_suite_variants(suite, 3)
    assert len(created) == 3
    assert all(copy_suite['draws'] == [] for copy_suite in created)   # el sorteo ya no está: quedó convertido en variable fija
    for copy_suite in created:
        value = copy_suite['variables']['draw:lead.nombre']
        assert value in ('Ana', 'Beto', 'Caro')
        first = automation.execute_suite(copy_suite)
        second = automation.execute_suite(copy_suite)
        name1 = core.get('runs', first['case_runs'][0]['run_id'])['request']['body']['name']
        name2 = core.get('runs', second['case_runs'][0]['run_id'])['request']['body']['name']
        assert name1 == name2 == value   # frozen: las dos corridas de la MISMA copia dan siempre el mismo valor


def test_execute_suite_many_draws_independently_each_run(world):
    """«Ejecutar N veces» no deja nada materializado: cada corrida vuelve a sortear por su cuenta."""
    core.save_dataset('leads', world['pid'], ['nombre'], [{'nombre': n} for n in ('A', 'B', 'C', 'D', 'E')])
    case = world['api_case']('paso', 'POST', '/api/items', [{'type': 'status', 'expected': 201}],
                             headers={'Authorization': 'Bearer tok-abc123'}, body={'name': '{{random:leads.nombre}}'})
    suite = core.save_suite('bulk', world['env']['id'], [case['id']], world['pid'])
    summary = automation.execute_suite_many(suite, 5)
    assert summary['total'] == summary['completed'] == 5
    assert summary['passed'] == 5
    names = {core.get('runs', r['case_runs'][0]['run_id'])['request']['body']['name'] for r in summary['runs']}
    assert len(names) > 1   # con 5 opciones y 5 corridas, prácticamente seguro que no todas coincidan


def test_suite_group_runs_flows_and_loose_cases_together(world):
    """Una Suite (grupo) junta Flujos y Casos sueltos y los corre todos en un solo run combinado — a diferencia
    de un Flujo, que es UNA secuencia encadenada de pasos."""
    flow_case = world['api_case']('paso del flujo', 'GET', '/health', [{'type': 'status', 'expected': 200}])
    flow = core.save_suite('mini flujo', world['env']['id'], [flow_case['id']], world['pid'])
    loose_case = world['api_case']('caso suelto', 'GET', '/health', [{'type': 'status', 'expected': 200}])
    group = core.save_suite_group('mi suite', world['pid'], [{'type': 'flow', 'id': flow['id']}, {'type': 'case', 'id': loose_case['id']}],
                                  environment_id=world['env']['id'])
    result = automation.execute_suite_group(group)
    assert result['status'] == 'passed', result
    assert result['type'] == 'suite_group'
    assert [i['type'] for i in result['item_runs']] == ['flow', 'case']
    assert all(i['status'] == 'passed' for i in result['item_runs'])


def test_suite_group_requires_an_environment_for_loose_cases(world):
    case = world['api_case']('suelto', 'GET', '/health', [{'type': 'status', 'expected': 200}])
    with pytest.raises(ValueError, match='ambiente'):
        core.save_suite_group('sin ambiente', world['pid'], [{'type': 'case', 'id': case['id']}])


def test_suite_group_cascades_on_project_delete(world):
    case = world['api_case']('suelto', 'GET', '/health', [{'type': 'status', 'expected': 200}])
    core.save_suite_group('a borrar', world['pid'], [{'type': 'case', 'id': case['id']}], environment_id=world['env']['id'])
    assert len(core.list_project_items('suite_groups', world['pid'])) == 1
    core.delete_project_cascade(world['pid'])
    assert core.list_items('suite_groups') == []


def test_execute_suites_runs_only_the_given_list(world):
    """«Ejecutar todos» y «ejecutar seleccionados» son la misma función: una lista explícita de ids, nunca
    «todos» hardcodeado — acá se prueba con una selección parcial de 2 de 3 flujos."""
    ids = []
    for name in ('uno', 'dos', 'tres'):
        case = world['api_case'](name, 'GET', '/health', [{'type': 'status', 'expected': 200}])
        ids.append(core.save_suite(name, world['env']['id'], [case['id']], world['pid'])['id'])
    summary = automation.execute_suites(ids[:2])
    assert summary['total'] == summary['completed'] == 2
    assert summary['passed'] == 2
    names = {r['suite_name'] for r in summary['runs']}
    assert names == {'uno', 'dos'}   # el tercero, fuera de la selección, no corrió


def test_execute_suite_groups_runs_only_the_given_list(world):
    case = world['api_case']('suelto', 'GET', '/health', [{'type': 'status', 'expected': 200}])
    g1 = core.save_suite_group('g1', world['pid'], [{'type': 'case', 'id': case['id']}], environment_id=world['env']['id'])
    core.save_suite_group('g2', world['pid'], [{'type': 'case', 'id': case['id']}], environment_id=world['env']['id'])
    summary = automation.execute_suite_groups([g1['id']])
    assert summary['total'] == summary['completed'] == 1
    assert summary['runs'][0]['group_name'] == 'g1'   # g2 nunca corrió: no estaba en la lista


def test_partial_retest_skips_steps_and_reuses_their_last_response_for_enrichment(world):
    """Re-ejecutar solo el paso 3 de un flujo de 3 debe: no repetir el paso 1 (queda 'skipped'), y seguir pudiendo
    enriquecer el paso 3 con lo que el paso 1 devolvió LA VEZ ANTERIOR que de verdad corrió (core.history_context,
    el mismo mecanismo que ya usa la Vista previa del enriquecimiento)."""
    login = world['api_case']('login', 'POST', '/api/login', [{'type': 'status', 'expected': 200}],
                              body={'user': 'qa', 'password': 'qa-pass'})
    middle = world['api_case']('medio', 'GET', '/health', [{'type': 'status', 'expected': 200}])
    create = world['api_case']('crear', 'POST', '/api/items', [{'type': 'status', 'expected': 201}],
                               headers={'Authorization': 'Bearer {{@login:$.token}}'}, body={'name': 'retest'})
    suite = core.save_suite('con reintento', world['env']['id'], [login['id'], middle['id'], create['id']], world['pid'],
                            steps=[{'case_id': login['id'], 'alias': 'login', 'environment_id': None, 'enrich': []},
                                   {'case_id': middle['id'], 'alias': 'medio', 'environment_id': None, 'enrich': []},
                                   {'case_id': create['id'], 'alias': 'crear', 'environment_id': None,
                                    'enrich': [{'action': 'set', 'target': 'headers', 'path': 'Authorization',
                                                'source': {'type': 'template', 'value': 'Bearer {{@login:$.token}}'}}]}])
    full = automation.execute_suite(suite)
    assert full['status'] == 'passed', full

    retest = automation.execute_suite(suite, only_aliases={'crear'})
    # 'crear' solo pasa si pudo resolver {{@login:$.token}} desde el contexto — si history_context no hubiera
    # encontrado la respuesta registrada de 'login', el enriquecimiento (strict=True) habría fallado antes de
    # enviar nada, y el status de 'crear' sería 'error', no 'passed'.
    assert retest['status'] == 'passed', retest
    statuses = {r['alias']: r['status'] for r in retest['case_runs']}
    assert statuses == {'login': 'skipped', 'medio': 'skipped', 'crear': 'passed'}


def test_executed_by_is_stamped_on_the_suite_run_and_on_every_step(world):
    """Quién ejecutó un Flujo debe quedar en el run combinado Y en el run propio de cada paso (cada uno es
    consultable por separado desde el Historial)."""
    user = core.create_user('Ana', 'Pérez', 'ana@acme.com', 'password', password='algomuylargo')
    case = world['api_case']('health', 'GET', '/health', [{'type': 'status', 'expected': 200}])
    suite = core.save_suite('s', world['env']['id'], [case['id']], world['pid'])
    result = automation.execute_suite(suite, executed_by=user['id'])
    assert result['executed_by'] == user['id']
    step_run = core.get('runs', result['case_runs'][0]['run_id'])
    assert step_run['executed_by'] == user['id']


def test_executed_by_propagates_into_a_suite_group_and_its_nested_flow(world):
    user = core.create_user('Ana', 'Pérez', 'ana@acme.com', 'password', password='algomuylargo')
    flow_case = world['api_case']('paso', 'GET', '/health', [{'type': 'status', 'expected': 200}])
    flow = core.save_suite('mini flujo', world['env']['id'], [flow_case['id']], world['pid'])
    loose_case = world['api_case']('suelto', 'GET', '/health', [{'type': 'status', 'expected': 200}])
    group = core.save_suite_group('g', world['pid'], [{'type': 'flow', 'id': flow['id']}, {'type': 'case', 'id': loose_case['id']}],
                                  environment_id=world['env']['id'])
    result = automation.execute_suite_group(group, executed_by=user['id'])
    assert result['executed_by'] == user['id']
    flow_run = core.get('runs', result['item_runs'][0]['run_id'])
    assert flow_run['executed_by'] == user['id']                       # el Flujo miembro hereda el mismo executed_by
    assert core.get('runs', flow_run['case_runs'][0]['run_id'])['executed_by'] == user['id']   # y su propio paso también
    case_run = core.get('runs', result['item_runs'][1]['run_id'])
    assert case_run['executed_by'] == user['id']                       # el Caso suelto miembro también


def test_execute_suites_and_execute_suite_groups_forward_executed_by(world):
    user = core.create_user('Ana', 'Pérez', 'ana@acme.com', 'password', password='algomuylargo')
    case = world['api_case']('health', 'GET', '/health', [{'type': 'status', 'expected': 200}])
    suite = core.save_suite('s', world['env']['id'], [case['id']], world['pid'])
    batch = automation.execute_suites([suite['id']], executed_by=user['id'])
    assert batch['runs'][0]['executed_by'] == user['id']
    group = core.save_suite_group('g', world['pid'], [{'type': 'case', 'id': case['id']}], environment_id=world['env']['id'])
    batch_groups = automation.execute_suite_groups([group['id']], executed_by=user['id'])
    assert batch_groups['runs'][0]['executed_by'] == user['id']


def test_dispatch_due_stamps_scheduled_runs_with_the_scheduler_sentinel(world):
    case = world['api_case']('health', 'GET', '/health', [{'type': 'status', 'expected': 200}])
    suite = core.save_suite('s', world['env']['id'], [case['id']], world['pid'])
    schedule = automation.create_schedule(suite['id'], 'daily', '00:00', 'UTC')
    schedule['next_run_at'] = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)).isoformat()
    core.save('schedules', schedule)
    completed = automation.dispatch_due()
    assert len(completed) == 1 and completed[0]['executed_by'] == 'scheduler'
    assert core.user_display_name('scheduler') == 'Programación automática'
