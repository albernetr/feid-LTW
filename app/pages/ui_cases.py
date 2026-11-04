"""Casos UI: one workspace, like the API one (history | steps | tools), instead of a list plus a separate
editor plus a separate navigator panel. Navigating/recording and editing the resulting steps are two moments
of the same task, so they share one screen - what changes are the tools on the right, fitted to UI steps
instead of to a request body."""
import datetime as dt
from nicegui import ui, run
from .. import core, automation, recorder
from .common import frame, guard, confirm, empty_state, require_project, show_run, fmt_time, status_badge, protected_page, current_user_id
from .widgets import method_badge

LOCATOR_LABELS = {'label': 'Etiqueta (label)', 'text': 'Texto', 'role': 'Rol ARIA', 'testid': 'data-testid', 'placeholder': 'Placeholder'}
ROLES = ['button', 'link', 'heading', 'textbox', 'checkbox', 'combobox', 'listitem', 'row', 'cell', 'tab', 'dialog', 'img']
FIELD_LABELS = {'url': 'URL o ruta', 'value': 'Valor', 'expected': 'Esperado'}


def blank_step():
    return {'action': 'click', 'locator': {'by': 'role', 'role': 'button', 'name': ''}}


def day_label(iso):
    try:
        moment = dt.datetime.fromisoformat(iso).astimezone()
    except ValueError:
        return iso
    today = dt.datetime.now().astimezone().date()
    if moment.date() == today:
        return 'Hoy'
    return 'Ayer' if (today - moment.date()).days == 1 else moment.strftime('%d/%m/%Y')


def _clean_steps(steps):
    return [dict(s, locator=dict(s['locator'])) if isinstance(s.get('locator'), dict) else dict(s) for s in (steps or [])] or [{'action': 'navigate', 'url': '/'}]


def new_draft():
    return {'id': None, 'name': 'Prueba UI', 'env_id': None, 'timeout_ms': 10000, 'steps': [{'action': 'navigate', 'url': '/'}], 'updated_at': None}


def draft_from_case(case):
    return {'id': case.get('id'), 'name': case.get('name', 'Prueba UI'), 'env_id': case.get('_env_id'), 'timeout_ms': case.get('timeout_ms', 10000),
            'steps': _clean_steps(case.get('steps')), 'updated_at': case.get('updated_at')}


@protected_page('/ui-cases')
def ui_cases_page(id: str = '', name: str = '', url: str = ''):
    with frame('Casos UI (Playwright)', '/ui-cases', wide=True):
        if not require_project():
            return
        pid = core.get_active_project_id()
        envs = core.list_project_items('environments', pid)
        preset = core.get('cases', id) if id else None
        if id and preset is None:
            ui.label('El caso no existe.')
            return
        d = draft_from_case(preset) if preset else new_draft()
        if not preset and (name or url):   # arriving from a Vista cataloged on a component: start from its name/route
            if name:
                d['name'] = name
            if url:
                d['steps'] = [{'action': 'navigate', 'url': url}]
        if not d['env_id'] and len(envs) == 1:
            d['env_id'] = envs[0]['id']
        W = {}

        def refresh_all():
            for name in ('step_rows', 'history_view', 'saved_view'):
                if name in W:
                    W[name].refresh()

        def load_draft(new_d):
            d.clear()
            d.update(new_d)
            W['name_input'].set_value(d['name'])
            W['timeout_input'].set_value(d['timeout_ms'])
            W['env_select'].set_value(d.get('env_id'))
            refresh_all()

        def load_case(case):
            load_draft(draft_from_case(case))

        def load_run(r):
            snapshot = r.get('case_snapshot') or {}
            load_draft(draft_from_case({**snapshot, 'id': None, '_env_id': r.get('environment_id')}))  # a tweakable copy; editing the saved case itself is via «Guardados»
            show_run(r)

        # ------------------------------------------------------------ left: historial / guardados
        def left():
            with ui.tabs().props('dense align=justify').classes('w-full') as tabs:
                t_hist = ui.tab('Historial', icon='history')
                t_saved = ui.tab('Guardados', icon='bookmarks')
            with ui.tab_panels(tabs, value=t_hist).classes('w-full'):
                with ui.tab_panel(t_hist).classes('p-2'):
                    @ui.refreshable
                    def history_view():
                        runs = [r for r in core.list_items('runs') if r.get('type') == 'ui' and (not pid or r.get('project_id') == pid)][:100]
                        if not runs:
                            ui.label('Aquí aparecerán tus ejecuciones.').classes('text-gray-500 text-sm p-2')
                        last = None
                        for r in runs:
                            label = day_label(r.get('started_at'))
                            if label != last:
                                ui.label(label).classes('text-xs text-gray-500 uppercase mt-2')
                                last = label
                            row = ui.row().classes('items-center w-full no-wrap gap-1 cursor-pointer px-1 rounded hover:bg-gray-100')
                            row.on('click', lambda _, run_doc=r: load_run(run_doc))
                            row.mark('ui-history-item')
                            with row:
                                status_badge(r.get('status'))
                                with ui.column().classes('gap-0 grow').style('min-width:0'):
                                    ui.label(r.get('case_name') or '(sin nombre)').classes('text-sm truncate').style('max-width:100%')
                                    ui.label(fmt_time(r.get('started_at'))).classes('text-xs text-gray-500')
                    W['history_view'] = history_view
                    history_view()

                with ui.tab_panel(t_saved).classes('p-2'):
                    @ui.refreshable
                    def saved_view():
                        all_cases = core.list_project_items('cases', pid)
                        if not all_cases:
                            ui.label('Aún no hay casos guardados.').classes('text-gray-500 text-sm p-2')
                        for case in all_cases:
                            is_ui = case.get('type') == 'ui'
                            row = ui.row().classes('items-center w-full no-wrap gap-1 cursor-pointer px-1 rounded hover:bg-gray-100' + (' bg-blue-50' if is_ui and d.get('id') == case['id'] else ''))
                            row.mark('ui-saved-item' if is_ui else f'ui-saved-api-{case["id"]}')
                            if is_ui:
                                row.on('click', lambda _, c=case: load_case(c))
                            else:
                                row.on('click', lambda _, c=case: ui.navigate.to(f'/workspace?case={c["id"]}'))
                            with row:
                                if is_ui:
                                    ui.icon('web', color='primary', size='sm')
                                else:
                                    method_badge(case.get('method', ''))
                                with ui.column().classes('gap-0 grow').style('min-width:0'):
                                    with ui.row().classes('items-center gap-1 no-wrap'):
                                        ui.label(case['name']).classes('text-sm truncate').style('max-width:100%')
                                        last = core.last_run_for_case(case['id'])
                                        if last:
                                            status_badge(last['status']).classes('text-xs')
                                    ui.label(f'{len(case.get("steps", []))} paso(s)' if is_ui else case.get('path', '')).classes('text-xs text-gray-500 truncate')
                                if not is_ui:
                                    ui.icon('open_in_new', size='xs', color='grey').tooltip('Se edita en Espacio de trabajo')

                                def remove(c=case):
                                    used = [s for s in core.list_items('suites') if c['id'] in s.get('case_ids', [])]
                                    if used:
                                        raise ValueError(f'No se puede eliminar: está en {len(used)} flujo(s)')
                                    core.delete('cases', c['id'])
                                    if d.get('id') == c['id']:
                                        load_draft(new_draft())
                                    saved_view.refresh()
                                ui.button(icon='delete', on_click=lambda _, c=case, r=remove: confirm(f'¿Eliminar «{c["name"]}»?', r)).props('flat round dense size=sm color=negative')
                    W['saved_view'] = saved_view
                    saved_view()

        # ------------------------------------------------------------ center: navegar/grabar + pasos
        def center():
            with ui.column().classes('w-full h-full no-wrap gap-0'):
                with ui.row().classes('w-full items-center gap-2 no-wrap px-3 pt-2'):
                    W['name_input'] = ui.input(placeholder='Prueba sin nombre', value=d['name']).props('borderless dense').classes('text-lg font-medium grow') \
                        .on_value_change(lambda e: d.__setitem__('name', e.value))
                    ui.button(icon='note_add', on_click=lambda: load_draft(new_draft())).props('flat round dense').tooltip('Nuevo caso UI')
                with ui.row().classes('w-full items-end gap-2 no-wrap px-3'):
                    scheme = ui.select(['https', 'http'], value='https', label='Protocolo').props('outlined dense').classes('w-28')
                    nav_url = ui.input('Dirección a navegar/grabar', placeholder='ejemplo.com/login').props('outlined dense').classes('grow')

                    def target():
                        return core.normalize_url(nav_url.value, scheme.value)

                    async def browse():
                        ui.notify('Se abrirá una ventana de navegador aparte en tu escritorio. Ciérrala al terminar; no se guarda nada.', type='info')
                        await run.io_bound(recorder.open_browser, target())

                    async def record():
                        ui.notify('Se abrirán, aparte en tu escritorio, el navegador y el Inspector de grabación. Interactúa ahí y cierra el navegador para terminar.', type='info')
                        script = await run.io_bound(recorder.launch_codegen, target())
                        if not script.strip():
                            raise ValueError('No se generó ninguna grabación')
                        add_recorded(recorder.import_codegen(script))
                    ui.button('Navegar', icon='travel_explore', on_click=guard(browse)).props('outline dense no-caps')
                    ui.button('Grabar', icon='fiber_manual_record', on_click=guard(record)).props('dense no-caps color=negative')
                ui.label('«Navegar» solo mira: no cambia el caso. «Grabar» agrega al final de los pasos de abajo lo que hagas en la ventana.') \
                    .classes('text-xs text-gray-500 px-3')
                import_report = ui.column().classes('w-full gap-1 px-3')

                def add_recorded(result):
                    d['steps'].extend(result['steps'])
                    import_report.clear()
                    with import_report:
                        ui.label(f'{len(result["steps"])} paso(s) agregado(s), {len(result["unsupported"])} instrucción(es) no soportada(s).').classes('text-sm font-medium')
                        for item in result['unsupported']:
                            ui.label(f'⚠ Línea {item["line"]}: {item["reason"]}').classes('text-xs text-amber-700 font-mono')
                    step_rows.refresh()
                    ui.notify(f'{len(result["steps"])} paso(s) agregado(s) al caso', type='positive')

                ui.separator().classes('my-2')
                with ui.scroll_area().classes('w-full grow').style('min-height:0'):
                    with ui.column().classes('w-full gap-2 px-3 pb-3'):
                        ui.label('Pasos. Cada uno se ejecuta en orden. Los valores admiten {{variables}} del ambiente o del flujo.').classes('text-gray-500 text-sm')

                        @ui.refreshable
                        def step_rows():
                            for index, step in enumerate(d['steps']):
                                with ui.card().classes('w-full').props('flat bordered'):
                                    with ui.row().classes('w-full items-center gap-2 no-wrap'):
                                        ui.label(str(index + 1)).classes('w-6 text-gray-500')

                                        def change_action(event, s=step):
                                            needs = automation.STEP_ACTIONS[event.value]['needs']
                                            s['action'] = event.value
                                            if 'locator' in needs and not isinstance(s.get('locator'), dict):
                                                s['locator'] = {'by': 'label', 'value': ''}
                                            step_rows.refresh()
                                        ui.select({k: v['label'] for k, v in automation.STEP_ACTIONS.items()}, value=step['action'], on_change=change_action) \
                                            .props('outlined dense options-dense').classes('w-52')
                                        needs = automation.STEP_ACTIONS[step['action']]['needs']
                                        if 'locator' in needs:
                                            spec = step.setdefault('locator', {'by': 'label', 'value': ''})

                                            def change_by(event, sp=spec):
                                                sp.clear(); sp['by'] = event.value
                                                step_rows.refresh()
                                            ui.select(LOCATOR_LABELS, value=spec.get('by', 'label'), on_change=change_by).props('outlined dense').classes('w-44')
                                            if spec.get('by') == 'role':
                                                ui.select(ROLES, value=spec.get('role'), label='Rol', new_value_mode='add-unique', with_input=True) \
                                                    .props('outlined dense').classes('w-36').on_value_change(lambda e, sp=spec: sp.__setitem__('role', e.value))
                                                ui.input('Nombre accesible', value=spec.get('name', '')).props('outlined dense').classes('grow') \
                                                    .on_value_change(lambda e, sp=spec: sp.__setitem__('name', e.value))
                                            else:
                                                ui.input('Valor del locator', value=spec.get('value', '')).props('outlined dense').classes('grow') \
                                                    .on_value_change(lambda e, sp=spec: sp.__setitem__('value', e.value))
                                        if 'locator' in needs:
                                            ui.checkbox('1º', value=bool(step['locator'].get('first'))).props('dense').tooltip('Usar solo el primer elemento que coincida') \
                                                .on_value_change(lambda e, sp=step['locator']: sp.__setitem__('first', True) if e.value else sp.pop('first', None))
                                        for field in ('url', 'value', 'expected'):
                                            if field in needs:
                                                ui.input(FIELD_LABELS[field], value=str(step.get(field, ''))).props('outlined dense').classes('w-56' if 'locator' in needs else 'grow') \
                                                    .on_value_change(lambda e, s=step, f=field: s.__setitem__(f, e.value))
                                        ui.space()

                                        def move(delta, i=index):
                                            j = i + delta
                                            if 0 <= j < len(d['steps']):
                                                d['steps'][i], d['steps'][j] = d['steps'][j], d['steps'][i]
                                                step_rows.refresh()
                                        ui.button(icon='arrow_upward', on_click=lambda _, m=move: m(-1)).props('flat round dense').tooltip('Subir')
                                        ui.button(icon='arrow_downward', on_click=lambda _, m=move: m(1)).props('flat round dense').tooltip('Bajar')
                                        ui.button(icon='delete', on_click=lambda _, s=step: (d['steps'].remove(s), step_rows.refresh())).props('flat round dense color=negative').tooltip('Quitar')
                        W['step_rows'] = step_rows
                        step_rows()
                        ui.button('Agregar paso', icon='add', on_click=lambda: (d['steps'].append(blank_step()), step_rows.refresh())).props('outline color=primary')

        # ------------------------------------------------------------ right rail: grabador (pegar script) / guardar
        def right():
            with ui.row().classes('w-full h-full no-wrap gap-0'):
                with ui.tab_panels(None, value='Guardar').props('vertical').style('flex:1 1 0;min-width:0;overflow:auto;height:100%') as panels:
                    with ui.tab_panel('Grabador').classes('p-3 gap-2'):
                        ui.label('Pega un script de Playwright Codegen para analizarlo e importar sus pasos, sin abrir un navegador.').classes('text-xs text-gray-500')
                        pasted = ui.textarea('Script Python de Codegen').props('outlined autogrow').classes('w-full font-mono')
                        script_report = ui.column().classes('w-full gap-1')

                        def import_script():
                            result = recorder.import_codegen(pasted.value or '')
                            script_report.clear()
                            with script_report:
                                ui.label(f'{len(result["steps"])} paso(s) analizado(s); {len(result["unsupported"])} instrucción(es) no soportada(s).').classes('font-medium text-sm')
                                for item in result['unsupported']:
                                    ui.label(f'Línea {item["line"]}: {item["reason"]}').classes('text-xs text-amber-700 font-mono')
                                if result['steps']:
                                    ui.button('Agregar pasos al caso', icon='playlist_add', on_click=guard(lambda: add_recorded(result))).props('dense size=sm no-caps color=primary')
                        ui.button('Analizar script', icon='rule', on_click=guard(import_script)).props('outline dense size=sm no-caps')

                    with ui.tab_panel('Guardar').classes('p-3 gap-2'):
                        env_select = W['env_select'] = ui.select({e['id']: e['name'] for e in envs}, value=d.get('env_id'), label='Ambiente de prueba').props('outlined dense').classes('w-full') \
                            .on_value_change(lambda e: d.__setitem__('env_id', e.value))
                        W['timeout_input'] = ui.number('Timeout por paso (ms)', value=d['timeout_ms'], min=500, max=120000).props('outlined dense').classes('w-full') \
                            .on_value_change(lambda e: d.__setitem__('timeout_ms', e.value))
                        _creator = core.get('cases', d['id']) if d['id'] else None
                        if _creator and _creator.get('created_by'):
                            ui.label(f'Creado por: {core.user_display_name(_creator["created_by"])}').classes('text-xs text-gray-500')

                        def build():
                            if not (d['name'] or '').strip():
                                raise ValueError('El nombre es obligatorio')
                            problems = automation.validate_steps(d['steps'])
                            if problems:
                                raise ValueError('\n'.join(problems))
                            existing = core.get('cases', d['id']) if d['id'] else None
                            item = {'name': d['name'].strip(), 'type': 'ui', 'project_id': pid, 'timeout_ms': int(d['timeout_ms'] or 10000), 'steps': d['steps'],
                                    'created_by': (existing or {}).get('created_by') or current_user_id()}
                            if d['id']:
                                item['id'] = d['id']
                            return item

                        def save():
                            item = build()
                            saved = core.save('cases', item, expected_updated_at=d.get('updated_at')) if d['id'] else core.save('cases', item)
                            d['id'], d['updated_at'] = saved['id'], saved['updated_at']
                            refresh_all()
                            ui.notify(f'Caso UI «{saved["name"]}» guardado', type='positive')
                            return saved

                        async def save_and_run():
                            env = core.get('environments', env_select.value) if env_select.value else None
                            if env is None:
                                raise ValueError('Elige un ambiente para ejecutar')
                            saved = save()
                            with ui.dialog() as busy, ui.card():
                                ui.spinner(size='lg'); ui.label('Ejecutando en Chromium…')
                            busy.open()
                            try:
                                result = await run.io_bound(automation.execute_ui, saved, env, meta={'executed_by': current_user_id()})
                            finally:
                                busy.close()
                            refresh_all()
                            show_run(result)

                        def remove():
                            used = [s for s in core.list_items('suites') if d['id'] in s.get('case_ids', [])]
                            if used:
                                raise ValueError(f'No se puede eliminar: está en {len(used)} flujo(s)')
                            core.delete('cases', d['id'])
                            load_draft(new_draft())
                            ui.notify('Caso UI eliminado', type='warning')
                        with ui.row().classes('gap-1'):
                            ui.button('Guardar', icon='save', on_click=guard(save)).props('dense size=sm no-caps')
                            ui.button('Guardar y ejecutar', icon='play_arrow', on_click=guard(save_and_run)).props('outline dense size=sm no-caps color=positive')
                        if d['id']:
                            ui.button('Eliminar caso', icon='delete', on_click=lambda: confirm('¿Eliminar este caso UI?', remove)).props('flat dense size=sm no-caps color=negative')
                with ui.tabs().props('vertical dense no-caps').classes('shrink-0').style('width:56px;border-left:1px solid #e5e7eb') as rail:
                    for name, icon in (('Grabador', 'movie'), ('Guardar', 'save')):
                        ui.tab(name, label='', icon=icon).tooltip(name)
                panels.bind_value_from(rail, 'value')
                rail.set_value('Guardar')

        with ui.element('div').classes('w-full').style('height: calc(100vh - 50px)'):
            with ui.splitter(value=19, limits=(12, 35)).classes('w-full').style('height:100%') as outer:
                with outer.before:
                    with ui.element('div').classes('ltw-pane'):
                        left()
                with outer.after:
                    with ui.splitter(value=70, limits=(40, 85)).classes('w-full').style('height:100%') as inner:
                        with inner.before:
                            with ui.element('div').classes('ltw-pane').style('display:flex;flex-direction:column'):
                                center()
                        with inner.after:
                            with ui.element('div').classes('ltw-pane').style('overflow:hidden'):
                                right()
