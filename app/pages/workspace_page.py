"""Workspace: history | request + response | inspector. Everything editable without leaving the screen."""
import datetime as dt
import json
import os
from nicegui import app, ui, run
from .. import core, workspace as ws, agent, llm
from .common import frame, guard, confirm, fmt_time, protected_page
from .suites import run_suite
from .widgets import kv_rows, assertion_rows, method_badge, status_chip

HTTP_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']
MODES = {'panel': 'Las pruebas del panel «Pruebas»', 'exact': 'Respuesta exacta (ignorando campos volátiles)', 'structure': 'Solo estructura (JSON Schema)', 'status': 'Solo código HTTP'}
HEADER_SUGGESTIONS = (('+ Content-Type', 'Content-Type', 'application/json'), ('+ Accept', 'Accept', 'application/json'), ('+ Bearer', 'Authorization', 'Bearer {{secret:TOKEN}}'))
NEW = '__new__'


def pretty(text):
    try:
        return json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return text or ''


def day_label(iso):
    try:
        moment = dt.datetime.fromisoformat(iso).astimezone()
    except ValueError:
        return iso
    today = dt.datetime.now().astimezone().date()
    if moment.date() == today:
        return 'Hoy'
    return 'Ayer' if (today - moment.date()).days == 1 else moment.strftime('%d/%m/%Y')


def short_target(key):
    """'GET http://host:8765/api/users/1' -> ('/api/users/1', 'host:8765')"""
    try:
        _, url = (key or '').split(' ', 1)
        parts = url.split('/', 3)
        return '/' + (parts[3] if len(parts) > 3 else ''), parts[2] if len(parts) > 2 else ''
    except ValueError:
        return key or '', ''


@protected_page('/lab')
def lab_redirect():
    ui.navigate.to('/workspace')


@protected_page('/workspace')
def workspace_page(case: str = '', method: str = '', path: str = '', environment: str = '', module: str = ''):
    with frame('Espacio de trabajo', '/workspace', wide=True):
        build(preset_case_id=case, prefill=(method, path, environment, module) if not case and method else None)


def build(preset_case_id=None, prefill=None):
    projects_by_id = {p['id']: p['name'] for p in core.list_items('projects')}
    all_envs = [e for e in core.list_items('environments') if e.get('name')]  # tolerant of a malformed record missing even the name
    active_project = core.get_active_project_id()
    d = ws.new_draft()
    S = {'result': None, 'run': None, 'entry': None, 'previous': None, 'resp_tab': 'Cuerpo', 'view': 'Texto', 'conn': None, 'mine': True, 'q': '',
         'volatile': [], 'batch_rows': [{'name': 'fila 1', 'values': {}}], 'batch': {}, 'recording': None, 'spec_text': ''}
    W = {}
    try:
        layout = app.storage.browser
    except Exception:
        layout = {}

    # ------------------------------------------------------------ helpers
    def results_list():
        return (S['result'] or {}).get('assertions', [])

    def refresh_all():
        for name in ('headers_view', 'query_view', 'vars_view', 'tests_view', 'source_view', 'response_view', 'chips_view', 'history_view', 'batch_view', 'agent_view', 'llm_view', 'body_status'):
            if name in W:
                W[name].refresh()
        if 'body' in W:
            W['body'].set_value(d['body'])

    def load_draft(new, result=None, entry=None):
        d.clear()
        d.update(new)
        S.update(result=result, run=None, entry=entry, previous=ws.previous_result(d, entry['id'] if entry else None) if result else None, conn=None, resp_tab='Cuerpo',
                 batch={}, batch_rows=[{'name': 'fila 1', 'values': {}}])      # batch results belong to the request that produced them
        refresh_all()

    def project_options():
        return {**projects_by_id, NEW: '➕ Crear proyecto nuevo…'}

    def refresh_suites(*_):
        options = {'': 'No agregar a un flujo existente'}
        if W['dest_project'].value and W['dest_project'].value != NEW:
            options.update({s['id']: s['name'] for s in core.list_project_items('suites', W['dest_project'].value)})
        W['dest_suite'].set_options(options, value='')

    def resolve_project():
        if W['dest_project'].value == NEW:
            project = core.create_project((W['new_project'].value or '').strip())
            projects_by_id[project['id']] = project['name']
            W['dest_project'].set_options(project_options(), value=project['id'])
            W['new_project'].set_value('')
            return project['id']
        if not W['dest_project'].value:
            raise ValueError('Elige el proyecto destino o crea uno nuevo (pestaña Guardar)')
        return W['dest_project'].value

    def persistent_env(project_id, env):
        if d['env_id']:
            return core.environment_for_project(core.get('environments', d['env_id']), project_id)
        return core.ensure_environment_for_url(project_id, env['base_url'] + '/')[0]

    # ------------------------------------------------------------ actions
    async def send():
        case, env = ws.build_case(d)
        W['send'].props('loading')
        try:
            run_doc = await run.io_bound(core.execute_api, case, env, None, False)
        finally:
            W['send'].props(remove='loading')
        previous = ws.previous_result(d)
        entry = ws.record_history(d, run_doc)
        S.update(result=entry['result'], run=run_doc, entry=entry, previous=previous, conn=None)
        try:
            S['volatile'] = core.suggest_volatile_paths(json.loads(run_doc['response']['body']))
        except (KeyError, TypeError, ValueError):
            S['volatile'] = []
        for key in ('ignore', 'gen_ignore'):
            if W.get(key) is not None and not W[key].value:
                W[key].set_value(', '.join(S['volatile']))
        refresh_all()

    async def probe_connectivity():
        env, path = ws.resolve_target(d)
        target = env['base_url'] + path
        S['conn'] = await run.io_bound(core.check_connectivity, target)
        S['resp_tab'] = 'Conectividad'
        W['response_view'].refresh()

    def copy_curl():
        case, env = ws.build_case(d)
        ui.clipboard.write(agent.curl_command(case['method'], env['base_url'].rstrip('/') + case['path'], case['headers'], case['body'], case['query']))
        ui.notify('Comando curl copiado', type='positive')

    def response_paths():
        result = S.get('result')
        if not result or result.get('status') == 'error':
            return []
        try:
            return core.json_paths(json.loads(result['body']))
        except (KeyError, TypeError, ValueError):
            return []

    def autogenerate(mode, ignore_text):
        result = S['result']
        if not result or result.get('status') == 'error':
            raise ValueError('Primero envía una petición que obtenga respuesta')
        paths = [p.strip() for p in (ignore_text or '').split(',') if p.strip()]
        d['assertions'] = core.snapshot_assertions(result['http_status'], result['body'], mode, paths)
        W['tests_view'].refresh()
        ui.notify(f'{len(d["assertions"])} prueba(s) generadas desde la respuesta', type='positive')

    def save_case():
        result = S['result']
        mode = W['mode'].value
        if mode == 'panel':
            rules = d['assertions']
        else:
            if not result or result.get('status') == 'error':
                raise ValueError('Para generar las pruebas necesito una respuesta: envía la petición primero (o elige «Las pruebas del panel»)')
            paths = [p.strip() for p in (W['ignore'].value or '').split(',') if p.strip()]
            rules = core.snapshot_assertions(result['http_status'], result['body'], mode, paths)
        if not rules:
            raise ValueError('No hay pruebas: agrégalas en «Pruebas» o elige otro modo')
        definition, env = ws.build_case(d, (W['case_name'].value or d['name'] or '').strip() or None, rules)
        source = d.get('source') or {}
        if source.get('type') == 'case' and W['update_existing'].value:
            current = core.get('cases', source['id'])
            if current is None:
                raise ValueError('El caso original ya no existe: guarda como nuevo')
            saved = core.save('cases', {**current, **definition, 'id': current['id'], 'project_id': current.get('project_id')}, expected_updated_at=source.get('updated_at'))
            source['updated_at'] = saved['updated_at']
            W['source_view'].refresh()
            ui.notify(f'Caso «{saved["name"]}» actualizado', type='positive')
            return
        project_id = resolve_project()
        env_doc = persistent_env(project_id, env)
        if W['dest_suite'].value:
            core.check_suite_origin(W['dest_suite'].value, env_doc['base_url'])
        saved = core.save('cases', {**definition, 'project_id': project_id, 'environment_id': env_doc['id']})
        note = ''
        if W['dest_suite'].value:
            note = f' y agregado al flujo «{core.add_cases_to_suite(W["dest_suite"].value, [saved["id"]])["name"]}»'
        d['source'] = {'type': 'case', 'id': saved['id'], 'updated_at': saved['updated_at']}
        refresh_suites()
        for name in ('source_view', 'saved_view'):
            if name in W:
                W[name].refresh()
        ui.notify(f'Caso «{saved["name"]}» guardado en el proyecto «{projects_by_id[project_id]}»{note}', type='positive', multi_line=True)

    def spec_validate_and_load(text, import_all):
        try:
            spec = json.loads(text)
        except ValueError as exc:
            raise ValueError(f'No es JSON válido: {exc}')
        result = agent.validate_spec(spec)
        W['spec_out'].clear()
        with W['spec_out']:
            for e in result['errors']:
                ui.label(f'✗ {e["path"]}: {e["message"]}').classes('text-sm text-red-700')
            for w in result['warnings']:
                ui.label(f'⚠ {w["path"]}: {w["message"]}').classes('text-sm text-amber-700')
            if result['valid']:
                ui.label('✓ Especificación válida').classes('text-sm text-green-800')
        if not result['valid']:
            return
        if import_all:
            project_id = resolve_project()
            imported = agent.import_spec(spec, project_id)
            ui.notify(f'Importado: {len(imported["cases"])} caso(s), {len(imported["suites"])} suite(s), {len(imported["environments"])} ambiente(s)', type='positive')
            for name in ('saved_view',):
                W[name].refresh()
        else:
            environment = next((e for e in spec.get('environments', []) if e['name'] == (spec['cases'][0].get('environment') or spec.get('default_environment') or spec['environments'][0]['name'])), None) if spec.get('environments') else None
            load_draft(ws.draft_from_spec_case(spec['cases'][0], environment))
            ui.notify('Primer caso cargado en el editor', type='positive')

    # ------------------------------------------------------------ left pane
    def left():
        with ui.tabs().props('dense align=justify').classes('w-full') as tabs:
            t_hist = ui.tab('Historial', icon='history')
            t_saved = ui.tab('Guardados', icon='bookmarks')
        with ui.tab_panels(tabs, value=t_hist).classes('w-full'):
            with ui.tab_panel(t_hist).classes('p-2'):
                with ui.row().classes('w-full items-center gap-1 no-wrap'):
                    ui.input(placeholder='Buscar').props('outlined dense clearable').classes('grow') \
                        .on_value_change(lambda e: (S.__setitem__('q', e.value or ''), W['history_view'].refresh())).mark('ws-search')
                    ui.switch(value=True, on_change=lambda e: (S.__setitem__('mine', e.value), W['history_view'].refresh())).props('dense').tooltip('Solo mis peticiones')

                @ui.refreshable
                def history_view():
                    entries = ws.list_history(S['mine'], S['q'])
                    if not entries:
                        ui.label('Aquí aparecerán tus peticiones.').classes('text-gray-500 text-sm p-2')
                    last = None
                    for entry in entries:
                        label = day_label(entry['at'])
                        if label != last:
                            ui.label(label).classes('text-xs text-gray-500 uppercase mt-2')
                            last = label
                        path, host = short_target(entry.get('key'))
                        selected = (S['entry'] or {}).get('id') == entry['id']
                        row = ui.row().classes('items-center w-full no-wrap gap-1 cursor-pointer px-1 rounded hover:bg-gray-100' + (' bg-blue-50' if selected else ''))
                        row.on('click', lambda _, e=entry: load_history(e))
                        row.mark('ws-history-item')
                        with row:
                            method_badge(entry['draft']['method'])
                            with ui.column().classes('gap-0 grow').style('min-width:0'):
                                ui.label(entry.get('name') or path).classes('text-sm truncate').style('max-width:100%')
                                ui.label(f'{path if entry.get("name") else host}' + ('' if S['mine'] else f' · {entry["author"]}')).classes('text-xs text-gray-500 truncate').style('max-width:100%')
                            res = entry['result']
                            status_chip(res.get('http_status'), res.get('status') == 'error')
                            ui.button(icon='star' if entry.get('starred') else 'star_border', color='amber' if entry.get('starred') else 'grey') \
                                .props('flat round dense size=sm').on('click.stop', lambda _, e=entry: (ws.toggle_star(e['id']), W['history_view'].refresh()))
                    if entries:
                        ui.button('Limpiar historial', icon='delete_sweep', on_click=lambda: confirm('Se borran tus peticiones del historial (las marcadas con estrella se conservan).',
                                                                                                    lambda: (ws.clear_history(S['mine']), W['history_view'].refresh()), 'Limpiar')).props('flat dense size=sm color=grey')
                W['history_view'] = history_view
                history_view()

            with ui.tab_panel(t_saved).classes('p-2'):
                @ui.refreshable
                def saved_view():
                    pid = core.get_active_project_id()
                    if not pid:
                        ui.label('Sin proyecto activo: crea o elige uno para ver lo guardado.').classes('text-gray-500 text-sm')
                        return
                    suites = core.list_project_items('suites', pid)
                    all_cases = core.list_project_items('cases', pid)
                    ui.label('Flujos').classes('text-xs text-gray-500 uppercase')
                    for suite in suites:
                        with ui.row().classes('items-center w-full no-wrap gap-1'):
                            ui.icon('playlist_play', color='primary', size='sm')
                            ui.label(suite['name']).classes('text-sm grow truncate')
                            ui.button(icon='play_arrow', on_click=guard(lambda s=suite: run_suite(s))).props('flat round dense size=sm color=positive')
                    if not suites:
                        ui.label('—').classes('text-gray-400 text-sm')
                    ui.label('Casos (API y UI)').classes('text-xs text-gray-500 uppercase mt-2')
                    for case in all_cases:
                        row = ui.row().classes('items-center w-full no-wrap gap-1 cursor-pointer px-1 rounded hover:bg-gray-100').mark(f'ws-saved-{case["id"]}')
                        if case.get('type') == 'ui':
                            row.on('click', lambda _, c=case: ui.navigate.to(f'/ui-cases?id={c["id"]}'))
                        else:
                            row.on('click', lambda _, c=case: load_case(c))
                        with row:
                            method_badge(case.get('method', '')) if case.get('type') != 'ui' else ui.icon('web', color='primary', size='sm')
                            ui.label(case['name']).classes('text-sm grow truncate')
                            if case.get('type') == 'ui':
                                ui.icon('open_in_new', size='xs', color='grey').tooltip('Se edita en Casos UI')
                    if not all_cases:
                        ui.label('—').classes('text-gray-400 text-sm')
                W['saved_view'] = saved_view
                saved_view()

    def load_history(entry):
        load_draft(ws.draft_from_history(entry), entry['result'], entry)

    def load_case(case):
        env_id = case.get('environment_id') or ''
        if env_id and core.get('environments', env_id) is None:
            env_id = ''
        if not env_id:
            envs = core.list_project_items('environments', case.get('project_id'))
            env_id = envs[0]['id'] if len(envs) == 1 else ''
        load_draft(ws.draft_from_case(case, env_id))
        if not env_id:
            ui.notify('Elige el ambiente donde quieres ejecutar este caso', type='info')

    # ------------------------------------------------------------ center pane
    def center():
        with ui.column().classes('w-full h-full no-wrap gap-0'):
            with ui.row().classes('w-full items-center gap-2 no-wrap px-3 pt-2'):
                ui.input(placeholder='Petición sin nombre').props('borderless dense').classes('text-lg font-medium grow').bind_value(d, 'name').mark('ws-name')

                @ui.refreshable
                def source_view():
                    src = d.get('source') or {}
                    if src.get('type') == 'case':
                        ui.badge('Caso guardado', color='primary').tooltip('Estás editando un caso guardado; «Guardar» puede actualizarlo')
                    elif src.get('type') == 'history':
                        ui.badge('Del historial', color='grey')
                W['source_view'] = source_view
                source_view()
                ui.button(icon='note_add', on_click=lambda: load_draft(ws.new_draft())).props('flat round dense').tooltip('Nueva petición')
                ui.button('Conectividad', icon='network_check', on_click=guard(probe_connectivity)).props('flat dense no-caps').tooltip('Probar conectividad de esta URL (DNS/TCP/TLS/HTTP)')
                ui.button(icon='terminal', on_click=guard(copy_curl)).props('flat round dense').tooltip('Copiar como curl')
            with ui.row().classes('w-full items-center gap-2 no-wrap px-3'):
                W['env'] = ui.select({'': 'URL completa', **{e['id']: f'{projects_by_id.get(e.get("project_id"), "sin proyecto")} · {e["name"]}' for e in all_envs}},
                                     label='Ambiente').props('outlined dense options-dense').classes('w-40').bind_value(d, 'env_id')
                ui.select(HTTP_METHODS, label='Método').props('outlined dense').classes('w-24').bind_value(d, 'method')
                scheme = ui.select(['https', 'http'], label='Proto.').props('outlined dense').classes('w-20').bind_value(d, 'scheme')
                scheme.bind_visibility_from(d, 'env_id', backward=lambda v: not v)
                url = ui.input(placeholder='ejemplo.com/api/recurso  ·  admite {{variables}}  ·  Ctrl+Enter para enviar').props('outlined dense').classes('grow').bind_value(d, 'url').mark('ws-url')

                def follow(event):
                    value = (event.value or '').strip().lower()
                    for candidate in ('https', 'http'):
                        if value.startswith(candidate + '://') and d['scheme'] != candidate:
                            d['scheme'] = candidate
                    W['chips_view'].refresh()
                url.on_value_change(follow)
                W['send'] = ui.button('Enviar', icon='send', on_click=guard(send)).props('color=primary').mark('ws-send')

            @ui.refreshable
            def chips_view():
                defined, missing = ws.placeholders(d)
                if not defined and not missing:
                    return
                with ui.row().classes('px-3 gap-1 items-center'):
                    ui.label('Variables:').classes('text-xs text-gray-500')
                    for name in defined:
                        ui.badge('{{' + name + '}}', color='positive').props('outline').classes('text-xs')
                    for name in missing:
                        ui.badge('{{' + name + '}} sin valor', color='warning').classes('text-xs').tooltip('Defínela en la pestaña Variables o en el ambiente')
            W['chips_view'] = chips_view
            chips_view()
            ui.separator().classes('mt-1')
            with ui.row().classes('w-full items-center px-3 pt-2'):
                ui.label('RESPUESTA').classes('text-xs font-semibold text-gray-400 tracking-wide')

            with ui.column().classes('w-full grow no-wrap gap-0').style('min-height:0;overflow:auto'):
                @ui.refreshable
                def response_view():
                    result = S['result']
                    if result is None and not S['batch']:
                        with ui.column().classes('w-full items-center justify-center text-gray-400 gap-1').style('height:100%;min-height:240px'):
                            ui.icon('send', size='xl')
                            ui.label('Escribe una URL y pulsa Enviar (Ctrl+Enter).')
                            ui.label('Edita body, headers y pruebas en el panel de la derecha sin cambiar de pantalla.').classes('text-sm')
                        return
                    if result is not None:
                        with ui.row().classes('items-center gap-3 px-3 py-2'):
                            status_chip(result.get('http_status'), result.get('status') == 'error').classes('text-base')
                            if result.get('status') == 'error':
                                ui.label(result.get('error') or 'Error').classes('text-red-700 text-sm')
                            else:
                                ui.label(f'{result.get("duration_ms")} ms · {result.get("size", 0)} caracteres').classes('text-sm text-gray-600')
                            asserts = result.get('assertions') or []
                            if asserts:
                                ok = sum(1 for a in asserts if a['passed'])
                                ui.badge(f'{ok}/{len(asserts)} pruebas', color='positive' if ok == len(asserts) else 'negative').classes('text-xs')
                    tabs_available = ['Cuerpo', 'Headers', 'Pruebas', 'Diff'] if result is not None else []
                    if S['conn']:
                        tabs_available.append('Conectividad')
                    if S['batch']:
                        tabs_available.append('Lote')
                    if S['resp_tab'] not in tabs_available:
                        S['resp_tab'] = tabs_available[0]
                    with ui.tabs(value=S['resp_tab'], on_change=lambda e: S.__setitem__('resp_tab', e.value)).props('dense align=left no-caps').classes('px-2') as rtabs:
                        for name in tabs_available:
                            ui.tab(name)
                    with ui.tab_panels(rtabs, value=S['resp_tab']).classes('w-full grow').props('keep-alive'):
                        if result is not None:
                            with ui.tab_panel('Cuerpo').classes('p-2'):
                                body = result.get('body') or ''
                                try:
                                    parsed = json.loads(body)
                                except ValueError:
                                    parsed = None
                                if parsed is not None:
                                    ui.toggle(['Texto', 'Árbol'], value=S['view'], on_change=lambda e: (S.__setitem__('view', e.value), W['response_view'].refresh())).props('dense no-caps')
                                if S['view'] == 'Árbol' and parsed is not None:
                                    ui.json_editor({'content': {'json': parsed}, 'readOnly': True}).classes('w-full')
                                else:
                                    ui.code((pretty(body) if parsed is not None else body)[:200000] or '(vacío)', language='json' if parsed is not None else 'text').classes('w-full')
                                if S['volatile']:
                                    ui.label('Campos que suelen cambiar: ' + ', '.join(S['volatile'])).classes('text-xs text-amber-700')
                            with ui.tab_panel('Headers').classes('p-2'):
                                for key, value in (result.get('headers') or {}).items():
                                    with ui.row().classes('gap-2 no-wrap'):
                                        ui.label(key).classes('font-mono text-sm font-medium')
                                        ui.label(str(value)).classes('font-mono text-sm text-gray-700')
                            with ui.tab_panel('Pruebas').classes('p-2'):
                                asserts = result.get('assertions') or []
                                if not asserts:
                                    ui.label('Esta petición no tiene pruebas. Agrégalas en el panel derecho (Pruebas) o genéralas desde esta respuesta.').classes('text-gray-500 text-sm')
                                for item in asserts:
                                    with ui.row().classes('items-start gap-2 no-wrap'):
                                        ui.icon('check_circle' if item['passed'] else 'cancel', color='positive' if item['passed'] else 'negative', size='sm')
                                        ui.label(agent.describe_rule(item['rule'])).classes('text-sm')
                                        if not item['passed']:
                                            actual = item['actual']
                                            ui.label('→ ' + (chr(10).join(actual) if isinstance(actual, list) and all(isinstance(x, str) for x in actual) else json.dumps(actual, ensure_ascii=False))[:400]).classes('text-sm text-red-700 whitespace-pre-wrap')
                            with ui.tab_panel('Diff').classes('p-2'):
                                previous = S['previous']
                                if previous is None:
                                    ui.label('No hay una respuesta anterior de esta misma petición para comparar.').classes('text-gray-500 text-sm')
                                else:
                                    differences = ws.diff_bodies(previous['result'].get('body'), result.get('body'))
                                    ui.label(f'Comparada con la respuesta del {fmt_time(previous["at"])} (HTTP {previous["result"].get("http_status")}):').classes('text-sm text-gray-600')
                                    if not differences:
                                        ui.label('Sin diferencias de estructura ni de valores.').classes('text-green-800 text-sm')
                                    for line in differences:
                                        ui.label('• ' + line).classes('text-sm font-mono')
                        if S['conn']:
                            with ui.tab_panel('Conectividad').classes('p-2'):
                                conn = S['conn']
                                with ui.row().classes('items-center gap-2'):
                                    ui.icon('check_circle' if conn['ok'] else 'cancel', color='positive' if conn['ok'] else 'negative')
                                    ui.label(f'{conn["url"]} — {"alcanzable" if conn["ok"] else "con problemas"}').classes('font-semibold')
                                for item in conn['steps']:
                                    with ui.row().classes('items-center gap-2 pl-6'):
                                        ui.icon('check' if item['ok'] else 'close', color='positive' if item['ok'] else 'negative', size='xs')
                                        ui.label(f'{item["name"]} · {item["ms"]} ms').classes('w-32')
                                        ui.label(item['detail']).classes('text-sm text-gray-600')
                        if S['batch']:
                            with ui.tab_panel('Lote').classes('p-2'):
                                for index, row_ in enumerate(S['batch_rows']):
                                    res = S['batch'].get(index)
                                    if not res:
                                        continue
                                    with ui.expansion().classes('w-full border rounded mb-1').props('dense') as ex:
                                        with ex.add_slot('header'):
                                            with ui.row().classes('items-center gap-2 w-full no-wrap'):
                                                status_chip(res.get('http_status'), res['status'] == 'error')
                                                ui.label(row_['name']).classes('font-medium')
                                                ui.label(', '.join(f'{k}={v}' for k, v in row_['values'].items())).classes('text-xs text-gray-500 grow truncate')
                                                ui.label(f'{res.get("duration_ms", "—")} ms').classes('text-xs text-gray-500')
                                        body = (res.get('response') or {}).get('body') or res.get('error') or ''
                                        ui.code(pretty(body)[:20000], language='json').classes('w-full')
                W['response_view'] = response_view
                response_view()

    # ------------------------------------------------------------ right pane
    def right():
        with ui.row().classes('w-full h-full no-wrap gap-0'):
            with ui.tab_panels(None, value='Params').props('vertical').style('flex:1 1 0;min-width:0;overflow:auto;height:100%') as panels:
                with ui.tab_panel('Params').classes('p-3 gap-2'):
                    ui.label('Parámetros de la query').classes('font-medium')
                    ui.label('Se combinan con los que escribas en la URL.').classes('text-xs text-gray-500')
                    W['query_view'] = kv_rows(lambda: d['query'], 'Parámetro', 'Valor', lambda: W['chips_view'].refresh())
                with ui.tab_panel('Headers').classes('p-3 gap-2'):
                    ui.label('Headers').classes('font-medium')
                    ui.label('Las filas desactivadas se conservan pero no se envían. La autenticación del ambiente se agrega sola.').classes('text-xs text-gray-500')
                    W['headers_view'] = kv_rows(lambda: d['headers'], 'Header', 'Valor', lambda: W['chips_view'].refresh(), HEADER_SUGGESTIONS)
                with ui.tab_panel('Body').classes('p-3 gap-1'):
                    with ui.row().classes('w-full items-center gap-1'):
                        ui.label('Body JSON').classes('font-medium')

                        @ui.refreshable
                        def body_status():
                            text = (d['body'] or '').strip()
                            if not text:
                                ui.badge('vacío', color='grey').classes('text-xs')
                                return
                            try:
                                json.loads(text)
                                ui.badge('JSON válido', color='positive').classes('text-xs')
                            except ValueError as exc:
                                ui.badge('JSON inválido', color='negative').classes('text-xs').tooltip(str(exc))
                        W['body_status'] = body_status
                        body_status()
                        ui.space()

                        def reformat(indent):
                            try:
                                data = json.loads(d['body'])
                            except ValueError as exc:
                                raise ValueError(f'No se puede formatear: {exc}')
                            d['body'] = json.dumps(data, indent=indent, ensure_ascii=False) if indent else json.dumps(data, ensure_ascii=False, separators=(',', ':'))
                            W['body'].set_value(d['body'])
                        ui.button('Formatear', on_click=guard(lambda: reformat(2))).props('flat dense size=sm no-caps')
                        ui.button('Minificar', on_click=guard(lambda: reformat(None))).props('flat dense size=sm no-caps')
                        ui.button('Usar la última respuesta', on_click=guard(lambda: (d.__setitem__('body', pretty((S['result'] or {}).get('body'))), W['body'].set_value(d['body'])))) \
                            .props('flat dense size=sm no-caps').tooltip('Copia el cuerpo de la respuesta como body de la petición')

                    def body_changed(event):
                        d['body'] = event.value
                        W['body_status'].refresh()
                        W['chips_view'].refresh()
                    W['body'] = ui.codemirror(d['body'], language='JSON', line_wrapping=True, on_change=body_changed).classes('w-full').style('height: calc(100vh - 200px)')
                with ui.tab_panel('Pruebas').classes('p-3 gap-2'):
                    ui.label('Pruebas (aserciones)').classes('font-medium')
                    ui.label('El resultado de la última respuesta aparece junto a cada regla.').classes('text-xs text-gray-500')
                    W['tests_view'] = assertion_rows(lambda: d['assertions'], results_list, get_paths=response_paths)
                    ui.separator()
                    ui.label('Generar desde la respuesta actual').classes('font-medium text-sm')
                    gen_mode = ui.select({'exact': MODES['exact'], 'structure': MODES['structure'], 'status': MODES['status']}, value='exact').props('outlined dense options-dense').classes('w-full')
                    gen_ignore = ui.input('Ignorar campos (JSONPath, coma)', placeholder='$.requested_at').props('outlined dense').classes('w-full')
                    ui.button('Generar pruebas', icon='auto_fix_high', on_click=guard(lambda: autogenerate(gen_mode.value, gen_ignore.value))).props('outline dense no-caps')
                    ui.label('Se reemplazan las pruebas actuales. Los campos que suelen cambiar se rellenan tras enviar.').classes('text-xs text-gray-500')
                    W['gen_ignore'] = gen_ignore
                with ui.tab_panel('Variables').classes('p-3 gap-2'):
                    ui.label('Variables de esta petición').classes('font-medium')
                    ui.label('Usa {{nombre}} en URL, headers, query o body. {{secret:NOMBRE}} toma el valor del almacén seguro.').classes('text-xs text-gray-500')
                    W['vars_view'] = kv_rows(lambda: d['variables'], 'Variable', 'Valor', lambda: W['chips_view'].refresh())
                    ui.separator()
                    ui.label('Extraer de la respuesta (para encadenar en un flujo)').classes('font-medium text-sm')

                    @ui.refreshable
                    def extract_view():
                        for rule in d['extract']:
                            with ui.row().classes('w-full items-center gap-1 no-wrap'):
                                ui.input('Guardar como', value=rule.get('name', '')).props('outlined dense').classes('w-1/3').on_value_change(lambda e, r=rule: r.__setitem__('name', e.value))
                                ui.input('Ruta ($.token)', value=rule.get('path', '')).props('outlined dense').classes('grow').on_value_change(lambda e, r=rule: r.__setitem__('path', e.value))
                                ui.button(icon='close', on_click=lambda _, r=rule: (d['extract'].remove(r), extract_view.refresh())).props('flat round dense size=sm color=grey')
                        ui.button('Agregar extracción', icon='add', on_click=lambda: (d['extract'].append({'name': '', 'source': 'json', 'path': ''}), extract_view.refresh())).props('flat dense size=sm color=primary')
                    W['extract_view'] = extract_view
                    extract_view()
                with ui.tab_panel('Lote').classes('p-3 gap-2'):
                    ui.label('Misma petición con distintas entradas').classes('font-medium')
                    ui.label('Escribe {{variables}} en la petición (p. ej. /api/users/{{id}}) y define un valor por fila.').classes('text-xs text-gray-500')

                    @ui.refreshable
                    def batch_view():
                        try:
                            case, _ = ws.build_case(d)
                        except ValueError as exc:
                            ui.label(f'Define primero la petición: {exc}').classes('text-amber-700 text-sm')
                            return
                        names = [n for n in core.find_unresolved(case['path'], case['headers'], case['query'], case['body']) if not n.startswith(('secret:', '@'))]
                        if not names:
                            ui.label('La petición no tiene {{variables}} todavía.').classes('text-amber-700 text-sm')
                            return
                        for index, row_ in enumerate(S['batch_rows']):
                            with ui.row().classes('w-full items-center gap-1 no-wrap'):
                                ui.input('Nombre', value=row_['name']).props('outlined dense').classes('w-28').on_value_change(lambda e, r=row_: r.__setitem__('name', e.value))
                                for name in names:
                                    ui.input(name, value=str(row_['values'].get(name, ''))).props('outlined dense').classes('grow').on_value_change(lambda e, r=row_, n=name: r['values'].__setitem__(n, e.value))
                                res = S['batch'].get(index)
                                if res:
                                    status_chip(res.get('http_status'), res['status'] == 'error')
                                ui.button(icon='close', on_click=lambda _, i=index: (S['batch_rows'].pop(i), S['batch'].clear(), batch_view.refresh(), W['response_view'].refresh())).props('flat round dense size=sm color=grey')
                    W['batch_view'] = batch_view
                    batch_view()
                    with ui.row().classes('gap-1'):
                        ui.button('Agregar fila', icon='add', on_click=lambda: (S['batch_rows'].append({'name': f'fila {len(S["batch_rows"]) + 1}', 'values': {}}), batch_view.refresh())).props('flat dense size=sm color=primary no-caps')
                        ui.button('Actualizar columnas', icon='refresh', on_click=lambda: batch_view.refresh()).props('flat dense size=sm no-caps')
                    paste = ui.textarea('Pegar filas: una por línea, valores separados por coma').props('outlined dense autogrow').classes('w-full')

                    def load_pasted():
                        case, _ = ws.build_case(d)
                        names = [n for n in core.find_unresolved(case['path'], case['headers'], case['query'], case['body']) if not n.startswith(('secret:', '@'))]
                        rows = [{'name': f'fila {i}', 'values': dict(zip(names, [p.strip() for p in line.split(',')]))} for i, line in enumerate((paste.value or '').splitlines(), 1) if line.strip()]
                        if not rows:
                            raise ValueError('No hay líneas para importar')
                        S['batch_rows'][:] = rows
                        S['batch'].clear()
                        batch_view.refresh()
                    ui.button('Cargar filas', icon='content_paste', on_click=guard(load_pasted)).props('flat dense size=sm no-caps')

                    async def run_batch():
                        base, env = ws.build_case(d)
                        names = [n for n in core.find_unresolved(base['path'], base['headers'], base['query'], base['body']) if not n.startswith(('secret:', '@'))]
                        if not names:
                            raise ValueError('La petición no tiene {{variables}}')
                        S['batch'].clear()
                        for index, row_ in enumerate(S['batch_rows']):
                            case = {**base, 'name': row_['name'], 'variables': {**base['variables'], **{n: row_['values'].get(n, '') for n in names}}}
                            S['batch'][index] = await run.io_bound(core.execute_api, case, env, None, False)
                        S['resp_tab'] = 'Lote'
                        batch_view.refresh()
                        W['response_view'].refresh()
                    ui.button('Ejecutar lote', icon='play_arrow', on_click=guard(run_batch)).props('color=positive dense no-caps')
                    ui.separator()
                    suite_name = ui.input('Nombre del flujo', value='Regresión (lote)').props('outlined dense').classes('w-full')
                    batch_mode = ui.select({k: v for k, v in MODES.items() if k != 'panel'}, value='exact').props('outlined dense options-dense').classes('w-full')
                    batch_ignore = ui.input('Ignorar campos (JSONPath, coma)').props('outlined dense').classes('w-full')

                    def save_batch():
                        base, env = ws.build_case(d)
                        names = [n for n in core.find_unresolved(base['path'], base['headers'], base['query'], base['body']) if not n.startswith(('secret:', '@'))]
                        if len(S['batch']) != len(S['batch_rows']) or any(r['status'] == 'error' for r in S['batch'].values()):
                            raise ValueError('Ejecuta el lote completo (sin errores de conexión) antes de guardarlo')
                        paths = [p.strip() for p in (batch_ignore.value or '').split(',') if p.strip()]
                        rows = [{'name': r['name'], 'variables': {n: r['values'].get(n, '') for n in names}, 'status': S['batch'][i]['http_status'], 'body': S['batch'][i]['response']['body']}
                                for i, r in enumerate(S['batch_rows'])]
                        project_id = resolve_project()
                        env_doc = persistent_env(project_id, env)
                        if W['dest_suite'].value:
                            core.check_suite_origin(W['dest_suite'].value, env_doc['base_url'])
                        cases = core.dataset_cases({**base, 'name': (suite_name.value or 'Lote').strip()}, rows, project_id, batch_mode.value, paths)
                        for case in cases:
                            core.save('cases', {**case, 'environment_id': env_doc['id']})
                        if W['dest_suite'].value:
                            suite = core.add_cases_to_suite(W['dest_suite'].value, [c['id'] for c in cases])
                        else:
                            suite = core.save_suite((suite_name.value or 'Lote').strip(), env_doc['id'], [c['id'] for c in cases], project_id)
                        refresh_suites()
                        W['saved_view'].refresh()
                        ui.notify(f'{len(cases)} casos guardados en el flujo «{suite["name"]}» ({projects_by_id[project_id]})', type='positive')
                    ui.button('Guardar lote como flujo', icon='playlist_add_check', on_click=guard(save_batch)).props('outline dense no-caps')
                    ui.label('Se guarda en el proyecto y flujo elegidos en la pestaña «Guardar».').classes('text-xs text-gray-500')
                with ui.tab_panel('Guardar').classes('p-3 gap-2'):
                    ui.label('Guardar como caso de prueba').classes('font-medium')
                    ui.label('Nada se guarda hasta que lo decidas.').classes('text-xs text-gray-500')
                    W['case_name'] = ui.input('Nombre del caso').props('outlined dense').classes('w-full').bind_value(d, 'name')
                    W['mode'] = ui.select(MODES, value='exact', label='Qué debe cumplir').props('outlined dense options-dense').classes('w-full')
                    W['ignore'] = ui.input('Ignorar campos (JSONPath, coma)', placeholder='$.requested_at').props('outlined dense').classes('w-full')
                    W['ignore'].bind_visibility_from(W['mode'], 'value', lambda v: v == 'exact')
                    ui.separator()
                    ui.label('Destino').classes('font-medium text-sm')
                    W['dest_project'] = ui.select(project_options(), label='Proyecto', value=active_project if active_project in projects_by_id else (NEW if not projects_by_id else None),
                                                  on_change=refresh_suites).props('outlined dense options-dense').classes('w-full')
                    W['new_project'] = ui.input('Nombre del proyecto nuevo').props('outlined dense').classes('w-full')
                    W['new_project'].bind_visibility_from(W['dest_project'], 'value', lambda v: v == NEW)
                    W['dest_suite'] = ui.select({'': 'No agregar a un flujo existente'}, value='', label='Agregar a un flujo existente').props('outlined dense options-dense').classes('w-full')
                    refresh_suites()
                    W['update_existing'] = ui.switch('Actualizar el caso guardado (en vez de crear otro)', value=True).props('dense')
                    W['update_existing'].bind_visibility_from(d, 'source', lambda s: bool(s) and s.get('type') == 'case')
                    ui.button('Guardar', icon='save', on_click=guard(save_case)).props('color=primary no-caps').mark('ws-save')
                with ui.tab_panel('Agente').classes('p-3 gap-2'):
                    agent_tab()
            with ui.tabs().props('vertical dense no-caps').classes('shrink-0').style('width:56px;border-left:1px solid #e5e7eb') as rail:
                # Params..Lote editan la petición; Guardar/Agente son acciones aparte (persistir, herramientas de
                # IA/protocolo) — un borde los separa visualmente sin tocar el cableado rail↔panels existente.
                for name, icon in (('Params', 'tune'), ('Headers', 'list_alt'), ('Body', 'data_object'), ('Pruebas', 'rule'), ('Variables', 'data_array'),
                                   ('Lote', 'table_rows'), ('Guardar', 'save'), ('Agente', 'smart_toy')):
                    tab = ui.tab(name, label='', icon=icon).tooltip(name).mark(f'rail-{name}')
                    if name == 'Guardar':
                        tab.style('border-top:1px solid #e5e7eb')
            panels.bind_value_from(rail, 'value')
            rail.set_value('Body')

    def agent_tab():
        base = f'http://127.0.0.1:{os.environ.get("LTW_PORT", "8080")}'
        ui.label('Protocolo para agentes').classes('font-medium')
        ui.label('Otro agente puede entregar casos en formato ltw.spec/1 y recibir los fallos como ltw.failure/1, con todo lo necesario para ir directo al código.').classes('text-xs text-gray-500')

        @ui.refreshable
        def agent_view():
            run_doc = S.get('run')
            failing = run_doc is not None and (run_doc['status'] == 'error' or any(not a['passed'] for a in run_doc.get('assertions', [])))
            with ui.expansion('Brief del último fallo', icon='bug_report', value=failing).classes('w-full border rounded'):
                if not failing:
                    ui.label('Cuando una petición con pruebas falle, aquí aparece el brief listo para pasárselo a un agente.').classes('text-xs text-gray-500')
                else:
                    brief = agent.failure_from_run(run_doc)
                    ui.label(f'{brief["title"]} · {brief["diagnosis"]["category"]}').classes('text-sm font-medium')
                    with ui.row().classes('gap-1'):
                        ui.button('Copiar brief (Markdown)', icon='content_copy', on_click=lambda: (ui.clipboard.write(brief['brief_markdown']), ui.notify('Brief copiado', type='positive'))).props('dense size=sm no-caps')
                        ui.button('Descargar failure.json', icon='download', on_click=lambda: ui.download(json.dumps(brief, indent=2, ensure_ascii=False).encode('utf-8'), 'failure.ltw.json')).props('flat dense size=sm no-caps')
                    ui.code(brief['brief_markdown'], language='markdown').classes('w-full').style('max-height:260px;overflow:auto')
            with ui.expansion('Esta petición como especificación', icon='description').classes('w-full border rounded'):
                try:
                    spec_text = json.dumps(ws.draft_to_spec(d), indent=2, ensure_ascii=False)
                except ValueError as exc:
                    spec_text = None
                    ui.label(f'Completa la petición para exportarla: {exc}').classes('text-xs text-amber-700')
                if spec_text:
                    with ui.row().classes('gap-1'):
                        ui.button('Copiar', icon='content_copy', on_click=lambda: (ui.clipboard.write(spec_text), ui.notify('Especificación copiada', type='positive'))).props('dense size=sm no-caps')
                        ui.button('Descargar', icon='download', on_click=lambda: ui.download(spec_text.encode('utf-8'), 'caso.ltw.json')).props('flat dense size=sm no-caps')
                    ui.code(spec_text, language='json').classes('w-full').style('max-height:260px;overflow:auto')
        W['agent_view'] = agent_view
        agent_view()
        with ui.expansion('Importar una especificación', icon='upload').classes('w-full border rounded'):
            spec_input = ui.textarea('Pega aquí un ltw.spec/1').props('outlined dense autogrow input-class=font-mono').classes('w-full')
            W['spec_out'] = ui.column().classes('w-full gap-0')
            with ui.row().classes('gap-1'):
                ui.button('Validar y cargar el primer caso', icon='input', on_click=guard(lambda: spec_validate_and_load(spec_input.value, False))).props('dense size=sm no-caps')
                ui.button('Importar todo al proyecto', icon='playlist_add', on_click=guard(lambda: spec_validate_and_load(spec_input.value, True))).props('outline dense size=sm no-caps')
            ui.label('El destino es el de la pestaña «Guardar».').classes('text-xs text-gray-500')
        with ui.expansion('API local y línea de comandos', icon='terminal').classes('w-full border rounded'):
            token = agent.agent_token()
            ui.label('Token (cabecera Authorization: Bearer …)').classes('text-xs text-gray-500')
            with ui.row().classes('items-center gap-1 w-full no-wrap'):
                shown = ui.input(value=token, password=True, password_toggle_button=True).props('outlined dense readonly').classes('grow')
                ui.button(icon='content_copy', on_click=lambda: (ui.clipboard.write(token), ui.notify('Token copiado', type='positive'))).props('flat round dense size=sm')

                def rotate():
                    shown.set_value(agent.rotate_agent_token())
                    ui.notify('Token regenerado: el anterior deja de valer', type='warning')
                ui.button(icon='autorenew', on_click=lambda: confirm('El token actual dejará de funcionar. ¿Regenerarlo?', rotate, 'Regenerar')).props('flat round dense size=sm').tooltip('Regenerar')
            ui.code(f'curl -s -X POST {base}/agent/v1/run \\\n  -H "Authorization: Bearer <token>" -H "Content-Type: application/json" \\\n  --data @spec.json\n\n'
                    f'python run.py --run spec.json --report report.json --md fallos.md', language='bash').classes('w-full')
            ui.label('Detalle del formato en AGENTS.md. Esquema: GET /agent/v1/schema').classes('text-xs text-gray-500')
        llm_section()

    def llm_section():
        """Optional model assistant: connection settings, explain the last failure, generate cases. Off until the connection works."""
        L = {'answer': None, 'generated': None, 'busy': False}

        @ui.refreshable
        def llm_view():
            state = llm.status()
            run_doc = S.get('run')
            failing = run_doc is not None and (run_doc['status'] == 'error' or any(not a['passed'] for a in run_doc.get('assertions', [])))
            with ui.row().classes('items-center gap-2'):
                ui.icon('psychology', color='primary' if state['ready'] else 'grey')
                ui.label('Asistente con modelo de lenguaje').classes('font-medium')
                ui.badge(state['summary'], color='positive' if state['ready'] and state['local'] else ('warning' if state['ready'] else 'grey')).props('outline')
            if not state['ready']:
                ui.label(state['problem'] + ' Configura la conexión más abajo: sin ella el asistente no hace nada.').classes('text-xs text-amber-700')
            else:
                ui.label('Local: los datos no salen de esta máquina.' if state['local'] else 'Nube: lo que envíes sale de esta máquina. Revisa la vista previa antes.').classes('text-xs text-gray-500')

            profiles = llm.list_profiles()
            if profiles:
                with ui.row().classes('items-center gap-2 w-full'):
                    picker = ui.select({p['id']: p['name'] for p in profiles}, value=llm.active_profile_id(), label='Modelo activo', clearable=False) \
                        .props('outlined dense').classes('grow')

                    def pick(event):
                        try:
                            llm.activate_profile(event.value)
                            ui.notify(f'Modelo activo: {llm.get_profile(event.value)["name"]}', type='positive')
                        except (llm.LLMError, ValueError) as exc:
                            ui.notify(str(exc), type='negative', multi_line=True)
                        llm_view.refresh()
                    picker.on_value_change(pick)
                    ui.button(icon='settings', on_click=lambda: ui.navigate.to('/models', new_tab=True)).props('flat round dense').tooltip('Administrar modelos registrados')
            else:
                ui.label('Aún no registraste ningún modelo en «Modelos de IA»: hazlo ahí para poder elegirlo desde aquí sin repetir URL ni clave.').classes('text-xs text-gray-500')
                ui.button('Ir a Modelos de IA', icon='smart_toy', on_click=lambda: ui.navigate.to('/models', new_tab=True)).props('outline dense size=sm no-caps')

            with ui.expansion('Explicar el último fallo', icon='bug_report', value=bool(failing and state['ready'])).classes('w-full border rounded'):
                if not failing:
                    ui.label('Cuando una petición con pruebas falle, aquí podrás pedirle una explicación al modelo.').classes('text-xs text-gray-500')
                else:
                    brief = agent.failure_from_run(run_doc)
                    system_text, user_text = llm.explain_messages(brief)
                    with ui.expansion('Ver exactamente lo que se enviará', icon='visibility').classes('w-full border rounded').props('dense'):
                        ui.code(user_text, language='markdown').classes('w-full').style('max-height:200px;overflow:auto')
                    ask_button = ui.button('Explicar con el modelo', icon='auto_awesome', on_click=guard(lambda: explain(brief))).props('dense size=sm no-caps')
                    ask_button.set_enabled(state['ready'] and not L['busy'])
                    if L['answer']:
                        ui.markdown(L['answer']).classes('w-full text-sm')
                        ui.label('Sugerencia del modelo: contrástala con la evidencia antes de actuar.').classes('text-xs text-gray-500')

            with ui.expansion('Generar casos con el modelo', icon='playlist_add_check').classes('w-full border rounded'):
                description = ui.textarea('Qué quieres probar').props('outlined dense autogrow').classes('w-full')
                modules = {m['id']: m['name'] for m in core.list_items('modules')}
                module_select = ui.select({None: '(sin contrato)', **modules}, value=None, label='Contrato OpenAPI como contexto').props('outlined dense').classes('w-full')
                generate_button = ui.button('Generar especificación', icon='auto_awesome',
                                            on_click=guard(lambda: generate(description.value, module_select.value))).props('dense size=sm no-caps')
                generate_button.set_enabled(state['ready'] and not L['busy'])
                result = L['generated']
                if result:
                    for e in result['errors']:
                        ui.label(f'✗ {e["path"]}: {e["message"]}').classes('text-sm text-red-700')
                    if result['valid']:
                        ui.label(f'✓ Especificación válida (intentos: {result["attempts"]}). Revísala: no se guarda nada hasta que la importes.').classes('text-sm text-green-800')
                        text = json.dumps(result['spec'], indent=2, ensure_ascii=False)
                        with ui.row().classes('gap-1'):
                            ui.button('Cargar el primer caso', icon='input', on_click=guard(lambda: spec_validate_and_load(text, False))).props('dense size=sm no-caps')
                            ui.button('Importar todo al proyecto', icon='playlist_add', on_click=guard(lambda: spec_validate_and_load(text, True))).props('outline dense size=sm no-caps')
                        ui.code(text, language='json').classes('w-full').style('max-height:260px;overflow:auto')
                    else:
                        ui.label('El modelo no logró una especificación válida; esto es lo que devolvió:').classes('text-xs text-gray-500')
                        ui.code(result['raw'][:3000], language='json').classes('w-full').style('max-height:200px;overflow:auto')

            with ui.expansion('Conexión directa (sin registrar)', icon='settings_ethernet', value=not state['ready'] and not profiles).classes('w-full border rounded'):
                ui.label('Para un modelo de uso puntual que no quieres guardar en «Modelos de IA». Ojo: esto reemplaza el modelo activo de arriba.').classes('text-xs text-gray-500')
                connection_form()
        W['llm_view'] = llm_view
        llm_view()

        async def explain(brief):
            L['busy'] = True
            ui.notify('Consultando al modelo…')
            try:
                L['answer'] = await run.io_bound(llm.explain_failure, brief)
            except llm.LLMError as exc:
                L['answer'] = None
                ui.notify(str(exc), type='negative', multi_line=True)
            finally:
                L['busy'] = False
                llm_view.refresh()

        async def generate(text, module_id):
            L['busy'] = True
            ui.notify('Generando con el modelo… los modelos locales pueden tardar')
            try:
                module = core.get('modules', module_id) if module_id else None
                environment_names = sorted({e['name'] for e in core.list_items('environments') if not active_project or e.get('project_id') == active_project})
                L['generated'] = await run.io_bound(llm.generate_spec, text, module, environment_names)
            except llm.LLMError as exc:
                L['generated'] = None
                ui.notify(str(exc), type='negative', multi_line=True)
            finally:
                L['busy'] = False
                llm_view.refresh()

    def connection_form():
        cfg = llm.get_config()
        ui.label('Pega los datos de acceso de tu servicio o apunta a un modelo local. Sin datos correctos, el asistente permanece apagado. '
                 'Ojo: las suscripciones de chat (Claude Max, ChatGPT Plus) no incluyen clave de API; hace falta una clave de API o un modelo local.').classes('text-xs text-gray-500')
        preset = ui.select({k: v['label'] for k, v in llm.PRESETS.items()}, value=cfg['preset'] if cfg['preset'] in llm.PRESETS else 'custom', label='Proveedor').props('outlined dense').classes('w-full')
        protocol = ui.select(llm.PROTOCOLS, value=cfg['protocol'], label='Protocolo').props('outlined dense').classes('w-full')
        url = ui.input('URL base', value=cfg['base_url'] or llm.PRESETS['ollama']['base_url']).props('outlined dense').classes('w-full')
        model = ui.input('Modelo (o nombre del despliegue)', value=cfg['model'] or llm.PRESETS['ollama']['model']).props('outlined dense').classes('w-full')
        auth = ui.select(llm.AUTH_STYLES, value=cfg['auth'], label='Autenticación').props('outlined dense').classes('w-full')
        key = ui.input('Clave de API', password=True, password_toggle_button=True, placeholder='(vacía = conservar la guardada)').props('outlined dense').classes('w-full')
        cloud = ui.switch('Permitir enviar datos fuera de esta máquina', value=cfg['allow_cloud'])
        timeout = ui.number('Tiempo de espera (s)', value=cfg['timeout'], min=5, max=600, step=10).props('outlined dense').classes('w-40')

        def on_preset(event):
            chosen = llm.PRESETS[event.value]
            protocol.set_value(chosen['protocol'])
            auth.set_value(chosen['auth'])
            if chosen['base_url']:
                url.set_value(chosen['base_url'])
            model.set_value(chosen['model'])
        preset.on_value_change(on_preset)

        def current():
            return {'preset': preset.value, 'protocol': protocol.value, 'base_url': url.value, 'model': model.value, 'auth': auth.value,
                    'allow_cloud': cloud.value, 'timeout': timeout.value}

        def save():
            llm.save_config(current(), api_key=key.value or None)
            key.set_value('')
            W['llm_view'].refresh()
            ui.notify('Conexión guardada', type='positive')

        async def probe():
            config = llm.save_config(current(), api_key=key.value or None)
            key.set_value('')
            try:
                result = await run.io_bound(llm.test_connection, config)
                ui.notify(f'Conexión correcta · {result["summary"]}', type='positive')
            except llm.LLMError as exc:
                ui.notify(str(exc), type='negative', multi_line=True)
            W['llm_view'].refresh()

        def clear():
            llm.clear_config()
            W['llm_view'].refresh()
            ui.notify('Configuración y clave eliminadas', type='warning')
        with ui.row().classes('gap-1'):
            ui.button('Guardar', icon='save', on_click=guard(save)).props('dense size=sm no-caps')
            ui.button('Probar conexión', icon='bolt', on_click=guard(probe)).props('outline dense size=sm no-caps')
            ui.button('Quitar', icon='delete', on_click=lambda: confirm('Se borrará la conexión y la clave guardada. ¿Continuar?', clear, 'Quitar')).props('flat dense size=sm no-caps')

    # ------------------------------------------------------------ layout
    def key_handler(event):
        if event.action.keydown and event.key.enter and event.modifiers.ctrl:
            return guard(send)()
    ui.keyboard(on_key=key_handler, ignore=[])

    left_w = float(layout.get('ws_left', 19)) if isinstance(layout, dict) or hasattr(layout, 'get') else 19
    right_w = float(layout.get('ws_right', 62)) if isinstance(layout, dict) or hasattr(layout, 'get') else 62

    def toggle_panel():
        S['panel_hidden'] = not S.get('panel_hidden', False)
        if isinstance(layout, dict) or hasattr(layout, 'get'):
            layout['ws_panel_hidden'] = S['panel_hidden']
        workspace_split.refresh()
    S['panel_hidden'] = bool(layout.get('ws_panel_hidden', False)) if isinstance(layout, dict) or hasattr(layout, 'get') else False

    @ui.refreshable
    def workspace_split():
        with ui.splitter(value=left_w, limits=(12, 35), on_change=lambda e: layout.__setitem__('ws_left', e.value)).classes('w-full').style('height:100%') as outer:
            with outer.before:
                with ui.element('div').classes('ltw-pane'):
                    left()
            with outer.after:
                if S['panel_hidden']:
                    # Sin panel de detalle (Params/Headers/Body/Pruebas/Variables/Lote/Guardar/Agente): la
                    # petición y la respuesta ocupan todo el ancho — útil cuando solo queres leer la respuesta.
                    with ui.element('div').classes('ltw-pane relative').style('display:flex;flex-direction:column'):
                        center()
                        ui.button(icon='chevron_left', on_click=toggle_panel).props('round dense flat color=primary') \
                            .classes('absolute top-2 right-2 z-10 bg-white shadow-2').tooltip('Mostrar el panel de detalle (Params, Body, Pruebas, Agente…)')
                else:
                    with ui.splitter(value=right_w, limits=(35, 85), on_change=lambda e: layout.__setitem__('ws_right', e.value)).classes('w-full').style('height:100%') as inner:
                        with inner.before:
                            with ui.element('div').classes('ltw-pane').style('display:flex;flex-direction:column'):
                                center()
                        with inner.after:
                            with ui.element('div').classes('ltw-pane relative').style('overflow:hidden'):
                                ui.button(icon='chevron_right', on_click=toggle_panel).props('round dense flat color=primary') \
                                    .classes('absolute top-2 left-2 z-10 bg-white shadow-2').tooltip('Ocultar este panel')
                                right()
    with ui.element('div').classes('w-full').style('height: calc(100vh - 50px)'):
        workspace_split()
    if preset_case_id:
        preset_case = core.get('cases', preset_case_id)
        if preset_case and preset_case.get('type') != 'ui':
            load_case(preset_case)
        elif preset_case is None:
            ui.notify('El caso que intentas abrir ya no existe.', type='warning')
    elif prefill:
        method_in, path_in, env_id, module_id = prefill
        if env_id and core.get('environments', env_id) is None:
            env_id = ''
        new = {**ws.new_draft(), 'method': (method_in or 'GET').upper(), 'url': path_in or '', 'env_id': env_id}
        # Completa query/body con lo que el propio contrato OpenAPI declara para esta operación — sin esto,
        # «Probar» abre una petición vacía que el endpoint rechaza de entrada si exige parámetros u campos.
        operation = next((op for op in (core.get('modules', module_id) or {}).get('operations', [])
                           if op['method'] == new['method'] and op['path'] == path_in), None) if module_id else None
        if operation:
            sample = core.sample_request_for_operation(operation)
            if sample['query']:
                new['query'] = ws.dict_to_rows(sample['query'])
            if sample['body'] is not None:
                new['body'] = json.dumps(sample['body'], indent=2, ensure_ascii=False)
        load_draft(new)
