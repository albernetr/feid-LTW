import json
from nicegui import ui, run
from .. import core, automation
from .common import frame, guard, confirm, empty_state, require_project, kv_editor, show_run, status_badge, parse_value, show_value


async def run_suite(suite):
    token = automation.new_cancel_token()
    progress = []
    with ui.dialog().props('persistent') as dialog, ui.card().classes('w-96'):
        ui.label(f'Ejecutando «{suite["name"]}»').classes('text-lg font-semibold')
        ui.linear_progress(show_value=False).props('indeterminate')
        status = ui.label('Iniciando…').classes('text-gray-600 text-sm')

        def cancel():
            token.set()
            status.set_text('Cancelando tras el caso en curso…')
        ui.button('Cancelar ejecución', icon='stop', on_click=cancel).props('outline color=negative')
    dialog.open()
    timer = ui.timer(0.5, lambda: status.set_text(f'{len(progress)} de {len(suite["case_ids"])} casos terminados'))
    try:
        result = await run.io_bound(automation.execute_suite, suite, token, progress.append)
    finally:
        timer.cancel()
        dialog.close()
    show_run(result)
    return result


def flow_summary(suite):
    """'Identidad → Pedidos' when the suite crosses environments (modules)."""
    names = []
    default = core.get('environments', suite.get('environment_id'))
    for step in core.suite_steps(suite):
        env = core.get('environments', step['environment_id']) if step.get('environment_id') else default
        name = env['name'] if env else 'ambiente eliminado'
        if not names or names[-1] != name:
            names.append(name)
    enriched = sum(1 for s in suite.get('steps') or [] if s.get('enrich'))
    return ' → '.join(names), enriched


@ui.page('/suites')
def suites_list():
    with frame('Suites y flujos', '/suites'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.button('Nueva suite / flujo', icon='add', on_click=lambda: ui.navigate.to('/suites/edit')).props('color=primary')
        items = core.list_project_items('suites', pid)
        if not items:
            empty_state('No hay suites. Agrupa casos en el orden en que deben ejecutarse; cada paso puede apuntar a otro módulo.')
        for suite in items:
            route, enriched = flow_summary(suite)
            with ui.card().classes('w-full'):
                with ui.row().classes('items-center gap-3 w-full no-wrap'):
                    with ui.column().classes('gap-0 grow'):
                        ui.label(suite['name']).classes('font-semibold')
                        policy = 'se detiene al primer fallo' if suite.get('on_failure') == 'stop' else 'continúa tras fallos'
                        ui.label(f'{len(suite["case_ids"])} casos · {route} · {policy} · {suite.get("retries", 0)} reintento(s)'
                                 + (f' · {enriched} paso(s) enriquecido(s)' if enriched else '')).classes('text-sm text-gray-500')
                    ui.button(icon='play_arrow', on_click=guard(lambda s=suite: run_suite(s))).props('flat round color=positive').tooltip('Ejecutar')
                    ui.button(icon='edit', on_click=lambda _, i=suite['id']: ui.navigate.to(f'/suites/edit?id={i}')).props('flat round').tooltip('Editar')

                    def remove(s=suite):
                        used = [x for x in core.list_items('schedules') if x.get('suite_id') == s['id']]
                        if used:
                            raise ValueError(f'No se puede eliminar: tiene {len(used)} programación(es)')
                        core.delete('suites', s['id'])
                        ui.navigate.reload()
                    ui.button(icon='delete', on_click=lambda _, s=suite, r=remove: confirm(f'¿Eliminar la suite «{s["name"]}»?', r)).props('flat round color=negative')


TARGET_HINT = {'body': 'Ruta JSON ($.cliente.id)', 'headers': 'Nombre del header', 'query': 'Nombre del parámetro'}


def enrichment_dialog(steps, index, on_close):
    """Technical users add or modify fields of THIS step's request using data from earlier steps."""
    step = steps[index]
    ops = step.setdefault('enrich', [])
    previous = [s['alias'] for s in steps[:index]]
    with ui.dialog() as dialog, ui.card().classes('w-[1000px] max-w-full'):
        ui.label(f'Enriquecer el request del paso «{step["alias"]}»').classes('text-lg font-semibold')
        ui.label('Agrega o modifica campos de lo que se enviará en este paso, con datos de la respuesta de pasos anteriores (incluso de otros módulos). '
                 'No cambia el caso: solo aplica dentro de esta suite.').classes('text-sm text-gray-600')

        @ui.refreshable
        def rows():
            if not ops:
                ui.label('Sin reglas: este paso se envía tal como lo define su caso.').classes('text-gray-500')
            for op in ops:
                with ui.card().classes('w-full').props('flat bordered'):
                    with ui.row().classes('w-full items-center gap-2 no-wrap'):
                        ui.select(core.ENRICH_ACTIONS, value=op['action'], on_change=lambda e, o=op: (o.__setitem__('action', e.value), rows.refresh())).props('outlined dense').classes('w-48')
                        ui.select(core.ENRICH_TARGETS, value=op['target'], on_change=lambda e, o=op: (o.__setitem__('target', e.value), rows.refresh())).props('outlined dense').classes('w-32')
                        if op['target'] != 'path':
                            ui.input(TARGET_HINT[op['target']] + (' (opcional si combinas)' if op['action'] == 'merge' else ''), value=op.get('path', '')) \
                                .props('outlined dense').classes('grow').on_value_change(lambda e, o=op: o.__setitem__('path', e.value))
                        else:
                            ui.label('Reemplaza la ruta de la petición').classes('grow text-sm text-gray-500')
                        ui.button(icon='delete', on_click=lambda _, o=op: (ops.remove(o), rows.refresh())).props('flat round dense color=negative').tooltip('Quitar regla')
                    if op['action'] != 'remove':
                        source = op.setdefault('source', {'type': 'literal', 'value': ''})

                        def change_type(e, s=source):
                            keep = {'type': e.value}
                            if e.value == 'literal':
                                keep['value'] = ''
                            s.clear(); s.update(keep)
                            rows.refresh()
                        with ui.row().classes('w-full items-center gap-2 no-wrap'):
                            ui.label('←').classes('text-gray-500')
                            ui.select(core.SOURCE_TYPES, value=source.get('type', 'literal'), on_change=change_type).props('outlined dense').classes('w-64')
                            kind = source.get('type', 'literal')
                            if kind == 'literal':
                                ui.input('Valor (número, true/false, JSON o texto)', value=show_value(source.get('value', ''))).props('outlined dense').classes('grow') \
                                    .on_value_change(lambda e, s=source: s.__setitem__('value', parse_value(e.value)))
                            elif kind == 'step':
                                if previous:
                                    ui.select(previous, value=source.get('step'), label='Paso').props('outlined dense').classes('w-48') \
                                        .on_value_change(lambda e, s=source: s.__setitem__('step', e.value))
                                    ui.input('Ruta en su respuesta (vacío = toda)', value=source.get('path', ''), placeholder='$.data.id').props('outlined dense').classes('grow') \
                                        .on_value_change(lambda e, s=source: s.__setitem__('path', e.value))
                                else:
                                    ui.label('No hay pasos anteriores a este.').classes('text-amber-700')
                            elif kind == 'var':
                                ui.input('Nombre de la variable', value=source.get('name', '')).props('outlined dense').classes('grow') \
                                    .on_value_change(lambda e, s=source: s.__setitem__('name', e.value))
                            else:
                                ui.input('Texto (usa {{@paso:$.ruta}} y {{variable}})', value=source.get('value', ''), placeholder='Bearer {{@login:$.token}}') \
                                    .props('outlined dense').classes('grow').on_value_change(lambda e, s=source: s.__setitem__('value', e.value))
        rows()
        ui.button('Agregar regla', icon='add', on_click=lambda: (ops.append({'action': 'set', 'target': 'body', 'path': '$.', 'source': {'type': 'literal', 'value': ''}}), rows.refresh())).props('outline color=primary')

        ui.separator()
        ui.label('Vista previa de lo que se enviará').classes('font-semibold')
        ui.label('Usa la última respuesta registrada de cada paso anterior (si aún no hay, ejecuta la suite una vez). No envía nada.').classes('text-sm text-gray-500')
        output = ui.column().classes('w-full gap-1')

        def preview():
            output.clear()
            problems = core.validate_enrichment(ops, previous)
            with output:
                if problems:
                    for problem in problems:
                        ui.label(problem).classes('text-red-700 text-sm')
                    return
                result = core.preview_step(steps, index)
                ui.label(f'{result["method"]} {result["request"]["path"]}').classes('font-mono')
                if result['request']['headers']:
                    ui.code(json.dumps(result['request']['headers'], indent=2, ensure_ascii=False), language='json').classes('w-full')
                if result['request']['query']:
                    ui.code(json.dumps(result['request']['query'], indent=2, ensure_ascii=False), language='json').classes('w-full')
                ui.code(json.dumps(result['request']['body'], indent=2, ensure_ascii=False) if result['request']['body'] is not None else '(sin body)', language='json').classes('w-full')
                for line in result['applied']:
                    ui.label('✓ ' + line).classes('text-sm text-green-800')
                for line in result['problems']:
                    ui.label('✗ ' + line).classes('text-sm text-red-700')
                if result['without_history']:
                    ui.label('Sin datos registrados de: ' + ', '.join(result['without_history']) + '. Ejecuta la suite una vez para ver valores reales.').classes('text-sm text-amber-700')
        with ui.row().classes('w-full justify-between'):
            ui.button('Vista previa', icon='visibility', on_click=guard(preview)).props('outline')

            def close():
                dialog.close()
                on_close()
            ui.button('Listo', icon='check', on_click=close).props('color=primary')
    dialog.open()


@ui.page('/suites/edit')
def suite_edit(id: str = ''):
    with frame('Editor de suite / flujo', '/suites'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        current = core.get('suites', id) if id else None
        if id and current is None:
            ui.label('La suite no existe.')
            return
        envs = core.list_project_items('environments', pid)
        cases = {c['id']: c for c in core.list_project_items('cases', pid)}
        if not envs or not cases:
            ui.label('Necesitas al menos un ambiente y un caso en este proyecto.').classes('text-amber-700')
            return
        steps = [dict(s, enrich=[dict(op, source=dict(op.get('source') or {})) for op in s.get('enrich') or []]) for s in core.suite_steps(current)] if current else []
        steps = [s for s in steps if s['case_id'] in cases]
        variables = dict((current or {}).get('variables', {}))

        with ui.card().classes('w-full'):
            with ui.row().classes('w-full gap-3'):
                name = ui.input('Nombre', value=(current or {}).get('name', 'Smoke')).props('outlined dense').classes('grow')
                env = ui.select({e['id']: e['name'] for e in envs}, value=(current or {}).get('environment_id', envs[0]['id']), label='Ambiente por defecto').props('outlined dense').classes('w-60')
            with ui.row().classes('w-full gap-3 items-center'):
                on_failure = ui.select({'continue': 'Continuar tras un fallo', 'stop': 'Detener al primer fallo'}, value=(current or {}).get('on_failure', 'continue'), label='Política de fallo').props('outlined dense').classes('w-64')
                retries = ui.number('Reintentos por caso', value=(current or {}).get('retries', 0), min=0, max=5, precision=0).props('outlined dense').classes('w-44')
                delay = ui.number('Espera entre reintentos (s)', value=(current or {}).get('retry_delay_s', 0), min=0, max=300).props('outlined dense').classes('w-56')

        with ui.row().classes('w-full gap-4 items-start no-wrap'):
            with ui.card().classes('w-1/3'):
                ui.label('Casos disponibles').classes('font-semibold')
                ui.input('Filtrar').props('outlined dense clearable').classes('w-full').on_value_change(lambda e: available.refresh(e.value or ''))

                @ui.refreshable
                def available(text=''):
                    shown = [c for c in cases.values() if text.lower() in c['name'].lower()]
                    if not shown:
                        ui.label('Sin coincidencias').classes('text-gray-500')
                    for case in shown:
                        with ui.row().classes('items-center w-full gap-2 no-wrap'):
                            ui.badge('UI' if case.get('type') == 'ui' else case.get('method', 'API'), color='secondary' if case.get('type') == 'ui' else 'primary').classes('w-14 justify-center')
                            ui.label(case['name']).classes('grow')

                            def add(c=case):
                                alias = core.slugify_alias(c['name'], [s['alias'] for s in steps])
                                steps.append({'case_id': c['id'], 'alias': alias, 'environment_id': None, 'enrich': []})
                                chosen.refresh()
                            ui.button(icon='add', on_click=lambda _, f=add: f()).props('flat round dense color=primary').tooltip('Agregar al final')
                available()
            with ui.card().classes('w-2/3'):
                ui.label('Orden de ejecución (cada paso puede apuntar a otro ambiente/módulo)').classes('font-semibold')

                @ui.refreshable
                def chosen():
                    if not steps:
                        ui.label('Agrega casos desde la izquierda.').classes('text-gray-500')
                    for index, step in enumerate(steps):
                        with ui.row().classes('items-center w-full gap-2 no-wrap'):
                            ui.label(f'{index + 1}.').classes('w-6 text-gray-500')
                            with ui.column().classes('gap-0 grow'):
                                ui.label(cases[step['case_id']]['name']).classes('font-medium')
                                ui.input('Nombre del paso', value=step['alias']).props('outlined dense').classes('w-44') \
                                    .on_value_change(lambda e, s=step: s.__setitem__('alias', (e.value or '').strip()))
                            ui.select({'': 'Ambiente por defecto', **{e['id']: e['name'] for e in envs}}, value=step.get('environment_id') or '', label='Ambiente / módulo') \
                                .props('outlined dense').classes('w-52').on_value_change(lambda e, s=step: s.__setitem__('environment_id', e.value or None))
                            count = len(step.get('enrich') or [])
                            if cases[step['case_id']].get('type') != 'ui':
                                ui.button(f'Enriquecer ({count})' if count else 'Enriquecer', icon='auto_fix_high',
                                          on_click=lambda _, i=index: enrichment_dialog(steps, i, chosen.refresh)).props('outline dense' + (' color=primary' if count else ''))

                            def move(delta, i=index):
                                j = i + delta
                                if 0 <= j < len(steps):
                                    steps[i], steps[j] = steps[j], steps[i]
                                    chosen.refresh()
                            ui.button(icon='arrow_upward', on_click=lambda _, m=move: m(-1)).props('flat round dense')
                            ui.button(icon='arrow_downward', on_click=lambda _, m=move: m(1)).props('flat round dense')
                            ui.button(icon='close', on_click=lambda _, i=index: (steps.pop(i), chosen.refresh())).props('flat round dense color=negative')
                chosen()
                ui.label('Un paso solo puede usar respuestas de pasos que estén ANTES que él; si reordenas, se vuelve a validar al guardar.').classes('text-xs text-gray-500')

        with ui.expansion('Variables compartidas iniciales', icon='data_object').classes('w-full border rounded'):
            ui.label('Disponibles como {{nombre}} en todos los casos. Los valores extraídos por un caso se suman para los siguientes.').classes('text-gray-500 text-sm')
            kv_editor(variables, 'Variable', 'Valor')

        def save():
            options = dict(id=(current or {}).get('id'), on_failure=on_failure.value, retries=int(retries.value or 0), retry_delay_s=float(delay.value or 0),
                           variables={k: v for k, v in variables.items() if k.strip()}, steps=steps)
            if current:
                options['expected_updated_at'] = current.get('updated_at')       # refuse to overwrite someone else's changes
            saved = core.save_suite(name.value or '', env.value, [], pid, **options)
            if current:
                current['updated_at'] = saved['updated_at']
            ui.notify('Suite guardada', type='positive')
            return saved
        with ui.row().classes('gap-3'):
            ui.button('Guardar', icon='save', on_click=guard(lambda: (save(), ui.navigate.to('/suites')))).props('color=primary')

            async def save_and_run():
                await run_suite(save())
            ui.button('Guardar y ejecutar', icon='play_arrow', on_click=guard(save_and_run)).props('outline color=positive')
            ui.button('Volver', on_click=lambda: ui.navigate.to('/suites')).props('flat')
