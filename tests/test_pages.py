"""Smoke tests of every page through NiceGUI's in-process user simulation."""
import json
import pytest
from nicegui.testing import User
from app import core

ROUTES = ['/', '/resumen', '/projects', '/workspace', '/lab', '/observer', '/observer/interface', '/modules', '/environments', '/cases', '/cases/edit', '/ui-cases',
          '/suites', '/schedules', '/runs', '/portable']


async def test_every_page_renders_without_a_project(user: User):
    for route in ROUTES:
        await user.open(route)
        await user.should_see('Local Test Workspace')


async def test_projects_flow_and_filtering(user: User):
    await user.open('/projects')
    user.find('Nombre').type('Proyecto QA')
    user.find('Crear proyecto').click()
    await user.should_see('Proyecto creado y seleccionado')
    assert [p['name'] for p in core.list_items('projects')] == ['Proyecto QA']
    for route in ROUTES:
        await user.open(route)
        await user.should_see('Proyecto QA')


async def eventually(condition, seconds=8):
    """Polls until condition() is true (background tasks such as io_bound requests need a moment)."""
    import asyncio
    for _ in range(int(seconds * 2)):
        await asyncio.sleep(0.5)          # user.find() builds a full page dump on a miss: poll gently so background tasks can run
        try:
            if condition():
                return
        except Exception:
            pass
    raise AssertionError('la condición no se cumplió a tiempo')


SPEC = b'openapi: 3.0.3\ninfo: {title: Subida, version: "1"}\npaths:\n  /x:\n    get: {responses: {"200": {description: ok}}}\n'


def seed():
    from scripts.seed_demo import seed
    return seed()


async def test_pages_render_with_data(user: User):
    seed()
    for route in ROUTES + ['/suites/edit']:
        await user.open(route)
        await user.should_see('Demo Sample App')
    await user.open('/cases')
    await user.should_see('Health OK')
    await user.open('/ui-cases')
    await user.should_see('Login UI')
    await user.open('/suites')
    await user.should_see('Smoke encadenado')
    await user.open('/schedules')
    await user.should_see('Lunes a viernes')


async def test_openapi_upload_works_with_nicegui_3(user: User):
    from nicegui import ui
    from nicegui.elements.upload_files import SmallFileUpload
    core.create_project('P')
    await user.open('/modules')
    upload = user.find(kind=ui.upload).elements.pop()
    await upload.handle_uploads([SmallFileUpload(name='spec.yaml', content_type='text/yaml', _data=SPEC)])
    await user.should_see('Importado «Subida»')
    assert core.list_items('modules')[0]['name'] == 'Subida'


async def test_workspace_import_preview_then_confirm(user: User, tmp_path):
    from nicegui import ui
    from nicegui.elements.upload_files import SmallFileUpload
    seed()
    package = core.export_workspace(tmp_path / 'p.zip', project_id=core.get_active_project_id())
    await user.open('/portable')
    upload = user.find(kind=ui.upload).elements.pop()
    await upload.handle_uploads([SmallFileUpload(name='p.zip', content_type='application/zip', _data=package.read_bytes())])
    await user.should_see('Vista previa')
    before = len(core.list_items('cases'))
    assert len(core.list_items('cases')) == before  # preview wrote nothing
    user.find('Confirmar importación').click()
    await user.should_see('Importación completada')
    await upload.handle_uploads([SmallFileUpload(name='bad.zip', content_type='application/zip', _data=b'not a zip')])
    await user.should_see('ZIP válido')


async def test_reset_workspace_requires_the_exact_phrase(user: User):
    seed()
    await user.open('/portable')
    user.find('Reiniciar workspace (borra todo)').click()
    await user.should_see('Escribe REINICIAR para confirmar.')
    user.find('Confirmación').type('no')
    user.find('Borrar todo y reiniciar').click()
    await user.should_see('Escribe exactamente REINICIAR')
    assert core.list_items('projects') != []  # the wrong phrase changed nothing

    user.find('Confirmación').clear()
    user.find('Confirmación').type('REINICIAR')
    user.find('Borrar todo y reiniciar').click()
    await user.should_see('Workspace reiniciado')
    assert core.list_items('projects') == []
    assert core.list_items('cases') == []


async def test_projects_page_hides_edit_fields_until_toggled(user: User):
    seed()
    pid = core.list_items('projects')[0]['id']
    await user.open('/projects')
    await user.should_not_see(marker=f'project-save-{pid}')
    user.find(f'project-edit-{pid}').click()
    await user.should_see(marker=f'project-save-{pid}')


async def test_projects_page_marks_duplicate_names_with_a_short_id(user: User):
    core.save('projects', {'name': 'p', 'description': '', 'version': 1})  # bypasses create_project's own dedup check
    second = core.save('projects', {'name': 'p', 'description': '', 'version': 1})
    await user.open('/projects')
    await user.should_see(f'#{second["id"][:8]}')


async def test_projects_page_search_filters_the_list(user: User):
    created = [core.create_project(f'Proyecto {i}') for i in range(6)]
    await user.open('/projects')
    user.find('project-search').type('Proyecto 3')
    await user.should_see('Proyecto 3')
    await user.should_not_see(marker=f'project-edit-{created[0]["id"]}')  # filtered out, not just hidden elsewhere (e.g. the header's project selector)


async def test_validation_messages(user: User):
    seed()
    await user.open('/cases/edit')
    user.find('Nombre del caso').clear()
    user.find('Guardar').click()
    await user.should_see('El nombre es obligatorio')
    await user.open('/environments')
    user.find('Guardar ambiente').click()
    await user.should_see('URL base inválida')
    await user.open('/ui-cases?id=nope')
    await user.should_see('El caso no existe')
    await user.open('/projects')
    user.find('Crear proyecto').click()
    await user.should_see('El nombre del proyecto es obligatorio')


async def test_environments_edit_param_cannot_steal_another_projects_environment(user: User):
    seed()
    other = core.create_project('Otro proyecto')
    foreign_env = core.save('environments', {'name': 'Ajeno', 'project_id': other['id'], 'base_url': 'https://ajeno.example.com', 'auth': {'type': 'none'}, 'variables': {}})
    pid = [p for p in core.list_items('projects') if p['name'] == 'Demo Sample App'][0]['id']
    core.set_active_project(pid)
    await user.open(f'/environments?edit={foreign_env["id"]}')
    await user.should_see('no pertenece al proyecto activo')
    assert user.find('env-name').elements.pop().value == 'QA'  # shows the "new environment" default, not the foreign one
    user.find('env-base-url').clear()
    user.find('env-base-url').type('https://qa.ejemplo.com')
    user.find('Guardar ambiente').click()
    await user.should_see('Ambiente guardado')
    assert core.get('environments', foreign_env['id'])['project_id'] == other['id']  # untouched


async def test_environments_rejects_duplicate_name_within_the_project(user: User):
    seed()
    await user.open('/environments')
    user.find('env-name').clear()
    user.find('env-name').type('Local')  # the name seed() already used in this project
    user.find('env-base-url').clear()
    user.find('env-base-url').type('https://otra.example.com')
    user.find('Guardar ambiente').click()
    await user.should_see('Ya existe un ambiente llamado')
    assert len(core.list_items('environments')) == 1


async def test_environments_rejects_invalid_ui_base_url(user: User):
    seed()
    await user.open('/environments')
    user.find('env-name').clear()
    user.find('env-name').type('Nuevo')
    user.find('env-base-url').clear()
    user.find('env-base-url').type('https://ok.example.com')
    user.find('env-ui-base-url').type('not a url')
    user.find('Guardar ambiente').click()
    await user.should_see('URL base inválida')
    assert len(core.list_items('environments')) == 1


async def test_environments_delete_blocked_by_a_step_level_reference(user: User):
    seed()
    pid = [p for p in core.list_items('projects') if p['name'] == 'Demo Sample App'][0]['id']
    other_env = core.save('environments', {'name': 'Solo en un paso', 'project_id': pid, 'base_url': 'https://solo-paso.example.com', 'auth': {'type': 'none'}, 'variables': {}})
    health = [c for c in core.list_items('cases') if c['name'] == 'Health OK'][0]
    suite = core.list_items('suites')[0]
    core.save_suite(suite['name'], suite['environment_id'], None, pid, id=suite['id'],
                     steps=[{'case_id': health['id'], 'alias': 'health', 'environment_id': other_env['id'], 'enrich': []}])
    await user.open('/environments')
    user.find(f'env-delete-{other_env["id"]}').click()
    await user.should_see('¿Eliminar el ambiente')
    user.find('confirm-dialog-accept').click()
    await user.should_see('paso(s) con ambiente propio')
    assert core.get('environments', other_env['id']) is not None


async def test_modules_warns_about_empty_header_value(user: User):
    from nicegui import ui
    seed()
    await user.open('/modules')
    # "Cabecera (opcional)" defaults to "Authorization" with no value typed: a very easy slip.
    user.find('Explorar automáticamente').click()
    await user.should_see('el valor está vacío')
    # let the exploration itself finish (it targets an unreachable host, so it fails fast) before the test ends:
    # otherwise it keeps running in the background and its result lands in whichever workspace core.DB points
    # to by the time it completes — i.e. the *next* test's isolated database, not this one's.
    await eventually(lambda: bool(user.find(kind=ui.code).elements))


async def test_modules_warns_about_duplicate_import_by_source_url(user: User, tmp_path):
    seed()
    import http.server, threading
    body = b'{"openapi":"3.0.3","info":{"title":"Dup"},"paths":{"/x":{"get":{"responses":{"200":{"description":"ok"}}}}}}'

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        spec_url = f'http://127.0.0.1:{server.server_port}/openapi.json'
        await user.open('/modules')
        user.find('URL del contrato, de su página de Swagger UI o un enlace de GitHub').type(spec_url)
        user.find('Importar desde URL').click()
        # run.io_bound: a real thread + HTTP round trip, slow and jittery under a loaded test run — poll the actual state, not a fixed retry budget
        await eventually(lambda: len(core.list_project_items('modules', core.get_active_project_id())) == 2)
        user.find('URL del contrato, de su página de Swagger UI o un enlace de GitHub').type(spec_url)
        user.find('Importar desde URL').click()
        await eventually(lambda: len(core.list_project_items('modules', core.get_active_project_id())) == 3)
        await user.should_see('Ya había 1 módulo')
    finally:
        server.shutdown()


def code_texts(user):
    from nicegui import ui
    return [(e.content or '') for e in user.find(kind=ui.code).elements]


async def test_workspace_sends_records_history_and_saves_into_a_new_project(user: User, sample_app):
    assert core.list_items('projects') == []
    await user.open('/workspace')
    await user.should_see('Escribe una URL y pulsa Enviar')
    user.find('ws-url').type(sample_app.url + '/api/users/2')
    user.find('ws-send').click()
    await eventually(lambda: any('"name": "user2"' in text for text in code_texts(user)))
    assert core.list_items('runs') == [] and core.list_items('cases') == []                    # nothing saved yet, but...
    history = core.list_items('lab_history')
    assert len(history) == 1 and history[0]['result']['http_status'] == 200 and history[0]['key'].endswith('/api/users/2')   # ...it is in the history
    user.find('rail-Guardar').click()
    user.find('ws-save').click()                                                              # a status/exact mode with no project chosen
    await user.should_see('El nombre del proyecto es obligatorio')
    assert core.list_items('cases') == []
    user.find('Nombre del proyecto nuevo').type('Proyecto del espacio')
    user.find('ws-save').click()
    await user.should_see('guardado en el proyecto')
    [project] = core.list_items('projects')
    [case] = core.list_items('cases')
    assert project['name'] == 'Proyecto del espacio' and case['project_id'] == project['id'] and case['path'] == '/api/users/2'
    assert case['assertions'][1]['type'] == 'json_matches'
    env = core.list_items('environments')[0]
    assert core.execute_api(case, env)['status'] == 'passed'


async def test_workspace_history_reload_and_search(user: User, sample_app):
    from app import workspace as ws_logic
    d = ws_logic.new_draft()
    d.update(name='Usuario uno', url=sample_app.url + '/api/users/1')
    case, env = ws_logic.build_case(d)
    ws_logic.record_history(d, core.execute_api(case, env, persist=False))
    await user.open('/workspace')
    await user.should_see('Usuario uno')
    user.find('ws-history-item').click()                                                      # loads the request into the editor
    await user.should_see('Del historial')
    assert user.find('ws-url').elements.pop().value == sample_app.url + '/api/users/1'
    user.find('ws-search').type('no-existe')
    await user.should_not_see('ws-history-item')                                              # the list is filtered (the name stays in the editor)
    await user.should_see('Aquí aparecerán tus peticiones')


async def test_workspace_shows_errors_instead_of_failing_silently(user: User):
    await user.open('/workspace')
    user.find('ws-send').click()
    await user.should_see('Escribe la URL')
    user.find('ws-url').type('/solo/ruta')
    user.find('ws-send').click()
    await user.should_see('URL completa')


async def test_workspace_imports_an_agent_spec_into_the_editor(user: User):
    spec = {'format': 'ltw.spec/1', 'environments': [{'name': 'api', 'base_url': 'http://127.0.0.1:9'}],
            'cases': [{'name': 'Crear', 'method': 'POST', 'path': '/api/items', 'body': {'name': 'x'}, 'assertions': [{'type': 'status', 'expected': 201}]}]}
    await user.open('/workspace')
    user.find('rail-Agente').click()
    user.find('Pega aquí un ltw.spec/1').type(json.dumps(spec))
    user.find('Validar y cargar el primer caso').click()
    await user.should_see('Primer caso cargado')
    assert user.find('ws-url').elements.pop().value == 'http://127.0.0.1:9/api/items'
    bad = user.find('Pega aquí un ltw.spec/1')
    bad.clear()
    bad.type(json.dumps({'format': 'ltw.spec/1', 'cases': [{'name': 'x', 'method': 'NOPE', 'path': '/'}]}))
    user.find('Validar y cargar el primer caso').click()
    await user.should_see('$.cases[0].method')


async def test_lab_url_redirects_to_the_workspace(user: User):
    await user.open('/lab')
    await user.should_see('Escribe una URL y pulsa Enviar')


async def test_observer_pages_show_the_catalog_and_baseline_flow(user: User):
    import json
    from app import observer
    project = core.create_project('Obs')
    doc = None
    for i in (1, 2, 3):
        doc = observer.record('Usuarios', project['id'], 'GET', f'/api/users/{i}', '', '', 200, json.dumps({'id': i, 'name': 'a'}), 4.0, origin='http://h:1')
    core.save('taps', {'name': 'Usuarios', 'company': 'Acme SA', 'owner': 'Ana', 'project_id': project['id'], 'listen_port': 9555, 'target': 'http://h:1'})
    await user.open('/observer')
    await user.should_see('Usuarios')
    await user.should_see('Acme SA')
    await user.should_see('sin línea base')
    await user.open(f'/observer/interface?id={doc["id"]}')
    await user.should_see('/api/users/{id}')
    await user.should_see('Fijar línea base')
    user.find('Fijar línea base').click()
    await user.should_see('Línea base fijada')
    assert core.get('interfaces', doc['id'])['baseline'] is not None
    await user.open('/observer/interface?id=nope')
    await user.should_see('La interfaz no existe')


async def test_observer_tap_form_validates(user: User):
    core.create_project('Obs')
    await user.open('/observer')
    user.find('Crear tap').click()
    await user.should_see('El nombre del módulo es obligatorio')
    assert core.list_items('taps') == []


async def test_browser_lives_in_ui_cases_not_in_the_api_workspace(user: User):
    """The real-browser navigator (navigate / record) is for building UI cases, not API requests: it belongs
    in the Casos UI workspace, not as a corner icon in the API workspace."""
    core.create_project('Nav')
    await user.open('/ui-cases')
    await user.should_see('Navegar')
    await user.should_see('Grabar')
    await user.open('/workspace')
    await user.should_see('Conectividad')          # kept: it is about the API request being built
    with pytest.raises(AssertionError):
        await user.should_see('Grabar', retries=1)


async def test_ui_cases_is_one_workspace_like_the_api_one(user: User):
    """History | steps | tools, same shape as the API workspace: clicking a saved case loads its real steps
    (not a blank draft), and clicking a run loads its snapshot too."""
    project = core.create_project('UIW')
    core.set_active_project(project['id'])
    case = core.save('cases', {'name': 'Login FEID', 'type': 'ui', 'project_id': project['id'], 'timeout_ms': 10000,
                               'steps': [{'action': 'navigate', 'url': 'http://x/login'}, {'action': 'assert_visible', 'locator': {'by': 'text', 'value': 'Entrar'}}]})
    await user.open('/ui-cases')
    await user.should_see('Historial')
    await user.should_see('Guardados')
    user.find('Guardados').click()
    user.find('ui-saved-item').click()
    await user.should_see('http://x/login')
    await user.should_see('Entrar')

    run = core.save('runs', {'type': 'ui', 'case_id': case['id'], 'case_name': 'Login FEID', 'project_id': project['id'], 'status': 'passed',
                             'started_at': '2026-01-01T00:00:00+00:00', 'case_snapshot': {**case, 'name': 'Snapshot cargado'}, 'steps': []})
    await user.open('/ui-cases')
    user.find('ui-history-item').click()
    await user.should_see('Snapshot cargado')


async def test_saved_cases_are_unified_across_both_workspaces(user: User):
    """A test case is a test case, API or UI: both workspaces show the full list of saved cases, and clicking
    one of the other kind takes you to the workspace that actually edits that kind."""
    import asyncio
    project = core.create_project('Unif')
    core.set_active_project(project['id'])
    env = core.save('environments', {'name': 'e', 'project_id': project['id'], 'base_url': 'http://x', 'auth': {'type': 'none'}, 'variables': {}})
    api_case = core.save('cases', {'name': 'Ping', 'method': 'GET', 'path': '/ping', 'project_id': project['id'], 'environment_id': env['id'],
                                   'headers': {}, 'query': {}, 'body': None, 'assertions': [], 'variables': {}, 'extract': [], 'timeout': 10})
    ui_case = core.save('cases', {'name': 'Login UI', 'type': 'ui', 'project_id': project['id'], 'timeout_ms': 10000, 'steps': [{'action': 'navigate', 'url': '/login'}]})

    await user.open('/workspace')
    user.find('rail-Guardar').click()
    await user.should_see('Casos (API y UI)')
    await user.should_see('Login UI')                             # the UI case shows up here too
    user.find(f'ws-saved-{ui_case["id"]}').click()
    await asyncio.sleep(0.3)                                       # ui.navigate.to runs as a background task in tests
    assert user.client.page.path == '/ui-cases'                   # navigated away to edit it where it belongs

    await user.open('/ui-cases')
    await user.should_see('Guardados')
    user.find('Guardados').click()
    await asyncio.sleep(0.3)
    await user.should_see('Ping')                                 # the API case shows up here too
    user.find(f'ui-saved-api-{api_case["id"]}').click()
    await asyncio.sleep(0.5)
    assert user.client.page.path == '/workspace'

    await user.open(f'/workspace?case={api_case["id"]}')
    await user.should_see('ws-url')
    assert user.find('ws-url').elements.pop().value == '/ping'   # preloaded (relative to its environment), not a blank draft

    await user.open('/workspace?case=no-existe')
    await user.should_see('ya no existe')


async def test_home_shows_the_maturity_disclaimer(user: User):
    """Transparency: no one should form an expectation the product hasn't earned - the home page says, up front,
    what is stable, what is beta and what is experimental, plus the use-at-your-own-risk notice."""
    from app import maturity
    await user.open('/')
    await user.should_see('Qué tan maduro está cada parte')
    await user.should_see(maturity.DISCLAIMER[:40])
    for level in maturity.LEVELS:
        await user.should_see(level['label'])
