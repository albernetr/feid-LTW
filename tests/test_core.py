import io
import json
import os
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from pathlib import Path
import pytest
from app import core

SPEC='''openapi: 3.0.3
info:
  title: Demo
  version: '1'
paths:
  /hello:
    get:
      responses:
        '200':
          description: ok
'''

@pytest.fixture(autouse=True)
def workspace(tmp_path,monkeypatch):
    monkeypatch.setattr(core,'ROOT',tmp_path)
    monkeypatch.setattr(core,'DB',tmp_path/'test.db')
    monkeypatch.setattr(core,'ARTIFACTS',tmp_path/'evidence')
    core.initialize()

def test_httpx_client_defaults_to_the_os_trust_store_but_lets_callers_override_verify():
    """Corporate networks terminate TLS with their own root CA, which certifi's bundled list doesn't know about —
    every outbound request goes through this helper so it checks against the OS trust store (which does) instead,
    without taking away a caller's ability to pass its own `verify` (e.g. disabling it for a known-bad cert)."""
    import ssl
    import truststore
    client = core._httpx_client(timeout=5)
    try:
        assert isinstance(client._transport._pool._ssl_context, truststore.SSLContext)
    finally:
        client.close()
    sentinel = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with core._httpx_client(timeout=5, verify=sentinel) as client:
        assert client._transport._pool._ssl_context is sentinel


def test_openapi():
    m=core.import_openapi(SPEC)
    assert m['operations'][0]['path']=='/hello'
    assert len(core.list_items('modules'))==1
    with pytest.raises(ValueError):core.import_openapi('foo: bar')


def test_openapi_resolves_local_refs_and_rejects_external_refs():
    raw=json.dumps({'openapi':'3.0.3','info':{'title':'Refs'},'components':{'parameters':{'Trace':{'name':'X-Trace','in':'header','required':True}}},'paths':{'/items':{'get':{'parameters':[{'$ref':'#/components/parameters/Trace'}],'responses':{'200':{'description':'ok'}}}}}})
    module=core.parse_openapi(raw)
    assert module['operations'][0]['parameters'][0]['name']=='X-Trace'
    with pytest.raises(ValueError, match='locales'):
        core.parse_openapi(json.dumps({'openapi':'3.0.3','paths':{'/x':{'get':{'$ref':'other.yaml#/get'}}}}))


def test_openapi_rejects_oversized_document():
    huge = 'openapi: 3.0.3\ninfo:\n  title: X\npaths: {}\n# ' + ('x' * (core.MAX_SPEC_BYTES + 10))
    with pytest.raises(ValueError, match='límite'):
        core.parse_openapi(huge)


def test_openapi_rejects_too_deep_ref_chain():
    schemas = {f'S{i}': {'$ref': f'#/components/schemas/S{i + 1}'} for i in range(core.MAX_REF_DEPTH + 10)}
    schemas[f'S{core.MAX_REF_DEPTH + 10}'] = {'type': 'string'}
    raw = json.dumps({'openapi': '3.0.3', 'info': {'title': 'Deep'}, 'components': {'schemas': schemas},
                       'paths': {'/x': {'get': {'responses': {'200': {'description': 'ok', 'content':
                           {'application/json': {'schema': {'$ref': '#/components/schemas/S0'}}}}}}}}})
    with pytest.raises(ValueError, match='profunda'):
        core.parse_openapi(raw)


def test_ensure_environment_for_module_creates_then_reuses():
    project = core.create_project('P')
    raw = 'openapi: 3.0.3\ninfo: {title: X, version: "1"}\nservers: [{url: https://api.example.com/v1}]\npaths: {}\n'
    module = core.import_openapi(raw, project['id'])

    env, created = core.ensure_environment_for_module(project['id'], module)
    assert created is True
    assert env['base_url'] == 'https://api.example.com/v1'
    assert env['name'] == module['name']

    again, created_again = core.ensure_environment_for_module(project['id'], module)
    assert created_again is False
    assert again['id'] == env['id']
    assert len(core.list_project_items('environments', project['id'])) == 1


def test_ensure_environment_for_module_returns_none_without_a_resolvable_server():
    project = core.create_project('P')
    module = core.import_openapi(SPEC, project['id'])  # no servers, no source_url
    env, created = core.ensure_environment_for_module(project['id'], module)
    assert env is None and created is False


def test_create_component_requires_a_name_and_at_least_one_kind():
    project = core.create_project('P')
    with pytest.raises(ValueError, match='nombre'):
        core.create_component('', project['id'])
    with pytest.raises(ValueError, match='backend, frontend'):
        core.create_component('X', project['id'], is_backend=False, is_frontend=False)
    component = core.create_component('Front web', project['id'], is_backend=False, is_frontend=True)
    assert component['is_backend'] is False and component['is_frontend'] is True and component['manual'] is True and component['operations'] == []
    assert core.component_kind_label(component) == 'Frontend'

    full_stack = core.create_component('Monolito', project['id'], is_backend=True, is_frontend=True)
    assert core.component_flags(full_stack) == (True, True)
    assert core.component_kind_label(full_stack) == 'Backend + Frontend'


def test_create_component_links_environments_and_rejects_a_foreign_one():
    project = core.create_project('P')
    env = core.save('environments', {'name': 'QA', 'project_id': project['id'], 'base_url': 'https://x', 'auth': {'type': 'none'}, 'variables': {}})
    component = core.create_component('Back sin contrato', project['id'], environment_ids=[env['id']])
    assert component['environment_ids'] == [env['id']]

    other_project = core.create_project('Otro')
    with pytest.raises(ValueError, match='no pertenece'):
        core.create_component('X', other_project['id'], environment_ids=[env['id']])

    with pytest.raises(ValueError, match='inexistente'):
        core.create_component('Y', project['id'], environment_ids=['no-existe'])


def test_update_component_renames_and_reclassifies_any_component_imported_or_manual():
    project = core.create_project('P')
    imported = core.import_openapi(SPEC, project['id'])
    renamed = core.update_component(imported['id'], 'Nombre propio', True, True)
    assert renamed['name'] == 'Nombre propio' and core.component_flags(renamed) == (True, True)
    assert renamed['operations'] == imported['operations']   # contract-sourced fields untouched

    manual = core.create_component('X', project['id'])
    updated = core.update_component(manual['id'], 'Y', False, True)
    assert updated['name'] == 'Y' and core.component_flags(updated) == (False, True)
    with pytest.raises(ValueError, match='obligatorio'):
        core.update_component(manual['id'], '', True, False)
    with pytest.raises(ValueError, match='backend, frontend'):
        core.update_component(manual['id'], 'Y', False, False)


def test_set_component_environments_works_on_any_component_and_component_environment_resolves_first():
    project = core.create_project('P')
    dev = core.save('environments', {'name': 'Dev', 'project_id': project['id'], 'base_url': 'https://dev.example.com', 'auth': {'type': 'none'}, 'variables': {}})
    qa = core.save('environments', {'name': 'QA', 'project_id': project['id'], 'base_url': 'https://qa.example.com', 'auth': {'type': 'none'}, 'variables': {}})
    imported = core.import_openapi(SPEC, project['id'])  # works even on an imported (non-manual) component
    core.set_component_environments(imported['id'], [dev['id'], qa['id']])
    updated = core.get('modules', imported['id'])
    envs = core.component_environments(updated)
    assert [e['id'] for e in envs] == [dev['id'], qa['id']]
    assert core.component_environment(updated)['id'] == dev['id']


def test_component_environment_falls_back_to_url_matching_for_legacy_components():
    project = core.create_project('P')
    core.save('environments', {'name': 'Por URL', 'project_id': project['id'], 'base_url': 'https://by-url.example.com', 'auth': {'type': 'none'}, 'variables': {}})
    raw = ('openapi: 3.0.3\ninfo: {title: X, version: "1"}\nservers: [{url: https://by-url.example.com}]\n'
           'paths: {"/x": {"get": {"responses": {"200": {"description": "ok"}}}}}\n')
    module = core.import_openapi(raw, project['id'])
    assert core.component_environment(module)['base_url'] == 'https://by-url.example.com'


def test_projects_persist_and_select_active():
  project=core.create_project('Comercial', 'Pruebas del módulo comercial')
  module=core.import_openapi(SPEC, project['id'])
  assert core.get('projects', project['id'])['name']=='Comercial'
  assert module['project_id']==project['id']
  assert core.get_active_project_id()==project['id']
  other=core.create_project('Operaciones')
  core.set_active_project(other['id'])
  assert core.get_active_project_id()==other['id']
  with pytest.raises(ValueError):core.set_active_project('missing-project')


def test_create_project_rejects_duplicate_name_case_and_space_insensitive():
    core.create_project('Comercial')
    with pytest.raises(ValueError, match='Ya existe'):
        core.create_project('  comercial  ')


def test_update_project_rejects_duplicate_name_but_allows_keeping_its_own():
    a = core.create_project('A')
    b = core.create_project('B')
    with pytest.raises(ValueError, match='Ya existe'):
        core.update_project(b['id'], 'a')
    renamed = core.update_project(a['id'], 'a')  # same project, same name (different case): no conflict with itself
    assert renamed['name'] == 'a'


def test_delete_project_cascade_wipes_everything_and_evidence_files():
    from app import automation
    project = core.create_project('A borrar')
    module = core.import_openapi(SPEC, project['id'])
    env = core.save('environments', {'name': 'E', 'project_id': project['id'], 'base_url': 'https://x', 'auth': {'type': 'none'}, 'variables': {}})
    case = core.save('cases', {'name': 'C', 'type': 'api', 'project_id': project['id'], 'method': 'GET', 'path': '/x', 'assertions': []})
    suite = core.save_suite('S', env['id'], [case['id']], project['id'])
    schedule = automation.create_schedule(suite['id'], 'daily', '02:00', 'UTC')
    shot = core.ARTIFACTS / 'ev.png'
    shot.write_text('x')
    run = core.save('runs', {'type': 'api', 'project_id': project['id'], 'status': 'passed', 'screenshot': 'ev.png'})

    core.delete_project_cascade(project['id'])

    assert core.get('projects', project['id']) is None
    assert core.get('modules', module['id']) is None
    assert core.get('environments', env['id']) is None
    assert core.get('cases', case['id']) is None
    assert core.get('suites', suite['id']) is None
    assert core.get('schedules', schedule['id']) is None
    assert core.get('runs', run['id']) is None
    assert not shot.exists()


def test_delete_project_cascade_clears_active_project_if_it_was_selected():
    project = core.create_project('Activo')
    assert core.get_active_project_id() == project['id']
    core.delete_project_cascade(project['id'])
    assert core.get_active_project_id() is None


def test_disable_project_blocks_activation_and_clears_it_if_active():
    project = core.create_project('A')
    assert core.get_active_project_id() == project['id']
    core.set_project_enabled(project['id'], False)
    assert core.get_active_project_id() is None
    with pytest.raises(ValueError, match='deshabilitado'):
        core.set_active_project(project['id'])
    core.set_project_enabled(project['id'], True)
    core.set_active_project(project['id'])
    assert core.get_active_project_id() == project['id']


def test_delete_project_lists_every_blocking_resource_type():
    project = core.create_project('Con recursos')
    core.import_openapi(SPEC, project['id'])
    core.save('environments', {'name': 'E', 'project_id': project['id'], 'base_url': 'https://x', 'auth': {'type': 'none'}, 'variables': {}})
    with pytest.raises(ValueError, match=r'1 componente.*1 ambiente') as exc:
        core.delete_project(project['id'])
    assert 'Bórralos' in str(exc.value)


def test_adopt_unassigned_includes_taps():
    project = core.create_project('P')
    core.save('taps', {'name': 'huérfano', 'port': 9101})  # no project_id: legacy/orphan record
    adopted = core.adopt_unassigned(project['id'])
    assert adopted['taps'] == 1
    assert core.list_items('taps')[0]['project_id'] == project['id']


def test_validate_base_url():
    assert core.validate_base_url('https://api.example.com/v1') == 'https://api.example.com/v1'
    assert core.validate_base_url('', required=False) == ''
    with pytest.raises(ValueError):
        core.validate_base_url('')
    with pytest.raises(ValueError):
        core.validate_base_url('ftp://api.example.com')
    with pytest.raises(ValueError):
        core.validate_base_url('https://user:pass@api.example.com')
    with pytest.raises(ValueError):
        core.validate_base_url('not a url')


def test_project_update_stats_and_safe_delete():
  project=core.create_project('Temporal')
  assert core.project_stats(project['id'])['modules']==0
  updated=core.update_project(project['id'], 'Temporal actualizado', 'Descripción')
  assert updated['name']=='Temporal actualizado'
  core.import_openapi(SPEC, project['id'])
  assert core.project_stats(project['id'])['modules']==1
  with pytest.raises(ValueError, match='1 componente'):
    core.delete_project(project['id'])
  empty=core.create_project('Vacío')
  core.delete_project(empty['id'])
  assert core.get('projects', empty['id']) is None


def test_safe_delete_also_purges_orphaned_history_and_its_evidence():
    # a project can have run/interface history (from resources deleted earlier by hand) without any of
    # that counting as "blocking" content in project_stats — delete_project must not leave it dangling
    project = core.create_project('Con historial suelto')
    shot = core.ARTIFACTS / 'suelto.png'
    shot.write_text('x')
    run = core.save('runs', {'type': 'api', 'project_id': project['id'], 'status': 'passed', 'screenshot': 'suelto.png'})
    interface = core.save('interfaces', {'module': 'M', 'method': 'GET', 'project_id': project['id']})
    assert core.project_stats(project['id']) == {'module_groups': 0, 'modules': 0, 'environments': 0, 'cases': 0, 'features': 0, 'suites': 0, 'schedules': 0, 'taps': 0,
                                                  'datasets': 0, 'suite_groups': 0, 'integrations': 0}

    core.delete_project(project['id'])

    assert core.get('projects', project['id']) is None
    assert core.get('runs', run['id']) is None
    assert core.get('interfaces', interface['id']) is None
    assert not shot.exists()

def test_roundtrip(tmp_path):
    m=core.import_openapi(SPEC)
    c=core.save('cases',{'name':'demo','module_id':m['id'],'assertions':[]})
    core.save('suites',{'name':'smoke','case_ids':[c['id']]})
    p=core.export_workspace(tmp_path/'out.zip')
    assert core.import_workspace(p,'merge')['modules']==0
    counts=core.import_workspace(p,'new')
    assert counts['modules']==1 and counts['cases']==1
    assert len(core.list_items('modules'))==2
    assert all(s['case_ids'][0] in [x['id'] for x in core.list_items('cases')] for s in core.list_items('suites'))

def test_http_run():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
          self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('X-Test','ok');self.end_headers();self.wfile.write(b'{"ok":true,"count":3}')
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        env=core.save('environments',{'base_url':f'http://127.0.0.1:{server.server_port}','auth':{'type':'none'}})
        case=core.save('cases',{'name':'test','method':'GET','path':'/hello','assertions':[{'type':'status','expected':200},{'type':'json_equals','path':'ok','expected':True},{'type':'header_equals','name':'X-Test','expected':'ok'},{'type':'numeric_greater','path':'count','expected':2},{'type':'response_time_max','expected':1000}]})
        result=core.execute_api(case,env)
        assert result['status']=='passed'
        assert len(core.list_items('runs'))==1
    finally:server.shutdown();server.server_close()


def test_token_needs_refresh():
    env_no_refresh = {'auth': {'type': 'bearer', 'secret': 'tok'}}
    assert core.token_needs_refresh(env_no_refresh) is False  # no refresh configured: never auto-refreshed

    core.secret_delete('tok-missing')
    env_missing = {'auth': {'type': 'bearer', 'secret': 'tok-missing', 'refresh': {'mode': 'command', 'command': 'echo x'}}}
    assert core.token_needs_refresh(env_missing) is True  # no token saved yet

    core.secret_set('tok-present', 'abc')
    env_no_expiry = {'auth': {'type': 'bearer', 'secret': 'tok-present', 'refresh': {'mode': 'command', 'command': 'echo x'}}}
    assert core.token_needs_refresh(env_no_expiry) is False  # present, no known expiry: trusted as-is

    import datetime as dt
    past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=5)).isoformat()
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)).isoformat()
    env_expired = {'auth': {'type': 'bearer', 'secret': 'tok-present', 'refresh': {'mode': 'command', 'command': 'echo x'}, 'token_expires_at': past}}
    env_fresh = {'auth': {'type': 'bearer', 'secret': 'tok-present', 'refresh': {'mode': 'command', 'command': 'echo x'}, 'token_expires_at': future}}
    assert core.token_needs_refresh(env_expired) is True
    assert core.token_needs_refresh(env_fresh) is False


def test_token_needs_refresh_respects_the_enabled_flag():
    """A refresh mechanism can be configured (so 'Obtener token ahora' works) without being applied
    automatically — the 'enabled' flag on the refresh config is what distinguishes the two; missing it
    (old saved environments, before this flag existed) still defaults to automatic, same as before."""
    core.secret_delete('tok-disabled')
    env_disabled = {'auth': {'type': 'bearer', 'secret': 'tok-disabled',
                    'refresh': {'mode': 'command', 'command': 'echo x', 'enabled': False}}}
    assert core.token_needs_refresh(env_disabled) is False  # configured, but not automatic: never proactively refreshed

    env_default = {'auth': {'type': 'bearer', 'secret': 'tok-disabled', 'refresh': {'mode': 'command', 'command': 'echo x'}}}
    assert core.token_needs_refresh(env_default) is True  # no 'enabled' key: backward-compatible default is automatic


def test_refresh_token_command_mode_writes_the_secret():
    env = core.save('environments', {'name': 'E', 'auth': {'type': 'bearer', 'secret': 'cmd-tok',
                    'refresh': {'mode': 'command', 'command': 'echo refreshed-value'}}})
    token = core.refresh_token(env)
    assert token == 'refreshed-value'
    assert core.secret_get('cmd-tok') == 'refreshed-value'
    assert core.get('environments', env['id'])['auth']['token_refreshed_at']


def test_refresh_token_works_even_when_automatic_refresh_is_disabled():
    """'Obtener token ahora' (manual) must work regardless of the 'enabled' flag — that flag only gates
    whether execute_api refreshes proactively/reactively on its own, never the manual action."""
    env = core.save('environments', {'name': 'E', 'auth': {'type': 'bearer', 'secret': 'cmd-tok-2',
                    'refresh': {'mode': 'command', 'command': 'echo manual-value', 'enabled': False}}})
    token = core.refresh_token(env)
    assert token == 'manual-value'
    assert core.secret_get('cmd-tok-2') == 'manual-value'


def test_refresh_token_command_mode_reports_a_failing_command():
    env = core.save('environments', {'name': 'E', 'auth': {'type': 'bearer', 'secret': 'cmd-tok-2',
                    'refresh': {'mode': 'command', 'command': 'exit 1'}}})
    with pytest.raises(ValueError, match='error'):
        core.refresh_token(env)


def test_refresh_token_requires_configuration():
    env = core.save('environments', {'name': 'E', 'auth': {'type': 'bearer', 'secret': 'x'}})
    with pytest.raises(ValueError, match='actualización automática'):
        core.refresh_token(env)


def test_execute_api_proactively_refreshes_a_missing_token_via_http():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get('Content-Length', 0)); self.rfile.read(length)
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
            self.wfile.write(b'{"access_token": "fresh-token", "expires_in": 3600}')

        def do_GET(self):
            ok = self.headers.get('Authorization') == 'Bearer fresh-token'
            self.send_response(200 if ok else 401); self.end_headers()

        def log_message(self, *a):
            pass
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        base = f'http://127.0.0.1:{server.server_port}'
        core.secret_delete('proactive-tok')
        env = core.save('environments', {'base_url': base, 'auth': {'type': 'bearer', 'secret': 'proactive-tok',
                        'refresh': {'mode': 'http', 'url': base + '/token', 'token_path': '$.access_token', 'expires_path': '$.expires_in'}}})
        case = core.save('cases', {'name': 'secure', 'method': 'GET', 'path': '/secure', 'assertions': [{'type': 'status', 'expected': 200}]})
        result = core.execute_api(case, env)
        assert result['status'] == 'passed'
        assert core.secret_get('proactive-tok') == 'fresh-token'
        assert core.get('environments', env['id'])['auth']['token_expires_at']
    finally:
        server.shutdown(); server.server_close()


def test_execute_api_reactively_refreshes_on_401():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get('Content-Length', 0)); self.rfile.read(length)
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
            self.wfile.write(b'{"access_token": "good-token"}')

        def do_GET(self):
            ok = self.headers.get('Authorization') == 'Bearer good-token'
            self.send_response(200 if ok else 401); self.end_headers()

        def log_message(self, *a):
            pass
    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        base = f'http://127.0.0.1:{server.server_port}'
        core.secret_set('reactive-tok', 'stale-token')  # already present, no known expiry: no *proactive* refresh
        env = core.save('environments', {'base_url': base, 'auth': {'type': 'bearer', 'secret': 'reactive-tok',
                        'refresh': {'mode': 'http', 'url': base + '/token', 'token_path': '$.access_token'}}})
        case = core.save('cases', {'name': 'secure', 'method': 'GET', 'path': '/secure', 'assertions': [{'type': 'status', 'expected': 200}]})
        result = core.execute_api(case, env)
        assert result['status'] == 'passed'   # the initial 401 with the stale token got a reactive retry
        assert result['http_status'] == 200
        assert core.secret_get('reactive-tok') == 'good-token'
    finally:
        server.shutdown(); server.server_close()


def test_project_filtering_and_adoption():
    a=core.create_project('A'); b=core.create_project('B')
    core.import_openapi(SPEC,a['id']); core.import_openapi(SPEC,b['id'])
    legacy=core.import_openapi(SPEC)
    assert len(core.list_project_items('modules',a['id']))==1
    assert len(core.list_project_items('modules',None))==3
    assert core.adopt_unassigned(a['id'])['modules']==1
    assert core.get('modules',legacy['id'])['project_id']==a['id']
    assert len(core.list_project_items('modules',b['id']))==1


def test_suite_requires_same_project_and_schedule_inherits_it():
    from app import automation
    a=core.create_project('A'); b=core.create_project('B')
    env_a=core.save('environments',{'name':'qa','project_id':a['id'],'base_url':'http://127.0.0.1'})
    case_a=core.save('cases',{'name':'c','project_id':a['id']})
    case_b=core.save('cases',{'name':'c','project_id':b['id']})
    with pytest.raises(ValueError,match='no pertenece'):
        core.save_suite('s',env_a['id'],[case_b['id']],a['id'])
    with pytest.raises(ValueError,match='no pertenece'):
        core.save_suite('s',env_a['id'],[case_a['id']],b['id'])
    suite=core.save_suite('s',env_a['id'],[case_a['id']],a['id'])
    assert suite['project_id']==a['id']
    schedule=automation.create_schedule(suite['id'],'daily','02:00','UTC')
    assert schedule['project_id']==a['id']
    assert core.project_stats(a['id'])['schedules']==1


def test_export_import_keeps_projects(tmp_path):
    a=core.create_project('A')
    core.import_openapi(SPEC,a['id'])
    path=core.export_workspace(tmp_path/'p.zip')
    counts=core.import_workspace(path,'new')
    assert counts['projects']==1 and counts['modules']==1
    new_ids={p['id'] for p in core.list_items('projects')}-{a['id']}
    assert len(new_ids)==1
    copied=[m for m in core.list_items('modules') if m['project_id'] in new_ids]
    assert len(copied)==1


def test_reset_workspace_wipes_everything():
    a=core.create_project('A')
    core.import_openapi(SPEC,a['id'])
    shot=core.ARTIFACTS/'evidence.txt'
    shot.write_text('x')
    core.reset_workspace()
    assert core.list_items('projects')==[]
    assert core.list_items('modules')==[]
    assert core.get_active_project_id() is None
    assert not shot.exists()
    assert core.DB.exists()  # the schema is recreated, usable right away


def test_reset_workspace_can_keep_evidence():
    core.create_project('A')
    shot=core.ARTIFACTS/'evidence.txt'
    shot.write_text('x')
    core.reset_workspace(remove_evidence=False)
    assert core.list_items('projects')==[]
    assert shot.exists()


def test_parse_dataset_file_txt_csv_json():
    columns, rows = core.parse_dataset_file('nombres.txt', b'Ana\nBeto\n\nCaro\n')
    assert columns == ['valor']
    assert rows == [{'valor': 'Ana'}, {'valor': 'Beto'}, {'valor': 'Caro'}]

    columns, rows = core.parse_dataset_file('leads.csv', b'nombre,rfc\nAna,AAA\nBeto,BBB\n')
    assert columns == ['nombre', 'rfc']
    assert rows == [{'nombre': 'Ana', 'rfc': 'AAA'}, {'nombre': 'Beto', 'rfc': 'BBB'}]

    columns, rows = core.parse_dataset_file('leads.json', json.dumps([{'nombre': 'Ana', 'rfc': 'AAA'}, {'nombre': 'Beto', 'rfc': 'BBB'}]).encode())
    assert columns == ['nombre', 'rfc']
    assert rows == [{'nombre': 'Ana', 'rfc': 'AAA'}, {'nombre': 'Beto', 'rfc': 'BBB'}]

    columns, rows = core.parse_dataset_file('valores.json', json.dumps(['x', 'y', 'z']).encode())
    assert columns == ['valor']
    assert rows == [{'valor': 'x'}, {'valor': 'y'}, {'valor': 'z'}]

    with pytest.raises(ValueError):
        core.parse_dataset_file('vacio.txt', b'   \n\n')
    with pytest.raises(ValueError):
        core.parse_dataset_file('malo.json', b'{not json')


def test_save_dataset_and_sample():
    project = core.create_project('Datos')
    core.save_dataset('leads', project['id'], ['nombre', 'rfc'], [{'nombre': 'Ana', 'rfc': 'AAA'}, {'nombre': 'Beto', 'rfc': 'BBB'}])
    for _ in range(10):
        row = core.dataset_sample('leads', project['id'])
        assert row in [{'nombre': 'Ana', 'rfc': 'AAA'}, {'nombre': 'Beto', 'rfc': 'BBB'}]
    assert core.dataset_sample('no existe', project['id']) is None
    with pytest.raises(ValueError):   # el mismo nombre no se puede repetir en el mismo proyecto
        core.save_dataset('leads', project['id'], ['x'], [{'x': '1'}])
    other = core.create_project('Otro')
    assert core.dataset_sample('leads', other['id']) is None   # un conjunto es propio de su proyecto, como un ambiente o un caso


def test_save_dataset_can_update_an_existing_one_by_id():
    """La pantalla de edición reusa save_dataset con id=... para guardar cambios (columnas/filas agregadas, quitadas
    o editadas a mano) sin crear un duplicado."""
    project = core.create_project('Datos')
    created = core.save_dataset('leads', project['id'], ['nombre'], [{'nombre': 'Ana'}])
    updated = core.save_dataset('leads', project['id'], ['nombre', 'rfc'], [{'nombre': 'Ana', 'rfc': 'AAA'}, {'nombre': 'Beto', 'rfc': 'BBB'}], id=created['id'])
    assert updated['id'] == created['id']
    items = core.list_project_items('datasets', project['id'])
    assert len(items) == 1   # no duplicó: actualizó el mismo registro
    assert items[0]['columns'] == ['nombre', 'rfc']
    assert len(items[0]['rows']) == 2


# --------------------------------------------------------------------------- sesión de Casos UI (SSO/MFA)

def test_validate_hostname_accepts_a_bare_host_and_rejects_urls_or_paths():
    assert core.validate_hostname('auth.miempresa.com') == 'auth.miempresa.com'
    assert core.validate_hostname('  MiEmpresa.PingOne.com  ') == 'miempresa.pingone.com'   # recortado y en minúsculas
    for bad in ('https://auth.miempresa.com', 'auth.miempresa.com/login', 'con espacio.com', ''):
        with pytest.raises(ValueError):
            core.validate_hostname(bad)


def test_save_get_clear_ui_session_roundtrip():
    project = core.create_project('SSO')
    env = core.save('environments', {'name': 'qa', 'project_id': project['id'], 'base_url': 'https://qa.example.com', 'variables': {}, 'auth': {'type': 'none'}})
    assert core.get_ui_session(env['id']) is None
    state = {'cookies': [{'name': 'session', 'value': 'abc'}], 'origins': []}
    core.save_ui_session(env['id'], state)
    assert core.get_ui_session(env['id']) == state
    assert core.get('environments', env['id'])['ui_session_saved_at']   # queda registrado cuándo se guardó
    core.clear_ui_session(env['id'])
    assert core.get_ui_session(env['id']) is None
    assert 'ui_session_saved_at' not in core.get('environments', env['id'])


def test_save_ui_session_requires_an_existing_environment():
    with pytest.raises(ValueError):
        core.save_ui_session('no-existe', {'cookies': [], 'origins': []})


def test_saving_the_environment_again_keeps_the_saved_session_reference():
    """Editar y guardar el ambiente desde la pantalla no debe perder la referencia a una sesión ya capturada."""
    project = core.create_project('SSO2')
    env = core.save('environments', {'name': 'qa', 'project_id': project['id'], 'base_url': 'https://qa.example.com', 'variables': {}, 'auth': {'type': 'none'}})
    core.save_ui_session(env['id'], {'cookies': [], 'origins': []})
    saved_at = core.get('environments', env['id'])['ui_session_saved_at']
    reloaded = core.get('environments', env['id'])
    core.save('environments', {**reloaded, 'name': 'qa renombrado'})   # igual que hace environments.py al guardar, preservando el campo
    assert core.get('environments', env['id'])['ui_session_saved_at'] == saved_at


def test_exporting_an_environment_never_carries_the_session_timestamp():
    """La sesión vive en el llavero de esta máquina, bajo el id actual — importarla con otro id no la trae."""
    project = core.create_project('SSO3')
    env = core.save('environments', {'name': 'qa', 'project_id': project['id'], 'base_url': 'https://qa.example.com', 'variables': {}, 'auth': {'type': 'none'}})
    core.save_ui_session(env['id'], {'cookies': [], 'origins': []})
    sanitized = core._sanitize_for_export('environments', core.get('environments', env['id']))
    assert 'ui_session_saved_at' not in sanitized
