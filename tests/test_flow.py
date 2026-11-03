"""Flows across modules: output of one step -> enrichment -> input of the next, possibly in another environment."""
import json
import sqlite3
import pytest
from app import core, automation


@pytest.fixture
def modules(sample_app, second_app):
    project = core.create_project('Integración')
    pid = project['id']
    identity = core.save('environments', {'name': 'Identidad', 'project_id': pid, 'base_url': sample_app.url, 'auth': {'type': 'none'}, 'variables': {}})
    orders = core.save('environments', {'name': 'Pedidos', 'project_id': pid, 'base_url': second_app.url, 'auth': {'type': 'none'}, 'variables': {}})
    login = core.save('cases', {'name': 'Login', 'type': 'api', 'project_id': pid, 'method': 'POST', 'path': '/api/login',
                                'body': {'user': 'qa', 'password': 'qa-pass'}, 'assertions': [{'type': 'status', 'expected': 200}]})
    create = core.save('cases', {'name': 'Crear pedido', 'type': 'api', 'project_id': pid, 'method': 'POST', 'path': '/api/items',
                                 'assertions': [{'type': 'status', 'expected': 201}, {'type': 'json_equals', 'path': '$.name', 'expected': 'qa'}]})
    enrich = [
        {'action': 'set', 'target': 'headers', 'path': 'Authorization', 'source': {'type': 'template', 'value': 'Bearer {{@login:$.token}}'}},
        {'action': 'set', 'target': 'body', 'path': '$.name', 'source': {'type': 'step', 'step': 'login', 'path': '$.user.name'}},
        {'action': 'set', 'target': 'body', 'path': '$.meta.origen', 'source': {'type': 'literal', 'value': 'flujo'}},
    ]
    return {'pid': pid, 'identity': identity, 'orders': orders, 'login': login, 'create': create, 'enrich': enrich,
            'a': sample_app, 'b': second_app}


def make_suite(m, enrich=None, name='Flujo'):
    steps = [{'case_id': m['login']['id'], 'alias': 'login', 'environment_id': None, 'enrich': []},
             {'case_id': m['create']['id'], 'alias': 'pedido', 'environment_id': m['orders']['id'], 'enrich': m['enrich'] if enrich is None else enrich}]
    return core.save_suite(name, m['identity']['id'], [], m['pid'], steps=steps)


def test_output_of_one_module_enriches_the_request_to_another(modules):
    suite = make_suite(modules)
    result = automation.execute_suite(suite)
    assert result['status'] == 'passed', result
    assert [(c['alias'], c['environment']) for c in result['case_runs']] == [('login', 'Identidad'), ('pedido', 'Pedidos')]
    # the second module really received the enriched request
    assert modules['b'].server.items[-1] == {'id': 2, 'name': 'qa'}
    assert len(modules['a'].server.items) == 1                                    # and the first module was not touched
    sent = core.get('runs', result['case_runs'][1]['run_id'])
    assert sent['request']['url'] == modules['b'].url + '/api/items'              # different host than the suite's default environment
    assert sent['request']['body'] == {'name': 'qa', 'meta': {'origen': 'flujo'}}  # what left is recorded
    assert sent['request']['headers']['Authorization'] == '[REDACTED]'
    assert sent['enriched'][0].startswith('Asignar header Authorization')


def test_suite_can_have_its_own_seq_separate_from_the_global_one(sample_app):
    """A suite's `seq_start` shadows the app-wide {{seq}} for its own run: starts at that number and advances by
    one per step, so two different flows (or two runs of the same one) don't fight over the same shared counter —
    the global {{seq}} used everywhere else is left untouched."""
    project = core.create_project('Consecutivo')
    env = core.save('environments', {'name': 'env', 'project_id': project['id'], 'base_url': sample_app.url, 'auth': {'type': 'none'}, 'variables': {}})
    case = core.save('cases', {'name': 'Crear', 'type': 'api', 'project_id': project['id'], 'method': 'POST', 'path': '/api/items',
                               'headers': {'Authorization': 'Bearer tok-abc123'}, 'body': {'name': '{{seq}}'},
                               'assertions': [{'type': 'status', 'expected': 201}]})
    suite = core.save_suite('Con consecutivo propio', env['id'], [], project['id'], seq_start=10,
                            steps=[{'case_id': case['id'], 'alias': 'uno', 'enrich': []}, {'case_id': case['id'], 'alias': 'dos', 'enrich': []}])
    result = automation.execute_suite(suite)
    assert result['status'] == 'passed', result
    assert [item['name'] for item in sample_app.server.items[1:]] == ['10', '11']


def test_a_failing_reference_stops_before_sending_anything(modules):
    broken = [{'action': 'set', 'target': 'body', 'path': '$.name', 'source': {'type': 'step', 'step': 'login', 'path': '$.no_existe'}}]
    result = automation.execute_suite(make_suite(modules, broken))
    assert result['case_runs'][1]['status'] == 'error'
    assert 'no_existe' in result['case_runs'][1]['error'] and 'Enriquecimiento 1' in result['case_runs'][1]['error']
    assert modules['b'].server.items == [{'id': 1, 'name': 'Acme'}]               # nothing reached module B


def test_a_step_that_failed_cannot_feed_the_next(modules):
    wrong = core.save('cases', {**modules['login'], 'body': {'user': 'x', 'password': 'y'}})     # login now answers 401
    modules['login'] = wrong
    result = automation.execute_suite(make_suite(modules))
    assert result['case_runs'][0]['status'] == 'failed' and result['case_runs'][1]['status'] == 'error'
    assert modules['b'].server.items == [{'id': 1, 'name': 'Acme'}]


def test_suite_validation_of_steps(modules):
    other = core.create_project('Otro')
    foreign = core.save('environments', {'name': 'x', 'project_id': other['id'], 'base_url': 'http://h', 'auth': {'type': 'none'}})

    def step(alias, env=None, enrich=()):
        return {'case_id': modules['login']['id'], 'alias': alias, 'environment_id': env, 'enrich': list(enrich)}

    def save(steps):
        return core.save_suite('s', modules['identity']['id'], [], modules['pid'], steps=steps)

    def ref(alias):
        return {'action': 'set', 'target': 'body', 'path': '$.x', 'source': {'type': 'step', 'step': alias, 'path': '$.a'}}
    with pytest.raises(ValueError, match='no existe o no es anterior'):
        save([step('a', enrich=[ref('b')]), step('b')])                          # forward reference
    with pytest.raises(ValueError, match='no existe o no es anterior'):
        save([step('a', enrich=[ref('a')])])                                      # self reference
    with pytest.raises(ValueError, match='repetido'):
        save([step('a'), step('a')])
    with pytest.raises(ValueError, match='no es válido'):
        save([step('con espacio')])
    with pytest.raises(ValueError, match='no pertenece al proyecto'):
        save([step('a', env=foreign['id'])])
    with pytest.raises(ValueError, match='debe empezar con'):
        save([step('a'), step('b', enrich=[{'action': 'set', 'target': 'body', 'path': 'x.y', 'source': {'type': 'literal', 'value': 1}}])])
    ok = save([step('a'), step('b', enrich=[ref('a')])])
    assert [s['alias'] for s in ok['steps']] == ['a', 'b'] and ok['case_ids'] == [modules['login']['id']] * 2


def test_enrichment_operations():
    ctx = {'a': {'http_status': 200, 'headers': {}, 'body': {'id': 7, 'tags': ['x', 'y'], 'cliente': {'nombre': 'Ana', 'extra': 1}}}}

    def run(ops, body=None, strict=True):
        request = {'path': '/orders', 'headers': {'H': '1'}, 'query': {'q': 'a'}, 'body': body}
        applied, problems = core.apply_enrichment(request, ops, ctx, {'v': 'VAR'}, strict=strict)
        return request, applied, problems

    def step(path=''):
        return {'type': 'step', 'step': 'a', 'path': path}
    req, applied, _ = run([
        {'action': 'set', 'target': 'body', 'path': '$.cliente', 'source': step('$.cliente')},                 # whole object, typed
        {'action': 'set', 'target': 'body', 'path': '$.lineas[0].sku', 'source': {'type': 'literal', 'value': 'A1'}},
        {'action': 'set', 'target': 'body', 'path': '$.pedido_id', 'source': step('$.id')},                    # number stays a number
        {'action': 'remove', 'target': 'body', 'path': '$.cliente.extra'},
        {'action': 'set', 'target': 'headers', 'path': 'X-Id', 'source': step('$.id')},
        {'action': 'remove', 'target': 'headers', 'path': 'H'},
        {'action': 'set', 'target': 'query', 'path': 'tag', 'source': step('$.tags[1]')},
        {'action': 'set', 'target': 'path', 'source': {'type': 'template', 'value': '/orders/{{@a:$.id}}/{{v}}'}},
    ])
    assert req['body'] == {'cliente': {'nombre': 'Ana'}, 'lineas': [{'sku': 'A1'}], 'pedido_id': 7}
    assert req['headers'] == {'X-Id': '7'} and req['query'] == {'q': 'a', 'tag': 'y'} and req['path'] == '/orders/7/VAR'
    assert len(applied) == 8
    merged, _, _ = run([{'action': 'merge', 'target': 'body', 'path': '$.datos', 'source': step('$.cliente')}], body={'datos': {'z': 1}})
    assert merged['body'] == {'datos': {'z': 1, 'nombre': 'Ana', 'extra': 1}}
    whole, _, _ = run([{'action': 'set', 'target': 'body', 'path': '', 'source': step('$.cliente')}], body={'old': 1})
    assert whole['body'] == {'nombre': 'Ana', 'extra': 1}
    # strict raises, preview mode reports and keeps going
    bad = [{'action': 'set', 'target': 'body', 'path': '$.a', 'source': step('$.nope')},
           {'action': 'set', 'target': 'body', 'path': '$.b', 'source': {'type': 'literal', 'value': 1}}]
    with pytest.raises(core.EnrichmentError):
        run(bad)
    soft, applied, problems = run(bad, strict=False)
    assert soft['body'] == {'b': 1} and len(applied) == 1 and 'nope' in problems[0]
    with pytest.raises(ValueError):
        core.set_path({'a': 1}, '$.a.b', 1)                                       # cannot descend into a number
    with pytest.raises(ValueError):
        core.set_path({}, '$.items[*]', 1)


def test_preview_uses_recorded_responses(modules):
    suite = make_suite(modules)
    before = core.preview_step(suite, 1)
    assert before['without_history'] == ['login'] and before['problems']          # nothing executed yet: says what is missing
    automation.execute_suite(suite)
    after = core.preview_step(suite, 1)
    assert after['problems'] == [] and after['without_history'] == []
    assert after['request']['body'] == {'name': 'qa', 'meta': {'origen': 'flujo'}}
    assert after['request']['headers']['Authorization'] == '[REDACTED]'


def test_flow_survives_export_and_import_as_new_copy(modules, tmp_path):
    suite = make_suite(modules)
    package = core.export_workspace(tmp_path / 'f.zip', suite_ids=[suite['id']])
    counts = core.import_workspace(package, 'new')
    assert counts['suites'] == 1 and counts['environments'] == 2 and counts['cases'] == 2
    copy = [s for s in core.list_items('suites') if s['id'] != suite['id']][0]
    new_envs = {e['id'] for e in core.list_items('environments')} - {modules['identity']['id'], modules['orders']['id']}
    assert copy['steps'][1]['environment_id'] in new_envs and copy['steps'][0]['case_id'] in copy['case_ids']
    assert copy['steps'][1]['enrich'] == modules['enrich'] and copy['steps'][1]['alias'] == 'pedido'
    assert automation.execute_suite(copy)['status'] == 'passed'                   # the copy is a working flow on its own


def test_add_cases_to_a_flow_keeps_its_steps(modules):
    suite = make_suite(modules)
    extra = core.save('cases', {'name': 'Extra', 'type': 'api', 'project_id': modules['pid'], 'method': 'GET', 'path': '/health',
                                'assertions': [{'type': 'status', 'expected': 200}]})
    updated = core.add_cases_to_suite(suite['id'], [extra['id']])
    assert [s['alias'] for s in updated['steps']] == ['login', 'pedido', 'Extra']
    assert updated['steps'][1]['environment_id'] == modules['orders']['id'] and updated['steps'][1]['enrich'] == modules['enrich']


def test_request_body_is_recorded_and_secrets_are_redacted(sample_app):
    core.secret_set('api-pass', 'qa-pass')
    env = core.save('environments', {'name': 'e', 'base_url': sample_app.url, 'auth': {'type': 'none'}})
    case = {'id': 'c1', 'name': 'login', 'method': 'POST', 'path': '/api/login', 'body': {'user': 'qa', 'password': '{{secret:api-pass}}'},
            'assertions': [{'type': 'status', 'expected': 200}]}
    run = core.execute_api(case, env)
    assert run['status'] == 'passed' and run['request']['body'] == {'user': 'qa', 'password': '[REDACTED]'}
    assert 'qa-pass' not in json.dumps(core.list_items('runs'))


def test_shared_database_conflicts_are_detected_not_overwritten():
    first = core.save('suites', {'name': 'v1'})
    mine = core.get('suites', first['id'])
    theirs = core.get('suites', first['id'])
    core.save('suites', {**theirs, 'name': 'cambio de otra persona'}, expected_updated_at=theirs['updated_at'])
    with pytest.raises(core.ConflictError, match='Otra persona'):
        core.save('suites', {**mine, 'name': 'mi cambio'}, expected_updated_at=mine['updated_at'])
    assert core.get('suites', first['id'])['name'] == 'cambio de otra persona'     # nothing was lost silently
    assert core.save('suites', {'id': 'nuevo-1', 'name': 'n'}, expected_updated_at=None)['name'] == 'n'   # creating is fine
    with pytest.raises(core.ConflictError):
        core.save('suites', {'id': 'nuevo-1', 'name': 'otra vez'}, expected_updated_at=None)               # already exists


def test_network_drive_databases_avoid_wal(monkeypatch):
    real_check = core.on_network_drive
    monkeypatch.setattr(core, 'on_network_drive', lambda path: True)
    core.initialize()
    assert sqlite3.connect(core.DB).execute('PRAGMA journal_mode').fetchone()[0] == 'delete'
    monkeypatch.setattr(core, 'on_network_drive', lambda path: False)
    core.initialize()
    assert sqlite3.connect(core.DB).execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
    assert real_check('\\\\servidor\\compartido\\ltw\\workspace.sqlite3') is True
    assert real_check(str(core.DB)) is False
