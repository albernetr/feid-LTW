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


def _text_server(body, content_type, status=200):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.end_headers()
            self.wfile.write(body.encode('utf-8'))
        def log_message(self, *args):
            pass
    server = HTTPServer(('127.0.0.1', 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_fetch_url_text_strips_html_tags_and_scripts():
    server = _text_server('<html><head><script>var x=1;</script></head><body><h1>Pagar con tarjeta</h1>'
                          '<p>Como cliente quiero pagar &amp; completar la compra.</p></body></html>', 'text/html; charset=utf-8')
    try:
        text = core.fetch_url_text(f'http://127.0.0.1:{server.server_port}/')
        assert 'Pagar con tarjeta' in text and 'Como cliente quiero pagar & completar la compra.' in text
        assert '<h1>' not in text and 'var x=1' not in text
    finally:
        server.shutdown(); server.server_close()


def test_fetch_url_text_returns_plain_text_as_is():
    server = _text_server('# Historia\n\nComo cliente quiero pagar.', 'text/markdown; charset=utf-8')
    try:
        text = core.fetch_url_text(f'http://127.0.0.1:{server.server_port}/doc.md')
        assert text == '# Historia\n\nComo cliente quiero pagar.'
    finally:
        server.shutdown(); server.server_close()


def test_fetch_url_text_rejects_an_invalid_url_or_an_error_response():
    with pytest.raises(ValueError, match='URL inválida'):
        core.fetch_url_text('not-a-url')
    server = _text_server('not found', 'text/plain', status=404)
    try:
        with pytest.raises(ValueError, match='HTTP 404'):
            core.fetch_url_text(f'http://127.0.0.1:{server.server_port}/missing')
    finally:
        server.shutdown(); server.server_close()


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


def test_save_suite_keeps_the_chat_mapping_it_was_created_with_until_explicitly_changed():
    """El mapeo de chat de un Flujo (si salió de una conversación) viaja con la propia suite, no solo con el
    chat que estaba abierto al guardarlo — así «Retomar un Flujo guardado» no depende de qué chat esté abierto
    en pantalla. Editar la suite desde cualquier otro lugar (p. ej. el editor de Flujos, que no sabe nada de
    `chat`) no debe borrarlo en el camino."""
    project = core.create_project('Flujo con mapeo')
    env = core.save('environments', {'name': 'E', 'project_id': project['id'], 'base_url': 'https://x', 'auth': {'type': 'none'}, 'variables': {}})
    case = core.save('cases', {'name': 'C', 'type': 'api', 'project_id': project['id'], 'method': 'GET', 'path': '/x', 'assertions': []})
    mapping = {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
               'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta'}

    suite = core.save_suite('S', env['id'], [case['id']], project['id'], chat=mapping)
    assert suite['chat'] == mapping

    unaware_update = core.save_suite('S renombrada', env['id'], [case['id']], project['id'], id=suite['id'])
    assert unaware_update['chat'] == mapping                              # un caller que no sabe de "chat" no lo pisa

    other_mapping = {**mapping, 'reply_path': '$.answer'}
    explicit_update = core.save_suite('S', env['id'], [case['id']], project['id'], id=suite['id'], chat=other_mapping)
    assert explicit_update['chat'] == other_mapping                       # pero sí se puede reemplazar a propósito

    plain_suite = core.save_suite('Suite común', env['id'], [case['id']], project['id'])
    assert 'chat' not in plain_suite                                      # una suite que nunca vino de un chat no lo gana de la nada


def test_delete_project_cascade_clears_active_project_if_it_was_selected():
    project = core.create_project('Activo')
    assert core.get_active_project_id() == project['id']
    core.delete_project_cascade(project['id'])
    assert core.get_active_project_id() is None


def test_save_exploration_tree_merges_a_path_and_marks_the_leaf_with_its_suite():
    """Guardar el mismo camino dos veces (p. ej. dos corridas que arrancan igual) no lo duplica — el segundo
    guardado reusa los nodos ya presentes y solo agrega lo nuevo al final."""
    project = core.create_project('Árbol')
    path = [
        {'message': 'Hola', 'option': None, 'bot_reply': '¿Preferís mensual o anual?', 'options_offered': ['Mensual', 'Anual']},
        {'message': 'Anual', 'option': 'Anual', 'bot_reply': 'Perfecto, ¿nombre completo?', 'options_offered': []},
    ]
    tree = core.save_exploration_tree('caso-1', project['id'], path, suite_id='suite-1')
    assert tree['case_id'] == 'caso-1'
    assert len(tree['root']['children']) == 1
    first = tree['root']['children'][0]
    assert first['message'] == 'Hola' and first['options_offered'] == ['Mensual', 'Anual']
    second = first['children'][0]
    assert second['message'] == 'Anual' and second['option'] == 'Anual' and second['suite_id'] == 'suite-1'

    # un segundo camino que arranca igual («Hola») pero toma la otra opción agrega una rama nueva, sin duplicar «Hola»
    other_path = [
        {'message': 'Hola', 'option': None, 'bot_reply': '¿Preferís mensual o anual?', 'options_offered': ['Mensual', 'Anual']},
        {'message': 'Mensual', 'option': 'Mensual', 'bot_reply': 'Dale, ¿nombre completo?', 'options_offered': []},
    ]
    tree = core.save_exploration_tree('caso-1', project['id'], other_path, suite_id='suite-2')
    assert len(tree['root']['children']) == 1                      # «Hola» se reusó, no se duplicó
    assert len(tree['root']['children'][0]['children']) == 2       # ahora cuelgan las dos ramas: Anual y Mensual
    assert core.exploration_tree_for_case('caso-1', project['id'])['id'] == tree['id']


def test_pending_branches_lists_offered_options_without_a_child_yet():
    project = core.create_project('Árbol pendientes')
    path = [{'message': 'Hola', 'option': None, 'bot_reply': '¿Mensual o anual?', 'options_offered': ['Mensual', 'Anual']},
            {'message': 'Anual', 'option': 'Anual', 'bot_reply': 'ok', 'options_offered': []}]
    tree = core.save_exploration_tree('caso-2', project['id'], path, suite_id='suite-1')
    pending = core.pending_branches(tree['root'])
    assert len(pending) == 1
    branch_path, option = pending[0]
    assert option == 'Mensual' and [n['message'] for n in branch_path] == ['Hola']   # hasta el padre, sin incluir la rama pendiente

    # al cubrir esa rama, ya no queda nada pendiente en ese punto
    path2 = [{'message': 'Hola', 'option': None, 'bot_reply': '¿Mensual o anual?', 'options_offered': ['Mensual', 'Anual']},
             {'message': 'Mensual', 'option': 'Mensual', 'bot_reply': 'ok', 'options_offered': []}]
    tree = core.save_exploration_tree('caso-2', project['id'], path2, suite_id='suite-2')
    assert core.pending_branches(tree['root']) == []


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
                                                  'datasets': 0, 'suite_groups': 0, 'integrations': 0, 'user_stories': 0, 'test_case_specs': 0}

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


def test_set_evidence_folder_validates_before_saving(tmp_path):
    with pytest.raises(ValueError):
        core.set_evidence_folder('')
    missing = tmp_path / 'no-existe'
    with pytest.raises(ValueError):
        core.set_evidence_folder(str(missing))
    folder = tmp_path / 'destino'
    folder.mkdir()
    saved = core.set_evidence_folder(str(folder))
    assert saved == str(folder)
    assert core.evidence_folder() == str(folder)


def test_save_evidence_file_requires_a_configured_folder_and_avoids_overwriting(tmp_path):
    with pytest.raises(ValueError):
        core.save_evidence_file('reporte.html', '<html></html>')
    folder = tmp_path / 'destino'
    folder.mkdir()
    core.set_evidence_folder(str(folder))
    first = core.save_evidence_file('reporte.html', '<html>uno</html>')
    assert first == folder / 'reporte.html'
    assert first.read_text(encoding='utf-8') == '<html>uno</html>'
    second = core.save_evidence_file('reporte.html', '<html>dos</html>')
    assert second == folder / 'reporte-1.html'
    assert second.read_text(encoding='utf-8') == '<html>dos</html>'
    assert first.read_text(encoding='utf-8') == '<html>uno</html>'    # el primero no se pisó


def test_save_evidence_file_sanitizes_slashes_in_the_name_instead_of_treating_them_as_folders(tmp_path):
    """Un nombre de caso típico («GET /api/users/2») trae / — sin sanear, pathlib los lee como separadores de
    carpeta y falla con FileNotFoundError (la carpeta intermedia no existe) en vez de guardar el archivo."""
    folder = tmp_path / 'destino'
    folder.mkdir()
    core.set_evidence_folder(str(folder))
    target = core.save_evidence_file('GET /api/users/2-20261108.html', '<html>ok</html>')
    assert target.parent == folder                 # nunca una subcarpeta
    assert target.read_text(encoding='utf-8') == '<html>ok</html>'


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


# --------------------------------------------------------------------------- especificación: HU, casos de prueba, plantillas

def test_initialize_seeds_seven_default_global_templates_idempotently():
    templates = [t for t in core.list_items('spec_templates') if t.get('project_id') is None]
    assert len(templates) == 7
    assert {t['kind'] for t in templates} == {'input', 'output'}
    assert all(t['is_builtin'] for t in templates)
    core.initialize()   # llamar de nuevo no duplica nada
    assert len([t for t in core.list_items('spec_templates') if t.get('project_id') is None]) == 7


def _without_ids(nodes):
    """Quita 'id' de cada nodo, recursivamente (incluidos los 'children' de un grupo) — para comparar dos
    árboles de plantilla por estructura/contenido sin que un id regenerado al azar los haga parecer distintos."""
    cleaned = []
    for n in nodes:
        n = {k: v for k, v in n.items() if k != 'id'}
        if n.get('children'):
            n['children'] = _without_ids(n['children'])
        cleaned.append(n)
    return cleaned


def test_seed_resyncs_a_pre_existing_builtin_templates_body_with_the_current_default():
    """Un builtin global nunca es editable por nadie (el editor lo deja `disabled`) — la única forma en que su
    `body` guardado puede divergir de DEFAULT_SPEC_TEMPLATES es haber quedado sembrado por una versión anterior
    del código: antes del árbol de nodos (bug real reportado en vivo — KeyError al abrir una plantilla así en
    el editor), o, como en este caso, antes de que esta plantilla agrupara sus campos fijos en secciones. Por
    eso `seed_default_spec_templates` RE-SINCRONIZA sin condición, no solo corrige el formato."""
    builtin = next(t for t in core.list_items('spec_templates') if t.get('project_id') is None and t.get('is_builtin')
                  and t['name'] == 'Criterios de aceptación (Gherkin)')
    builtin['body'] = [{'field': 'given', 'label': 'Dado (contexto inicial)'}]   # simula una fila vieja, incompleta
    core.save('spec_templates', builtin)   # nunca se vuelve a guardar sola (seed solo CREA las que faltan, por nombre)
    assert 'kind' not in builtin['body'][0]

    # core.initialize() solo llama a seed_default_spec_templates() UNA vez por proceso/DB (memoizado en
    # _SEEDED_TEMPLATES_FOR, ver core.py) — el caso real (una base vieja que arranca en un proceso NUEVO del
    # servidor) ya pasa por ese primer llamado; acá se invoca el seeder directo para no depender de esa cache.
    core.seed_default_spec_templates()   # debe restaurar el body canónico completo, sin duplicar ni tocar otra plantilla
    upgraded = core.get('spec_templates', builtin['id'])
    # Ahora el body canónico es 2 grupos (general con los metadatos + criteria con given/when/then) — ya no una
    # lista plana de 3 campos, desde que los metadatos pasaron a ser parte de la plantilla (ver AGENTS.md/sesión).
    assert len(upgraded['body']) == 2 and all(n.get('kind') == 'group' for n in upgraded['body'])
    assert upgraded['body'][0]['id'] == 'general' and upgraded['body'][0]['children'][0]['field_key'] == 'title'
    assert upgraded['body'][1]['id'] == 'criteria'
    assert [n['field_key'] for n in upgraded['body'][1]['children']] == ['given', 'when', 'then']
    assert len([t for t in core.list_items('spec_templates') if t.get('project_id') is None]) == 7   # nada duplicado

    core.seed_default_spec_templates()   # idempotente (salvo el 'id' de un nodo sin id propio en
    # default_spec_templates.json — field o group — que se regenera en cada limpieza — irrelevante, nada lo
    # direcciona por fuera; _without_ids lo quita recursivamente, no solo del nivel de grupo)
    resynced = core.get('spec_templates', builtin['id'])['body']
    assert _without_ids(resynced) == _without_ids(upgraded['body'])


def test_promote_and_adopt_normalize_a_legacy_flat_body_on_copy():
    """promote_template/adopt_template copian `template.get('body')` tal cual venía guardado — si la plantilla
    ORIGEN todavía está en el formato plano viejo (p. ej. una global sembrada antes de este esquema), la copia
    debe salir ya en el árbol nuevo, no arrastrar el problema a un registro más."""
    project = core.create_project('Copiar legado')
    local = core.create_spec_template('Legado', 'input', 'user_story', project_id=project['id'], body=[{'field': 'as_a', 'label': 'Como'}])
    stored = core.get('spec_templates', local['id'])
    stored['body'] = [{'field': 'as_a', 'label': 'Como'}]   # fuerza el registro de vuelta al formato plano viejo
    core.save('spec_templates', stored)

    promoted = core.promote_template(local['id'])
    assert promoted['body'][0].get('kind') == 'field' and promoted['body'][0]['field_key'] == 'as_a'

    project2 = core.create_project('Copiar legado 2')
    adopted = core.adopt_template(promoted['id'], project2['id'])
    assert adopted['body'][0].get('kind') == 'field' and adopted['body'][0]['field_key'] == 'as_a'


def test_new_project_automatically_adopts_the_seven_default_templates():
    project = core.create_project('Adopta plantillas')
    adopted = [t for t in core.list_items('spec_templates') if t.get('project_id') == project['id']]
    assert len(adopted) == 7
    assert all(not t['is_builtin'] for t in adopted)
    assert all(t.get('cloned_from') for t in adopted)


def test_create_user_story_requires_a_title_and_an_existing_feature():
    project = core.create_project('HU')
    with pytest.raises(ValueError):
        core.create_user_story('  ', project['id'])
    with pytest.raises(ValueError):
        core.create_user_story('Pagar', project['id'], feature_id='no-existe')
    feature = core.create_feature('Checkout', project['id'])
    story = core.create_user_story('Pagar con tarjeta', project['id'], as_a='cliente', i_want='pagar', so_that='completar la compra',
                                   feature_id=feature['id'], criteria=[{'text': 'veo confirmación'}, {'text': '  '}, 'texto suelto'])
    assert story['feature_id'] == feature['id']
    assert [c['text'] for c in story['criteria']] == ['veo confirmación', 'texto suelto']   # el criterio vacío se descarta
    assert all(c['status'] == 'pending' for c in story['criteria'])


def test_update_user_story_can_clear_the_feature_link_and_change_status():
    project = core.create_project('HU2')
    feature = core.create_feature('Checkout', project['id'])
    story = core.create_user_story('Pagar', project['id'], feature_id=feature['id'])
    updated = core.update_user_story(story['id'], 'Pagar (editado)', feature_id=None, status='ready')
    assert updated['feature_id'] is None
    assert updated['status'] == 'ready'
    with pytest.raises(ValueError):
        core.update_user_story('no-existe', 'x')


def test_delete_user_story_blocks_while_a_test_case_spec_is_linked():
    project = core.create_project('HU3')
    story = core.create_user_story('Pagar', project['id'])
    spec = core.create_test_case_spec('Pagar con tarjeta válida', project['id'], story_id=story['id'])
    with pytest.raises(ValueError):
        core.delete_user_story(story['id'])
    core.delete_test_case_spec(spec['id'])
    core.delete_user_story(story['id'])
    assert core.get('user_stories', story['id']) is None


def test_user_story_criteria_accept_gherkin_and_keep_old_flat_text_working():
    project = core.create_project('Gherkin')
    story = core.create_user_story('Pagar', project['id'], criteria=[
        {'text': 'Pago válido', 'given': 'una tarjeta válida', 'when': 'el cliente confirma el pago', 'then': 'se aprueba la compra'},
        {'text': 'solo texto, sin estructurar'},   # criterio "viejo", sin romperse
        {'given': '', 'when': '', 'then': ''},     # vacío del todo: se descarta
    ])
    assert len(story['criteria']) == 2
    scenario = story['criteria'][0]
    assert scenario['given'] == 'una tarjeta válida' and scenario['when'] == 'el cliente confirma el pago' and scenario['then'] == 'se aprueba la compra'
    assert story['criteria'][1]['text'] == 'solo texto, sin estructurar' and story['criteria'][1]['given'] == ''


def test_user_story_definition_of_ready_and_done_are_checklists():
    project = core.create_project('DoR DoD')
    story = core.create_user_story('Pagar', project['id'],
                                   definition_of_ready=[{'text': 'Mockups aprobados', 'done': True}, {'text': '  '}, 'Dependencias resueltas'],
                                   definition_of_done=[{'text': 'Pruebas automatizadas pasando'}])
    assert story['definition_of_ready'] == [{'text': 'Mockups aprobados', 'done': True}, {'text': 'Dependencias resueltas', 'done': False}]
    assert story['definition_of_done'] == [{'text': 'Pruebas automatizadas pasando', 'done': False}]


def test_user_story_depends_on_only_keeps_stories_in_the_same_project():
    project = core.create_project('Depende')
    other_project = core.create_project('Otro')
    a = core.create_user_story('A', project['id'])
    b = core.create_user_story('B', project['id'])
    foreign = core.create_user_story('Ajena', other_project['id'])
    c = core.create_user_story('C', project['id'], depends_on=[a['id'], b['id'], foreign['id'], 'no-existe'])
    assert set(c['depends_on']) == {a['id'], b['id']}
    # no puede depender de sí misma
    updated = core.update_user_story(c['id'], 'C', depends_on=[a['id'], c['id']])
    assert updated['depends_on'] == [a['id']]


def test_delete_user_story_blocks_while_another_story_depends_on_it():
    project = core.create_project('Dependencia bloquea borrado')
    a = core.create_user_story('A', project['id'])
    core.create_user_story('B', project['id'], depends_on=[a['id']])
    with pytest.raises(ValueError):
        core.delete_user_story(a['id'])


def test_user_story_story_points_must_be_a_non_negative_integer():
    project = core.create_project('Story points')
    story = core.create_user_story('Pagar', project['id'], story_points=5)
    assert story['story_points'] == 5
    assert core.create_user_story('Sin estimar', project['id'])['story_points'] is None
    with pytest.raises(ValueError):
        core.create_user_story('x', project['id'], story_points=-1)
    with pytest.raises(ValueError):
        core.create_user_story('x', project['id'], story_points='no-es-un-número')


def test_user_story_assigned_to_must_be_an_existing_user():
    project = core.create_project('Asignado')
    with pytest.raises(ValueError):
        core.create_user_story('Pagar', project['id'], assigned_to='no-existe')
    user = core.create_user('Ana', 'QA', 'ana@ltw.local', 'password', password='x' * 12)
    story = core.create_user_story('Pagar', project['id'], assigned_to=user['id'])
    assert story['assigned_to'] == user['id']
    cleared = core.update_user_story(story['id'], 'Pagar', assigned_to=None)
    assert cleared['assigned_to'] is None


def test_user_story_business_context_fields_round_trip():
    project = core.create_project('Contexto de negocio')
    story = core.create_user_story('Pagar', project['id'], business_rules='Solo tarjetas propias', assumptions='El banco responde en <2s',
                                   risks='Picos de tráfico en campañas', out_of_scope='No cubre pagos en cuotas')
    assert story['business_rules'] == 'Solo tarjetas propias' and story['assumptions'] == 'El banco responde en <2s'
    assert story['risks'] == 'Picos de tráfico en campañas' and story['out_of_scope'] == 'No cubre pagos en cuotas'


def test_user_story_custom_fields_round_trip_through_create_update_and_list_items():
    """custom_fields no pide ninguna migración de esquema — core.save()/list_items() son agnósticos (json.dumps
    del dict completo), así que un dict arbitrario (texto, lista, tabla, referencia de archivo) va y vuelve
    intacto por create/update/get/list_items, sin tocar core.py más allá de limpiar claves vacías."""
    project = core.create_project('Custom fields')
    custom = {'presupuesto': '5000 USD', 'riesgos_extra': [{'text': 'Proveedor único', 'done': False}],
             'matriz': {'headers': ['A', 'B'], 'rows': [['1', '2']]}, '': 'se descarta (clave vacía)'}
    story = core.create_user_story('Con campos custom', project['id'], custom_fields=custom)
    assert story['custom_fields'] == {'presupuesto': '5000 USD', 'riesgos_extra': [{'text': 'Proveedor único', 'done': False}],
                                      'matriz': {'headers': ['A', 'B'], 'rows': [['1', '2']]}}
    assert core.get('user_stories', story['id'])['custom_fields'] == story['custom_fields']
    assert next(s for s in core.list_items('user_stories') if s['id'] == story['id'])['custom_fields'] == story['custom_fields']

    updated = core.update_user_story(story['id'], 'Con campos custom', custom_fields={'presupuesto': '7000 USD'})
    assert updated['custom_fields'] == {'presupuesto': '7000 USD'}   # reemplaza entero, igual que criteria/dor/dod


def test_test_case_spec_custom_fields_round_trip():
    project = core.create_project('CP custom')
    spec = core.create_test_case_spec('x', project['id'], custom_fields={'severidad': 'alta'})
    assert spec['custom_fields'] == {'severidad': 'alta'}
    updated = core.update_test_case_spec(spec['id'], 'x', custom_fields={'severidad': 'baja'})
    assert updated['custom_fields'] == {'severidad': 'baja'}


def test_save_custom_field_file_writes_to_artifacts_and_is_servable_via_evidence_path():
    result = core.save_custom_field_file(b'contenido-binario', 'Mi Reporte Final.png', content_type='image/png')
    assert result['filename'] == 'Mi Reporte Final.png' and result['content_type'] == 'image/png' and result['size'] == len(b'contenido-binario')
    served = core.evidence_path(result['id'], f'{result["id"]}-Mi Reporte Final.png')
    assert served.is_file() and served.read_bytes() == b'contenido-binario'
    served.unlink()


def test_iter_template_fields_flattens_groups_and_template_field_keys_collects_custom_and_known():
    body = core.create_spec_template('Con grupos', 'input', 'user_story', project_id=core.create_project('Grupos')['id'], body=[
        {'kind': 'field', 'label': 'Como', 'field_key': 'as_a'},
        {'kind': 'group', 'label': 'Extra', 'children': [
            {'kind': 'field', 'label': 'Presupuesto', 'field_key': 'presupuesto', 'field_type': 'text'},
            {'kind': 'group', 'label': 'Sub', 'children': [{'kind': 'field', 'label': 'Riesgo extra', 'field_key': 'riesgo_extra', 'field_type': 'textarea'}]}]},
    ])['body']
    keys = core.template_field_keys(body)
    assert keys == {'as_a', 'presupuesto', 'riesgo_extra'}
    fields = list(core.iter_template_fields(body))
    assert [f['field_key'] for f in fields] == ['as_a', 'presupuesto', 'riesgo_extra']


def test_template_top_level_groups_wraps_stray_fields_and_keeps_explicit_groups():
    pid = core.create_project('Grupos de primer nivel')['id']
    # Totalmente plana (sin ningún 'group'): todo cae en UN solo grupo implícito — mismo comportamiento de
    # siempre (un solo panel) para cualquier plantilla custom creada antes de este mecanismo.
    flat = core.create_spec_template('Plana', 'input', 'user_story', project_id=pid, body=[
        {'kind': 'field', 'label': 'Como', 'field_key': 'as_a'}, {'kind': 'field', 'label': 'Quiero', 'field_key': 'i_want'}])
    groups = core.template_top_level_groups(flat['body'])
    assert len(groups) == 1 and len(groups[0]['children']) == 2 and groups[0]['icon'] is None

    # Con grupos explícitos (como la Historia de usuario (INVEST) sembrada): cada uno es su propia pestaña,
    # con su id/label/icon tal cual los declaró la plantilla.
    rich = core.create_spec_template('Con grupos', 'input', 'user_story', project_id=pid, body=[
        {'kind': 'group', 'id': 'g1', 'label': 'Narrativa', 'icon': 'edit_note', 'children': [{'kind': 'field', 'label': 'Como', 'field_key': 'as_a'}]},
        {'kind': 'field', 'label': 'Suelto', 'field_key': 'i_want'},   # un campo suelto DESPUÉS de un grupo explícito
        {'kind': 'group', 'id': 'g2', 'label': 'Negocio', 'icon': 'business_center', 'children': []},
    ])
    groups = core.template_top_level_groups(rich['body'])
    assert [g['id'] for g in groups[:1]] == ['g1'] and groups[0]['icon'] == 'edit_note'
    implicit = groups[1]
    assert implicit['id'] != 'g1' and implicit['id'] != 'g2' and implicit['children'][0]['field_key'] == 'i_want'
    assert groups[2]['id'] == 'g2' and groups[2]['icon'] == 'business_center' and groups[2]['children'] == []


def test_custom_field_catalog_lists_custom_fields_from_input_templates_without_deduplicating():
    pid = core.create_project('Catálogo de campos')['id']
    core.create_spec_template('HU con presupuesto', 'input', 'user_story', project_id=pid, body=[
        {'kind': 'field', 'label': 'Presupuesto', 'field_key': 'presupuesto', 'field_type': 'text'}])
    core.create_spec_template('Caso con presupuesto', 'input', 'test_case', project_id=pid, body=[
        {'kind': 'field', 'label': 'Presupuesto (número)', 'field_key': 'presupuesto', 'field_type': 'table'}])
    other_project = core.create_project('Otro proyecto')['id']
    core.create_spec_template('No debería aparecer', 'input', 'user_story', project_id=other_project, body=[
        {'kind': 'field', 'label': 'Ajeno', 'field_key': 'ajeno', 'field_type': 'text'}])

    catalog = core.custom_field_catalog(pid)
    keys = [(c['field_key'], c['field_type'], c['template_name']) for c in catalog]
    assert ('presupuesto', 'text', 'HU con presupuesto') in keys
    assert ('presupuesto', 'table', 'Caso con presupuesto') in keys   # mismo field_key, tipos distintos: las DOS, sin pisarse
    assert all(c['template_name'] != 'No debería aparecer' for c in catalog)

    only_test_case = core.custom_field_catalog(pid, applies_to='test_case')
    assert {c['template_name'] for c in only_test_case} == {'Caso con presupuesto'}


def test_pair_rows_groups_consecutive_half_width_siblings_into_rows():
    nodes = [{'id': 'a', 'width': 'full'}, {'id': 'b', 'width': 'half'}, {'id': 'c', 'width': 'half'},
             {'id': 'd', 'width': 'half'}]   # 'd' queda solo: su posible pareja ya se usó con 'c'
    rows = core.pair_rows(nodes)
    assert [[n['id'] for n in row] for row in rows] == [['a'], ['b', 'c'], ['d']]


def test_known_fields_include_registration_metadata_now_that_its_template_governed():
    """Título/Prioridad/Estado/... (HU) y Título/Historia/.../Caso ligado (Caso de prueba) dejaron de ser fijos
    fuera de toda plantilla — son campos conocidos más, que una plantilla ubica donde quiera (ver
    default_spec_templates.json, grupo 'general')."""
    assert {'title', 'feature_id', 'priority', 'status', 'story_points', 'assigned_to', 'depends_on'} <= set(core.KNOWN_STORY_FIELDS)
    assert {'title', 'story_id', 'feature_id', 'linked_case_id', 'priority', 'type'} <= set(core.KNOWN_TEST_CASE_FIELDS)


def test_default_spec_templates_json_has_seven_templates_with_a_general_metadata_group_first():
    assert len(core.DEFAULT_SPEC_TEMPLATES) == 7
    assert {t['kind'] for t in core.DEFAULT_SPEC_TEMPLATES} == {'input', 'output'}
    input_templates_with_metadata = ('Historia de usuario (INVEST)', 'Criterios de aceptación (Gherkin)',
                                     'Caso de prueba (ISTQB)', 'Formato libre')
    for name in input_templates_with_metadata:
        tpl = next(t for t in core.DEFAULT_SPEC_TEMPLATES if t['name'] == name)
        general = tpl['body'][0]
        assert general['kind'] == 'group' and general['id'] == 'general'
        assert general['children'][0]['field'] == 'title'


def test_input_template_id_round_trips_on_user_story_and_test_case_spec():
    pid = core.create_project('Plantilla elegida')['id']
    tpl = core.create_spec_template('Mi plantilla', 'input', 'user_story', project_id=pid, body=[])
    story = core.create_user_story('Con plantilla', pid, input_template_id=tpl['id'])
    assert core.get('user_stories', story['id'])['input_template_id'] == tpl['id']
    core.update_user_story(story['id'], 'Con plantilla', input_template_id=None)
    assert core.get('user_stories', story['id'])['input_template_id'] is None

    spec_tpl = core.create_spec_template('Mi plantilla de caso', 'input', 'test_case', project_id=pid, body=[])
    spec = core.create_test_case_spec('Con plantilla', pid, input_template_id=spec_tpl['id'])
    assert core.get('test_case_specs', spec['id'])['input_template_id'] == spec_tpl['id']
    core.update_test_case_spec(spec['id'], 'Con plantilla', input_template_id=None)
    assert core.get('test_case_specs', spec['id'])['input_template_id'] is None


def test_create_test_case_spec_requires_existing_links_and_cleans_empty_steps():
    project = core.create_project('CP')
    with pytest.raises(ValueError):
        core.create_test_case_spec('x', project['id'], story_id='no-existe')
    with pytest.raises(ValueError):
        core.create_test_case_spec('x', project['id'], linked_case_id='no-existe')
    spec = core.create_test_case_spec('Pagar', project['id'], steps=[{'action': 'ir a pago', 'expected': 'veo el formulario'}, {'action': '', 'expected': ''}])
    assert len(spec['steps']) == 1
    assert spec['status'] == 'draft'


def test_test_case_spec_linked_to_a_case_is_automated_by_default():
    project = core.create_project('CP2')
    env = core.save('environments', {'name': 'e', 'project_id': project['id'], 'base_url': 'http://x', 'auth': {'type': 'none'}, 'variables': {}})
    api_case = core.save('cases', {'name': 'Ping', 'method': 'GET', 'path': '/ping', 'project_id': project['id'], 'environment_id': env['id'],
                                   'headers': {}, 'query': {}, 'body': None, 'assertions': [], 'variables': {}, 'extract': [], 'timeout': 10})
    spec = core.create_test_case_spec('Ping responde', project['id'], linked_case_id=api_case['id'])
    assert spec['status'] == 'automated'
    unlinked = core.update_test_case_spec(spec['id'], 'Ping responde', linked_case_id=None)
    assert unlinked['linked_case_id'] is None
    assert unlinked['status'] == 'draft'


def test_spec_template_crud_validates_kind_and_applies_to():
    project = core.create_project('PT')
    with pytest.raises(ValueError):
        core.create_spec_template('x', 'bogus', 'user_story', project_id=project['id'])
    with pytest.raises(ValueError):
        core.create_spec_template('x', 'input', 'bogus', project_id=project['id'])
    # Esquema nuevo (árbol de nodos, Rediseño de Plantillas): un nodo plano viejo {field, label} se sube de
    # versión a un nodo 'field' que referencia ese field_key fijo (field_type=None) — con etiqueta vacía
    # completada desde la clave, igual que antes.
    template = core.create_spec_template('Mi HU', 'input', 'user_story', body=[{'field': 'x', 'label': ' '}, {'field': '', 'label': ''}], project_id=project['id'])
    assert len(template['body']) == 1
    node = template['body'][0]
    assert node['kind'] == 'field' and node['field_key'] == 'x' and node['label'] == 'x' and node['field_type'] is None

    # field_type=None SIEMPRE se acepta, sin exigir que field_key esté en la lista de fijos conocidos — mismo
    # trato que un nodo plano viejo (sin 'kind'); si no, re-normalizar un nodo ya limpio (promote_template/
    # adopt_template/re-seed, ver core.py) rompería en la segunda pasada lo que la primera había aceptado.
    sin_tipo = core.create_spec_template('Mi HU 2', 'input', 'user_story', body=[{'kind': 'field', 'label': 'Presupuesto', 'field_key': 'presupuesto'}], project_id=project['id'])
    assert sin_tipo['body'][0]['field_type'] is None and sin_tipo['body'][0]['field_key'] == 'presupuesto'
    with pytest.raises(ValueError):   # un field_type explícito pero inválido: inválido
        core.create_spec_template('Mi HU 2b', 'input', 'user_story',
                                  body=[{'kind': 'field', 'label': 'Presupuesto', 'field_key': 'presupuesto', 'field_type': 'bogus'}], project_id=project['id'])
    with pytest.raises(ValueError):   # colisión: un campo custom no puede usar el field_key de uno fijo
        core.create_spec_template('Mi HU 3', 'input', 'user_story',
                                  body=[{'kind': 'field', 'label': 'Como', 'field_key': 'as_a', 'field_type': 'text'}], project_id=project['id'])
    rich = core.create_spec_template('Mi HU 4', 'input', 'user_story', project_id=project['id'], body=[
        {'kind': 'field', 'label': 'Como (rol)', 'field_key': 'as_a'},
        {'kind': 'group', 'label': 'Contexto adicional', 'as_tab': True, 'children': [
            {'kind': 'field', 'label': 'Presupuesto', 'field_key': 'presupuesto', 'field_type': 'text'}]}])
    assert rich['body'][0] == {'id': rich['body'][0]['id'], 'kind': 'field', 'label': 'Como (rol)', 'field_key': 'as_a', 'field_type': None, 'width': 'full'}
    group = rich['body'][1]
    assert group['kind'] == 'group' and group['as_tab'] is True and group['children'][0]['field_type'] == 'text'


def test_global_templates_are_read_only_and_only_local_ones_can_be_deleted():
    project = core.create_project('PT2')
    builtin = next(t for t in core.list_items('spec_templates') if t.get('project_id') is None)
    with pytest.raises(ValueError):
        core.update_spec_template(builtin['id'], 'nuevo nombre')
    with pytest.raises(ValueError):
        core.delete_spec_template(builtin['id'])
    local = core.create_spec_template('Mía', 'input', 'test_case', project_id=project['id'])
    core.update_spec_template(local['id'], 'Mía renombrada', body=[{'field': 'a', 'label': 'A'}])
    core.delete_spec_template(local['id'])
    assert core.get('spec_templates', local['id']) is None


def test_promote_and_adopt_template_round_trip():
    project = core.create_project('Promo')
    local = core.create_spec_template('Mi plantilla', 'input', 'user_story', body=[{'field': 'x', 'label': 'X'}], project_id=project['id'])
    with pytest.raises(ValueError):
        core.adopt_template(local['id'], project['id'])   # no es global todavía
    promoted = core.promote_template(local['id'])
    assert promoted['project_id'] is None and promoted['promoted_from'] == local['id']
    with pytest.raises(ValueError):
        core.promote_template(promoted['id'])   # ya es global

    project2 = core.create_project('Promo2')
    adopted = core.adopt_template(promoted['id'], project2['id'])
    assert adopted['project_id'] == project2['id'] and adopted['cloned_from'] == promoted['id']
    assert core.update_spec_template(adopted['id'], 'Editada en el proyecto 2')['name'] == 'Editada en el proyecto 2'


def test_safe_delete_project_is_not_blocked_by_its_auto_adopted_templates_and_cleans_them_up():
    """Las 7 plantillas que cada proyecto adopta solas al crearse no deberían exigir borrarlas a mano — mismo
    espíritu que runs/interfaces en _purge_project_history (no bloquean, pero no quedan huérfanas)."""
    project = core.create_project('Borrado limpio')
    adopted_ids = [t['id'] for t in core.list_items('spec_templates') if t.get('project_id') == project['id']]
    assert len(adopted_ids) == 7
    core.delete_project(project['id'])   # no debe levantar ValueError por las plantillas
    assert all(core.get('spec_templates', tid) is None for tid in adopted_ids)
    assert len([t for t in core.list_items('spec_templates') if t.get('project_id') is None]) == 7   # las globales, intactas


def test_deleting_a_project_is_blocked_by_stories_and_specs_then_cascade_removes_them():
    project = core.create_project('CascadaHU')
    story = core.create_user_story('HU', project['id'])
    with pytest.raises(ValueError):
        core.delete_project(project['id'])
    core.delete_project_cascade(project['id'])
    assert core.get('user_stories', story['id']) is None
    assert core.get('projects', project['id']) is None


def test_story_coverage_crosses_specs_with_their_linked_case_last_run():
    project = core.create_project('Matriz')
    story = core.create_user_story('Pagar', project['id'])
    env = core.save('environments', {'name': 'e', 'project_id': project['id'], 'base_url': 'http://x', 'auth': {'type': 'none'}, 'variables': {}})
    api_case = core.save('cases', {'name': 'Pagar', 'method': 'GET', 'path': '/pay', 'project_id': project['id'], 'environment_id': env['id'],
                                   'headers': {}, 'query': {}, 'body': None, 'assertions': [], 'variables': {}, 'extract': [], 'timeout': 10})
    manual_spec = core.create_test_case_spec('Manual', project['id'], story_id=story['id'])
    automated_spec = core.create_test_case_spec('Automatizado', project['id'], story_id=story['id'], linked_case_id=api_case['id'])
    core.save('runs', {'type': 'api', 'case_id': api_case['id'], 'status': 'passed', 'started_at': core.now()})

    coverage = core.story_coverage(story['id'])
    assert coverage['total'] == 2 and coverage['automated'] == 1 and coverage['passing'] == 1
    rows_by_spec = {r['spec']['id']: r for r in coverage['rows']}
    assert rows_by_spec[manual_spec['id']]['last_run'] is None
    assert rows_by_spec[automated_spec['id']]['last_run']['status'] == 'passed'
    with pytest.raises(ValueError):
        core.story_coverage('no-existe')
