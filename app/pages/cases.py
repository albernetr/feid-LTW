import json
from nicegui import ui, run
from .. import core
from .common import (frame, guard, confirm, empty_state, require_project, kv_editor, parse_value, show_value,
                     show_run, status_badge)

STRING_ONLY = ('contains', 'not_contains', 'regex', 'json_regex', 'header_equals', 'header_contains', 'body_equals')
HTTP_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']


def is_api(case):
    return case.get('type', 'api') != 'ui'


async def run_case(case, env_id):
    env = core.get('environments', env_id) if env_id else None
    if env is None:
        raise ValueError('Elige un ambiente para ejecutar')
    with ui.dialog() as busy, ui.card():
        ui.spinner(size='lg')
        ui.label('Ejecutando…')
    busy.open()
    try:
        result = await run.io_bound(core.execute_api, case, env)
    finally:
        busy.close()
    show_run(result)
    return result


@ui.page('/cases')
def cases_list():
    with frame('Casos API', '/cases'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        envs = core.list_project_items('environments', pid)
        with ui.row().classes('items-center gap-3'):
            ui.button('Nuevo caso', icon='add', on_click=lambda: ui.navigate.to('/cases/edit')).props('color=primary')
            env_select = ui.select({e['id']: e['name'] for e in envs}, value=envs[0]['id'] if envs else None, label='Ejecutar en ambiente').props('outlined dense').classes('w-60')
        if not envs:
            ui.label('Registra un ambiente para poder ejecutar casos.').classes('text-amber-700')
        items = [c for c in core.list_project_items('cases', pid) if is_api(c)]
        if not items:
            empty_state('No hay casos API en este proyecto.')
        for case in items:
            with ui.card().classes('w-full'):
                with ui.row().classes('items-center gap-3 w-full no-wrap'):
                    ui.badge(case.get('method', ''), color='primary').classes('w-16 justify-center')
                    with ui.column().classes('gap-0 grow'):
                        ui.label(case['name']).classes('font-semibold')
                        ui.label(f'{case.get("path", "")} · {len(case.get("assertions", []))} aserciones').classes('font-mono text-sm text-gray-500')
                    ui.button(icon='play_arrow', on_click=guard(lambda c=case: run_case(c, env_select.value))).props('flat round color=positive').tooltip('Ejecutar')
                    ui.button(icon='edit', on_click=lambda _, i=case['id']: ui.navigate.to(f'/cases/edit?id={i}')).props('flat round').tooltip('Editar')

                    def duplicate(c=case):
                        copy = {k: v for k, v in c.items() if k not in ('id', 'updated_at')}
                        copy['name'] = c['name'] + ' (copia)'
                        core.save('cases', copy)
                        ui.navigate.reload()
                    ui.button(icon='content_copy', on_click=guard(duplicate)).props('flat round').tooltip('Duplicar')

                    def remove(c=case):
                        used = [s for s in core.list_items('suites') if c['id'] in s.get('case_ids', [])]
                        if used:
                            raise ValueError(f'No se puede eliminar: está en {len(used)} suite(s)')
                        core.delete('cases', c['id'])
                        ui.navigate.reload()
                    ui.button(icon='delete', on_click=lambda _, c=case, r=remove: confirm(f'¿Eliminar el caso «{c["name"]}»?', r)).props('flat round color=negative').tooltip('Eliminar')


@ui.page('/cases/edit')
def case_edit(id: str = '', module: str = '', op: int = -1):
    with frame('Editor de caso API', '/cases'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        current = core.get('cases', id) if id else None
        if id and current is None:
            ui.label('El caso no existe.')
            return
        modules = core.list_project_items('modules', pid)
        envs = core.list_project_items('environments', pid)
        base = current or {'name': 'Nuevo caso API', 'method': 'GET', 'path': '/', 'module_id': module or None, 'assertions': [{'type': 'status', 'expected': 200}],
                           'headers': {}, 'query': {}, 'body': None, 'extract': []}
        module_id = base.get('module_id') or (module or None)
        if module and not current and op >= 0:
            selected_module = core.get('modules', module)
            if selected_module and op < len(selected_module['operations']):
                operation = selected_module['operations'][op]
                base.update({'name': f'{operation["method"]} {operation["path"]}', 'method': operation['method'], 'path': operation['path']})
        rules = [dict(r) for r in base.get('assertions', [])]
        extracts = [dict(r) for r in base.get('extract', [])]
        headers = {k: str(v) for k, v in (base.get('headers') or {}).items()}
        query = {k: str(v) for k, v in (base.get('query') or {}).items()}

        with ui.card().classes('w-full'):
            name = ui.input('Nombre del caso', value=base['name']).props('outlined dense').classes('w-full')
            with ui.row().classes('w-full items-center gap-3'):
                method = ui.select(HTTP_METHODS, value=base.get('method', 'GET'), label='Método').props('outlined dense').classes('w-32')
                path = ui.input('Ruta (admite {{variables}})', value=base.get('path', '/')).props('outlined dense').classes('grow')
                timeout = ui.number('Timeout (s)', value=base.get('timeout', 20), min=1, max=300).props('outlined dense').classes('w-32')
            with ui.row().classes('w-full items-center gap-3'):
                module_select = ui.select({m['id']: m['name'] for m in modules}, value=module_id, label='Componente (opcional)', clearable=True).props('outlined dense').classes('w-72')
                operation_select = ui.select({}, label='Operación del contrato').props('outlined dense clearable').classes('grow')

                def load_operations():
                    selected = core.get('modules', module_select.value) if module_select.value else None
                    operations = selected['operations'] if selected else []
                    operation_select.set_options({str(i): f'{o["method"]} {o["path"]}' for i, o in enumerate(operations)})
                    operation_select.set_visibility(bool(operations))

                def choose_operation(event):
                    selected = core.get('modules', module_select.value) if module_select.value else None
                    if selected and event.value not in (None, ''):
                        operation = selected['operations'][int(event.value)]
                        method.set_value(operation['method'])
                        path.set_value(operation['path'])
                module_select.on_value_change(lambda _: load_operations())
                operation_select.on_value_change(choose_operation)
                load_operations()

        with ui.tabs().classes('w-full') as tabs:
            tab_request = ui.tab('Petición')
            tab_assert = ui.tab('Aserciones')
            tab_chain = ui.tab('Encadenamiento')
        with ui.tab_panels(tabs, value=tab_request).classes('w-full'):
            with ui.tab_panel(tab_request):
                ui.label('Headers').classes('font-medium')
                kv_editor(headers, 'Header', 'Valor')
                ui.label('Query params').classes('font-medium')
                kv_editor(query, 'Parámetro', 'Valor')
                body = ui.textarea('Body JSON (opcional; admite {{variables}} dentro de textos)',
                                   value=json.dumps(base['body'], indent=2, ensure_ascii=False) if base.get('body') is not None else '').props('outlined autogrow').classes('w-full font-mono')
            with ui.tab_panel(tab_assert):
                ui.label('Cada aserción se evalúa contra la respuesta. El caso pasa si todas pasan.').classes('text-gray-500 text-sm')

                @ui.refreshable
                def assertion_rows():
                    for rule in rules:
                        with ui.row().classes('w-full items-start gap-2 no-wrap'):
                            def change_type(event, r=rule):
                                r.clear(); r['type'] = event.value
                                assertion_rows.refresh()
                            ui.select({k: v['label'] for k, v in core.ASSERTION_TYPES.items()}, value=rule['type'], on_change=change_type).props('outlined dense options-dense').classes('w-72')
                            fields = core.ASSERTION_TYPES.get(rule['type'], {}).get('fields', [])
                            if 'path' in fields:
                                ui.input('JSONPath', value=rule.get('path', ''), placeholder='$.data.id').props('outlined dense').classes('w-56') \
                                    .on_value_change(lambda e, r=rule: r.__setitem__('path', e.value))
                            if 'name' in fields:
                                ui.input('Header', value=rule.get('name', '')).props('outlined dense').classes('w-48') \
                                    .on_value_change(lambda e, r=rule: r.__setitem__('name', e.value))
                            if 'expected' in fields and rule['type'] == 'json_type':
                                ui.select(list(core.JSON_TYPES), value=rule.get('expected'), label='Tipo').props('outlined dense').classes('w-40') \
                                    .on_value_change(lambda e, r=rule: r.__setitem__('expected', e.value))
                            elif rule['type'] == 'json_matches':
                                def set_matches(e, r=rule):
                                    try:
                                        r['expected'] = json.loads(e.value)
                                    except ValueError:
                                        r['expected'] = None
                                ui.textarea('JSON esperado', value=json.dumps(rule.get('expected', {}), indent=2, ensure_ascii=False), on_change=set_matches)                                     .props('outlined dense autogrow').classes('grow font-mono')
                                ui.input('Ignorar (JSONPath, coma)', value=', '.join(rule.get('ignore', [])), placeholder='$.requested_at')                                     .props('outlined dense').classes('w-64')                                     .on_value_change(lambda e, r=rule: r.__setitem__('ignore', [p.strip() for p in (e.value or '').split(',') if p.strip()]))
                            elif 'expected' in fields:
                                def set_expected(e, r=rule):
                                    r['expected'] = e.value if r['type'] in STRING_ONLY else parse_value(e.value)
                                ui.input('Valor esperado', value=show_value(rule['expected']) if 'expected' in rule else '').props('outlined dense').classes('w-56') \
                                    .on_value_change(set_expected)
                            if 'schema' in fields:
                                def set_schema(e, r=rule):
                                    try:
                                        r['schema'] = json.loads(e.value)
                                    except ValueError:
                                        r['schema'] = None
                                ui.textarea('JSON Schema', value=json.dumps(rule.get('schema', {}), indent=2), on_change=set_schema).props('outlined dense autogrow').classes('grow font-mono')
                            ui.space()
                            ui.button(icon='delete', on_click=lambda _, r=rule: (rules.remove(r), assertion_rows.refresh())).props('flat round dense color=negative').tooltip('Quitar aserción')
                assertion_rows()
                with ui.row().classes('gap-2'):
                    ui.button('Agregar aserción', icon='add', on_click=lambda: (rules.append({'type': 'status', 'expected': 200}), assertion_rows.refresh())).props('outline color=primary')

                    def add_contract():
                        selected = core.get('modules', module_select.value) if module_select.value else None
                        if not selected or operation_select.value in (None, ''):
                            raise ValueError('Elige un componente y una operación del contrato')
                        operation = selected['operations'][int(operation_select.value)]
                        codes = [c for c in operation.get('responses', {}) if str(c).startswith('2')]
                        schema = core.operation_response_schema(operation, codes[0]) if codes else None
                        if not schema:
                            raise ValueError('El contrato no declara un schema de respuesta 2xx para esta operación')
                        rules.append({'type': 'json_schema', 'schema': schema})
                        assertion_rows.refresh()
                        ui.notify('Aserción de contrato agregada', type='positive')
                    ui.button('Agregar validación del contrato', icon='verified', on_click=guard(add_contract)).props('outline').tooltip('Valida la respuesta contra el JSON Schema del OpenAPI')
            with ui.tab_panel(tab_chain):
                ui.label('Extrae valores de la respuesta para usarlos como {{variable}} en los casos siguientes de una suite.').classes('text-gray-500 text-sm')

                @ui.refreshable
                def extract_rows():
                    for rule in extracts:
                        with ui.row().classes('w-full items-center gap-2 no-wrap'):
                            ui.input('Guardar como', value=rule.get('name', '')).props('outlined dense').classes('w-44') \
                                .on_value_change(lambda e, r=rule: r.__setitem__('name', e.value))
                            ui.select({'json': 'JSONPath del body', 'header': 'Header', 'status': 'Código HTTP', 'regex': 'Regex del body'}, value=rule.get('source', 'json'), label='Origen') \
                                .props('outlined dense').classes('w-52').on_value_change(lambda e, r=rule: r.__setitem__('source', e.value))
                            ui.input('Ruta / nombre / patrón', value=rule.get('path', ''), placeholder='$.token').props('outlined dense').classes('grow') \
                                .on_value_change(lambda e, r=rule: r.__setitem__('path', e.value))
                            ui.button(icon='delete', on_click=lambda _, r=rule: (extracts.remove(r), extract_rows.refresh())).props('flat round dense color=negative')
                extract_rows()
                ui.button('Agregar extracción', icon='add', on_click=lambda: (extracts.append({'name': '', 'source': 'json', 'path': ''}), extract_rows.refresh())).props('outline color=primary')

        def build():
            if not (name.value or '').strip():
                raise ValueError('El nombre es obligatorio')
            if not (path.value or '').strip():
                raise ValueError('La ruta es obligatoria')
            for index, rule in enumerate(rules, 1):
                problem = core.validate_assertion_rule(rule)
                if problem:
                    raise ValueError(f'Aserción {index}: {problem}')
            if not rules:
                raise ValueError('Agrega al menos una aserción')
            for index, rule in enumerate(extracts, 1):
                if not (rule.get('name') or '').strip() or (rule.get('source') != 'status' and not (rule.get('path') or '').strip()):
                    raise ValueError(f'Extracción {index}: completa el nombre y la ruta')
            try:
                data = json.loads(body.value) if (body.value or '').strip() else None
            except ValueError as exc:
                raise ValueError(f'El body no es JSON válido: {exc}')
            item = {'name': name.value.strip(), 'type': 'api', 'project_id': pid, 'module_id': module_select.value, 'method': method.value,
                    'path': path.value.strip(), 'timeout': timeout.value or 20, 'body': data,
                    'headers': {k: v for k, v in headers.items() if k.strip()}, 'query': {k: v for k, v in query.items() if k.strip()},
                    'assertions': rules, 'extract': [dict(r, name=r['name'].strip()) for r in extracts]}
            if current:
                item['id'] = current['id']
            return item

        ui.separator()
        with ui.row().classes('items-center gap-3'):
            env_select = ui.select({e['id']: e['name'] for e in envs}, value=envs[0]['id'] if envs else None, label='Ambiente de prueba').props('outlined dense').classes('w-60')

            def save():
                item = build()
                saved = core.save('cases', item, expected_updated_at=current.get('updated_at')) if current else core.save('cases', item)
                if current:
                    current['updated_at'] = saved['updated_at']      # keep editing without a false conflict
                ui.notify('Caso guardado', type='positive')
                return saved

            async def save_and_run():
                saved = save()
                await run_case(saved, env_select.value)
                if not current:
                    ui.navigate.to(f'/cases/edit?id={saved["id"]}')
            ui.button('Guardar', icon='save', on_click=guard(lambda: (save(), ui.navigate.to('/cases')))).props('color=primary')
            ui.button('Guardar y ejecutar', icon='play_arrow', on_click=guard(save_and_run)).props('outline color=positive')
            ui.button('Volver', on_click=lambda: ui.navigate.to('/cases')).props('flat')
