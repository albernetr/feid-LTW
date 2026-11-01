"""Shared layout and widgets for every page."""
import datetime as dt
import json
from contextlib import contextmanager
from nicegui import ui
from .. import core, automation

NAV = [
    ('Inicio', '/', 'home'), ('Resumen', '/resumen', 'monitor_heart'), ('Espacio de trabajo', '/workspace', 'space_dashboard'), ('Proyectos', '/projects', 'folder_open'),
    ('Módulos', '/module-groups', 'account_tree'), ('Componentes', '/modules', 'widgets'), ('Ambientes', '/environments', 'dns'),
    ('Casos API', '/cases', 'http'), ('Casos UI', '/ui-cases', 'web'), ('Funcionalidades', '/features', 'flag'),
    ('Suites', '/suites', 'playlist_play'), ('Observador', '/observer', 'visibility'), ('Programaciones', '/schedules', 'schedule'),
    ('Historial', '/runs', 'history'), ('Importar / Exportar', '/portable', 'swap_vert'),
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
    with drawer:
        for label, route, icon in NAV:
            selected = route == current
            ui.button(label, icon=icon, on_click=lambda r=route: ui.navigate.to(r)) \
                .props(f'flat align=left no-caps {"color=primary" if selected else "color=grey-8"}') \
                .classes('w-full' + (' bg-blue-50' if selected else ''))
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


def show_run(run):
    """Dialog with the full detail of a run (api / ui / suite)."""
    with ui.dialog() as dialog, ui.card().classes('w-[820px] max-w-full'):
        with ui.row().classes('items-center gap-3'):
            status_badge(run.get('status'))
            ui.label(run.get('case_name') or run.get('suite_name') or '').classes('text-lg font-semibold')
            ui.label(fmt_time(run.get('started_at'))).classes('text-gray-500 text-sm')
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
