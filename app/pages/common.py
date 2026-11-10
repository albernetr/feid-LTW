"""Shared layout and widgets for every page."""
import base64
import datetime as dt
import functools
import json
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from fastapi.responses import RedirectResponse
from nicegui import app, ui, run
from .. import core, automation, evidence_report, integrations, llm

NAV = [
    ('Inicio', '/', 'home'), ('Resumen', '/resumen', 'monitor_heart'), ('Espacio de trabajo', '/workspace', 'space_dashboard'), ('Proyectos', '/projects', 'folder_open'),
    ('Módulos', '/module-groups', 'account_tree'), ('Componentes', '/modules', 'widgets'), ('Ambientes', '/environments', 'dns'),
    ('Historias de usuario', '/stories', 'auto_stories'), ('Casos de prueba', '/test-specs', 'checklist'), ('Plantillas', '/spec-templates', 'description'),
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
    ('Especificación', 'auto_stories', ('/stories', '/test-specs', '/spec-templates')),
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

# Aire de "documento" (fondo suave + tarjetas tipo papel) — solo para frame(doc_style=True), hoy únicamente
# Historias de usuario / Casos de prueba / Plantillas, porque conceptualmente SON documentos de especificación.
# Inyectado por página (ui.add_head_html vuelve a renderizar en cada carga), nunca toca el resto de la app.
DOC_CSS = '''<style>
body{background:#f3f4f6}
.ltw-doc .q-card,.ltw-doc .q-table{border-radius:10px;box-shadow:0 1px 3px rgba(0,0,0,.07),0 1px 2px rgba(0,0,0,.04);border:1px solid #e9eaee;overflow:hidden}
.ltw-doc .q-card+.q-card{margin-top:4px}
.ltw-doc>.q-page-title,.ltw-doc .ltw-doc-title{font-size:26px;font-weight:700;letter-spacing:-.01em;margin-bottom:2px}
.ltw-doc .ltw-doc-subtitle{color:#6b7280;font-size:14px;margin-bottom:8px}
</style>'''

# Captura de pantalla y video «slideshow» del propio Chat/Espacio de trabajo (Fase D) — nunca Playwright (no hay
# navegador de prueba del lado del servidor para esas dos pantallas, es la UI misma de LTW), así que se hace en
# el cliente con html2canvas sobre el panel pedido. Cargado una sola vez acá, en el esqueleto compartido de
# página — no depende de qué pantalla lo necesite. «-pro»: el html2canvas original (1.4.1) no sabe parsear
# oklch() — el color que usa Tailwind/Quasar en esta misma pantalla — y tira la captura entera; el fork
# mantenido lo soporta, es reemplazo directo (mismo global `html2canvas`, confirmado probando ambos en vivo).
HTML2CANVAS_SCRIPT = '<script src="https://cdn.jsdelivr.net/npm/html2canvas-pro@2.6.3/dist/html2canvas-pro.min.js"></script>'


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


def remembered(key, default=False):
    """Preferencia (bool, str, lo que sea JSON-serializable) recordada por usuario (app.storage.user — a
    diferencia de app.storage.browser, que NiceGUI solo deja escribir durante la petición inicial de la página;
    después de esa respuesta queda de solo lectura, así que un botón clickeado ya con la página cargada nunca
    lograría persistir nada con `.browser`). Mismo try/except defensivo que ya usa frame() para la expansión de
    cada grupo de nav. Devuelve (valor, set_valor)."""
    try:
        layout = app.storage.user
    except Exception:
        layout = {}

    def set_value(value):
        try:
            layout[key] = value
        except Exception:
            pass

    return layout.get(key, default) if hasattr(layout, 'get') else default, set_value


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
def frame(title, current, wide=False, doc_style=False, full_width=False):
    """Page skeleton: header with active-project switcher, navigation drawer and content column.
    wide=True is for work screens: the menu collapses to icons (expands on hover) and the content uses the whole window.
    doc_style=True gives the content area a "documento" look (fondo suave, tarjetas tipo papel) — para pantallas
    que conceptualmente son documentos (Especificación), nunca por defecto: no afecta a ninguna otra pantalla.
    full_width=True da el mismo ancho-completo-sin-título-automático que ya da wide=True, pero sin el drawer
    mini-icono de las pantallas tipo Chat/Workspace — para pantallas que solo necesitan el ancho, no ese menú."""
    ui.colors(primary='#2563eb')
    ui.add_head_html(ARIA_SCRIPT)
    ui.add_head_html(HTML2CANVAS_SCRIPT)
    if doc_style:
        ui.add_head_html(DOC_CSS)
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
    if wide or full_width:
        with ui.column().classes('w-full gap-0 p-0'):
            yield
        return
    with ui.column().classes('w-full p-4 gap-4' + (' max-w-7xl mx-auto ltw-doc' if doc_style else ' max-w-6xl mx-auto')):
        ui.label(title).classes('ltw-doc-title text-2xl font-semibold' if doc_style else 'text-2xl font-semibold')
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
    raw = run_doc.get('case_name') or run_doc.get('suite_name') or run_doc.get('group_name') or run_doc.get('id') or 'evidencia'
    return re.sub(r'[\\/:*?"<>|]+', '_', raw).replace(' ', '_')


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


async def _download_evidence(run_doc, kind, llm_verdict=None):
    data = evidence_report.build_report_data(run_doc, llm_verdict=llm_verdict)
    content, _ = await render_evidence(data, kind)
    ui.download(content, f'{_evidence_stem(run_doc)}.{kind}')
    ui.notify('Evidencia generada', type='positive')


def open_evidence_in_new_tab(view_id, filename, client=None):
    """`ui.navigate.to(..., new_tab=True)` igual pasa por `Client.open`, que en el navegador real manda un mensaje
    al cliente para que abra la pestaña — pero bajo pruebas (NiceGUI testing) `new_tab` se ignora y el harness
    simula una navegación COMPLETA de página, que falla para una ruta como /evidence/ que no devuelve una página
    NiceGUI sino un archivo (FileResponse). `window.open` por JS logra lo mismo en el navegador real sin pasar
    por ese camino — fire-and-forget, no se espera respuesta, así que tampoco bloquea bajo pruebas. `client`
    (opcional, ver _run_js) evita la resolución de context.client cuando quien llama viene de «Hablale al
    Asistente», con un refresh previo en el mismo turno de por medio."""
    _run_js(client, f'window.open({json.dumps(f"/evidence/{view_id}/{filename}")}, "_blank")', 5.0)


async def _save_evidence_to_folder(run_doc, llm_verdict=None):
    """Guarda el HTML de evidencia en la carpeta configurada en Configuraciones → Base de datos (siempre a
    demanda, nunca sola al terminar una corrida) — core.save_evidence_file ya evita pisar un archivo existente."""
    data = evidence_report.build_report_data(run_doc, llm_verdict=llm_verdict)
    html = evidence_report.render_evidence_html(data)
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    target = core.save_evidence_file(f'{_evidence_stem(run_doc)}-{stamp}.html', html)
    ui.notify(f'Evidencia guardada en {target}', type='positive', multi_line=True)


async def _view_evidence_in_tab(run_doc, llm_verdict=None):
    """Escribe el HTML de evidencia en core.ARTIFACTS (servido por /evidence/) y lo abre en una pestaña nueva,
    sin pasar por una descarga — el run_id propio del caso identifica el archivo; un run no persistido (p. ej.
    desde el Chat) usa un id nuevo porque no hace falta que coincida con ninguna fila de 'runs'."""
    data = evidence_report.build_report_data(run_doc, llm_verdict=llm_verdict)
    html = evidence_report.render_evidence_html(data)
    view_id = run_doc.get('id') or core.uid()
    filename = f'{view_id}-view.html'
    (core.ARTIFACTS / filename).write_text(html, encoding='utf-8')
    open_evidence_in_new_tab(view_id, filename)


# --------------------------------------------------------------------------- capturas y video (Fase D): Chat y
# Espacio de trabajo no tienen un navegador de prueba propio del lado del servidor para grabar (son la UI misma
# de LTW) — se hace del lado del CLIENTE con html2canvas sobre el panel pedido. El video es un «slideshow»
# (fotos sucesivas sobre un <canvas> oculto, grabadas con MediaRecorder vía canvas.captureStream()) — nunca
# getDisplayMedia, así que no pide permiso de pantalla al navegador. Limitación real, no oculta: no es un video
# fluido, es una sucesión de capturas — se documenta así en el manual.

def _run_js(client, code, timeout):
    """`ui.run_javascript` resuelve el cliente «actual» a partir del slot activo de la tarea — si quien llama
    viene de «Hablale al Asistente», un refresh anterior en ese mismo turno (assistant_chat_view) ya dejó ese
    slot apuntando a un elemento borrado, y la resolución puede quedarse esperando para siempre (no es un error
    inmediato — `await client.connected()` nunca se cumple, y el timeout no lo cubre). `client`, si se pasa, es
    una referencia capturada ANTES de ese refresh (ver handle_assistant_message) y evita tener que resolverla
    de nuevo acá; sin ella (botón directo, sin refresh de por medio), se resuelve como siempre."""
    if client is not None:
        return client.run_javascript(code, timeout=timeout)
    return ui.run_javascript(code, timeout=timeout)


def notify_via_client(client, message, **options):
    """Mismo motivo que _run_js: `ui.notify` también resuelve el cliente «actual» vía context.client — con un
    slot ya viejo, ni siquiera el AVISO DE ERROR del propio guard() se llega a mostrar (las dos resoluciones
    fallan igual, en silencio). Replica lo mínimo de nicegui.functions.notify.notify con un cliente ya resuelto."""
    if client is None:
        ui.notify(message, **options)
        return
    arg_map = {'close_button': 'closeBtn', 'multi_line': 'multiLine'}
    payload = {arg_map.get(k, k): v for k, v in options.items() if v is not None}
    payload['message'] = str(message)
    client.outbox.enqueue_message('notify', payload, client.id)


async def capture_screenshot(selector, case_name, project_id=None, client=None):
    """Captura el panel que matchee `selector` (CSS) con html2canvas y la guarda como una corrida suelta tipo
    'screenshot' — show_run la muestra con _evidence(), sin pedirle veredicto (no es un Caso API/UI)."""
    data_url = await _run_js(client,
        'const el = document.querySelector(%s); if (!el) return null; '
        'const canvas = await html2canvas(el); return canvas.toDataURL("image/png");' % json.dumps(selector),
        15.0)
    if not data_url:
        raise ValueError('No se encontró el panel a capturar')
    content = base64.b64decode(data_url.split(',', 1)[1])
    run_id = core.uid()
    (core.ARTIFACTS / f'{run_id}.png').write_bytes(content)
    return core.save('runs', {'id': run_id, 'type': 'screenshot', 'case_name': case_name, 'project_id': project_id,
                              'status': 'passed', 'started_at': core.now(), 'screenshot': f'{run_id}.png'})


async def start_screen_recording(selector, client=None):
    """Arranca el «slideshow»: una captura por segundo sobre un <canvas> oculto, grabada con MediaRecorder. El
    estado (recorder, intervalo, canvas) queda en `window.__ltwVideo` — stop_screen_recording lo retoma más
    tarde, en otra llamada separada a run_javascript (misma página, el estado de JS sigue vivo entre medio)."""
    ok = await _run_js(client,
        'const el = document.querySelector(%s); if (!el) return false; '
        'if (window.__ltwVideo) return false; '
        'const w = el.offsetWidth || 800, h = el.offsetHeight || 600; '
        'const canvas = document.createElement("canvas"); canvas.width = w; canvas.height = h; '
        'const ctx = canvas.getContext("2d"); '
        'const stream = canvas.captureStream(2); '
        'const recorder = new MediaRecorder(stream, {mimeType: "video/webm"}); '
        'const chunks = []; '
        'recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); }; '
        'recorder.start(); '
        'const tick = async () => { try { '
        '  const shot = await html2canvas(el); ctx.clearRect(0, 0, w, h); ctx.drawImage(shot, 0, 0, w, h); '
        '} catch (e) {} }; '
        'tick(); '
        'const interval = setInterval(tick, 1000); '
        'window.__ltwVideo = {recorder, chunks, interval}; '
        'return true;' % json.dumps(selector), 15.0)
    if not ok:
        raise ValueError('No se encontró el panel a grabar, o ya había una grabación en curso')


async def stop_screen_recording(case_name, project_id=None, client=None):
    """Termina el «slideshow» en curso y guarda el .webm como corrida tipo 'video' — mismo tratamiento que
    capture_screenshot. ValueError claro si no había ninguna grabación arrancada."""
    b64 = await _run_js(client,
        'const state = window.__ltwVideo; if (!state) return null; '
        'clearInterval(state.interval); '
        'const blob = await new Promise((resolve) => { state.recorder.onstop = () => '
        '  resolve(new Blob(state.chunks, {type: "video/webm"})); state.recorder.stop(); }); '
        'delete window.__ltwVideo; '
        'const buf = await blob.arrayBuffer(); const bytes = new Uint8Array(buf); '
        'let binary = ""; for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]); '
        'return btoa(binary);', 20.0)
    if not b64:
        raise ValueError('No había ninguna grabación en curso')
    content = base64.b64decode(b64)
    run_id = core.uid()
    (core.ARTIFACTS / f'{run_id}.webm').write_bytes(content)
    return core.save('runs', {'id': run_id, 'type': 'video', 'case_name': case_name, 'project_id': project_id,
                              'status': 'passed', 'started_at': core.now(), 'video': f'{run_id}.webm'})


def _send_to_ticket_dialog(run_doc, llm_verdict=None):
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
            data = evidence_report.build_report_data(run_doc, llm_verdict=llm_verdict)
            content, content_type = await render_evidence(data, kind.value)
            integration = core.get('integrations', integ.value)
            await run.io_bound(integrations.attach_evidence, integration, f'{_evidence_stem(run_doc)}.{kind.value}', content, content_type, ticket_value)
            ui.notify('Evidencia enviada', type='positive')
            dialog.close()
        with ui.row().classes('gap-2 justify-end w-full'):
            ui.button('Cancelar', on_click=dialog.close).props('flat')
            ui.button('Enviar', icon='send', on_click=guard(send)).props('color=primary')
    dialog.open()


def _resolve_run_verdict_context(run_doc):
    """Única fuente de criterio hoy para un run suelto de Caso API/UI: la Funcionalidad ligada a la suite de la
    que este run es un paso (si la hay) — a diferencia de un caso de Chat, un caso API/UI no tiene su propio
    hu_text/feature_id. El resto lo infiere el propio prompt de llm.judge_run (nombre del caso, aserciones)."""
    suite_id = run_doc.get('suite_id')
    if suite_id:
        suite = core.get('suites', suite_id)
        feature_id = suite.get('feature_id') if suite else None
        if feature_id:
            feature = core.get('features', feature_id)
            if feature and (feature.get('description') or '').strip():
                return feature['description'].strip(), f'Funcionalidad «{feature["name"]}»'
    return '', 'inferido del caso y sus aserciones (sin Funcionalidad ligada)'


def show_run(run_doc):
    """Dialog with the full detail of a run (api / ui / suite)."""
    V = {'verdict': None, 'busy': False}   # veredicto del modelo (Fase 6) — vacío para suite/suite_group, que no piden uno propio
    with ui.dialog() as dialog, ui.card().classes('w-[820px] max-w-full'):
        with ui.row().classes('items-center gap-3'):
            status_badge(run_doc.get('status'))
            ui.label(run_doc.get('case_name') or run_doc.get('suite_name') or run_doc.get('group_name') or '').classes('text-lg font-semibold')
            ui.label(fmt_time(run_doc.get('started_at'))).classes('text-gray-500 text-sm')
        if run_doc.get('executed_by'):
            ui.label(f'Ejecutado por: {core.user_display_name(run_doc["executed_by"])}').classes('text-xs text-gray-500')
        if run_doc.get('error'):
            ui.label(run_doc['error']).classes('text-red-700 whitespace-pre-wrap')
        if run_doc.get('type') == 'suite':
            with ui.column().classes('w-full gap-1'):
                for entry in run_doc.get('case_runs', []):
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
        elif run_doc.get('type') == 'suite_group':
            with ui.column().classes('w-full gap-1'):
                for entry in run_doc.get('item_runs', []):
                    with ui.row().classes('items-center gap-2'):
                        status_badge(entry['status'])
                        ui.badge('Flujo' if entry['type'] == 'flow' else 'Caso', color='deep-orange' if entry['type'] == 'flow' else 'primary').classes('text-xs')
                        ui.label(entry.get('name') or entry['id'][:8])
                        if entry.get('error'):
                            ui.label(entry['error']).classes('text-red-700 text-sm')
                        if entry.get('run_id') and core.get('runs', entry['run_id']):
                            ui.button('Ver detalle', on_click=lambda _, r=entry['run_id']: show_run(core.get('runs', r))).props('flat dense')
        elif run_doc.get('type') == 'ui':
            for step in run_doc.get('steps', []):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('check_circle' if step.get('passed') else 'cancel', color='positive' if step.get('passed') else 'negative')
                    label = automation.STEP_ACTIONS.get(step['action'], {}).get('label', step['action'])
                    ui.label(f'{step["index"] + 1}. {label}')
                    if step.get('screenshot'):
                        ui.button(icon='photo', on_click=lambda _, rid=run_doc['id'], f=step['screenshot']: open_evidence_in_new_tab(rid, f)) \
                            .props('flat round dense size=sm').mark(f'ui-step-screenshot-{step["index"]}').tooltip('Ver captura de este paso')
            _evidence(run_doc)
        elif run_doc.get('type') in ('screenshot', 'video'):
            # Capturas/video del propio Chat o Espacio de trabajo (Fase D) — no son una corrida de Caso API/UI,
            # así que no tienen request/aserciones/steps ni tiene sentido pedirles un veredicto: solo la media.
            _evidence(run_doc)
        else:
            ui.label(f'HTTP {run_doc.get("http_status", "—")} · {run_doc.get("duration_ms", "—")} ms').classes('text-gray-600')
            if run_doc.get('request'):
                ui.label(f'{run_doc["request"]["method"]} {run_doc["request"]["url"]}').classes('font-mono text-sm')
                for line in run_doc.get('enriched') or []:
                    ui.label('✎ ' + line).classes('text-sm text-blue-800')
                sent = run_doc['request']
                if sent.get('body') is not None or sent.get('query'):
                    with ui.expansion('Petición enviada (lo que salió)').classes('w-full'):
                        if sent.get('query'):
                            ui.code(json.dumps(sent['query'], indent=2, ensure_ascii=False), language='json').classes('w-full')
                        if sent.get('body') is not None:
                            ui.code(json.dumps(sent['body'], indent=2, ensure_ascii=False) if not isinstance(sent['body'], str) else sent['body'], language='json').classes('w-full')
            for item in run_doc.get('assertions', []):
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
            if run_doc.get('extracted'):
                ui.label('Variables extraídas: ' + ', '.join(run_doc['extracted'])).classes('text-sm text-gray-600')
            if run_doc.get('status') in ('failed', 'error') and core.get('runs', run_doc['id']):
                ui.button('Brief para agente', icon='smart_toy', on_click=guard(lambda: agent_brief(run_doc['id']))).props('outline dense no-caps').tooltip('Fallo con todo el contexto, listo para que un agente vaya al código')
            if run_doc.get('response'):
                with ui.expansion('Respuesta').classes('w-full'):
                    ui.code(run_doc['response'].get('body', '')[:5000], language='json').classes('w-full')
        if run_doc.get('type') in ('api', 'ui'):
            # Veredicto con argumento (Fase 6): mismo mecanismo que ya usa Chat (llm.judge_conversation), pero
            # sobre UN run de Caso API/UI (llm.judge_run) — no aplica a una fila de suite/grupo (listas de
            # sub-runs, cada uno con su propio «Ver detalle» para pedirlo ahí) ni a una captura/video sueltos.
            context_text, context_source = _resolve_run_verdict_context(run_doc)

            async def ask_verdict():
                V['busy'] = True
                verdict_view.refresh()
                try:
                    V['verdict'] = await run.io_bound(llm.judge_run, run_doc, context_text)
                except llm.LLMError as exc:
                    ui.notify(str(exc), type='negative', multi_line=True)
                finally:
                    V['busy'] = False
                    verdict_view.refresh()

            @ui.refreshable
            def verdict_view():
                state = llm.status()
                ui.label(f'Criterio del veredicto: {context_source}').classes('text-xs text-gray-500')
                if V['verdict']:
                    icon, color = ('check_circle', 'positive') if V['verdict']['pass'] else ('cancel', 'negative')
                    with ui.row().classes('items-center gap-2'):
                        ui.icon(icon, color=color)
                        ui.label('Pasa' if V['verdict']['pass'] else 'No pasa').classes('font-medium')
                    ui.label(V['verdict']['reasoning']).classes('text-sm text-gray-700').mark('run-verdict-reasoning')
                ui.button('Pedir veredicto al modelo', icon='psychology', on_click=guard(ask_verdict)) \
                    .props('flat dense no-caps').mark('run-ask-verdict').set_enabled(state['ready'] and not V['busy'])
                if not state['ready']:
                    ui.label(state['problem']).classes('text-xs text-gray-500')
            verdict_view()
        if run_doc.get('id') and run_doc.get('type') not in ('screenshot', 'video'):   # no exige que esté persistida: build_report_data/_download_evidence solo leen el dict (p. ej. Chat, que nunca guarda en Historial)
            with ui.row().classes('items-center gap-2'):
                ui.label('Descargar evidencia:').classes('text-sm text-gray-600')
                ui.button('Ver en pestaña nueva', icon='open_in_new', on_click=guard(lambda: _view_evidence_in_tab(run_doc, V['verdict']))).props('flat dense no-caps').mark('run-view-evidence-tab')
                ui.button('Guardar en mi carpeta', icon='folder', on_click=guard(lambda: _save_evidence_to_folder(run_doc, V['verdict']))).props('flat dense no-caps').mark('run-save-evidence-folder')
                ui.button('HTML', icon='download', on_click=guard(lambda: _download_evidence(run_doc, 'html', V['verdict']))).props('flat dense no-caps')
                ui.button('PDF', icon='picture_as_pdf', on_click=guard(lambda: _download_evidence(run_doc, 'pdf', V['verdict']))).props('flat dense no-caps')
                ui.button('Word', icon='description', on_click=guard(lambda: _download_evidence(run_doc, 'docx', V['verdict']))).props('flat dense no-caps')
                ui.button('Markdown', icon='code', on_click=guard(lambda: _download_evidence(run_doc, 'md', V['verdict']))).props('flat dense no-caps')
                ui.button('Enviar a Jira/Azure DevOps', icon='send', on_click=guard(lambda: _send_to_ticket_dialog(run_doc, V['verdict']))).props('flat dense no-caps')
        with ui.row().classes('justify-end w-full'):
            ui.button('Cerrar', on_click=dialog.close).props('flat')
    dialog.open()


def _evidence(run):
    for key, label, icon in (('screenshot', 'Descargar captura', 'image'), ('trace', 'Descargar traza (Playwright)', 'timeline'),
                              ('video', 'Descargar video', 'videocam')):
        if run.get(key):
            def download(_, k=key):
                try:
                    ui.download(core.evidence_path(run['id'], run[k]))
                except (ValueError, FileNotFoundError) as exc:
                    ui.notify(str(exc), type='warning')
            ui.button(label, icon=icon, on_click=download).props('flat dense')
            if key == 'video':
                def save_video_to_folder(_, k=key):
                    try:
                        content = core.evidence_path(run['id'], run[k]).read_bytes()
                        target = core.save_evidence_file(f'{_evidence_stem(run)}.webm', content)
                        ui.notify(f'Video guardado en {target}', type='positive', multi_line=True)
                    except (ValueError, FileNotFoundError) as exc:
                        ui.notify(str(exc), type='warning')
                ui.button('Guardar video en mi carpeta', icon='folder', on_click=save_video_to_folder).props('flat dense')
    if run.get('screenshot'):
        ui.image(f'/evidence/{run["id"]}/{run["screenshot"]}').classes('w-full border')
    if run.get('video'):
        ui.video(f'/evidence/{run["id"]}/{run["video"]}').classes('w-full border')
