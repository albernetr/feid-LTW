"""Interface observer: shape learning, baseline/drift, contract comparison, the tap proxy and history source."""
import json
import socket
import httpx
import pytest
from app import core, observer, automation


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@pytest.fixture
def project():
    return core.create_project('Observador')


def make_tap(project, target, name='Usuarios', module_id=None, **extra):
    tap = {'name': name, 'project_id': project['id'], 'listen_port': free_port(), 'target': target, 'module_id': module_id, **extra}
    observer.validate_tap(tap)
    return core.save('taps', tap)


@pytest.fixture
def stop_taps():
    yield
    observer.stop_all_taps()


def test_paths_are_normalized_with_or_without_a_contract():
    assert observer.normalize_path('/api/users/42?x=1') == '/api/users/{id}'
    assert observer.normalize_path('/a/123e4567-e89b-12d3-a456-426614174000/b') == '/a/{uuid}/b'
    assert observer.normalize_path('/files/0123456789abcdef0123') == '/files/{hash}'
    assert observer.normalize_path('/api/users/abc', ['/api/users/{userId}', '/api/users/me']) == '/api/users/{userId}'
    assert observer.normalize_path('/api/users/me', ['/api/users/{userId}', '/api/users/me']) == '/api/users/me'   # literal wins
    assert observer.normalize_path('') == '/'


def test_sensitive_values_are_masked_everywhere():
    body = {'user': 'qa', 'password': 'p4ss', 'auth': {'token': 'abc', 'ok': True}, 'items': [{'api_key': 'k', 'n': 1}]}
    assert observer.mask(body) == {'user': 'qa', 'password': '***', 'auth': {'token': '***', 'ok': True}, 'items': [{'api_key': '***', 'n': 1}]}
    flat = observer.flatten(body)
    assert flat['$.password']['examples'] == ['***'] and flat['$.user']['examples'] == ['qa']
    assert body['password'] == 'p4ss'                                      # the original is untouched


def test_shape_learning_types_optional_and_schema():
    section = observer.new_section()
    for doc in ({'id': 1, 'name': 'a', 'tags': ['x'], 'extra': None},
                {'id': 2, 'name': 'b', 'tags': [], 'score': 1.5},
                {'id': 3, 'name': 'c', 'tags': ['y', 'z'], 'score': 2}):
        observer.merge_section(section, observer.flatten(doc))
    fields = section['fields']
    assert section['total'] == 3 and fields['$.tags[*]']['count'] == 3
    assert fields['$.score']['count'] == 2 and set(fields['$.score']['types']) == {'number', 'integer'}
    assert set(observer.required_paths(section)) >= {'$.id', '$.name', '$.tags'} and '$.score' not in observer.required_paths(section)
    schema = observer.observed_schema(section)
    assert schema['required'] == ['id', 'name', 'tags']                          # 'score' (2 of 3) and 'extra' (1 of 3) are optional
    assert schema['properties']['score']['type'] == 'number' and schema['properties']['tags']['items']['type'] == 'string'
    import jsonschema
    jsonschema.Draft202012Validator(schema).validate({'id': 9, 'name': 'z', 'tags': ['q'], 'extra': None})
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate({'id': 'nine', 'name': 'z', 'tags': [], 'extra': None})


def feed(project, body, status=200, path='/api/users/1', module='Usuarios', request=None, method='GET'):
    return observer.record(module, project['id'], method, path, '', json.dumps(request) if request is not None else '', status, json.dumps(body), 5.0)


def test_baseline_and_drift_events(project):
    shape = lambda i: {'id': i, 'name': f'u{i}', 'role': 'member'}
    for i in (1, 2, 3):
        doc = feed(project, shape(i), path=f'/api/users/{i}')
    assert doc['count'] == 3 and doc['path_template'] == '/api/users/{id}' and observer.interface_state(doc) == 'sin línea base'
    based = observer.set_baseline(doc['id'])
    assert observer.interface_state(based) == 'sin cambios'
    feed(project, shape(4), path='/api/users/4')                                           # same shape: nothing to report
    assert core.get('interfaces', doc['id'])['drift'] == []
    # unannounced change: id becomes a string, role disappears, email appears, a new status code shows up
    feed(project, {'id': '5', 'name': 'u5', 'email': 'a@b.c'}, path='/api/users/5')
    feed(project, {'id': '6', 'name': 'u6', 'email': 'a@b.c'}, path='/api/users/6')
    feed(project, {'error': 'boom'}, status=500, path='/api/users/7')
    drift = core.get('interfaces', doc['id'])['drift']
    kinds = {(d['kind'], d['path']) for d in drift}
    assert ('tipo distinto', '$.id') in kinds and ('campo nuevo', '$.email') in kinds
    assert ('campo requerido ausente', '$.role') in kinds and any(d['kind'] == 'código HTTP nuevo' for d in drift)
    assert next(d for d in drift if d['path'] == '$.email')['count'] == 2                 # repeated events are counted, not duplicated
    assert observer.interface_state(core.get('interfaces', doc['id'])).endswith('cambio(s)')
    accepted = observer.set_baseline(doc['id'])                                            # the team agrees: new normal
    assert accepted['drift'] == [] and accepted['baseline_history'][-1]['accepted_changes'] >= 4
    feed(project, {'id': '8', 'name': 'u8', 'email': 'a@b.c'}, path='/api/users/8')
    assert core.get('interfaces', doc['id'])['drift'] == []


def test_non_json_and_empty_bodies_are_counted_not_learned(project):
    observer.record('M', project['id'], 'GET', '/login', '', '', 200, '<html>hi</html>', 3.0)
    doc = observer.record('M', project['id'], 'DELETE', '/x/1', '', '', 204, '', 3.0)
    html = core.get('interfaces', observer.interface_id(project['id'], 'M', 'GET', '/login'))
    assert html['non_json'] == 1 and html['responses'] == {} and doc['non_json'] == 0 and doc['responses'] == {}


CONTRACT = json.dumps({'openapi': '3.0.3', 'info': {'title': 'Usuarios', 'version': '1'}, 'paths': {'/api/users/{id}': {'get': {'responses': {
    '200': {'description': 'ok', 'content': {'application/json': {'schema': {'type': 'object', 'required': ['id', 'name', 'role'], 'properties': {
        'id': {'type': 'integer'}, 'name': {'type': 'string'}, 'role': {'type': 'string'}}}}}}}}}}})


def test_comparison_with_the_openapi_contract(project):
    module = core.import_openapi(CONTRACT, project['id'])
    good = None
    for i in (1, 2):
        good = feed(project, {'id': i, 'name': 'a', 'role': 'admin'}, path=f'/api/users/{i}')
    assert observer.compare_with_contract(good, module) == {'matched': True, 'issues': []}
    for i in (3, 4):
        bad = feed(project, {'id': str(i), 'name': 'a', 'email': 'x'}, path=f'/api/users/{i}')
    result = observer.compare_with_contract(bad, module)
    text = ' | '.join(result['issues'])
    assert 'llega como string' in text and '$.email se observa pero el contrato no lo declara' in text
    assert '$.role es requerido por el contrato pero no siempre viene' in text
    feed(project, {'error': 'x'}, status=404, path='/api/users/9')
    again = observer.compare_with_contract(core.get('interfaces', bad['id']), module)
    assert any('404' in issue for issue in again['issues'])
    other = observer.record('Usuarios', project['id'], 'POST', '/api/users', '', '', 201, '{}', 1.0)
    assert observer.compare_with_contract(other, module)['matched'] is False


def test_tap_forwards_faithfully_and_learns(project, sample_app, stop_taps):
    tap = make_tap(project, sample_app.url)
    observer.start_tap(tap['id'])
    base = f'http://127.0.0.1:{tap["listen_port"]}'
    with httpx.Client(timeout=10, trust_env=False) as client:
        direct = [client.get(f'{sample_app.url}/api/users/{i}') for i in (1, 2, 3)]
        proxied = [client.get(f'{base}/api/users/{i}') for i in (1, 2, 3)]
        assert [r.status_code for r in proxied] == [200, 200, 200]
        assert [{k: v for k, v in r.json().items() if k != 'requested_at'} for r in proxied] == [{k: v for k, v in r.json().items() if k != 'requested_at'} for r in direct]
        assert client.get(f'{base}/api/users/99').status_code == 404
        login = client.post(f'{base}/api/login', json={'user': 'qa', 'password': 'qa-pass'})
        assert login.status_code == 200 and login.json()['token'] == 'tok-abc123'              # the caller still gets the real token
        assert client.post(f'{base}/api/items', json={'name': 'x'}).status_code == 401
        page = client.get(f'{base}/login')
        assert page.status_code == 200 and 'Iniciar sesión' in page.text                       # non-JSON passes through untouched
    users = core.get('interfaces', observer.interface_id(project['id'], 'Usuarios', 'GET', '/api/users/{id}'))
    assert users['count'] == 4 and users['statuses'] == {'200': 3, '404': 1} and users['origin'] == sample_app.url
    assert set(users['responses']['200']['fields']) >= {'$.id', '$.name', '$.role', '$.requested_at'}
    login_doc = core.get('interfaces', observer.interface_id(project['id'], 'Usuarios', 'POST', '/api/login'))
    assert login_doc['request']['fields']['$.password']['examples'] == ['***']                # masked before storing
    assert 'qa-pass' not in json.dumps(core.list_items('interfaces')) and 'tok-abc123' not in json.dumps(core.list_items('interfaces'))
    assert core.get('interfaces', observer.interface_id(project['id'], 'Usuarios', 'GET', '/login'))['non_json'] == 1
    assert observer.tap_running(tap['id']) and observer.tap_calls(tap['id']) == 7
    observer.stop_tap(tap['id'])
    assert not observer.tap_running(tap['id'])
    with pytest.raises(httpx.HTTPError):
        httpx.get(f'{base}/health', timeout=2, trust_env=False)                                 # stopped for real


def test_tap_reports_a_dead_target_without_crashing(project, stop_taps):
    tap = make_tap(project, 'http://127.0.0.1:9')
    observer.start_tap(tap['id'])
    answer = httpx.get(f'http://127.0.0.1:{tap["listen_port"]}/x', timeout=10, trust_env=False)
    assert answer.status_code == 502 and 'no respondió' in answer.json()['error']
    assert core.list_items('interfaces') == []


def test_tap_detects_drift_when_the_module_changes(project, sample_app, stop_taps):
    tap = make_tap(project, sample_app.url)
    observer.start_tap(tap['id'])
    base = f'http://127.0.0.1:{tap["listen_port"]}'
    for i in (1, 2, 3):
        httpx.get(f'{base}/api/users/{i}', trust_env=False)
    key = observer.interface_id(project['id'], 'Usuarios', 'GET', '/api/users/{id}')
    observer.set_baseline(key)
    sample_app.server.drift_users = True                                    # the team behind the module ships a change
    for i in (1, 2):
        httpx.get(f'{base}/api/users/{i}', trust_env=False)
    kinds = {(d['kind'], d['path']) for d in core.get('interfaces', key)['drift']}
    assert {('tipo distinto', '$.id'), ('campo nuevo', '$.email'), ('campo requerido ausente', '$.role')} <= kinds


def test_tap_validation(project):
    base = {'name': 'A', 'project_id': project['id'], 'listen_port': 9100, 'target': 'http://127.0.0.1:1'}
    for bad, message in (({'name': ''}, 'nombre'), ({'listen_port': 'x'}, 'número'), ({'listen_port': 80}, 'entre 1024'),
                         ({'target': 'ftp://x'}, 'URL inválida')):
        with pytest.raises(ValueError, match=message):
            observer.validate_tap({**base, **bad})
    core.save('taps', {**base, 'listen_port': 9100})
    with pytest.raises(ValueError, match='ya lo usa'):
        observer.validate_tap({**base, 'name': 'B'})
    with pytest.raises(ValueError, match='No se pudo abrir'):
        busy = socket.socket(); busy.bind(('127.0.0.1', 0)); busy.listen()
        try:
            tap = core.save('taps', {**base, 'listen_port': busy.getsockname()[1]})
            observer.start_tap(tap['id'])
        finally:
            busy.close()


def test_history_source_is_used_once_and_needs_no_proxy(project, sample_app):
    env = core.save('environments', {'name': 'Usuarios', 'project_id': project['id'], 'base_url': sample_app.url, 'auth': {'type': 'none'}})
    for i in (1, 2):
        case = core.save('cases', {'name': f'u{i}', 'type': 'api', 'project_id': project['id'], 'method': 'GET', 'path': f'/api/users/{i}',
                                   'assertions': [{'type': 'status', 'expected': 200}]})
        core.execute_api(case, env)
    login = core.save('cases', {'name': 'login', 'type': 'api', 'project_id': project['id'], 'method': 'POST', 'path': '/api/login',
                                'body': {'user': 'qa', 'password': 'qa-pass'}, 'assertions': [{'type': 'status', 'expected': 200}]})
    core.execute_api(login, env)
    assert observer.observe_runs(project['id']) == 3
    assert observer.observe_runs(project['id']) == 0                                          # idempotent
    doc = core.get('interfaces', observer.interface_id(project['id'], 'Usuarios', 'GET', '/api/users/{id}'))
    assert doc['count'] == 2 and doc['origin'] == sample_app.url
    assert 'qa-pass' not in json.dumps(core.list_items('interfaces'))
    modules = observer.module_summaries(project['id'])
    assert modules == [{'module': 'Usuarios', 'interfaces': 2, 'calls': 3, 'drift': 0, 'unbaselined': 2, 'last_seen': modules[0]['last_seen']}]


def test_regression_case_from_an_observed_sample(project, sample_app, stop_taps):
    tap = make_tap(project, sample_app.url)
    observer.start_tap(tap['id'])
    base = f'http://127.0.0.1:{tap["listen_port"]}'
    httpx.get(f'{base}/api/users/2', trust_env=False)
    httpx.post(f'{base}/api/login', json={'user': 'qa', 'password': 'qa-pass'}, trust_env=False)
    users = core.get('interfaces', observer.interface_id(project['id'], 'Usuarios', 'GET', '/api/users/{id}'))
    case, env = observer.create_case_from_sample(users, project['id'])
    assert env['base_url'] == sample_app.url and case['path'] == '/api/users/2' and case['assertions'][1]['type'] == 'json_schema'
    assert core.execute_api(case, env)['status'] == 'passed'
    sample_app.server.drift_users = True
    assert core.execute_api(case, env)['status'] == 'failed'                                   # the generated case notices the change
    login_doc = core.get('interfaces', observer.interface_id(project['id'], 'Usuarios', 'POST', '/api/login'))
    login_case, _ = observer.create_case_from_sample(login_doc, project['id'])
    assert login_case['body'] == {'user': 'qa', 'password': '{{password}}'}                    # masked secrets become explicit variables
    assert 'password' in core.execute_api(login_case, env)['error']                           # ...and the case refuses to run until provided
