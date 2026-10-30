"""Agent protocol: ltw.spec/1 in, ltw.report/1 + ltw.failure/1 out, via library, CLI and local HTTP API."""
import json
import xml.etree.ElementTree as ET
import pytest
from app import agent, core


def make_spec(a, b, *, failing=True):
    spec = {
        'format': 'ltw.spec/1', 'name': 'Humo integración', 'project': 'Agente demo', 'default_environment': 'identidad',
        'environments': [{'name': 'identidad', 'base_url': a.url}, {'name': 'pedidos', 'base_url': b.url}],
        'cases': [
            {'name': 'login', 'method': 'POST', 'path': '/api/login', 'body': {'user': 'qa', 'password': 'qa-pass'},
             'assertions': [{'type': 'status', 'expected': 200}], 'extract': [{'name': 'token', 'path': '$.token'}]},
            {'name': 'crear pedido', 'method': 'POST', 'path': '/api/items', 'environment': 'pedidos',
             'assertions': [{'type': 'status', 'expected': 201}, {'type': 'json_equals', 'path': '$.name', 'expected': 'qa'}]},
            {'name': 'health', 'method': 'GET', 'path': '/health', 'assertions': [{'type': 'status', 'expected': 200}]},
        ],
        'suites': [{'name': 'flujo', 'environment': 'identidad', 'on_failure': 'continue', 'steps': [
            {'case': 'login', 'alias': 'login'},
            {'case': 'crear pedido', 'alias': 'pedido', 'environment': 'pedidos', 'enrich': [
                {'action': 'set', 'target': 'headers', 'path': 'Authorization', 'source': {'type': 'template', 'value': 'Bearer {{@login:$.token}}'}},
                {'action': 'set', 'target': 'body', 'path': '$.name', 'source': {'type': 'step', 'step': 'login', 'path': '$.user.name'}}]}]}],
    }
    if failing:   # a standalone case that cannot pass: no token -> 401 where 201 is expected
        spec['cases'].append({'name': 'crear sin token', 'method': 'POST', 'path': '/api/items', 'environment': 'pedidos', 'body': {'name': 'x'},
                              'assertions': [{'type': 'status', 'expected': 201}, {'type': 'json_equals', 'path': '$.name', 'expected': 'x'}],
                              'tags': ['regresion'], 'notes': 'Debe exigir token',
                              'code_hints': {'files': ['src/orders/routes.py'], 'symbol': 'create_item', 'owner': 'equipo-pedidos'}})
    return spec


def errors_of(spec, **kw):
    return {(e['path'], e['message']) for e in agent.validate_spec(spec, **kw)['errors']}


def test_schema_is_published_and_valid_json_schema():
    import jsonschema
    jsonschema.Draft202012Validator.check_schema(agent.SPEC_SCHEMA)
    assert agent.SPEC_SCHEMA['properties']['format']['const'] == 'ltw.spec/1'
    assert set(agent.SPEC_SCHEMA['properties']['cases']['items']['properties']['assertions']['items']['properties']['type']['enum']) == set(core.ASSERTION_TYPES)


def test_valid_spec_and_precise_errors(sample_app, second_app):
    spec = make_spec(sample_app, second_app)
    result = agent.validate_spec(spec)
    assert result['valid'] and result['errors'] == []
    # step 1: structural problems come first, each with the exact path
    structural = json.loads(json.dumps(spec))
    structural['cases'][0]['method'] = 'FETCH'
    structural['cases'][1]['assertions'][0]['type'] = 'status_code'
    found = {e['path']: e['message'] for e in agent.validate_spec(structural)['errors']}
    assert set(found) == {'$.cases[0].method', '$.cases[1].assertions[0].type'} and 'FETCH' in found['$.cases[0].method']
    # step 2: once the shape is right, references and flow rules are checked
    semantic = json.loads(json.dumps(spec))
    semantic['cases'][2]['path'] = 'health'
    semantic['cases'].append({'name': 'health', 'method': 'GET', 'path': '/x', 'environment': 'nube'})
    semantic['suites'][0]['steps'][1]['enrich'][0]['source']['value'] = 'Bearer {{@pedido:$.token}}'          # refers to itself
    semantic['suites'][0]['steps'].append({'case': 'no existe'})
    got = {(e['path'], e['message']) for e in agent.validate_spec(semantic)['errors']}
    text = ' | '.join(m for _, m in got)
    assert 'repetido' in text and 'nube' in text and 'La ruta debe empezar' in text
    assert 'no existe o no es anterior' in text and any(p == '$.suites[0].steps[2].case' for p, _ in got)
    assert agent.validate_spec({'format': 'otra'})['errors'] and agent.validate_spec([])['valid'] is False
    warn = json.loads(json.dumps(spec))
    warn['cases'][0]['headers'] = {'Authorization': 'Bearer literal'}
    warn['cases'][1]['assertions'] = []
    kinds = ' | '.join(w['message'] for w in agent.validate_spec(warn)['warnings'])
    assert 'Valor literal' in kinds and 'nunca pasa' in kinds


def test_import_is_an_idempotent_upsert_by_name(sample_app, second_app):
    spec = make_spec(sample_app, second_app)
    project = agent.ensure_project('Agente demo')
    first = agent.import_spec(spec, project['id'])
    ids = {kind: {n: d['id'] for n, d in group.items()} for kind, group in first.items() if kind != 'warnings'}
    spec['cases'][0]['assertions'].append({'type': 'json_exists', 'path': '$.token'})
    spec['environments'][1]['base_url'] = 'http://127.0.0.1:1'
    second = agent.import_spec(spec, project['id'])
    assert {kind: {n: d['id'] for n, d in group.items()} for kind, group in second.items() if kind != 'warnings'} == ids
    assert len(second['cases']['login']['assertions']) == 2 and second['environments']['pedidos']['base_url'] == 'http://127.0.0.1:1'
    assert len(core.list_project_items('cases', project['id'])) == 4 and len(core.list_project_items('suites', project['id'])) == 1
    suite = second['suites']['flujo']
    assert [s['alias'] for s in suite['steps']] == ['login', 'pedido'] and suite['steps'][1]['environment_id'] == second['environments']['pedidos']['id']
    assert second['cases']['crear sin token']['code_hints']['symbol'] == 'create_item'
    with pytest.raises(agent.SpecError) as info:
        agent.import_spec({'format': 'ltw.spec/1', 'cases': [{'name': 'x', 'method': 'NOPE', 'path': '/'}]}, project['id'])
    assert info.value.errors[0]['path'] == '$.cases[0].method'


def test_run_produces_a_report_with_agent_ready_failures(sample_app, second_app):
    report = agent.run_spec(make_spec(sample_app, second_app), ltw_command='python run.py --run spec.json')
    assert report['format'] == 'ltw.report/1' and report['summary']['status'] == 'failed'
    assert report['summary']['total'] == 4 and report['summary']['passed'] == 3 and report['summary']['failed'] == 1
    assert [(r['case'], r['status']) for r in report['results'] if r['suite']] == [('Login', 'passed'), ('Crear pedido', 'passed')] or \
           {(r['case'], r['status']) for r in report['results'] if r['suite']} == {('login', 'passed'), ('crear pedido', 'passed')}
    assert second_app.server.items[-1] == {'id': 3, 'name': 'qa'} or second_app.server.items[-1]['name'] == 'qa'     # the flow really crossed modules
    [failure] = report['failures']
    assert failure['format'] == 'ltw.failure/1' and failure['kind'] == 'assertion' and failure['diagnosis']['category'] == 'auth'
    assert failure['case'] == {'name': 'crear sin token', 'method': 'POST', 'path': '/api/items', 'tags': ['regresion'], 'notes': 'Debe exigir token'}
    assert failure['environment'] == {'name': 'pedidos', 'base_url': second_app.url}
    assert failure['response']['status'] == 401 and failure['response']['body'] == {'error': 'unauthorized'}
    assert failure['request']['body'] == {'name': 'x'} and failure['request']['url'] == second_app.url + '/api/items'
    assert [f['assertion'] for f in failure['expected']['failed']][0].startswith('Código HTTP igual a 201') and failure['expected']['rules']
    assert failure['where_to_look']['code_hints'] == {'files': ['src/orders/routes.py'], 'symbol': 'create_item', 'owner': 'equipo-pedidos'}
    assert failure['repro']['curl'].startswith('curl -sS -i -X POST') and second_app.url + '/api/items' in failure['repro']['curl']
    assert failure['repro']['ltw'] == 'python run.py --run spec.json' and 'sin debilitar' in failure['fix_goal']
    brief = failure['brief_markdown']
    for heading in ('## Objetivo', '## Qué se envió', '## Esperado vs obtenido', '## Respuesta recibida', '## Dónde mirar', '## Cómo reproducir', '## Reglas'):
        assert heading in brief
    assert 'src/orders/routes.py' in brief and 'no debilites' in brief
    xml = ET.fromstring(agent.report_junit(report))
    assert xml.get('tests') == '4' and xml.get('failures') == '1' and len(xml.findall('.//failure')) == 1
    assert 'qa-pass' not in json.dumps(report)                                                      # no credentials leave in the report


def test_failure_inside_a_flow_carries_the_previous_steps(sample_app, second_app):
    spec = make_spec(sample_app, second_app, failing=False)
    spec['suites'][0]['steps'][1]['enrich'][1]['source']['path'] = '$.user.nombre_inexistente'
    report = agent.run_spec(spec)
    [failure] = report['failures']
    assert failure['kind'] == 'enrichment' and failure['diagnosis']['category'] == 'flow'
    assert failure['suite_step'] == {'suite': 'flujo', 'index': 2, 'alias': 'pedido'}
    assert failure['previous_steps'] == [{'alias': 'login', 'case': 'login', 'status': 'passed', 'environment': 'identidad'}]
    assert failure['request'] is None and 'nombre_inexistente' in failure['error']
    assert second_app.server.items == [{'id': 1, 'name': 'Acme'}]                                  # nothing reached module B
    again = agent.failure_for_run_id(report['results'][1]['run_id'])                                # same failure from the stored run
    assert again['suite_step']['alias'] == 'pedido' and again['id'] == failure['id']


def test_diagnosis_covers_common_causes(sample_app, second_app):
    spec = make_spec(sample_app, second_app, failing=False)
    spec['environments'].append({'name': 'caido', 'base_url': 'http://127.0.0.1:1'})
    spec['cases'] += [
        {'name': 'sin servicio', 'method': 'GET', 'path': '/health', 'environment': 'caido', 'assertions': [{'type': 'status', 'expected': 200}]},
        {'name': 'no existe', 'method': 'GET', 'path': '/api/users/99', 'assertions': [{'type': 'status', 'expected': 200}]},
        {'name': 'variable', 'method': 'GET', 'path': '/api/users/{{id}}', 'assertions': [{'type': 'status', 'expected': 200}]},
        {'name': 'forma', 'method': 'GET', 'path': '/api/users/1', 'assertions': [{'type': 'json_schema', 'schema': {'type': 'object', 'required': ['email']}}]},
    ]
    categories = {f['case']['name']: f['diagnosis']['category'] for f in agent.run_spec(spec)['failures']}
    assert categories == {'sin servicio': 'network', 'no existe': 'not_found', 'variable': 'test_setup', 'forma': 'contract_mismatch'}


def test_cli_exit_codes_files_and_rerun_of_failures(sample_app, second_app, tmp_path, capsys):
    spec_path = tmp_path / 'spec.json'
    spec_path.write_text(json.dumps(make_spec(sample_app, second_app)), encoding='utf-8')
    out = lambda name: str(tmp_path / name)
    assert agent.cli(['--validate', str(spec_path)]) == 0
    code = agent.cli(['--run', str(spec_path), '--report', out('r.json'), '--md', out('f.md'), '--junit', out('j.xml')])
    assert code == 1
    printed = capsys.readouterr().out
    assert 'FAILED' in printed and 'crear sin token' in printed
    report = json.loads((tmp_path / 'r.json').read_text(encoding='utf-8'))
    assert report['summary']['failed'] == 1 and '## Objetivo' in (tmp_path / 'f.md').read_text(encoding='utf-8')
    assert ET.fromstring((tmp_path / 'j.xml').read_text(encoding='utf-8')).get('failures') == '1'
    # the agent "fixed" the service: the rerun of only what failed now passes
    second_app.server.items.clear()
    fixed = json.loads(spec_path.read_text(encoding='utf-8'))
    fixed['cases'][-1]['assertions'] = [{'type': 'status', 'expected': 401}]
    spec_path.write_text(json.dumps(fixed), encoding='utf-8')
    assert agent.cli(['--run', str(spec_path), '--only-failed', out('r.json'), '--report', out('r2.json')]) == 0
    rerun = json.loads((tmp_path / 'r2.json').read_text(encoding='utf-8'))
    assert rerun['summary']['total'] == 1 and rerun['results'][0]['case'] == 'crear sin token'
    # invalid spec -> exit 2 with precise paths on stderr
    spec_path.write_text(json.dumps({'format': 'ltw.spec/1', 'cases': [{'name': 'x', 'method': 'NOPE', 'path': '/'}]}), encoding='utf-8')
    assert agent.cli(['--run', str(spec_path)]) == 2 and '$.cases[0].method' in capsys.readouterr().err
    assert agent.cli(['--validate', str(spec_path)]) == 2 and agent.cli(['--schema']) == 0 and agent.cli([]) == 2


def test_cli_uses_a_throwaway_workspace_unless_asked(sample_app, second_app, tmp_path):
    spec_path = tmp_path / 'spec.json'
    spec_path.write_text(json.dumps(make_spec(sample_app, second_app, failing=False)), encoding='utf-8')
    real_db = core.DB
    assert agent.cli(['--run', str(spec_path)]) == 0
    assert core.DB != real_db                                                                       # ran somewhere else...
    core.ROOT, core.DB, core.ARTIFACTS = real_db.parent, real_db, real_db.parent / 'evidence'
    assert core.list_items('projects') == []                                                        # ...and left the real workspace untouched
    assert agent.cli(['--run', str(spec_path), '--persist', '--project', 'Persistido']) == 0
    assert [p['name'] for p in core.list_items('projects')] == ['Persistido'] and core.list_items('runs')


def test_http_api_requires_the_token_and_is_local_only(sample_app, second_app):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    agent.register_api(app)
    client = TestClient(app, base_url='http://127.0.0.1')
    token = agent.agent_token()
    assert token == agent.agent_token() and len(token) >= 24                                        # generated once, then stable
    spec = make_spec(sample_app, second_app)
    auth = {'Authorization': f'Bearer {token}'}
    assert client.get('/agent/v1/schema').json()['title'] == 'ltw.spec/1'                           # the schema is public
    assert client.post('/agent/v1/run', json=spec).status_code == 401
    assert client.post('/agent/v1/run', json=spec, headers={'Authorization': 'Bearer nope'}).status_code == 401
    assert client.post('/agent/v1/run', json=spec, headers={**auth, 'Host': 'evil.example.com'}).status_code == 403   # DNS-rebinding style access
    assert client.post('/agent/v1/validate', json=spec, headers=auth).json()['valid'] is True
    bad = client.post('/agent/v1/run', json={'format': 'ltw.spec/1', 'cases': [{'name': 'x', 'method': 'NOPE', 'path': '/'}]}, headers=auth)
    assert bad.status_code == 422 and bad.json()['errors'][0]['path'] == '$.cases[0].method'
    report = client.post('/agent/v1/run', json=spec, headers=auth).json()
    assert report['summary']['failed'] == 1
    failing_id = report['failures'][0]['id']
    assert client.get(f'/agent/v1/failures/{failing_id}', headers=auth).json()['kind'] == 'assertion'
    assert client.get(f'/agent/v1/failures/{failing_id}?format=md', headers=auth).text.startswith('# Fallo de prueba')
    assert client.get('/agent/v1/failures/nope', headers=auth).status_code == 404
    rotated = agent.rotate_agent_token()
    assert rotated != token and not agent.check_token(token) and agent.check_token(f'Bearer {rotated}')


def test_published_schema_and_example_stay_in_sync_with_the_code():
    from pathlib import Path
    docs = Path(__file__).resolve().parent.parent / 'docs' / 'agent'
    assert json.loads((docs / 'ltw.spec.schema.json').read_text(encoding='utf-8')) == agent.SPEC_SCHEMA       # regenerate with: python run.py --schema
    example = json.loads((docs / 'example.spec.json').read_text(encoding='utf-8'))
    assert agent.validate_spec(example) == {'valid': True, 'errors': [], 'warnings': []}
    protocol = (Path(__file__).resolve().parent.parent / 'AGENTS.md').read_text(encoding='utf-8')
    for term in ('ltw.spec/1', 'ltw.report/1', 'ltw.failure/1', '--only-failed', '/agent/v1/run', 'code_hints', 'where_to_look', 'brief_markdown'):
        assert term in protocol
