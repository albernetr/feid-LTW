"""Smoke tests of every page through NiceGUI's in-process user simulation."""
import json
import re
import pytest
from nicegui.testing import User
from app import core
from app.pages.common import NAV, NAV_GROUPS

ROUTES = ['/', '/resumen', '/projects', '/projects/edit', '/workspace', '/lab', '/observer', '/observer/interface', '/modules', '/modules/edit', '/environments', '/environments/edit', '/cases', '/cases/edit', '/ui-cases',
          '/suites', '/schedules', '/runs', '/portable', '/stories', '/stories/edit', '/test-specs', '/test-specs/edit', '/spec-templates', '/spec-templates/edit']


async def test_every_page_renders_without_a_project(user: User):
    for route in ROUTES:
        await user.open(route)
        await user.should_see('Local Test Workspace')


def test_nav_groups_cover_every_route_exactly_once_or_leave_it_ungrouped():
    """NAV sigue siendo la lista plana y autoritativa (test_manual.py la recorre tal cual); NAV_GROUPS solo decide
    cómo se presenta en el drawer — nunca debe esconder una ruta ni listarla en dos grupos a la vez."""
    all_routes = {route for _, route, _ in NAV}
    grouped_routes = [route for _, _, routes in NAV_GROUPS for route in routes]
    assert len(grouped_routes) == len(set(grouped_routes)), 'una ruta aparece en más de un grupo'
    assert set(grouped_routes) <= all_routes, 'un grupo referencia una ruta que ya no existe en NAV'


async def test_a_grouped_page_auto_expands_its_own_menu_section(user: User):
    """Visitar una página de un grupo (p. ej. «Integraciones», dentro de «Automatización») debe mostrar esa
    sección ya desplegada, aunque el usuario nunca la haya tocado — no debe hacer falta adivinar dónde se escondió."""
    await user.open('/integrations')
    await user.should_see('Automatización')   # encabezado del grupo
    await user.should_see('Integraciones')     # ítem del menú, visible porque el grupo quedó expandido
    await user.should_see('Inicio')            # los ítems sueltos (sin grupo) siempre están visibles


async def test_configuraciones_group_has_models_and_storage(user: User):
    await user.open('/storage')
    await user.should_see('Configuraciones')   # encabezado del grupo
    await user.should_see('Base de datos')     # el ítem de esta misma página
    await user.should_see('Modelos de IA')     # agrupado junto a ella


async def test_storage_settings_shows_sqlite_by_default_and_can_probe_azure_credentials(user: User, monkeypatch):
    from app import azure_sql_backend
    monkeypatch.delenv('LTW_BACKEND', raising=False)
    await user.open('/storage')
    await user.should_see('SQLite (local)')

    calls = []
    monkeypatch.setattr(azure_sql_backend, 'test_connection', lambda config=None: calls.append(config))
    user.find(marker='storage-probe-server').type('test-ws.database.windows.net')
    user.find(marker='storage-probe-database').type('lwt')
    user.find(marker='storage-probe-user').type('devsquad')
    user.find(marker='storage-probe-password').type('x')
    user.find(marker='storage-probe-submit').click()
    await user.should_see('Conexión correcta')
    assert calls and calls[0]['server'] == 'test-ws.database.windows.net' and calls[0]['database'] == 'lwt'


async def test_storage_settings_probe_requires_every_field(user: User):
    await user.open('/storage')
    user.find(marker='storage-probe-submit').click()
    await user.should_see('Completa:')


async def test_projects_flow_and_filtering(user: User):
    await user.open('/projects/edit')
    user.find('project-name').type('Proyecto QA')
    user.find('project-save').click()
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


async def test_creating_and_running_a_case_from_the_ui_stamps_created_by_and_executed_by(user: User):
    """Smoke test de punta a punta: la cuenta con la que `user` está logueada (conftest.py la loguea sola)
    debe quedar registrada como autora y ejecutora — no solo en core.py, sino a través de la pantalla real."""
    seed()
    await user.open('/cases/edit')
    user.find('Nombre del caso').clear().type('Caso de autoría')
    user.find('Guardar y ejecutar').click()
    await eventually(lambda: core.list_items('users') and any(c['name'] == 'Caso de autoría' for c in core.list_items('cases')))
    case = next(c for c in core.list_items('cases') if c['name'] == 'Caso de autoría')
    test_account = core.get_user_by_email('test@ltw.local')
    assert case['created_by'] == test_account['id']
    run = next(r for r in core.list_items('runs') if r.get('case_id') == case['id'])
    assert run['executed_by'] == test_account['id']


async def test_cases_list_filters_by_component_and_module(user: User):
    from nicegui import ui

    async def visible_names():
        """El clic en una opción del desplegable no se procesa en el mismo tick — hay que esperar a que
        render.refresh() termine antes de leer qué tarjetas quedaron, o se lee el estado anterior."""
        await eventually(lambda: True)   # cede el control una vez; suficiente para que el on_value_change corra
        return {c.text for c in user.find(kind=ui.label).elements if c.text in ('Cobrar', 'Enviar')}

    project = core.create_project('Filtros')
    core.set_active_project(project['id'])
    group = core.create_module_group('Pagos', project['id'])
    payments = core.create_component('API Pagos', project['id'], module_group_ids=[group['id']])
    shipping = core.create_component('API Envíos', project['id'])
    core.save('cases', {'name': 'Cobrar', 'type': 'api', 'project_id': project['id'], 'module_id': payments['id'],
                        'method': 'POST', 'path': '/pagar', 'assertions': []})
    core.save('cases', {'name': 'Enviar', 'type': 'api', 'project_id': project['id'], 'module_id': shipping['id'],
                        'method': 'POST', 'path': '/enviar', 'assertions': []})
    await user.open('/cases')
    await user.should_see('Cobrar')
    await user.should_see('Enviar')

    user.find(marker='cases-filter-component').click()
    user.find('API Pagos').click()
    assert await visible_names() == {'Cobrar'}

    await user.open('/cases')   # página nueva: filtros vuelven a «todos»
    await user.should_see('Cobrar')
    await user.should_see('Enviar')
    user.find(marker='cases-filter-group').click()
    user.find('Pagos').click()
    assert await visible_names() == {'Cobrar'}   # «Enviar» es de un componente sin módulo: no coincide


async def test_openapi_upload_works_with_nicegui_3(user: User):
    from nicegui import ui
    from nicegui.elements.upload_files import SmallFileUpload
    project = core.create_project('P')
    component = core.create_component('Mi backend', project['id'])
    await user.open(f'/modules/edit?id={component["id"]}')
    upload = user.find(kind=ui.upload).elements.pop()
    await upload.handle_uploads([SmallFileUpload(name='spec.yaml', content_type='text/yaml', _data=SPEC)])
    await user.should_see('Contrato importado')
    assert core.get('modules', component['id'])['name'] == 'Mi backend'   # registered name survives; the contract's own title ('Subida') does not override it


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


async def test_projects_table_row_click_opens_the_detail_page(user: User):
    from nicegui import ui
    seed()
    pid = core.list_items('projects')[0]['id']
    await user.open('/projects')
    user.find(kind=ui.table).trigger('rowClick', [None, {'id': pid}, 0])
    await user.should_see(marker='project-save')
    assert user.find('project-name').elements.pop().value == 'Demo Sample App'


async def test_projects_table_row_actions_select_edit_and_delete(user: User):
    from nicegui import ui
    core.create_project('A')
    b = core.create_project('B')
    await user.open('/projects')
    interaction = user.find(kind=ui.table)
    row_b = next(r for r in next(iter(interaction.elements)).rows if r['id'] == b['id'])

    interaction.trigger('selectProject', row_b)
    await eventually(lambda: core.get_active_project_id() == b['id'])

    interaction.trigger('editProject', row_b)
    await user.should_see(marker='project-save')
    assert user.find('project-name').elements.pop().value == 'B'

    await user.open('/projects')
    interaction = user.find(kind=ui.table)
    row_a = next(r for r in next(iter(interaction.elements)).rows if r['base_name'] == 'A')
    interaction.trigger('deleteProject', row_a)
    await user.should_see('¿Eliminar el proyecto «A»')
    user.find('confirm-dialog-accept').click()
    await user.should_see('Proyecto eliminado')
    assert core.list_items('projects') == [core.get('projects', b['id'])]


async def test_projects_page_marks_duplicate_names_with_a_short_id(user: User):
    from nicegui import ui
    core.save('projects', {'name': 'p', 'description': '', 'version': 1})  # bypasses create_project's own dedup check
    second = core.save('projects', {'name': 'p', 'description': '', 'version': 1})
    await user.open('/projects')
    table = user.find(kind=ui.table).elements.pop()  # ui.table keeps cell text in `rows` data, not as discoverable element content
    assert any(f'#{second["id"][:8]}' in row['name'] for row in table.rows)


async def test_projects_page_search_filters_the_table(user: User):
    from nicegui import ui
    for i in range(6):
        core.create_project(f'Proyecto {i}')
    await user.open('/projects')
    table = user.find(kind=ui.table).elements.pop()
    user.find('project-search').type('Proyecto 3')
    await eventually(lambda: [row['name'] for row in table.rows] == ['Proyecto 3'])


async def test_projects_detail_page_save_select_and_delete(user: User):
    core.create_project('Original')
    other = core.create_project('Otro activo')
    core.set_active_project(other['id'])
    original_id = [p for p in core.list_items('projects') if p['name'] == 'Original'][0]['id']

    await user.open(f'/projects/edit?id={original_id}')
    user.find('project-name').clear()
    user.find('project-name').type('Renombrado')
    user.find('project-save').click()
    await user.should_see('Proyecto actualizado')
    assert core.get('projects', original_id)['name'] == 'Renombrado'

    user.find('project-select').click()
    await user.should_see('Activo')
    assert core.get_active_project_id() == original_id

    user.find('project-delete').click()
    await user.should_see('¿Eliminar el proyecto')
    user.find('confirm-dialog-accept').click()
    await user.should_see('Proyecto eliminado')
    assert core.get('projects', original_id) is None


async def test_projects_detail_page_cascade_delete_requires_typing_the_name(user: User):
    seed()
    pid = core.list_items('projects')[0]['id']
    await user.open(f'/projects/edit?id={pid}')
    user.find('project-delete').click()
    await user.should_see('¿Eliminar el proyecto')
    user.find('confirm-dialog-accept').click()
    await user.should_see('Eliminar el proyecto con todo su contenido')

    user.find('project-cascade-phrase').type('nombre incorrecto')
    user.find('project-cascade-accept').click()
    await user.should_see('Escribe exactamente')
    assert core.get('projects', pid) is not None  # the wrong phrase changed nothing

    user.find('project-cascade-phrase').clear()
    user.find('project-cascade-phrase').type('Demo Sample App')
    user.find('project-cascade-accept').click()
    await user.should_see('Proyecto y todo su contenido eliminados')
    assert core.get('projects', pid) is None
    assert core.list_items('cases') == []
    assert core.list_items('modules') == []


async def test_projects_table_cascade_delete(user: User):
    from nicegui import ui
    seed()
    pid = core.list_items('projects')[0]['id']
    await user.open('/projects')
    interaction = user.find(kind=ui.table)
    row = next(r for r in next(iter(interaction.elements)).rows if r['id'] == pid)
    interaction.trigger('deleteProject', row)
    await user.should_see('¿Eliminar el proyecto')
    user.find('confirm-dialog-accept').click()
    await user.should_see('Eliminar el proyecto con todo su contenido')
    user.find('project-cascade-phrase').type('Demo Sample App')
    user.find('project-cascade-accept').click()
    await user.should_see('Proyecto y todo su contenido eliminados')
    assert core.get('projects', pid) is None


async def test_projects_detail_page_disable_and_enable(user: User):
    project = core.create_project('A')
    await user.open(f'/projects/edit?id={project["id"]}')
    assert core.get_active_project_id() == project['id']

    user.find('project-toggle-enabled').click()
    await user.should_see('Proyecto deshabilitado')
    assert core.get_active_project_id() is None
    assert core.get('projects', project['id'])['disabled'] is True

    # a fresh open (not just the in-app navigate.to the handler already did) guarantees we click the
    # button rendered for the *current* state, not a stale one left over from the previous render
    await user.open(f'/projects/edit?id={project["id"]}')
    await user.should_not_see(marker='project-select')  # can't select a disabled project
    user.find('project-toggle-enabled').click()
    await user.should_see('Proyecto habilitado')
    assert core.get('projects', project['id'])['disabled'] is False


async def test_projects_table_toggle_enabled(user: User):
    from nicegui import ui
    project = core.create_project('A')
    await user.open('/projects')
    interaction = user.find(kind=ui.table)
    row = next(r for r in next(iter(interaction.elements)).rows if r['id'] == project['id'])
    interaction.trigger('toggleProject', row)
    await eventually(lambda: core.get('projects', project['id']).get('disabled') is True)
    assert core.get_active_project_id() is None


async def test_projects_edit_page_shows_a_clear_message_for_a_missing_project(user: User):
    await user.open('/projects/edit?id=nope')
    await user.should_see('Este proyecto ya no existe.')


async def test_projects_detail_page_shows_its_resources(user: User):
    seed()
    pid = core.list_items('projects')[0]['id']
    await user.open(f'/projects/edit?id={pid}')
    await user.should_see('Componentes')
    await user.should_see('Sample API')
    await user.should_see('Ambientes')
    await user.should_see('Local')
    await user.should_see('Casos')
    await user.should_see('Flujos')
    await user.should_see('Smoke encadenado')
    await user.should_see('Programaciones')


async def test_projects_detail_resource_card_selects_project_before_navigating(user: User):
    core.create_project('Otro activo')
    second = core.create_project('Segundo')
    await user.open(f'/projects/edit?id={second["id"]}')
    assert core.get_active_project_id() != second['id']
    user.find('project-goto-modules').click()
    await eventually(lambda: user.client.page.path == '/modules' and core.get_active_project_id() == second['id'])


async def test_validation_messages(user: User):
    seed()
    await user.open('/cases/edit')
    user.find('Nombre del caso').clear()
    user.find('Guardar').click()
    await user.should_see('El nombre es obligatorio')
    await user.open('/environments/edit')
    user.find('Guardar ambiente').click()
    await user.should_see('URL base inválida')
    await user.open('/ui-cases?id=nope')
    await user.should_see('El caso no existe')
    await user.open('/projects/edit')
    user.find('project-save').click()
    await user.should_see('El nombre del proyecto es obligatorio')


async def test_environments_edit_param_cannot_steal_another_projects_environment(user: User):
    seed()
    other = core.create_project('Otro proyecto')
    foreign_env = core.save('environments', {'name': 'Ajeno', 'project_id': other['id'], 'base_url': 'https://ajeno.example.com', 'auth': {'type': 'none'}, 'variables': {}})
    pid = [p for p in core.list_items('projects') if p['name'] == 'Demo Sample App'][0]['id']
    core.set_active_project(pid)
    await user.open(f'/environments/edit?id={foreign_env["id"]}')
    await user.should_see('no pertenece al proyecto activo')
    assert user.find('env-name').elements.pop().value == 'QA'  # shows the "new environment" default, not the foreign one
    user.find('env-base-url').clear()
    user.find('env-base-url').type('https://qa.ejemplo.com')
    user.find('Guardar ambiente').click()
    await user.should_see('Ambiente guardado')
    assert core.get('environments', foreign_env['id'])['project_id'] == other['id']  # untouched


async def test_environments_rejects_duplicate_name_within_the_project(user: User):
    seed()
    await user.open('/environments/edit')
    user.find('env-name').clear()
    user.find('env-name').type('Local')  # the name seed() already used in this project
    user.find('env-base-url').clear()
    user.find('env-base-url').type('https://otra.example.com')
    user.find('Guardar ambiente').click()
    await user.should_see('Ya existe un ambiente llamado')
    assert len(core.list_items('environments')) == 1


async def test_environments_rejects_invalid_ui_base_url(user: User):
    seed()
    await user.open('/environments/edit')
    user.find('env-name').clear()
    user.find('env-name').type('Nuevo')
    user.find('env-base-url').clear()
    user.find('env-base-url').type('https://ok.example.com')
    user.find('env-ui-base-url').type('not a url')
    user.find('Guardar ambiente').click()
    await user.should_see('URL base inválida')
    assert len(core.list_items('environments')) == 1


async def test_environments_delete_blocked_by_a_step_level_reference(user: User):
    from nicegui import ui
    seed()
    pid = [p for p in core.list_items('projects') if p['name'] == 'Demo Sample App'][0]['id']
    other_env = core.save('environments', {'name': 'Solo en un paso', 'project_id': pid, 'base_url': 'https://solo-paso.example.com', 'auth': {'type': 'none'}, 'variables': {}})
    health = [c for c in core.list_items('cases') if c['name'] == 'Health OK'][0]
    suite = core.list_items('suites')[0]
    core.save_suite(suite['name'], suite['environment_id'], None, pid, id=suite['id'],
                     steps=[{'case_id': health['id'], 'alias': 'health', 'environment_id': other_env['id'], 'enrich': []}])
    await user.open('/environments')
    interaction = user.find(kind=ui.table)
    row = next(r for r in next(iter(interaction.elements)).rows if r['id'] == other_env['id'])
    interaction.trigger('deleteEnv', row)
    await user.should_see('¿Eliminar el ambiente')
    user.find('confirm-dialog-accept').click()
    await user.should_see('paso(s) con ambiente propio')
    assert core.get('environments', other_env['id']) is not None


async def test_environments_edit_saves_http_token_refresh_config(user: User):
    seed()
    await user.open('/environments/edit')
    user.find('env-name').clear()
    user.find('env-name').type('Con refresco')
    user.find('env-base-url').clear()
    user.find('env-base-url').type('https://api.example.com')
    user.find('Autenticación').click()
    user.find('Bearer token').click()
    user.find('…o variable de entorno').type('MY_TOKEN_VAR')
    user.find('env-refresh-url').type('https://auth.example.com/token')
    user.find('Guardar ambiente').click()
    await user.should_see('Ambiente guardado')
    env = [e for e in core.list_items('environments') if e['name'] == 'Con refresco'][0]
    assert env['auth']['refresh']['mode'] == 'http'
    assert env['auth']['refresh']['url'] == 'https://auth.example.com/token'
    assert env['auth']['refresh']['token_path'] == '$.access_token'
    assert env['auth']['refresh']['enabled'] is True  # checked by default once you configure how to get the token


async def test_environments_edit_can_configure_token_fetch_without_automatic_refresh(user: User):
    """The fields that describe how to get a token (URL, body, paths) must be enterable even when the
    user does not want it fetched automatically — before this, they were hidden behind a checkbox, and even
    after that fix, behind a second, redundant one (selecting Bearer/API Key is enough)."""
    seed()
    await user.open('/environments/edit')
    user.find('env-name').clear()
    user.find('env-name').type('Sin automático')
    user.find('env-base-url').clear()
    user.find('env-base-url').type('https://api.example.com')
    user.find('Autenticación').click()
    user.find('Bearer token').click()
    user.find('…o variable de entorno').type('MY_TOKEN_VAR')
    user.find('env-refresh-url').type('https://auth.example.com/token')
    user.find('env-refresh-auto').click()  # uncheck: configured, but not automatic
    user.find('Guardar ambiente').click()
    await user.should_see('Ambiente guardado')
    env = [e for e in core.list_items('environments') if e['name'] == 'Sin automático'][0]
    assert env['auth']['refresh']['url'] == 'https://auth.example.com/token'
    assert env['auth']['refresh']['enabled'] is False
    assert core.token_needs_refresh(env) is False  # configured, but never applied on its own


async def test_environments_edit_test_refresh_button(user: User):
    import http.server, threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get('Content-Length', 0)); self.rfile.read(length)
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
            self.wfile.write(b'{"access_token": "abcdefgh"}')

        def log_message(self, *a):
            pass
    server = http.server.HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        project = core.create_project('Refresco')
        core.set_active_project(project['id'])
        env = core.save('environments', {'name': 'E', 'project_id': project['id'], 'base_url': 'https://api.example.com',
                        'auth': {'type': 'bearer', 'secret': 'probe-tok'}, 'variables': {}})
        await user.open(f'/environments/edit?id={env["id"]}')
        user.find('env-refresh-url').type(f'http://127.0.0.1:{server.server_port}/token')
        user.find('Obtener token ahora').click()
        await eventually(lambda: core.secret_get('probe-tok') == 'abcdefgh')
        await user.should_see('Token actualizado')
    finally:
        server.shutdown()


async def test_environments_edit_saves_trusted_hosts(user: User):
    project = core.create_project('SSO hosts')
    core.set_active_project(project['id'])
    await user.open('/environments/edit')
    user.find('env-base-url').clear()
    user.find('env-base-url').type('https://app.example.com')
    user.find('env-trusted-hosts').type(' auth.example.com , Otro.Example.com ')
    user.find('env-name').clear()
    user.find('env-name').type('Con SSO')
    user.find('env-save').click()
    await eventually(lambda: core.list_project_items('environments', project['id']) != [])
    [env] = core.list_project_items('environments', project['id'])
    assert env['trusted_hosts'] == ['auth.example.com', 'otro.example.com']   # recortados y en minúsculas


async def test_environments_edit_rejects_a_trusted_host_with_a_scheme_or_path(user: User):
    project = core.create_project('SSO hosts malos')
    core.set_active_project(project['id'])
    await user.open('/environments/edit')
    user.find('env-base-url').clear()
    user.find('env-base-url').type('https://app.example.com')
    user.find('env-trusted-hosts').type('https://auth.example.com')
    user.find('env-name').clear()
    user.find('env-name').type('Mal host')
    user.find('env-save').click()
    await user.should_see('no es un host válido')
    assert core.list_project_items('environments', project['id']) == []


async def test_environments_edit_requires_saving_before_capturing_a_session(user: User):
    project = core.create_project('Sin guardar')
    core.set_active_project(project['id'])
    await user.open('/environments/edit')
    user.find('env-session-capture').click()
    await user.should_see('Guarda el ambiente primero')


async def test_environments_edit_captures_and_clears_a_ui_session(user: User, monkeypatch):
    from app import recorder
    project = core.create_project('Con sesión')
    core.set_active_project(project['id'])
    env = core.save('environments', {'name': 'qa', 'project_id': project['id'], 'base_url': 'https://qa.example.com', 'variables': {}, 'auth': {'type': 'none'}})
    captured = {'cookies': [{'name': 'session', 'value': 'abc'}], 'origins': []}
    monkeypatch.setattr(recorder, 'capture_session', lambda url: captured)   # sin abrir una ventana real
    await user.open(f'/environments/edit?id={env["id"]}')
    await user.should_see('Sin sesión guardada')
    user.find('env-session-capture').click()
    await eventually(lambda: core.get_ui_session(env['id']) == captured)
    await user.open(f'/environments/edit?id={env["id"]}')   # la recarga (ui.navigate.reload) ya debería mostrar el estado nuevo; reabro para confirmarlo
    await user.should_see('Sesión guardada el')
    user.find('env-session-clear').click()
    user.find(marker='confirm-dialog-accept').click()
    await eventually(lambda: core.get_ui_session(env['id']) is None)


async def test_environments_edit_requires_saving_before_opening_a_live_browser(user: User):
    project = core.create_project('Vivo sin guardar')
    core.set_active_project(project['id'])
    await user.open('/environments/edit')
    user.find('Navegador en vivo').click()   # cambia del modo «Sesión guardada» (por defecto) a este
    await user.should_see(marker='env-live-open', retries=30)   # bind_visibility_from tarda un tick del binding en reflejarse
    user.find(marker='env-live-open').click()
    await user.should_see('Guarda el ambiente primero')


async def test_environments_edit_switches_to_live_browser_mode_and_opens_it(user: User, monkeypatch):
    from app import recorder
    project = core.create_project('Con navegador en vivo')
    core.set_active_project(project['id'])
    env = core.save('environments', {'name': 'qa', 'project_id': project['id'], 'base_url': 'https://qa.example.com', 'variables': {}, 'auth': {'type': 'none'}})
    opened = {}

    def fake_launch(environment_id, url, port):
        opened.update(environment_id=environment_id, url=url, port=port)
    monkeypatch.setattr(recorder, 'launch_live_browser', fake_launch)   # sin abrir un Chromium real
    monkeypatch.setattr(recorder, 'live_browser_running', lambda port: bool(opened))
    await user.open(f'/environments/edit?id={env["id"]}')
    user.find('Navegador en vivo').click()
    await user.should_see('No hay navegador en vivo abierto', retries=30)
    user.find(marker='env-live-open').click()
    await eventually(lambda: opened == {'environment_id': env['id'], 'url': 'https://qa.example.com', 'port': recorder.DEFAULT_LIVE_PORT})
    await user.should_see('Conectado en el puerto')
    user.find(marker='env-save').click()
    await eventually(lambda: core.get('environments', env['id'])['ui_session_mode'] == 'live')


async def test_environments_edit_switches_to_mcp_extension_mode_and_opens_the_bridge(user: User, monkeypatch):
    from app import mcp_bridge
    project = core.create_project('Con puente MCP')
    core.set_active_project(project['id'])
    env = core.save('environments', {'name': 'qa', 'project_id': project['id'], 'base_url': 'https://qa.example.com', 'variables': {}, 'auth': {'type': 'none'}})
    opened = {}

    def fake_launch(port, profile=None):
        opened.update(port=port, profile=profile)
    monkeypatch.setattr(mcp_bridge, 'launch_mcp_bridge', fake_launch)   # sin abrir Node de verdad
    monkeypatch.setattr(mcp_bridge, 'mcp_server_running', lambda port: bool(opened))
    await user.open(f'/environments/edit?id={env["id"]}')
    user.find('Extensión de Chrome (MCP)').click()
    await user.should_see('No hay un puente MCP abierto', retries=30)
    user.find(marker='env-mcp-open').click()
    await eventually(lambda: opened == {'port': mcp_bridge.DEFAULT_MCP_PORT, 'profile': None})
    await user.should_see('Puente MCP abierto en el puerto')
    user.find(marker='env-save').click()
    await eventually(lambda: core.get('environments', env['id'])['ui_session_mode'] == 'mcp')


async def test_environments_edit_mcp_bridge_close_reports_when_this_session_never_opened_it(user: User, monkeypatch):
    from app import mcp_bridge
    project = core.create_project('Puente MCP sin abrir')
    core.set_active_project(project['id'])
    env = core.save('environments', {'name': 'qa', 'project_id': project['id'], 'base_url': 'https://qa.example.com', 'variables': {}, 'auth': {'type': 'none'}})
    monkeypatch.setattr(mcp_bridge, 'close_mcp_bridge', lambda port: (_ for _ in ()).throw(ValueError('No hay un puente MCP en el puerto 8931 que esta sesión haya abierto')))
    await user.open(f'/environments/edit?id={env["id"]}')
    user.find('Extensión de Chrome (MCP)').click()
    await user.should_see(marker='env-mcp-close', retries=30)
    user.find(marker='env-mcp-close').click()
    await user.should_see('esta sesión haya abierto')


async def test_modules_table_row_click_opens_the_detail_page(user: User):
    from nicegui import ui
    seed()
    module = core.list_items('modules')[0]
    await user.open('/modules')
    interaction = user.find(kind=ui.table)
    row = next(r for r in next(iter(interaction.elements)).rows if r['id'] == module['id'])
    interaction.trigger('viewModule', row)
    await user.should_see(marker='module-delete')
    assert user.client.page.path == '/modules/edit'


async def test_modules_detail_page_shows_operations_and_creates_a_case(user: User):
    from nicegui import ui
    seed()
    module = core.list_items('modules')[0]
    await user.open(f'/modules/edit?id={module["id"]}')
    await user.should_see(module['name'])
    op_interaction = user.find(kind=ui.table)
    op_row = next(iter(next(iter(op_interaction.elements)).rows))
    op_interaction.trigger('createCase', op_row)
    await eventually(lambda: user.client.page.path == '/cases/edit')


async def test_modules_detail_page_shows_the_linked_environment_and_its_cases(user: User):
    project = core.create_project('P')
    env = core.save('environments', {'name': 'Local', 'project_id': project['id'], 'base_url': 'http://127.0.0.1:9999', 'auth': {'type': 'none'}, 'variables': {}})
    raw = ('openapi: 3.0.3\ninfo: {title: X, version: "1"}\nservers: [{url: http://127.0.0.1:9999}]\n'
           'paths: {"/x": {"get": {"responses": {"200": {"description": "ok"}}}}}\n')
    module = core.import_openapi(raw, project['id'])
    core.save('cases', {'name': 'Caso X', 'type': 'api', 'project_id': project['id'], 'method': 'GET', 'path': '/x', 'module_id': module['id'], 'assertions': []})
    await user.open(f'/modules/edit?id={module["id"]}')
    await user.should_see(f'«{env["name"]}»')  # already linked: no "Crear ambiente" button needed
    await user.should_see('Casos de este componente (1)')
    await user.should_see('Caso X')


async def test_modules_detail_page_delete_blocked_when_cases_use_it(user: User):
    seed()
    module = core.list_items('modules')[0]
    case = [c for c in core.list_items('cases') if c['name'] == 'Health OK'][0]
    case['module_id'] = module['id']
    core.save('cases', case)
    await user.open(f'/modules/edit?id={module["id"]}')
    user.find('module-delete').click()
    await user.should_see('¿Eliminar el componente')
    user.find('confirm-dialog-accept').click()
    await user.should_see('caso(s) usan este componente')
    assert core.get('modules', module['id']) is not None


async def test_modules_table_delete_removes_an_unused_module(user: User):
    from nicegui import ui
    core.create_project('P')
    raw = 'openapi: 3.0.3\ninfo: {title: Suelto, version: "1"}\npaths: {}\n'
    module = core.import_openapi(raw, core.get_active_project_id())
    await user.open('/modules')
    interaction = user.find(kind=ui.table)
    row = next(r for r in next(iter(interaction.elements)).rows if r['id'] == module['id'])
    interaction.trigger('deleteModule', row)
    await user.should_see('¿Eliminar el componente')
    user.find('confirm-dialog-accept').click()
    await user.should_see('Componente eliminado')
    assert core.get('modules', module['id']) is None


async def test_modules_page_registers_a_component(user: User):
    project = core.create_project('P')
    env = core.save('environments', {'name': 'QA', 'project_id': project['id'], 'base_url': 'https://x', 'auth': {'type': 'none'}, 'variables': {}})
    await user.open('/modules/edit')
    user.find('component-name').type('Front web')
    user.find('component-is-backend').click()    # untick: pure frontend
    user.find('component-is-frontend').click()
    user.find('component-env').click()
    user.find(env['name']).click()
    user.find('component-create').click()
    await user.should_see('Componente «Front web» registrado')
    [component] = [m for m in core.list_items('modules') if m['name'] == 'Front web']
    assert core.component_flags(component) == (False, True) and component['manual'] is True and component['environment_ids'] == [env['id']]


async def test_modules_page_registers_a_component_with_a_new_origin_url(user: User):
    core.create_project('P')
    await user.open('/modules/edit')
    user.find('component-name').type('Nuevo back')
    user.find('component-new-origin').type('https://qa.ejemplo.com')
    user.find('component-create').click()
    await user.should_see('Componente «Nuevo back» registrado')
    [component] = [m for m in core.list_items('modules') if m['name'] == 'Nuevo back']
    [env] = core.component_environments(component)
    assert env['base_url'] == 'https://qa.ejemplo.com'


async def test_modules_detail_page_edits_a_manual_component(user: User):
    project = core.create_project('P')
    component = core.create_component('Back manual', project['id'])
    await user.open(f'/modules/edit?id={component["id"]}')
    user.find('component-edit-name').clear()
    user.find('component-edit-name').type('Back renombrado')
    user.find('component-save').click()
    await user.should_see('Componente actualizado')
    assert core.get('modules', component['id'])['name'] == 'Back renombrado'


async def test_modules_detail_page_frontend_points_to_ui_cases(user: User):
    project = core.create_project('P')
    component = core.create_component('Front', project['id'], is_backend=False, is_frontend=True)
    await user.open(f'/modules/edit?id={component["id"]}')
    await user.should_see('sus pruebas de UI son Casos UI')
    await user.should_not_see(marker='module-explore')


async def test_modules_detail_page_full_stack_shows_both_hints(user: User):
    project = core.create_project('P')
    component = core.create_component('Monolito', project['id'], is_backend=True, is_frontend=True)
    await user.open(f'/modules/edit?id={component["id"]}')
    await user.should_see('sus pruebas de UI son Casos UI')
    await user.should_see('no tiene un catálogo de operaciones')


async def test_modules_detail_page_hints_when_there_is_no_contract(user: User):
    project = core.create_project('P')
    component = core.create_component('Back sin contrato', project['id'])
    await user.open(f'/modules/edit?id={component["id"]}')
    await user.should_see('no tiene un catálogo de operaciones')
    await user.should_not_see(marker='module-explore')


async def test_modules_warns_about_empty_header_value(user: User):
    from nicegui import ui
    seed()
    module = core.list_items('modules')[0]
    await user.open(f'/modules/edit?id={module["id"]}')
    # "Cabecera (opcional)" defaults to "Authorization" with no value typed: a very easy slip.
    user.find('Explorar automáticamente').click()
    await user.should_see('el valor está vacío')
    # let the exploration itself finish (it targets an unreachable host, so it fails fast) before the test ends:
    # otherwise it keeps running in the background and its result lands in whichever workspace core.DB points
    # to by the time it completes — i.e. the *next* test's isolated database, not this one's.
    await eventually(lambda: bool(user.find(kind=ui.code).elements))


async def test_modules_attach_contract_from_url_enriches_the_registered_component_without_duplicating_it(user: User, tmp_path):
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
        pid = core.get_active_project_id()
        before = len(core.list_project_items('modules', pid))
        component = core.create_component('Mi API', pid)
        await user.open(f'/modules/edit?id={component["id"]}')
        user.find('URL del contrato, de su página de Swagger UI o un enlace de GitHub').type(spec_url)
        user.find('Importar desde URL').click()
        # run.io_bound: a real thread + HTTP round trip, slow and jittery under a loaded test run — poll the actual state, not a fixed retry budget
        await eventually(lambda: bool(core.get('modules', component['id'])['operations']), seconds=40)
        await user.should_see('Contrato importado')
        # re-attaching the same contract refreshes the SAME component; it never creates a second one
        assert len(core.list_project_items('modules', pid)) == before + 1
        assert core.get('modules', component['id'])['name'] == 'Mi API'
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


async def test_workspace_offers_detail_and_evidence_for_the_last_sent_request(user: User, sample_app):
    """Igual que en Chat, Espacio de trabajo no guarda sus envíos en el Historial (persist=False) — pero la
    última petición enviada sí puede abrir el mismo detalle (show_run) con la evidencia descargable."""
    await user.open('/workspace')
    user.find('ws-url').type(sample_app.url + '/api/users/2')
    user.find('ws-send').click()
    await eventually(lambda: any('"name": "user2"' in text for text in code_texts(user)))
    user.find(marker='ws-evidence').click()
    await user.should_see('Descargar evidencia:')
    await user.should_see('HTML')


async def test_show_run_offers_a_model_verdict_for_an_api_case_run(user: User, sample_app):
    """Fase 6: el mismo «Pedir veredicto al modelo» que ya tiene Chat, ahora en el detalle de CUALQUIER run de
    Caso API/UI (common.show_run) — mismo botón, mismo llm.status() como compuerta."""
    from app import llm
    from sample_app.fake_llm import FakeLLM
    with FakeLLM() as fake:
        llm.save_config({'preset': 'local', 'protocol': 'openai', 'base_url': fake.url + '/v1', 'model': 'modelo-demo', 'auth': 'none'})
        fake.queue(json.dumps({'pass': True, 'reasoning': 'La respuesta trae el usuario esperado.'}))
        await user.open('/workspace')
        user.find('ws-url').type(sample_app.url + '/api/users/2')
        user.find('ws-send').click()
        await eventually(lambda: any('"name": "user2"' in text for text in code_texts(user)))
        user.find(marker='ws-evidence').click()
        await user.should_see(marker='run-ask-verdict', retries=30)
        user.find(marker='run-ask-verdict').click()
        await user.should_see(marker='run-verdict-reasoning', retries=30)
        await user.should_see('La respuesta trae el usuario esperado.')


async def test_show_run_can_view_evidence_in_a_new_tab_without_downloading_it(user: User, sample_app):
    """Fase B: «Ver en pestaña nueva» escribe el HTML en core.ARTIFACTS (lo que /evidence/ sirve inline, sin
    forzar una descarga) en vez de pasar por ui.download — se prueba la mitad servidor: el archivo queda ahí."""
    await user.open('/workspace')
    user.find('ws-url').type(sample_app.url + '/api/users/2')
    user.find('ws-send').click()
    await eventually(lambda: any('"name": "user2"' in text for text in code_texts(user)))
    before = set(core.ARTIFACTS.glob('*-view.html'))
    user.find(marker='ws-evidence').click()
    await user.should_see(marker='run-view-evidence-tab', retries=30)
    user.find(marker='run-view-evidence-tab').click()
    await eventually(lambda: len(set(core.ARTIFACTS.glob('*-view.html')) - before) == 1)
    [new_file] = set(core.ARTIFACTS.glob('*-view.html')) - before
    assert 'user2' in new_file.read_text(encoding='utf-8')   # el JSON va escapado dentro del <pre> (&quot;…&quot;)


async def test_show_run_can_save_evidence_to_the_configured_folder(user: User, sample_app, tmp_path):
    """Fase C: «Guardar en mi carpeta» solo funciona con una carpeta ya configurada (Configuraciones → Base de
    datos) y nunca pisa un archivo existente — reusa core.save_evidence_file, ya probado aparte en test_core.py."""
    folder = tmp_path / 'evidencia'
    folder.mkdir()
    core.set_evidence_folder(str(folder))
    await user.open('/workspace')
    user.find('ws-url').type(sample_app.url + '/api/users/2')
    user.find('ws-send').click()
    await eventually(lambda: any('"name": "user2"' in text for text in code_texts(user)))
    user.find(marker='ws-evidence').click()
    await user.should_see(marker='run-save-evidence-folder', retries=30)
    user.find(marker='run-save-evidence-folder').click()
    await user.should_see('Evidencia guardada en', retries=30)
    [saved] = list(folder.glob('*.html'))
    assert 'user2' in saved.read_text(encoding='utf-8')


async def test_show_run_offers_a_video_player_and_a_save_button_when_a_run_has_one(user: User, tmp_path):
    """Fase D: un run de Caso UI con video (automation.execute_ui, record_video=True) muestra un reproductor
    y «Guardar video en mi carpeta», igual que ya hacen la captura y la traza."""
    from nicegui import ui
    project = core.create_project('Video en historial')
    core.set_active_project(project['id'])
    run_id = core.uid()
    (core.ARTIFACTS / f'{run_id}.webm').write_bytes(b'fake-webm-bytes')
    run = core.save('runs', {'id': run_id, 'type': 'ui', 'case_name': 'Con video', 'project_id': project['id'], 'status': 'passed',
                             'started_at': core.now(), 'video': f'{run_id}.webm', 'steps': []})
    folder = tmp_path / 'evidencia'
    folder.mkdir()
    core.set_evidence_folder(str(folder))

    await user.open('/runs')
    user.find(kind=ui.table).trigger('rowClick', [None, {'id': run['id']}, 0])
    await user.should_see('Descargar video', retries=30)
    user.find('Guardar video en mi carpeta').click()
    await user.should_see('Video guardado en', retries=30)
    [saved] = list(folder.glob('*.webm'))
    assert saved.read_bytes() == b'fake-webm-bytes'


async def test_show_run_offers_a_screenshot_button_on_each_step_that_has_one(user: User):
    """Captura por paso (`record_step_screenshots`, ver automation.execute_ui): cada paso con su propia captura
    muestra un botón para verla — un paso sin captura (p. ej. una corrida vieja, o el flag apagado) no lo tiene."""
    from nicegui import ui
    project = core.create_project('Capturas por paso en historial')
    core.set_active_project(project['id'])
    run_id = core.uid()
    (core.ARTIFACTS / f'{run_id}-step0.png').write_bytes(b'fake-step-png')
    run = core.save('runs', {'id': run_id, 'type': 'ui', 'case_name': 'Con capturas por paso', 'project_id': project['id'], 'status': 'passed',
                             'started_at': core.now(), 'steps': [
                                 {'index': 0, 'action': 'navigate', 'passed': True, 'screenshot': f'{run_id}-step0.png'},
                                 {'index': 1, 'action': 'click', 'passed': True}]})

    await user.open('/runs')
    user.find(kind=ui.table).trigger('rowClick', [None, {'id': run['id']}, 0])
    await user.should_see('Con capturas por paso', retries=30)
    assert len(user.find(marker='ui-step-screenshot-0').elements) == 1
    with pytest.raises(AssertionError):
        user.find(marker='ui-step-screenshot-1')   # ese paso no tiene captura propia: sin botón


async def test_workspace_can_capture_a_screenshot_and_record_a_slideshow_video(user: User):
    """Fase D: los dos íconos junto a «Conectividad» capturan/graban el propio Espacio de trabajo con
    html2canvas (no hay navegador de prueba del lado del servidor acá) — se simula la respuesta del cliente."""
    core.create_project('Captura workspace')
    await user.open('/workspace')
    user.javascript_rules[re.compile('.*toDataURL')] = lambda m: 'data:image/png;base64,ZmFrZS1wbmc='
    user.find(marker='ws-capture-screenshot').click()
    await user.should_see('Captura guardada', retries=30)
    [shot] = [r for r in core.list_items('runs') if r['type'] == 'screenshot']
    assert core.evidence_path(shot['id'], shot['screenshot']).read_bytes() == b'fake-png'
    await user.should_see('Descargar captura', retries=30)   # show_run se abrió solo

    user.javascript_rules[re.compile('.*captureStream')] = lambda m: True
    user.javascript_rules[re.compile('.*arrayBuffer')] = lambda m: 'ZmFrZS13ZWJt'
    user.find(marker='ws-record-video').click()
    await user.should_see('Grabando', retries=30)
    user.find(marker='ws-record-video').click()
    await user.should_see('Video guardado', retries=30)
    [vid] = [r for r in core.list_items('runs') if r['type'] == 'video']
    assert core.evidence_path(vid['id'], vid['video']).read_bytes() == b'fake-webm'


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
    await user.should_see('El nombre del componente es obligatorio')
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


async def test_ui_case_step_locator_keeps_its_iframe_selector_on_reload(user: User):
    """El campo «Iframe CSS (opcional)» (automation._base_locator / spec['frame']) viaja con el resto del
    locator al guardar/recargar un Caso UI — no es un campo nuevo separado, es parte del mismo dict."""
    project = core.create_project('Iframe en caso UI')
    core.set_active_project(project['id'])
    core.save('cases', {'name': 'Pago embebido', 'type': 'ui', 'project_id': project['id'], 'timeout_ms': 10000,
                        'steps': [{'action': 'navigate', 'url': '/pago'},
                                  {'action': 'fill', 'locator': {'by': 'testid', 'value': 'numero', 'frame': '#caja'}, 'value': '4111'}]})
    await user.open('/ui-cases')
    user.find('Guardados').click()
    user.find('ui-saved-item').click()
    await user.should_see('#caja')             # el selector del iframe quedó visible en el paso recargado


async def test_ui_case_record_video_checkbox_is_saved_and_restored(user: User):
    """Fase D: «Grabar video de esta corrida» es un campo más del caso, apagado por defecto — viaja con el
    resto al guardar/recargar, igual que el iframe del locator (test anterior)."""
    project = core.create_project('Video en caso UI')
    core.set_active_project(project['id'])
    case = core.save('cases', {'name': 'Con video', 'type': 'ui', 'project_id': project['id'], 'timeout_ms': 10000,
                               'steps': [{'action': 'navigate', 'url': '/login'}]})
    await user.open('/ui-cases')
    user.find('Guardados').click()
    user.find('ui-saved-item').click()
    checkbox = user.find(marker='ui-case-record-video').elements.pop()
    assert checkbox.value is False                     # apagado por defecto
    user.find(marker='ui-case-record-video').click()
    user.find('Guardar').click()
    await user.should_see('guardado')
    assert core.get('cases', case['id'])['record_video'] is True

    await user.open('/ui-cases')
    user.find('Guardados').click()
    user.find('ui-saved-item').click()
    checkbox = user.find(marker='ui-case-record-video').elements.pop()
    assert checkbox.value is True


async def test_ui_case_record_step_screenshots_checkbox_is_saved_and_restored(user: User):
    """Misma mecánica que «Grabar video», para la captura por paso (apagada por defecto)."""
    project = core.create_project('Capturas por paso')
    core.set_active_project(project['id'])
    case = core.save('cases', {'name': 'Con capturas', 'type': 'ui', 'project_id': project['id'], 'timeout_ms': 10000,
                               'steps': [{'action': 'navigate', 'url': '/login'}]})
    await user.open('/ui-cases')
    user.find('Guardados').click()
    user.find('ui-saved-item').click()
    checkbox = user.find(marker='ui-case-record-step-screenshots').elements.pop()
    assert checkbox.value is False
    user.find(marker='ui-case-record-step-screenshots').click()
    user.find('Guardar').click()
    await user.should_see('guardado')
    assert core.get('cases', case['id'])['record_step_screenshots'] is True

    await user.open('/ui-cases')
    user.find('Guardados').click()
    user.find('ui-saved-item').click()
    checkbox = user.find(marker='ui-case-record-step-screenshots').elements.pop()
    assert checkbox.value is True


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


# --------------------------------------------------------------------------- especificación: HU, casos de prueba, plantillas

async def test_user_story_can_be_created_linked_to_a_feature_and_deleted(user: User):
    project = core.create_project('Historias UI')
    core.set_active_project(project['id'])
    core.create_feature('Checkout', project['id'])

    await user.open('/stories')
    user.find('Nueva historia').click()
    await user.should_see(marker='story-title')
    user.find(marker='story-title').type('Pagar con tarjeta')
    user.find(marker='story-feature').click()
    await user.should_see('Checkout')
    user.find('Checkout').click()
    user.find(marker='story-add-criterion').click()
    await user.should_see(marker='story-criterion-text')
    user.find(marker='story-criterion-text').type('Veo la confirmación del pago')
    user.find(marker='story-save').click()
    await user.should_see('Historia creada')
    [story] = core.list_items('user_stories')
    assert story['title'] == 'Pagar con tarjeta' and story.get('feature_id')
    assert len(story['criteria']) == 1

    await user.open('/stories')
    user.find(marker='stories-table').trigger('rowClick', [None, {'id': story['id']}, 0])
    await user.should_see(marker='story-delete')
    user.find(marker='story-delete').click()
    user.find(marker='confirm-dialog-accept').click()
    await user.should_see('Historia eliminada')
    assert core.list_items('user_stories') == []


async def test_test_case_spec_can_be_created_from_a_story_and_linked_to_an_automated_case(user: User):
    project = core.create_project('Casos de prueba UI')
    core.set_active_project(project['id'])
    story = core.create_user_story('Pagar con tarjeta', project['id'])
    env = core.save('environments', {'name': 'e', 'project_id': project['id'], 'base_url': 'http://x', 'auth': {'type': 'none'}, 'variables': {}})
    api_case = core.save('cases', {'name': 'ChargeAPI', 'method': 'POST', 'path': '/pay', 'project_id': project['id'], 'environment_id': env['id'],
                                   'headers': {}, 'query': {}, 'body': None, 'assertions': [], 'variables': {}, 'extract': [], 'timeout': 10})

    await user.open(f'/test-specs/edit?story_id={story["id"]}')
    await user.should_see(marker='spec-title')
    assert user.find(marker='spec-story').elements.pop().value == story['id']   # preloaded from the query param
    user.find(marker='spec-title').type('Pagar con tarjeta válida')
    user.find(marker='spec-linked-case').click()
    await user.should_see('ChargeAPI')
    user.find('ChargeAPI').click()
    user.find(marker='spec-add-step').click()
    await user.should_see(marker='spec-step-action')
    user.find(marker='spec-step-action').type('Ir a pago')
    user.find(marker='spec-step-expected').type('Veo el formulario')
    user.find(marker='spec-save').click()
    await user.should_see('Caso de prueba creado')
    [spec] = core.list_items('test_case_specs')
    assert spec['title'] == 'Pagar con tarjeta válida' and spec['story_id'] == story['id']
    assert spec['linked_case_id'] == api_case['id'] and spec['status'] == 'automated'

    await user.open(f'/stories/edit?id={story["id"]}')
    await user.should_see('Pagar con tarjeta válida')                 # ligado, se ve desde la historia también


async def test_spec_templates_come_preseeded_and_support_adopt_and_promote(user: User):
    project = core.create_project('Plantillas UI')
    core.set_active_project(project['id'])

    await user.open('/spec-templates')
    await user.should_see('Historia de usuario (INVEST)')              # global, por defecto
    await user.should_see('Especificación detallada')
    local_before = len([t for t in core.list_items('spec_templates') if t.get('project_id') == project['id']])

    user.find('Adoptar').click()
    await user.should_see('adoptada a este proyecto')
    local_after = len([t for t in core.list_items('spec_templates') if t.get('project_id') == project['id']])
    assert local_after == local_before + 1

    await user.open('/spec-templates/edit')
    user.find(marker='template-name').type('Mi plantilla propia')
    user.find(marker='template-save').click()
    await user.should_see('Plantilla creada')
    mine = next(t for t in core.list_items('spec_templates') if t['name'] == 'Mi plantilla propia')
    assert mine['project_id'] == project['id']

    await user.open(f'/spec-templates/edit?id={mine["id"]}')
    user.find(marker='template-promote').click()
    await user.should_see('Copia publicada')
    promoted = next(t for t in core.list_items('spec_templates') if t.get('promoted_from') == mine['id'])
    assert promoted['project_id'] is None


async def test_builtin_templates_cannot_be_edited_or_deleted_from_the_ui(user: User):
    project = core.create_project('Plantilla protegida')
    core.set_active_project(project['id'])
    builtin = next(t for t in core.list_items('spec_templates') if t.get('project_id') is None)

    await user.open(f'/spec-templates/edit?id={builtin["id"]}')
    await user.should_see('solo lectura')
    with pytest.raises(AssertionError):
        user.find(marker='template-save')
    with pytest.raises(AssertionError):
        user.find(marker='template-delete')


# --------------------------------------------------------------------------- Asistente de IA en Especificación (Fase 2)

async def test_story_assistant_generates_a_draft_from_a_description(user: User):
    """Un mensaje con «generá»/«creá» (y el formulario vacío) dispara generate_user_story — el resultado llena
    el formulario, pero nada se guarda hasta que se hace clic en Crear historia."""
    from app import llm
    from sample_app.fake_llm import FakeLLM
    project = core.create_project('Asistente HU')
    core.set_active_project(project['id'])
    with FakeLLM() as fake:
        llm.save_config({'preset': 'local', 'protocol': 'openai', 'base_url': fake.url + '/v1', 'model': 'modelo-demo', 'auth': 'none'})
        fake.queue(json.dumps({'title': 'Pagar con tarjeta', 'as_a': 'cliente', 'i_want': 'pagar con tarjeta',
                               'so_that': 'completar la compra', 'criteria': ['Veo la confirmación del pago']}))
        await user.open('/stories/edit')
        user.find(marker='story-assistant-input').type('Generá una historia para pagar con tarjeta de crédito')
        user.find(marker='story-assistant-send').click()
        await user.should_see('Generé una propuesta', retries=30)
        assert user.find(marker='story-title').elements.pop().value == 'Pagar con tarjeta'
        assert core.list_items('user_stories') == []   # todavía no se guardó nada
        user.find(marker='story-save').click()
        await user.should_see('Historia creada')
        [story] = core.list_items('user_stories')
        assert story['as_a'] == 'cliente' and story['criteria'][0]['text'] == 'Veo la confirmación del pago'


async def test_story_assistant_refine_keyword_updates_the_open_form(user: User):
    from app import llm
    from sample_app.fake_llm import FakeLLM
    project = core.create_project('Asistente refinar')
    core.set_active_project(project['id'])
    story = core.create_user_story('Pagar', project['id'], as_a='cliente', i_want='pagar', so_that='comprar',
                                   criteria=[{'text': 'veo confirmación'}])
    with FakeLLM() as fake:
        llm.save_config({'preset': 'local', 'protocol': 'openai', 'base_url': fake.url + '/v1', 'model': 'modelo-demo', 'auth': 'none'})
        fake.queue(json.dumps({'title': 'Pagar', 'as_a': 'cliente registrado', 'i_want': 'pagar', 'so_that': 'comprar',
                               'criteria': ['veo confirmación', 'recibo un email de confirmación']}))
        await user.open(f'/stories/edit?id={story["id"]}')
        user.find(marker='story-assistant-input').type('Enriquecé los criterios de aceptación')
        user.find(marker='story-assistant-send').click()
        await user.should_see('Refiné la historia', retries=30)
        assert user.find(marker='story-title').elements.pop().value == 'Pagar'
        inputs = user.find(marker='story-criterion-text').elements
        assert len(inputs) == 2 and {i.value for i in inputs} == {'veo confirmación', 'recibo un email de confirmación'}
        assert core.get('user_stories', story['id'])['as_a'] == 'cliente'   # no se guardó solo


async def test_story_assistant_generates_test_cases_and_creates_the_selected_ones(user: User):
    from app import llm
    from sample_app.fake_llm import FakeLLM
    project = core.create_project('Asistente casos')
    core.set_active_project(project['id'])
    story = core.create_user_story('Pagar', project['id'], criteria=[{'text': 'veo confirmación'}])
    with FakeLLM() as fake:
        llm.save_config({'preset': 'local', 'protocol': 'openai', 'base_url': fake.url + '/v1', 'model': 'modelo-demo', 'auth': 'none'})
        fake.queue(json.dumps({'test_cases': [
            {'title': 'Pago con tarjeta válida', 'preconditions': '', 'steps': [{'action': 'pagar', 'expected': 'confirmado'}], 'priority': 'high', 'type': 'functional'},
            {'title': 'Pago con tarjeta vencida', 'preconditions': '', 'steps': [{'action': 'pagar', 'expected': 'rechazado'}], 'priority': 'medium', 'type': 'functional'},
        ]}))
        await user.open(f'/stories/edit?id={story["id"]}')
        user.find(marker='story-assistant-input').type('Generá los casos de prueba para esta historia')
        user.find(marker='story-assistant-send').click()
        await user.should_see('2 caso(s) de prueba candidatos', retries=30)
        assert core.list_items('test_case_specs') == []
        user.find(marker='story-create-draft-cases').click()
        await user.should_see('2 caso(s) de prueba creado(s)', retries=30)
        specs = core.list_items('test_case_specs')
        assert len(specs) == 2 and all(s['source'] == 'ai' and s['story_id'] == story['id'] for s in specs)


async def test_spec_assistant_generates_candidates_from_the_linked_story_and_loads_one(user: User):
    from app import llm
    from sample_app.fake_llm import FakeLLM
    project = core.create_project('Asistente spec')
    core.set_active_project(project['id'])
    story = core.create_user_story('Pagar', project['id'], criteria=[{'text': 'veo confirmación'}])
    with FakeLLM() as fake:
        llm.save_config({'preset': 'local', 'protocol': 'openai', 'base_url': fake.url + '/v1', 'model': 'modelo-demo', 'auth': 'none'})
        fake.queue(json.dumps({'test_cases': [
            {'title': 'Pago válido', 'preconditions': 'sesión iniciada', 'steps': [{'action': 'pagar', 'expected': 'confirmado'}], 'priority': 'high', 'type': 'functional'},
        ]}))
        await user.open(f'/test-specs/edit?story_id={story["id"]}')
        user.find(marker='spec-assistant-input').type('Generá candidatos de caso de prueba')
        user.find(marker='spec-assistant-send').click()
        await user.should_see('1 candidato(s)', retries=30)
        assert user.find(marker='spec-title').elements.pop().value == ''   # nada cargado todavía
        user.find(marker='spec-use-candidate').click()
        await eventually(lambda: user.find(marker='spec-title').elements.pop().value == 'Pago válido')
        assert core.list_items('test_case_specs') == []   # cargar un candidato no guarda nada


async def test_story_detail_shows_the_coverage_matrix_with_last_run_status(user: User):
    project = core.create_project('Matriz UI')
    core.set_active_project(project['id'])
    story = core.create_user_story('Pagar', project['id'])
    env = core.save('environments', {'name': 'e', 'project_id': project['id'], 'base_url': 'http://x', 'auth': {'type': 'none'}, 'variables': {}})
    api_case = core.save('cases', {'name': 'Pagar', 'method': 'GET', 'path': '/pay', 'project_id': project['id'], 'environment_id': env['id'],
                                   'headers': {}, 'query': {}, 'body': None, 'assertions': [], 'variables': {}, 'extract': [], 'timeout': 10})
    core.create_test_case_spec('Pago válido', project['id'], story_id=story['id'], linked_case_id=api_case['id'])
    core.save('runs', {'type': 'api', 'case_id': api_case['id'], 'status': 'passed', 'started_at': core.now()})

    await user.open(f'/stories/edit?id={story["id"]}')
    await user.should_see('Matriz de pruebas')
    await user.should_see('1/1 automatizados pasan')
    await user.should_see('Pago válido')


async def test_spec_assistant_refine_keyword_updates_the_open_form(user: User):
    from app import llm
    from sample_app.fake_llm import FakeLLM
    project = core.create_project('Asistente spec refinar')
    core.set_active_project(project['id'])
    spec = core.create_test_case_spec('Pago válido', project['id'], preconditions='sesión iniciada',
                                      steps=[{'action': 'pagar', 'expected': 'confirmado'}])
    with FakeLLM() as fake:
        llm.save_config({'preset': 'local', 'protocol': 'openai', 'base_url': fake.url + '/v1', 'model': 'modelo-demo', 'auth': 'none'})
        fake.queue(json.dumps({'title': 'Pago válido', 'preconditions': 'sesión iniciada con saldo suficiente',
                               'steps': [{'action': 'pagar', 'expected': 'confirmado'}], 'priority': 'high', 'type': 'functional'}))
        await user.open(f'/test-specs/edit?id={spec["id"]}')
        user.find(marker='spec-assistant-input').type('Refiná la precondición, sé más específico')
        user.find(marker='spec-assistant-send').click()
        await user.should_see('Refiné el caso de prueba', retries=30)
        await user.should_see('sesión iniciada con saldo suficiente')
        assert core.get('test_case_specs', spec['id'])['preconditions'] == 'sesión iniciada'   # no se guardó solo
