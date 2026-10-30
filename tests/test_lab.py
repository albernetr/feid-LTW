"""Laboratory features: ad-hoc requests, connectivity, parameter batches and regression snapshots."""
import pytest
from app import core, automation


@pytest.fixture
def lab(sample_app):
    project = core.create_project('Lab')
    env, path = core.ensure_environment_for_url(project['id'], sample_app.url + '/api/users/1')
    return {'app': sample_app, 'pid': project['id'], 'env': env}


def adhoc(lab, path, **extra):
    case = {'name': 'adhoc', 'method': 'GET', 'path': path, 'assertions': [], **extra}
    return core.execute_api(case, lab['env'], persist=False)


def test_adhoc_requests_are_not_persisted_and_need_no_case(lab):
    run = adhoc(lab, '/api/users/1')
    assert run['http_status'] == 200 and run['status'] == 'failed'  # no assertions yet: nothing to pass
    assert core.list_items('runs') == [] and core.list_items('cases') == []
    assert adhoc(lab, '/api/users/99')['http_status'] == 404


def test_environment_is_found_or_created_from_a_url(lab):
    again, path = core.ensure_environment_for_url(lab['pid'], lab['app'].url + '/x?y=1')
    assert again['id'] == lab['env']['id'] and path == '/x?y=1'
    other, _ = core.ensure_environment_for_url(lab['pid'], 'https://example.org:8443/a')
    assert other['base_url'] == 'https://example.org:8443' and len(core.list_project_items('environments', lab['pid'])) == 2
    for bad in ('ftp://x', 'javascript:alert(1)', 'http://u:p@h/', 'nada'):
        with pytest.raises(ValueError):
            core.split_url(bad)


def test_connectivity_reports_each_step(lab):
    ok = core.check_connectivity(lab['app'].url + '/health')
    assert ok['ok'] and [s['name'] for s in ok['steps']] == ['DNS', 'TCP', 'HTTP'] and '200' in ok['steps'][-1]['detail']
    closed = core.check_connectivity('http://127.0.0.1:1/', timeout=1)
    assert not closed['ok'] and closed['steps'][-1]['name'] == 'TCP'
    unknown = core.check_connectivity('http://host-que-no-existe.invalid/', timeout=2)
    assert not unknown['ok'] and unknown['steps'][0]['name'] == 'DNS'


def test_volatile_paths_and_ignore_removal():
    body = {'id': 1, 'name': 'a', 'requested_at': '2026-10-28T10:00:00+00:00', 'items': [{'uid': '123e4567-e89b-12d3-a456-426614174000', 'n': 1}],
            'session_token': 'abc', 'ts': 1793226037123}
    assert core.suggest_volatile_paths(body) == ['$.items[*].uid', '$.requested_at', '$.session_token', '$.ts']
    for path in core.suggest_volatile_paths(body):
        core.remove_path(body, path)
    assert body == {'id': 1, 'name': 'a', 'items': [{'n': 1}]}
    assert core.json_diff({'a': 1, 'b': [1, 2]}, {'a': 2, 'b': [1], 'c': 0}) == [
        '$.a: obtenido 2 (esperado 1)', '$.b: longitud 1 (esperada 2)', '$.c: campo nuevo en la respuesta']


def test_snapshot_modes():
    text = '{"id": 1, "name": "a", "requested_at": "2026-10-28T10:00:00Z"}'
    assert core.snapshot_assertions(200, text, 'status') == [{'type': 'status', 'expected': 200}]
    schema = core.snapshot_assertions(200, text, 'structure')[1]['schema']
    assert schema['required'] == ['id', 'name', 'requested_at'] and schema['properties']['id'] == {'type': 'integer'}
    exact = core.snapshot_assertions(200, text, 'exact', ['$.requested_at'])[1]
    assert exact == {'type': 'json_matches', 'expected': {'id': 1, 'name': 'a'}, 'ignore': ['$.requested_at']}
    assert core.snapshot_assertions(200, 'hola', 'exact')[1] == {'type': 'body_equals', 'expected': 'hola'}
    with pytest.raises(ValueError):
        core.snapshot_assertions(200, 'hola', 'structure')
    assert core.validate_assertion_rule({'type': 'json_matches', 'expected': {}, 'ignore': 'x'})


def test_parameter_batch_becomes_a_suite_that_detects_changes(lab):
    """Same endpoint, several inputs -> expected responses captured once -> rerun later to see if something changed."""
    template = {'name': 'Usuario', 'type': 'api', 'method': 'GET', 'path': '/api/users/{{id}}', 'assertions': []}
    inputs = [('uno', '1'), ('dos', '2'), ('inexistente', '99')]
    rows = []
    for name, ident in inputs:                       # "Ejecutar lote": observe the real responses once
        run = core.execute_api({**template, 'variables': {'id': ident}}, lab['env'], persist=False)
        rows.append({'name': name, 'variables': {'id': ident}, 'status': run['http_status'], 'body': run['response']['body']})
    assert [r['status'] for r in rows] == [200, 200, 404]
    cases = core.dataset_cases(template, rows, lab['pid'], mode='exact', ignore=['$.requested_at'])
    suite = core.save_suite('Regresión usuarios', lab['env']['id'], [c['id'] for c in cases], lab['pid'])
    assert cases[0]['variables'] == {'id': '1'} and cases[0]['assertions'][1]['ignore'] == ['$.requested_at']

    first = automation.execute_suite(suite)
    assert first['status'] == 'passed'               # deterministic inputs -> deterministic outputs (volatile field ignored)
    assert automation.execute_suite(suite)['status'] == 'passed'

    lab['app'].server.rename_users = True            # "the code changed"
    changed = automation.execute_suite(suite)
    assert [c['status'] for c in changed['case_runs']] == ['failed', 'failed', 'passed']
    detail = core.get('runs', changed['case_runs'][0]['run_id'])
    assert any('name' in line and 'USER' in line for line in detail['assertions'][1]['actual'])
    assert core.get('runs', changed['case_runs'][2]['run_id'])['status'] == 'passed'   # the 404 case is unaffected


def test_batch_without_snapshot_keeps_template_assertions(lab):
    template = {'name': 'U', 'method': 'GET', 'path': '/api/users/{{id}}', 'assertions': [{'type': 'status', 'expected': 200}]}
    cases = core.dataset_cases(template, [{'name': 'a', 'variables': {'id': '3'}}, {'name': 'b', 'variables': {'id': '77'}}], lab['pid'])
    assert [automation.execute_suite(core.save_suite('s', lab['env']['id'], [c['id']], lab['pid']))['status'] for c in cases] == ['passed', 'failed']
    with pytest.raises(ValueError):
        core.dataset_cases(template, [], lab['pid'])


def test_add_to_existing_suite_checks_origin_and_keeps_policies(lab):
    other = core.create_project('Otro')
    template = {'name': 'U', 'method': 'GET', 'path': '/api/users/1', 'assertions': [{'type': 'status', 'expected': 200}]}
    first = core.save('cases', {**template, 'project_id': lab['pid'], 'type': 'api'})
    suite = core.save_suite('Existente', lab['env']['id'], [first['id']], lab['pid'], on_failure='stop', retries=2, variables={'a': '1'})
    second = core.save('cases', {**template, 'name': 'U2', 'project_id': lab['pid'], 'type': 'api'})
    updated = core.add_cases_to_suite(suite['id'], [second['id'], first['id']], origin=lab['env']['base_url'])
    assert updated['case_ids'] == [first['id'], second['id']]                       # appended once, order kept
    assert (updated['on_failure'], updated['retries'], updated['variables']) == ('stop', 2, {'a': '1'})
    with pytest.raises(ValueError, match='se ejecuta contra'):
        core.add_cases_to_suite(suite['id'], [second['id']], origin='http://otro-host:9999')
    # a case from another project cannot be attached
    stranger = core.save('cases', {**template, 'project_id': other['id'], 'type': 'api'})
    with pytest.raises(ValueError, match='no pertenece'):
        core.add_cases_to_suite(suite['id'], [stranger['id']])


def test_environment_is_copied_into_the_destination_project(lab):
    other = core.create_project('Destino')
    secured = core.save('environments', {**{k: v for k, v in lab['env'].items() if k != 'id'}, 'name': 'Con auth',
                                         'auth': {'type': 'bearer', 'secret': 'tok'}, 'base_url': 'http://127.0.0.1:9'})
    copy = core.environment_for_project(secured, other['id'])
    assert copy['id'] != secured['id'] and copy['project_id'] == other['id'] and copy['auth'] == {'type': 'bearer', 'secret': 'tok'}
    assert core.environment_for_project(secured, other['id'])['id'] == copy['id']      # reused, not duplicated
    assert core.environment_for_project(secured, secured['project_id']) == secured


def test_normalize_url_adds_the_chosen_protocol_only_when_missing():
    assert core.normalize_url('google.com') == 'https://google.com'
    assert core.normalize_url('  google.com/x?y=1 ', 'http') == 'http://google.com/x?y=1'
    assert core.normalize_url('//localhost:8080/a', 'http') == 'http://localhost:8080/a'
    assert core.normalize_url('http://a.b/c') == 'http://a.b/c' and core.normalize_url('https://a.b') == 'https://a.b'
    assert core.normalize_url('') == '' and core.normalize_url(None) == ''
    with pytest.raises(ValueError):
        core.normalize_url('a.b', 'ftp')
