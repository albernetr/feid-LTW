"""Workspace logic: drafts, bulk editing, persistent history, spec round trip."""
import json
import pytest
from app import core, workspace as ws, agent


def draft(**kw):
    d = ws.new_draft()
    d.update(kw)
    return d


def test_rows_and_bulk_editing_round_trip():
    rows = [ws.row('Accept', 'application/json'), ws.row('X-Off', '1', on=False), ws.row('', 'ignored')]
    assert ws.rows_to_dict(rows) == {'Accept': 'application/json'}                  # disabled and unnamed rows are not sent
    text = ws.format_bulk(rows)
    assert text == 'Accept: application/json\n# X-Off: 1'
    parsed = ws.parse_bulk('Accept: application/json\n# X-Off: 1\nq=5\n\nsolo-clave')
    assert [(r['key'], r['value'], r['on']) for r in parsed] == [('Accept', 'application/json', True), ('X-Off', '1', False), ('q', '5', True), ('solo-clave', '', True)]
    assert ws.parse_bulk(ws.format_bulk(parsed))[:2] == parsed[:2]
    assert ws.dict_to_rows({'a': 1, 'b': {'x': 1}}) == [ws.row('a', '1'), ws.row('b', '{"x": 1}')]


def test_build_case_resolves_target_query_and_body(sample_app):
    d = draft(method='POST', url=sample_app.url.split('://')[1] + '/api/items?tag=a', scheme='http', body='{"name": "x"}',
              headers=[ws.row('X-Id', '1')], query=[ws.row('page', '2')])
    case, env = ws.build_case(d)
    assert env['base_url'] == sample_app.url and env['id'] == 'espacio-de-trabajo' and core.get('environments', 'espacio-de-trabajo') is None   # transient
    assert case['path'] == '/api/items' and case['query'] == {'page': '2', 'tag': 'a'} and case['body'] == {'name': 'x'} and case['headers'] == {'X-Id': '1'}
    assert ws.build_case(draft(url=sample_app.url + '/x'))[0]['body'] is None
    project = core.create_project('P')
    saved_env, _ = core.ensure_environment_for_url(project['id'], sample_app.url)
    case, env = ws.build_case(draft(env_id=saved_env['id'], url='api/users/1'))
    assert env['id'] == saved_env['id'] and case['path'] == '/api/users/1'
    for bad, message in ((draft(), 'Escribe la URL'), (draft(url='/solo/ruta'), 'URL completa'), (draft(url='x.com', body='{no json'), 'JSON válido'),
                         (draft(env_id=saved_env['id'], url='http://otro:9/x'), 'no pertenece al ambiente')):
        with pytest.raises(ValueError, match=message):
            ws.build_case(bad)


def test_placeholders_split_defined_and_missing(sample_app):
    d = draft(url=sample_app.url + '/api/users/{{id}}', headers=[ws.row('X-T', '{{tenant}}'), ws.row('Authorization', 'Bearer {{secret:tok}}')],
              variables=[ws.row('id', '3')])
    assert ws.placeholders(d) == (['id'], ['tenant'])
    assert ws.placeholders(draft()) == ([], [])


def run_and_record(d):
    case, env = ws.build_case(d)
    run = core.execute_api(case, env, persist=False)
    return ws.record_history(d, run), run


def test_history_records_searches_stars_and_trims(sample_app, monkeypatch):
    first, run = run_and_record(draft(name='uno', url=sample_app.url + '/api/users/1'))
    assert core.list_items('runs') == [] and first['result']['http_status'] == 200 and first['key'] == f'GET {sample_app.url}/api/users/1'
    second, _ = run_and_record(draft(name='dos', method='POST', url=sample_app.url + '/api/login', body='{"user": "qa", "password": "mala"}'))
    assert second['result']['http_status'] == 401
    assert [e['name'] for e in ws.list_history()] == ['dos', 'uno']                       # newest first
    assert [e['name'] for e in ws.list_history(query='login')] == ['dos'] and ws.list_history(mine_only=True, query='zzz') == []
    ws.toggle_star(first['id'])
    monkeypatch.setattr(ws, 'MAX_HISTORY', 2)
    for i in range(3):
        run_and_record(draft(name=f'n{i}', url=sample_app.url + f'/api/users/{i + 2}'))
    names = [e['name'] for e in ws.list_history()]
    assert 'uno' in names and len(names) == 3 and 'dos' not in names                        # starred survives; oldest unstarred trimmed
    assert ws.clear_history() == 2 and [e['name'] for e in ws.list_history()] == ['uno']    # clear keeps starred
    ws.delete_entry(first['id'])
    assert ws.list_history() == []


def test_load_from_history_and_previous_result_diff(sample_app):
    url = sample_app.url + '/api/users/1'
    a, _ = run_and_record(draft(name='a', url=url, headers=[ws.row('X', '1')]))
    sample_app.server.drift_users = True
    b, _ = run_and_record(draft(name='b', url=url))
    prev = ws.previous_result(draft(url=url), exclude_id=b['id'])
    assert prev['id'] == a['id']
    differences = ws.diff_bodies(prev['result']['body'], b['result']['body'])
    text = ' | '.join(differences)
    assert '$.id' in text and '$.email' in text and '$.role' in text
    assert ws.diff_bodies('hola', 'hola') == [] and 'cambió' in ws.diff_bodies('hola', 'adios')[0]
    loaded = ws.draft_from_history(a)
    assert loaded['url'] == url and ws.rows_to_dict(loaded['headers']) == {'X': '1'} and loaded['source'] == {'type': 'history', 'id': a['id']}
    assert ws.previous_result(draft(url=sample_app.url + '/nunca')) is None


def test_saved_case_round_trip_and_agent_spec(sample_app):
    project = core.create_project('P')
    env, _ = core.ensure_environment_for_url(project['id'], sample_app.url)
    case = core.save('cases', {'name': 'Crear', 'type': 'api', 'project_id': project['id'], 'method': 'POST', 'path': '/api/items', 'body': {'name': 'n'},
                               'headers': {'X-A': '1'}, 'query': {'q': '1'}, 'variables': {'v': 'x'}, 'timeout': 7,
                               'assertions': [{'type': 'status', 'expected': 201}], 'extract': [{'name': 'id', 'path': '$.id'}]})
    d = ws.draft_from_case(case, env['id'])
    rebuilt, _ = ws.build_case(d)
    for key in ('method', 'path', 'body', 'headers', 'query', 'variables', 'assertions', 'extract', 'timeout'):
        assert rebuilt[key] == case[key]
    assert d['source']['id'] == case['id']
    spec = ws.draft_to_spec(d)
    assert spec['format'] == 'ltw.spec/1' and spec['environments'][0]['base_url'] == sample_app.url
    assert agent.validate_spec(spec)['valid']                                              # what the workspace exports is a valid spec
    assert spec['cases'][0]['assertions'] == [{'type': 'status', 'expected': 201}]
    bare = ws.draft_to_spec(draft(url=sample_app.url + '/health'))
    assert bare['cases'][0]['assertions'] == [{'type': 'status', 'expected': 200}] and agent.validate_spec(bare)['valid']
    back = ws.draft_from_spec_case(spec['cases'][0], spec['environments'][0])
    assert back['url'] == sample_app.url + '/api/items' and back['scheme'] == 'http' and json.loads(back['body']) == {'name': 'n'}
