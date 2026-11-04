import asyncio
import json
from nicegui import ui, run
from .. import core, automation
from .common import frame, guard, confirm, empty_state, require_project, kv_editor, show_run, status_badge, parse_value, show_value
from .widgets import assertion_rows, json_box, dynamic_variable_chips
from .cases import HTTP_METHODS


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


def _ask_count(title, hint, run_label):
    """Diálogo chico: pide una cantidad N y devuelve una promesa que resuelve con ese N (o None si cancelan)."""
    result = asyncio.get_running_loop().create_future()
    with ui.dialog() as dialog, ui.card().classes('w-80'):
        ui.label(title).classes('text-lg font-semibold')
        if hint:
            ui.label(hint).classes('text-sm text-gray-500')
        count = ui.number('Cantidad', value=10, min=1, max=500, precision=0).props('outlined dense autofocus').classes('w-full')
        with ui.row().classes('w-full justify-end gap-2'):
            def cancel():
                dialog.close()
                if not result.done():
                    result.set_result(None)
            def confirm_count():
                dialog.close()
                if not result.done():
                    result.set_result(int(count.value or 0))
            ui.button('Cancelar', on_click=cancel).props('flat')
            ui.button(run_label, icon='play_arrow', on_click=confirm_count).props('color=primary')
    dialog.open()
    return result


async def run_suite_many(suite):
    count = await _ask_count(f'Ejecutar «{suite["name"]}» varias veces', 'Cada corrida vuelve a sortear sus Sorteos y sus {{random:…}} de forma independiente. Queda registrada en el Historial, no se guarda nada nuevo.', 'Ejecutar')
    if not count:
        return
    token = automation.new_cancel_token()
    progress = {'done': 0, 'passed': 0}
    with ui.dialog().props('persistent') as dialog, ui.card().classes('w-96'):
        ui.label(f'Ejecutando «{suite["name"]}» × {count}').classes('text-lg font-semibold')
        ui.linear_progress(show_value=False).props('indeterminate')
        status = ui.label('Iniciando…').classes('text-gray-600 text-sm')

        def cancel():
            token.set()
            status.set_text('Cancelando tras la corrida en curso…')
        ui.button('Cancelar', icon='stop', on_click=cancel).props('outline color=negative')
    dialog.open()

    def on_run(index, result):
        progress['done'] = index
        if result['status'] == 'passed':
            progress['passed'] += 1
    timer = ui.timer(0.5, lambda: status.set_text(f'{progress["done"]} de {count} corridas · {progress["passed"]} pasaron'))
    try:
        summary = await run.io_bound(automation.execute_suite_many, suite, count, token, on_run)
    finally:
        timer.cancel()
        dialog.close()
    with ui.dialog() as result_dialog, ui.card().classes('w-[520px] max-w-full'):
        ok = summary['passed'] == summary['completed'] and summary['completed'] == summary['total']
        ui.label(f'{summary["passed"]} de {summary["completed"]} pasaron' + (f' (se canceló tras {summary["completed"]} de {summary["total"]})' if summary['completed'] < summary['total'] else '')) \
            .classes('text-lg font-semibold ' + ('text-positive' if ok else 'text-negative'))
        with ui.column().classes('w-full gap-1').style('max-height:300px;overflow:auto'):
            for index, run_doc in enumerate(summary['runs'], 1):
                with ui.row().classes('items-center gap-2'):
                    status_badge(run_doc['status'])
                    ui.label(f'Corrida {index}').classes('text-sm')
                    ui.button('Ver', on_click=lambda _, r=run_doc: show_run(r)).props('flat dense size=sm')
        ui.button('Cerrar', on_click=result_dialog.close).props('color=primary')
    result_dialog.open()


async def generate_suite_variants(suite):
    count = await _ask_count(f'Generar copias de «{suite["name"]}»', 'Crea N flujos nuevos, cada uno con sus Sorteos ya resueltos a valores fijos — quedan como flujos propios, editables y re-ejecutables.', 'Generar')
    if not count:
        return
    created = await run.io_bound(core.materialize_suite_variants, suite, count)
    ui.notify(f'{len(created)} flujo(s) generado(s)', type='positive')
    ui.navigate.reload()


def feature_name(suite):
    feature = core.get('features', suite.get('feature_id')) if suite.get('feature_id') else None
    return feature['name'] if feature else None


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
    with frame('Flujos', '/suites'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.button('Nuevo flujo', icon='add', on_click=lambda: ui.navigate.to('/suites/edit')).props('color=primary')
        items = core.list_project_items('suites', pid)
        if not items:
            empty_state('No hay flujos. Agrupa casos en el orden en que deben ejecutarse; cada paso puede apuntar a otro ambiente/componente.')
        for suite in items:
            route, enriched = flow_summary(suite)
            with ui.card().classes('w-full'):
                with ui.row().classes('items-center gap-3 w-full no-wrap'):
                    with ui.column().classes('gap-0 grow'):
                        with ui.row().classes('items-center gap-2'):
                            ui.label(suite['name']).classes('font-semibold')
                            fname = feature_name(suite)
                            if fname:
                                ui.badge(fname, color='pink')
                        policy = 'se detiene al primer fallo' if suite.get('on_failure') == 'stop' else 'continúa tras fallos'
                        ui.label(f'{len(suite["case_ids"])} casos · {route} · {policy} · {suite.get("retries", 0)} reintento(s)'
                                 + (f' · {enriched} paso(s) enriquecido(s)' if enriched else '')).classes('text-sm text-gray-500')
                    ui.button(icon='play_arrow', on_click=guard(lambda s=suite: run_suite(s))).props('flat round color=positive').tooltip('Ejecutar')
                    ui.button(icon='repeat', on_click=guard(lambda s=suite: run_suite_many(s))).props('flat round color=positive').tooltip('Ejecutar N veces (datos aleatorios distintos en cada una)')
                    ui.button(icon='dynamic_feed', on_click=guard(lambda s=suite: generate_suite_variants(s))).props('flat round').tooltip('Generar N copias con sus Sorteos ya resueltos')
                    ui.button(icon='edit', on_click=lambda _, i=suite['id']: ui.navigate.to(f'/suites/edit?id={i}')).props('flat round').tooltip('Editar')

                    def duplicate(s=suite):
                        copy_item = {k: v for k, v in s.items() if k not in ('id', 'updated_at')}
                        copy_item['name'] = s['name'] + ' (copia)'
                        core.save('suites', copy_item)
                        ui.navigate.reload()
                    ui.button(icon='content_copy', on_click=guard(duplicate)).props('flat round').tooltip('Duplicar')

                    def remove(s=suite):
                        used = [x for x in core.list_items('schedules') if x.get('suite_id') == s['id']]
                        if used:
                            raise ValueError(f'No se puede eliminar: tiene {len(used)} programación(es)')
                        core.delete('suites', s['id'])
                        ui.navigate.reload()
                    ui.button(icon='delete', on_click=lambda _, s=suite, r=remove: confirm(f'¿Eliminar el flujo «{s["name"]}»?', r)).props('flat round color=negative')


TARGET_HINT = {'body': 'Ruta JSON ($.cliente.id)', 'headers': 'Nombre del header', 'query': 'Nombre del parámetro'}


def enrichment_dialog(steps, index, on_close):
    """Technical users add or modify fields of THIS step's request using data from earlier steps."""
    step = steps[index]
    ops = step.setdefault('enrich', [])
    previous = [s['alias'] for s in steps[:index]]
    with ui.dialog() as dialog, ui.card().classes('w-[1000px] max-w-full'):
        ui.label(f'Enriquecer el request del paso «{step["alias"]}»').classes('text-lg font-semibold')
        ui.label('Agrega o modifica campos de lo que se enviará en este paso, con datos de la respuesta de pasos anteriores (incluso de otros componentes). '
                 'No cambia el caso: solo aplica dentro de este flujo.').classes('text-sm text-gray-600')

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
        ui.label('Usa la última respuesta registrada de cada paso anterior (si aún no hay, ejecuta el flujo una vez). No envía nada.').classes('text-sm text-gray-500')
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
                    ui.label('Sin datos registrados de: ' + ', '.join(result['without_history']) + '. Ejecuta el flujo una vez para ver valores reales.').classes('text-sm text-amber-700')
        with ui.row().classes('w-full justify-between'):
            ui.button('Vista previa', icon='visibility', on_click=guard(preview)).props('outline')

            def close():
                dialog.close()
                on_close()
            ui.button('Listo', icon='check', on_click=close).props('color=primary')
    dialog.open()


@ui.page('/suites/edit')
def suite_edit(id: str = ''):
    with frame('Editor de flujo', '/suites'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        current = core.get('suites', id) if id else None
        if id and current is None:
            ui.label('El flujo no existe.')
            return
        envs = core.list_project_items('environments', pid)
        cases = {c['id']: c for c in core.list_project_items('cases', pid)}
        if not envs or not cases:
            ui.label('Necesitas al menos un ambiente y un caso en este proyecto.').classes('text-amber-700')
            return
        steps = [dict(s, enrich=[dict(op, source=dict(op.get('source') or {})) for op in s.get('enrich') or []]) for s in core.suite_steps(current)] if current else []
        steps = [s for s in steps if s['case_id'] in cases]
        variables = dict((current or {}).get('variables', {}))
        draws = [dict(d) for d in (current or {}).get('draws', [])]
        datasets = core.list_project_items('datasets', pid)
        view = {'mode': 'suite', 'case_id': None}   # 'suite' | 'case' — qué se muestra debajo de la tarjeta de datos de la suite

        def edit_case(cid):
            view.update(mode='case', case_id=cid)
            content.refresh()

        def back_to_suite():
            view.update(mode='suite', case_id=None)
            content.refresh()

        features = core.list_project_items('features', pid)
        with ui.card().classes('w-full'):
            with ui.row().classes('w-full gap-3'):
                name = ui.input('Nombre', value=(current or {}).get('name', 'Smoke')).props('outlined dense').classes('grow')
                env = ui.select({e['id']: e['name'] for e in envs}, value=(current or {}).get('environment_id', envs[0]['id']), label='Ambiente por defecto').props('outlined dense').classes('w-60')
                feature = ui.select({f['id']: f['name'] for f in features}, value=(current or {}).get('feature_id'), label='Funcionalidad (opcional)', clearable=True) \
                    .props('outlined dense').classes('w-60').mark('suite-feature')
                if not features:
                    ui.label('Crea Funcionalidades para ligar este flujo a una capacidad de negocio.').classes('text-xs text-gray-500 self-center')
            with ui.row().classes('w-full gap-3 items-center'):
                on_failure = ui.select({'continue': 'Continuar tras un fallo', 'stop': 'Detener al primer fallo'}, value=(current or {}).get('on_failure', 'continue'), label='Política de fallo').props('outlined dense').classes('w-64')
                retries = ui.number('Reintentos por caso', value=(current or {}).get('retries', 0), min=0, max=5, precision=0).props('outlined dense').classes('w-44')
                delay = ui.number('Espera entre reintentos (s)', value=(current or {}).get('retry_delay_s', 0), min=0, max=300).props('outlined dense').classes('w-56')

        all_tags = sorted({t for c in cases.values() for t in c.get('tags', [])})
        selected_tag = {'value': None}

        def filtered_cases(text):
            text = (text or '').lower()
            return [c for c in cases.values() if text in c['name'].lower() and (not selected_tag['value'] or selected_tag['value'] in c.get('tags', []))]

        def case_detail(case_id):
            """Edición rápida de un caso (headers, query, body, aserciones) en la misma área de trabajo, con un
            botón para volver a la suite — en vez de una modal, o de navegar a Casos API y perder el borrador de
            la suite en curso. No toca el componente/contrato ni el encadenamiento (extracción) del caso; para
            eso sigue estando el editor completo."""
            case = core.get('cases', case_id)
            ui.button('← Volver al flujo', on_click=back_to_suite).props('flat dense no-caps').classes('mb-1')
            if case is None:
                ui.label('El caso ya no existe.').classes('text-amber-700')
                return
            with ui.card().classes('w-full gap-2'):
                ui.label(f'Editando «{case["name"]}»').classes('text-lg font-semibold')
                ui.label('Cambios rápidos, sin salir del flujo. El componente/contrato y el encadenamiento del caso se editan en Casos API.').classes('text-xs text-gray-500')
                headers = {k: str(v) for k, v in (case.get('headers') or {}).items()}
                query = {k: str(v) for k, v in (case.get('query') or {}).items()}
                case_vars = {k: str(v) for k, v in (case.get('variables') or {}).items()}
                rules = [dict(r) for r in case.get('assertions', [])]
                body_state = {'value': case.get('body')}
                cname = ui.input('Nombre', value=case['name']).props('outlined dense').classes('w-full')
                with ui.row().classes('w-full gap-3'):
                    method = ui.select(HTTP_METHODS, value=case.get('method', 'GET'), label='Método').props('outlined dense').classes('w-32')
                    path = ui.input('Ruta', value=case.get('path', '/')).props('outlined dense').classes('grow')
                with ui.tabs().classes('w-full') as tabs:
                    tab_req = ui.tab('Petición')
                    tab_assert = ui.tab('Aserciones')
                with ui.tab_panels(tabs, value=tab_req).classes('w-full'):
                    with ui.tab_panel(tab_req):
                        ui.label('Headers').classes('font-medium text-sm')
                        kv_editor(headers, 'Header', 'Valor')
                        ui.label('Query params').classes('font-medium text-sm')
                        kv_editor(query, 'Parámetro', 'Valor')
                        ui.label('Variables').classes('font-medium text-sm')
                        ui.label('{{nombre}} en headers/query/body de este caso, propias de él (además de las del flujo y del ambiente).').classes('text-xs text-gray-500')
                        kv_editor(case_vars, 'Nombre', 'Valor')
                        dynamic_variable_chips()
                        ui.label('Body (JSON)').classes('font-medium text-sm')
                        json_box(body_state['value'], lambda v: body_state.__setitem__('value', v))
                    with ui.tab_panel(tab_assert):
                        assertion_rows(lambda: rules)
                with ui.row().classes('gap-3'):
                    def save_case():
                        if not (cname.value or '').strip():
                            raise ValueError('El nombre es obligatorio')
                        for index, rule in enumerate(rules, 1):
                            problem = core.validate_assertion_rule(rule)
                            if problem:
                                raise ValueError(f'Aserción {index}: {problem}')
                        updated = core.save('cases', {**case, 'name': cname.value.strip(), 'method': method.value, 'path': (path.value or '/').strip(),
                                            'headers': {k: v for k, v in headers.items() if k.strip()}, 'query': {k: v for k, v in query.items() if k.strip()},
                                            'variables': {k: v for k, v in case_vars.items() if k.strip()},
                                            'body': body_state['value'], 'assertions': rules})
                        cases[case_id] = updated   # para que la suite lo muestre actualizado al volver, sin recargar la página
                        ui.notify('Caso actualizado', type='positive')
                    ui.button('Guardar', icon='save', on_click=guard(save_case)).props('color=primary')
                    ui.button('Volver al flujo', icon='arrow_back', on_click=back_to_suite).props('flat')

        def suite_body():
            with ui.row().classes('w-full gap-4 items-start no-wrap'):
                with ui.card().classes('w-1/3'):
                    ui.label('Casos disponibles').classes('font-semibold')
                    filter_input = ui.input('Filtrar por nombre').props('outlined dense clearable').classes('w-full').on_value_change(lambda e: available.refresh(e.value or ''))
                    if all_tags:
                        # Con cientos de casos (p. ej. un proyecto explorado automáticamente desde un contrato grande),
                        # agregarlos uno por uno buscando por nombre es poco práctico — filtrar por etiqueta acota la
                        # lista a un grupo manejable, y «Agregar los N visibles» los suma todos de una vez.
                        with ui.row().classes('items-center gap-1 flex-wrap'):
                            ui.label('Etiquetas:').classes('text-xs text-gray-500')
                            for tag in all_tags:
                                def pick_tag(_, t=tag):
                                    selected_tag['value'] = None if selected_tag['value'] == t else t
                                    available.refresh(filter_input.value or '')
                                ui.chip(tag, selectable=True, on_click=pick_tag).props('dense size=sm outline color=primary')

                    # Altura acotada con scroll propio: sin esto, un proyecto con cientos de casos (p. ej. uno
                    # explorado automáticamente desde un contrato grande) estira toda la página varios miles de
                    # píxeles y los botones Guardar quedan enterrados al final de la lista completa.
                    with ui.column().classes('w-full gap-1').style('max-height:60vh;overflow-y:auto'):
                        @ui.refreshable
                        def available(text=''):
                            shown = filtered_cases(text)
                            if not shown:
                                ui.label('Sin coincidencias').classes('text-gray-500')

                            def add_all():
                                for c in shown:
                                    alias = core.slugify_alias(c['name'], [s['alias'] for s in steps])
                                    steps.append({'case_id': c['id'], 'alias': alias, 'environment_id': None, 'enrich': []})
                                chosen.refresh()
                                available.refresh(filter_input.value or '')
                                ui.notify(f'{len(shown)} caso(s) agregados', type='positive')
                            if len(shown) > 1:
                                ui.button(f'Agregar los {len(shown)} visibles', icon='playlist_add', on_click=guard(add_all)) \
                                    .props('outline dense size=sm color=primary no-caps').classes('mb-1')
                            for case in shown:
                                added = sum(1 for s in steps if s['case_id'] == case['id'])
                                with ui.row().classes('items-center w-full gap-2 no-wrap'):
                                    ui.badge('UI' if case.get('type') == 'ui' else case.get('method', 'API'), color='secondary' if case.get('type') == 'ui' else 'primary').classes('w-14 justify-center shrink-0')
                                    # 'min-width:0' es necesario: sin él, un label dentro de una fila 'no-wrap' no se
                                    # achica más allá de su contenido y empuja al ícono/botón fuera del área visible
                                    # — invisible del todo una vez que el contenedor con scroll empieza a recortar
                                    # también el eje horizontal (efecto colateral de 'overflow-y:auto').
                                    ui.label(case['name']).classes('grow').style('min-width:0')
                                    if added:
                                        # Sigue en la lista (no desaparece): un flujo puede necesitar el mismo caso más de una
                                        # vez (p. ej. el mismo endpoint llamado dos veces con un consecutivo propio de la
                                        # suite) — solo se marca cuántas veces ya está agregado, para no perder el rastro.
                                        ui.badge(f'Agregado ×{added}' if added > 1 else 'Agregado', color='positive').classes('shrink-0 text-xs')
                                    if case['name'].startswith('[auto-explorado]'):
                                        ui.icon('warning', color='amber', size='xs').classes('shrink-0') \
                                            .tooltip('Guarda un ID real capturado al momento de explorar. Si ese dato se borra o cambia en el '
                                                     'servicio, el caso empieza a fallar — no es un bug de la suite, es el caso el que quedó obsoleto.')

                                    if case.get('type') != 'ui':
                                        ui.button(icon='edit', on_click=lambda _, cid=case['id']: edit_case(cid)) \
                                            .props('flat round dense').classes('shrink-0').tooltip('Editar caso')

                                    def add(c=case):
                                        alias = core.slugify_alias(c['name'], [s['alias'] for s in steps])
                                        steps.append({'case_id': c['id'], 'alias': alias, 'environment_id': None, 'enrich': []})
                                        chosen.refresh()
                                        available.refresh(filter_input.value or '')
                                    ui.button(icon='add', on_click=lambda _, f=add: f()).props('flat round dense color=primary').classes('shrink-0') \
                                        .tooltip('Agregar otra vez' if added else 'Agregar al final')
                        available()
                with ui.card().classes('w-2/3'):
                    ui.label('Orden de ejecución (cada paso puede apuntar a otro ambiente/componente)').classes('font-semibold')

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
                                ui.select({'': 'Ambiente por defecto', **{e['id']: e['name'] for e in envs}}, value=step.get('environment_id') or '', label='Ambiente') \
                                    .props('outlined dense').classes('w-52').on_value_change(lambda e, s=step: s.__setitem__('environment_id', e.value or None))
                                count = len(step.get('enrich') or [])
                                if cases[step['case_id']].get('type') != 'ui':
                                    ui.button(f'Enriquecer ({count})' if count else 'Enriquecer', icon='auto_fix_high',
                                              on_click=lambda _, i=index: enrichment_dialog(steps, i, chosen.refresh)).props('outline dense' + (' color=primary' if count else ''))
                                    ui.button(icon='edit', on_click=lambda _, cid=step['case_id']: edit_case(cid)) \
                                        .props('flat round dense').tooltip('Editar caso')

                                def move(delta, i=index):
                                    j = i + delta
                                    if 0 <= j < len(steps):
                                        steps[i], steps[j] = steps[j], steps[i]
                                        chosen.refresh()
                                ui.button(icon='arrow_upward', on_click=lambda _, m=move: m(-1)).props('flat round dense')
                                ui.button(icon='arrow_downward', on_click=lambda _, m=move: m(1)).props('flat round dense')
                                ui.button(icon='close', on_click=lambda _, i=index: (steps.pop(i), chosen.refresh(), available.refresh(filter_input.value or ''))).props('flat round dense color=negative')
                    chosen()
                    ui.label('Un paso solo puede usar respuestas de pasos que estén ANTES que él; si reordenas, se vuelve a validar al guardar.').classes('text-xs text-gray-500')

            with ui.expansion('Variables compartidas iniciales', icon='data_object').classes('w-full border rounded'):
                ui.label('Disponibles como {{nombre}} en todos los casos. Los valores extraídos por un caso se suman para los siguientes.').classes('text-gray-500 text-sm')
                kv_editor(variables, 'Variable', 'Valor')
                ui.separator().classes('my-1')
                seq_start = ui.number('Consecutivo propio de este flujo (opcional)', value=(current or {}).get('seq_start'), precision=0) \
                    .props('outlined dense clearable').classes('w-72')
                ui.label('Si lo completás, {{seq}} arranca en ese número y sube de a uno por paso en cada corrida de este flujo — '
                          'en vez del consecutivo global de toda la app, que nunca se reinicia.').classes('text-xs text-gray-500')

            with ui.expansion('Sorteos (datos aleatorios que no cambian durante la conversación)', icon='casino').classes('w-full border rounded'):
                ui.label('Elige una fila al azar de un conjunto de datos (Conjuntos de datos, en el menú) UNA vez por corrida, y la comparte entre '
                          'todos los pasos — por ejemplo, para que el nombre y el RFC de «la misma persona» no cambien de un paso al otro. '
                          'Usala como {{draw:alias.columna}}.').classes('text-gray-500 text-sm')
                if not datasets:
                    ui.label('No hay conjuntos de datos en este proyecto todavía. Subí uno en «Conjuntos de datos».').classes('text-amber-700 text-sm')
                else:
                    @ui.refreshable
                    def draw_rows():
                        for draw in draws:
                            with ui.row().classes('w-full items-center gap-2 no-wrap'):
                                ui.input('Nombre del sorteo', value=draw['alias']).props('outlined dense').classes('w-48') \
                                    .on_value_change(lambda e, d=draw: d.__setitem__('alias', (e.value or '').strip()))
                                ui.select({d['name']: f'{d["name"]} ({len(d["columns"])} col., {len(d["rows"])} filas)' for d in datasets},
                                          value=draw.get('dataset'), label='Conjunto de datos').props('outlined dense').classes('grow') \
                                    .on_value_change(lambda e, d=draw: d.__setitem__('dataset', e.value))
                                chosen_dataset = next((d for d in datasets if d['name'] == draw.get('dataset')), None)
                                if chosen_dataset:
                                    ui.label(', '.join(f'{{{{draw:{draw["alias"] or "alias"}.{c}}}}}' for c in chosen_dataset['columns'][:3])) \
                                        .classes('text-xs font-mono text-gray-500')
                                ui.button(icon='delete', on_click=lambda _, d=draw: (draws.remove(d), draw_rows.refresh())).props('flat round dense color=negative')
                    draw_rows()
                    ui.button('Agregar sorteo', icon='add', on_click=lambda: (draws.append({'alias': f'dato{len(draws) + 1}', 'dataset': datasets[0]['name']}), draw_rows.refresh())) \
                        .props('flat dense color=primary')

            def save():
                options = dict(id=(current or {}).get('id'), on_failure=on_failure.value, retries=int(retries.value or 0), retry_delay_s=float(delay.value or 0),
                               variables={k: v for k, v in variables.items() if k.strip()}, seq_start=seq_start.value, steps=steps, feature_id=feature.value,
                               draws=draws)
                if current:
                    options['expected_updated_at'] = current.get('updated_at')       # refuse to overwrite someone else's changes
                saved = core.save_suite(name.value or '', env.value, [], pid, **options)
                if current:
                    current['updated_at'] = saved['updated_at']
                ui.notify('Flujo guardado', type='positive')
                return saved
            with ui.row().classes('gap-3'):
                ui.button('Guardar', icon='save', on_click=guard(lambda: (save(), ui.navigate.to('/suites')))).props('color=primary')

                async def save_and_run():
                    await run_suite(save())
                ui.button('Guardar y ejecutar', icon='play_arrow', on_click=guard(save_and_run)).props('outline color=positive')
                ui.button('Volver', on_click=lambda: ui.navigate.to('/suites')).props('flat')

        @ui.refreshable
        def content():
            if view['mode'] == 'case':
                case_detail(view['case_id'])
            else:
                suite_body()
        content()
