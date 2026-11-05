"""Shared layout and widgets for every page."""
import datetime as dt
import functools
import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from fastapi.responses import RedirectResponse
from nicegui import app, ui, run
from .. import core, automation, evidence_report, integrations

NAV = [
    ('Inicio', '/', 'home'), ('Resumen', '/resumen', 'monitor_heart'), ('Espacio de trabajo', '/workspace', 'space_dashboard'), ('Proyectos', '/projects', 'folder_open'),
    ('Módulos', '/module-groups', 'account_tree'), ('Componentes', '/modules', 'widgets'), ('Ambientes', '/environments', 'dns'),
    ('Casos API', '/cases', 'http'), ('Casos UI', '/ui-cases', 'web'), ('Funcionalidades', '/features', 'flag'),
    ('Flujos', '/suites', 'playlist_play'), ('Suites', '/suite-groups', 'folder_special'), ('Chat', '/chat', 'forum'), ('Observador', '/observer', 'visibility'), ('Programaciones', '/schedules', 'schedule'),
    ('Modelos de IA', '/models', 'smart_toy'), ('Variables y secuencias', '/sequences', 'numbers'), ('Conjuntos de datos', '/datasets', 'dataset'),
    ('Integraciones', '/integrations', 'extension'),
    ('Historial', '/runs', 'history'), ('Importar / Exportar', '/portable', 'swap_vert'),
    ('Base de datos', '/storage', 'storage'),
]
# Agrupa el menú (ya son ~20 opciones) en secciones desplegables/replegables — NAV sigue siendo la lista plana
# y autoritativa (test_manual.py la recorre tal cual); esto solo decide cómo se presenta en el drawer.
NAV_GROUPS = [
    ('Proyecto', 'folder_open', ('/projects', '/module-groups', '/modules', '/environments')),
    ('Pruebas', 'science', ('/cases', '/ui-cases', '/features', '/suites', '/suite-groups', '/chat')),
    ('Automatización', 'smart_toy', ('/observer', '/schedules', '/sequences', '/datasets', '/integrations')),
    ('Resultados', 'history', ('/runs', '/portable')),
    ('Configuraciones', 'settings', ('/models', '/storage')),
]
STATUS_COLOR = {'passed': 'positive', 'failed': 'negative', 'error': 'warning', 'cancelled': 'grey', 'skipped': 'grey'}
STATUS_LABEL = {'passed': 'Pasó', 'failed': 'Falló', 'error': 'Error', 'cancelled': 'Cancelada', 'skipped': 'Omitido'}


ICON_LABELS = {'delete': 'Eliminar', 'edit': 'Editar', 'play_arrow': 'Ejecutar', 'content_copy': 'Duplicar', 'arrow_upward': 'Subir',
               'arrow_downward': 'Bajar', 'close': 'Quitar', 'menu': 'Mostrar u ocultar el menú', 'add': 'Agregar'}
ARIA_SCRIPT = """<script>
(function(){const L=%s;
function fix(){document.querySelectorAll('button.q-btn:not([aria-label])').forEach(b=>{
 const i=b.querySelector('.q-icon'); if(i&&!b.querySelector('.q-btn__content > .block')){const n=i.textContent.trim(); b.setAttribute('aria-label',L[n]||n);}});}
new MutationObserver(fix).observe(document.documentElement,{childList:true,subtree:true});document.addEventListener('DOMContentLoaded',fix);})();
</script>""" % json.dumps(ICON_LABELS)


MINI_CSS = '''<style>
.q-drawer--mini .q-btn__content .block{font-size:0 !important;width:0 !important;height:0 !important;overflow:hidden !important} /* Tailwind's !important .block wins over display:none */
.q-drawer--mini .q-btn__content{justify-content:center !important}
.q-drawer--mini .q-btn__content .q-icon{margin:0 !important}
.ltw-pane{height:100%;overflow:auto} .q-splitter__separator{background:#e5e7eb}
.ltw-pane .q-tab-panel{min-width:0} .ltw-pane pre{white-space:pre-wrap !important;word-break:break-word}
.ltw-pane .nicegui-code{max-width:100%}
</style>'''


def current_user():
    """El usuario logueado en ESTE navegador (app.storage.user: sesión por navegador, cifrada con
    storage_secret) — None si nadie entró todavía. Mismo try/except defensivo que ya usa app.storage.browser."""
    try:
        uid = app.storage.user.get('user_id')
    except Exception:
        uid = None
    return core.get('users', uid) if uid else None


def current_user_id():
    return (current_user() or {}).get('id')


def login(user):
    app.storage.user['user_id'] = user['id']


def logout():
    app.storage.user.clear()
    ui.navigate.to('/login')


def protected_page(route, **kwargs):
    """Como ui.page(route), pero redirige a /login si nadie inició sesión — toda pantalla de la app usa esto en
    vez de ui.page directamente, así nadie puede olvidarse de proteger una ruta nueva."""
    def decorator(func):
        @ui.page(route, **kwargs)
        @functools.wraps(func)
        def wrapper(*args, **kw):
            if not current_user():
                return RedirectResponse('/login')
            return func(*args, **kw)
        return wrapper
    return decorator


@contextmanager
def frame(title, current, wide=False):
    """Page skeleton: header with active-project switcher, navigation drawer and content column.
    wide=True is for work screens: the menu collapses to icons (expands on hover) and the content uses the whole window."""
    ui.colors(primary='#2563eb')
    ui.add_head_html(ARIA_SCRIPT)
    ui.page_title(f'{title} · Local Test Workspace')
    drawer = ui.left_drawer(value=True, bordered=True).classes('bg-gray-50 pt-4')
    if wide:
        ui.add_head_html(MINI_CSS)
        drawer.props('mini mini-to-overlay mini-width=64 width=240')
        drawer.on('mouseenter', lambda: drawer.props(remove='mini'))
        drawer.on('mouseleave', lambda: drawer.props('mini'))
    with ui.header(elevated=False).classes('bg-white text-gray-800 border-b items-center gap-3 px-4'):
        ui.button(icon='menu', on_click=drawer.toggle).props('flat round dense').tooltip('Mostrar u ocultar el menú')
        ui.label('Local Test Workspace').classes('text-lg font-semibold')
        ui.space()
        projects = core.list_items('projects')
        active = core.get_active_project_id()
        if projects:
            def switch(e):
                try:
                    core.set_active_project(e.value)
                    ui.navigate.reload()
                except Exception as exc:
                    ui.notify(str(exc) or type(exc).__name__, type='negative', multi_line=True)
            selectable = {p['id']: p['name'] for p in projects if not p.get('disabled')}
            if selectable:
                ui.select(selectable, value=active, label='Proyecto activo', on_change=switch) \
                    .props('outlined dense options-dense').classes('w-60').tooltip('Todo lo que ves y creas pertenece a este proyecto')
            else:
                ui.button('Todos los proyectos están deshabilitados', icon='warning', on_click=lambda: ui.navigate.to('/projects')) \
                    .props('flat dense color=warning no-caps').tooltip('Habilita alguno en Proyectos para poder seleccionarlo')
        else:
            ui.button('Crear primer proyecto', icon='add', on_click=lambda: ui.navigate.to('/projects')).props('color=primary dense')
        user = current_user()
        if user:
            label = f'{user.get("first_name", "")} {user.get("last_name", "")}'.strip() or user.get('email', '')
            with ui.button(label, icon='account_circle').props('flat dense no-caps color=grey-8'):
                with ui.menu():
                    ui.menu_item('Gestionar usuarios', on_click=lambda: ui.navigate.to('/users'))
                    ui.menu_item('Cerrar sesión', on_click=logout)
    def nav_button(label, route, icon, extra=''):
        selected = route == current
        ui.button(label, icon=icon, on_click=lambda r=route: ui.navigate.to(r)) \
            .props(f'flat align=left no-caps {"color=primary" if selected else "color=grey-8"}') \
            .classes('w-full' + extra + (' bg-blue-50' if selected else ''))
    with drawer:
        # Mismo menú agrupado para todas las pantallas, sean «wide» (mini, colapsable) o no — antes una pantalla
        # wide mostraba las ~20 opciones sueltas sin agrupar, distinto del resto de la app (ver menú lateral).
        grouped_routes = {route for _, _, routes in NAV_GROUPS for route in routes}
        for label, route, icon in NAV:
            if route not in grouped_routes:
                nav_button(label, route, icon)
        try:
            layout = app.storage.browser
        except Exception:
            layout = {}
        for name, group_icon, routes in NAV_GROUPS:
            items = [item for item in NAV if item[1] in routes]
            has_current = any(route == current for _, route, _ in items)
            key = f'nav_group_{name}'
            stored = layout.get(key) if hasattr(layout, 'get') else None
            with ui.expansion(name, icon=group_icon, value=has_current if stored is None else bool(stored)) \
                    .props('dense').classes('w-full') as section:
                def remember(e, k=key):
                    try:
                        layout[k] = e.value
                    except Exception:
                        pass
                section.on_value_change(remember)
                for label, route, icon in items:
                    nav_button(label, route, icon, ' pl-2')
    if wide:
        with ui.column().classes('w-full gap-0 p-0'):
            yield
        return
    with ui.column().classes('w-full max-w-6xl mx-auto p-4 gap-4'):
        ui.label(title).classes('text-2xl font-semibold')
        yield


def active_project_id():
    return core.get_active_project_id()


def require_project(message='Primero crea y selecciona un proyecto.'):
    """Shows a call to action and returns False when there is no active project."""
    if active_project_id() and core.get('projects', active_project_id()):
        return True
    with ui.card().classes('bg-amber-50'):
        ui.label(message)
        ui.button('Ir a Proyectos', icon='folder_open', on_click=lambda: ui.navigate.to('/projects')).props('color=primary')
    return False


def guard(func):
    """Wraps a click handler so exceptions become a toast instead of a silent failure."""
    async def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            if hasattr(result, '__await__'):
                result = await result
            return result
        except Exception as exc:
            ui.notify(str(exc) or type(exc).__name__, type='negative', multi_line=True)
    return wrapper


def confirm(message, on_yes, confirm_label='Eliminar'):
    with ui.dialog() as dialog, ui.card():
        ui.label(message)
        with ui.row().classes('justify-end w-full'):
            ui.button('Cancelar', on_click=dialog.close).props('flat')

            async def accept():
                dialog.close()
                await guard(on_yes)()
            ui.button(confirm_label, on_click=accept, color='negative').mark('confirm-dialog-accept')
    dialog.open()


def confirm_with_phrase(message, phrase, on_yes, confirm_label='Confirmar'):
    """Como confirm(), pero para una acción de más impacto: hay que escribir `phrase` exactamente para
    habilitar el botón — mismo patrón ya usado por «Reiniciar workspace» (app/pages/portable.py)."""
    with ui.dialog() as dialog, ui.card():
        ui.label(message).classes('font-semibold text-red-700')
        ui.label(f'Escribe {phrase} para confirmar.').classes('text-sm text-gray-600')
        typed = ui.input(label='Confirmación').props('outlined dense').mark('confirm-phrase-input')
        with ui.row().classes('justify-end w-full gap-2'):
            ui.button('Cancelar', on_click=dialog.close).props('flat')

            async def accept():
                if typed.value != phrase:
                    ui.notify(f'Escribe exactamente {phrase} para confirmar.', type='warning')
                    return
                dialog.close()
                await guard(on_yes)()
            ui.button(confirm_label, on_click=accept, color='negative').mark('confirm-phrase-accept')
    dialog.open()


def team_config_card():
    """Tarjeta «Exportar / importar configuración del equipo»: junta modelos de IA (con su clave) y la conexión
    a base de datos (con su contraseña) en un solo archivo cifrado — lo único que no puede vivir en git pero
    que todo el equipo necesita igual. Se muestra tanto en /models como en /storage para que sea visible desde
    cualquiera de las dos pantallas de «Configuraciones»."""
    from .. import team_config
    with ui.card().classes('w-full'):
        ui.label('Exportar / importar configuración del equipo').classes('text-lg font-semibold')
        ui.label('Junta en un solo archivo cifrado los modelos de IA (con su clave) y la conexión a base de '
                 'datos (con su contraseña) — lo que no puede ir a git pero el equipo necesita igual. '
                 'Comparte la frase de cifrado por un canal distinto del archivo (nunca en el mismo correo/chat).').classes('text-sm text-gray-500')
        with ui.row().classes('w-full gap-8 flex-wrap'):
            with ui.column().classes('gap-2'):
                ui.label('Exportar').classes('font-semibold')
                exp_models = ui.checkbox('Modelos de IA', value=True).mark('team-config-export-models')
                exp_db = ui.checkbox('Base de datos', value=True).mark('team-config-export-db')
                exp_phrase = ui.input('Frase de cifrado', password=True, password_toggle_button=True) \
                    .props('outlined dense').classes('w-64').mark('team-config-export-phrase')

                def do_export():
                    phrase = (exp_phrase.value or '').strip()
                    if not phrase:
                        raise ValueError('Indica una frase para cifrar el archivo')
                    data = team_config.export_encrypted(phrase, include_db=exp_db.value, include_models=exp_models.value)
                    ui.download(data, 'ltw-config-equipo.json')
                    ui.notify('Archivo descargado. Comparte la frase por un canal aparte (no en el mismo correo/chat).',
                             type='positive', multi_line=True)
                ui.button('Exportar', icon='download', on_click=guard(do_export)).props('color=primary').mark('team-config-export-submit')

            with ui.column().classes('gap-2'):
                ui.label('Importar').classes('font-semibold')
                pending = {}

                async def on_upload(event):
                    pending['data'] = await read_upload(event)
                    ui.notify('Archivo cargado. Escribe la frase y pulsa Importar.', type='positive')
                ui.upload(label='Elige el archivo', on_upload=on_upload, auto_upload=True) \
                    .props('accept=.json flat bordered').classes('w-64').mark('team-config-import-upload')
                imp_phrase = ui.input('Frase de cifrado', password=True, password_toggle_button=True) \
                    .props('outlined dense').classes('w-64').mark('team-config-import-phrase')

                def do_import():
                    if 'data' not in pending:
                        raise ValueError('Primero elige el archivo exportado por tu equipo')
                    phrase = (imp_phrase.value or '').strip()
                    if not phrase:
                        raise ValueError('Indica la frase que se usó para exportarlo')
                    summary = team_config.import_encrypted(pending['data'], phrase)
                    parts = []
                    if summary['db']:
                        parts.append('conexión de base de datos guardada')
                    if summary['models_imported']:
                        parts.append(f'{summary["models_imported"]} modelo(s) de IA importado(s)')
                    for skipped in summary['models_skipped']:
                        ui.notify(f'Se omitió el modelo «{skipped["name"]}»: {skipped["reason"]}', type='warning', multi_line=True)
                    ui.notify('Importado: ' + (', '.join(parts) if parts else 'nada nuevo') + '. Nada se activó solo.',
                             type='positive', multi_line=True)
                ui.button('Importar', icon='upload', on_click=guard(do_import)).props('outline').mark('team-config-import-submit')


def status_badge(status):
    return ui.badge(STATUS_LABEL.get(status, status), color=STATUS_COLOR.get(status, 'grey'))


def fmt_time(iso):
    if not iso:
        return '—'
    try:
        return dt.datetime.fromisoformat(iso).astimezone().strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        return iso


def empty_state(message, button=None):
    with ui.card().classes('w-full items-center py-8 bg-gray-50'):
        ui.icon('inbox', size='lg').classes('text-gray-400')
        ui.label(message).classes('text-gray-600')
        if button:
            button()


def parse_value(text):
    """Visual editor values: '5' -> 5, 'true' -> True, '"x"' -> 'x', anything else stays text."""
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def show_value(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


async def read_upload(event):
    """Reads an uploaded file with the NiceGUI 3 API."""
    return await event.file.read()


# --------------------------------------------------------------------------- key/value editor

def kv_editor(state, key_label='Nombre', value_label='Valor'):
    """Visual editor for a dict[str, str]; `state` is mutated in place."""
    @ui.refreshable
    def rows():
        for key in list(state):
            with ui.row().classes('w-full items-center gap-2 no-wrap'):
                name = ui.input(key_label, value=key).props('outlined dense').classes('w-48')
                value = ui.input(value_label, value=str(state[key])).props('outlined dense').classes('grow')

                def rename(_, old=key, widget=name):
                    new = (widget.value or '').strip()
                    if new and new != old and new not in state:
                        state[new] = state.pop(old)

                name.on('blur', rename)
                value.on_value_change(lambda e, w=name: state.__setitem__((w.value or '').strip(), e.value) if (w.value or '').strip() else None)
                ui.button(icon='delete', on_click=lambda _, k=key: (state.pop(k, None), rows.refresh())).props('flat round dense color=negative').tooltip('Quitar')
        ui.button('Agregar', icon='add', on_click=lambda: (state.setdefault(f'nuevo_{len(state) + 1}', ''), rows.refresh())).props('flat dense color=primary')
    rows()
    return rows


# --------------------------------------------------------------------------- run details

def agent_brief(run_id):
    """Dialog with the failure of a stored run as an agent-ready brief (ltw.failure/1)."""
    from .. import agent
    failure = agent.failure_for_run_id(run_id)
    with ui.dialog() as dialog, ui.card().classes('w-[860px] max-w-full'):
        ui.label('Brief para agente').classes('text-lg font-semibold')
        ui.label(f'{failure["title"]} · diagnóstico (heurístico): {failure["diagnosis"]["category"]}').classes('text-sm text-gray-600')
        ui.code(failure['brief_markdown'], language='markdown').classes('w-full').style('max-height:58vh;overflow:auto')
        with ui.row().classes('gap-2'):
            ui.button('Copiar Markdown', icon='content_copy', on_click=lambda: (ui.clipboard.write(failure['brief_markdown']), ui.notify('Brief copiado', type='positive'))).props('color=primary no-caps')
            ui.button('Descargar failure.json', icon='download', on_click=lambda: ui.download(json.dumps(failure, indent=2, ensure_ascii=False).encode('utf-8'), 'failure.ltw.json')).props('outline no-caps')
            ui.button('Cerrar', on_click=dialog.close).props('flat')
    dialog.open()


CONTENT_TYPES = {'html': 'text/html', 'pdf': 'application/pdf', 'md': 'text/markdown',
                 'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}


def _evidence_stem(run_doc):
    return (run_doc.get('case_name') or run_doc.get('suite_name') or run_doc.get('group_name') or run_doc.get('id') or 'evidencia').replace(' ', '_')


async def render_evidence(data, kind):
    """Devuelve (bytes, content_type) en el formato pedido — mismo contenido en los tres, reusado tanto para
    descargar como para enviar a un ticket (y, desde otras páginas como Chat, para un reporte de varias corridas
    sueltas armado a mano con evidence_report.build_multi_report_data)."""
    if kind == 'pdf':
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'r.pdf'
            await run.io_bound(evidence_report.render_evidence_pdf, evidence_report.render_evidence_html(data), target)
            return target.read_bytes(), CONTENT_TYPES['pdf']
    if kind == 'docx':
        return await run.io_bound(evidence_report.render_evidence_docx, data), CONTENT_TYPES['docx']
    if kind == 'md':
        return evidence_report.render_evidence_markdown(data).encode('utf-8'), CONTENT_TYPES['md']
    return evidence_report.render_evidence_html(data).encode('utf-8'), CONTENT_TYPES['html']


async def _download_evidence(run_doc, kind):
    data = evidence_report.build_report_data(run_doc)
    content, _ = await render_evidence(data, kind)
    ui.download(content, f'{_evidence_stem(run_doc)}.{kind}')
    ui.notify('Evidencia generada', type='positive')


def _send_to_ticket_dialog(run_doc):
    pid = core.get_active_project_id()
    items = core.list_project_items('integrations', pid) if pid else []
    if not items:
        ui.notify('No hay integraciones configuradas. Ve a «Integraciones» para agregar una.', type='warning')
        return
    with ui.dialog() as dialog, ui.card().classes('w-96'):
        ui.label('Enviar evidencia a un ticket').classes('text-lg font-semibold')
        integ = ui.select({i['id']: f'{i["name"]} ({core.INTEGRATION_PLATFORMS.get(i["platform"], i["platform"])})' for i in items},
                          value=items[0]['id'], label='Integración').props('outlined dense').classes('w-full')
        ticket = ui.input('Ticket (Jira, p. ej. PROJ-123) o work item (Azure DevOps)').props('outlined dense').classes('w-full')
        kind = ui.select({'pdf': 'PDF', 'html': 'HTML', 'docx': 'Word', 'md': 'Markdown'}, value='pdf', label='Formato').props('outlined dense').classes('w-full')

        async def send():
            ticket_value = (ticket.value or '').strip()
            if not ticket_value:
                raise ValueError('Indica el ticket o work item de destino')
            data = evidence_report.build_report_data(run_doc)
            content, content_type = await render_evidence(data, kind.value)
            integration = core.get('integrations', integ.value)
            await run.io_bound(integrations.attach_evidence, integration, f'{_evidence_stem(run_doc)}.{kind.value}', content, content_type, ticket_value)
            ui.notify('Evidencia enviada', type='positive')
            dialog.close()
        with ui.row().classes('gap-2 justify-end w-full'):
            ui.button('Cancelar', on_click=dialog.close).props('flat')
            ui.button('Enviar', icon='send', on_click=guard(send)).props('color=primary')
    dialog.open()


def show_run(run):
    """Dialog with the full detail of a run (api / ui / suite)."""
    with ui.dialog() as dialog, ui.card().classes('w-[820px] max-w-full'):
        with ui.row().classes('items-center gap-3'):
            status_badge(run.get('status'))
            ui.label(run.get('case_name') or run.get('suite_name') or run.get('group_name') or '').classes('text-lg font-semibold')
            ui.label(fmt_time(run.get('started_at'))).classes('text-gray-500 text-sm')
        if run.get('executed_by'):
            ui.label(f'Ejecutado por: {core.user_display_name(run["executed_by"])}').classes('text-xs text-gray-500')
        if run.get('error'):
            ui.label(run['error']).classes('text-red-700 whitespace-pre-wrap')
        if run.get('type') == 'suite':
            with ui.column().classes('w-full gap-1'):
                for entry in run.get('case_runs', []):
                    with ui.row().classes('items-center gap-2'):
                        status_badge(entry['status'])
                        ui.label((entry.get('alias') + ' · ' if entry.get('alias') else '') + (entry.get('case_name') or entry['case_id'][:8])
                                 + (f' ({entry["environment"]})' if entry.get('environment') else ''))
                        if entry.get('attempts', 1) > 1:
                            ui.label(f'({entry["attempts"]} intentos)').classes('text-gray-500 text-sm')
                        if entry.get('error'):
                            ui.label(entry['error']).classes('text-red-700 text-sm')
                        if entry.get('run_id') and core.get('runs', entry['run_id']):
                            ui.button('Ver detalle', on_click=lambda _, r=entry['run_id']: show_run(core.get('runs', r))).props('flat dense')
        elif run.get('type') == 'suite_group':
            with ui.column().classes('w-full gap-1'):
                for entry in run.get('item_runs', []):
                    with ui.row().classes('items-center gap-2'):
                        status_badge(entry['status'])
                        ui.badge('Flujo' if entry['type'] == 'flow' else 'Caso', color='deep-orange' if entry['type'] == 'flow' else 'primary').classes('text-xs')
                        ui.label(entry.get('name') or entry['id'][:8])
                        if entry.get('error'):
                            ui.label(entry['error']).classes('text-red-700 text-sm')
                        if entry.get('run_id') and core.get('runs', entry['run_id']):
                            ui.button('Ver detalle', on_click=lambda _, r=entry['run_id']: show_run(core.get('runs', r))).props('flat dense')
        elif run.get('type') == 'ui':
            for step in run.get('steps', []):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('check_circle' if step.get('passed') else 'cancel', color='positive' if step.get('passed') else 'negative')
                    label = automation.STEP_ACTIONS.get(step['action'], {}).get('label', step['action'])
                    ui.label(f'{step["index"] + 1}. {label}')
            _evidence(run)
        else:
            ui.label(f'HTTP {run.get("http_status", "—")} · {run.get("duration_ms", "—")} ms').classes('text-gray-600')
            if run.get('request'):
                ui.label(f'{run["request"]["method"]} {run["request"]["url"]}').classes('font-mono text-sm')
                for line in run.get('enriched') or []:
                    ui.label('✎ ' + line).classes('text-sm text-blue-800')
                sent = run['request']
                if sent.get('body') is not None or sent.get('query'):
                    with ui.expansion('Petición enviada (lo que salió)').classes('w-full'):
                        if sent.get('query'):
                            ui.code(json.dumps(sent['query'], indent=2, ensure_ascii=False), language='json').classes('w-full')
                        if sent.get('body') is not None:
                            ui.code(json.dumps(sent['body'], indent=2, ensure_ascii=False) if not isinstance(sent['body'], str) else sent['body'], language='json').classes('w-full')
            for item in run.get('assertions', []):
                rule = item['rule']
                spec = core.ASSERTION_TYPES.get(rule.get('type'), {})
                with ui.row().classes('items-start gap-2 no-wrap'):
                    ui.icon('check_circle' if item['passed'] else 'cancel', color='positive' if item['passed'] else 'negative')
                    detail = ' '.join(str(show_value(rule[k]))[:80] for k in ('path', 'name', 'expected') if rule.get(k) not in (None, ''))
                    ui.label(f'{spec.get("label", rule.get("type"))} {detail}').classes('text-sm')
                    if not item['passed']:
                        actual = item['actual']
                        shown = chr(10).join(actual) if isinstance(actual, list) and all(isinstance(x, str) for x in actual) else show_value(actual)
                        ui.label(f'→ {shown[:400]}').classes('text-sm text-red-700 whitespace-pre-wrap')
            if run.get('extracted'):
                ui.label('Variables extraídas: ' + ', '.join(run['extracted'])).classes('text-sm text-gray-600')
            if run.get('status') in ('failed', 'error') and core.get('runs', run['id']):
                ui.button('Brief para agente', icon='smart_toy', on_click=guard(lambda: agent_brief(run['id']))).props('outline dense no-caps').tooltip('Fallo con todo el contexto, listo para que un agente vaya al código')
            if run.get('response'):
                with ui.expansion('Respuesta').classes('w-full'):
                    ui.code(run['response'].get('body', '')[:5000], language='json').classes('w-full')
        if run.get('id'):   # no exige que esté persistida: build_report_data/_download_evidence solo leen el dict (p. ej. Chat, que nunca guarda en Historial)
            with ui.row().classes('items-center gap-2'):
                ui.label('Descargar evidencia:').classes('text-sm text-gray-600')
                ui.button('HTML', icon='download', on_click=guard(lambda: _download_evidence(run, 'html'))).props('flat dense no-caps')
                ui.button('PDF', icon='picture_as_pdf', on_click=guard(lambda: _download_evidence(run, 'pdf'))).props('flat dense no-caps')
                ui.button('Word', icon='description', on_click=guard(lambda: _download_evidence(run, 'docx'))).props('flat dense no-caps')
                ui.button('Markdown', icon='code', on_click=guard(lambda: _download_evidence(run, 'md'))).props('flat dense no-caps')
                ui.button('Enviar a Jira/Azure DevOps', icon='send', on_click=guard(lambda: _send_to_ticket_dialog(run))).props('flat dense no-caps')
        with ui.row().classes('justify-end w-full'):
            ui.button('Cerrar', on_click=dialog.close).props('flat')
    dialog.open()


def _evidence(run):
    for key, label, icon in (('screenshot', 'Descargar captura', 'image'), ('trace', 'Descargar traza (Playwright)', 'timeline')):
        if run.get(key):
            def download(_, k=key):
                try:
                    ui.download(core.evidence_path(run['id'], run[k]))
                except (ValueError, FileNotFoundError) as exc:
                    ui.notify(str(exc), type='warning')
            ui.button(label, icon=icon, on_click=download).props('flat dense')
    if run.get('screenshot'):
        ui.image(f'/evidence/{run["id"]}/{run["screenshot"]}').classes('w-full border')
