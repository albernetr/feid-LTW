import json
from nicegui import ui, run
from .. import core
from .common import frame, guard, confirm, empty_state, require_project, kv_editor, show_run, status_badge
from .widgets import assertion_rows, dynamic_variable_chips

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
        all_items = [c for c in core.list_project_items('cases', pid) if is_api(c)]
        if not all_items:
            empty_state('No hay casos API en este proyecto.')
            return

        all_tags = sorted({t for c in all_items for t in c.get('tags', [])})
        selected_tag = {'value': None}
        if all_tags:
            def pick_tag(tag):
                selected_tag['value'] = None if selected_tag['value'] == tag else tag
                render.refresh()
            with ui.row().classes('items-center gap-1 flex-wrap'):
                ui.label('Etiquetas del contrato:').classes('text-xs text-gray-500')
                for tag in all_tags:
                    ui.chip(tag, selectable=True, on_click=lambda _, t=tag: pick_tag(t)).props('dense size=sm outline color=primary')

        @ui.refreshable
        def render():
            items = [c for c in all_items if not selected_tag['value'] or selected_tag['value'] in c.get('tags', [])]
            if not items:
                ui.label('Ningún caso con esa etiqueta.').classes('text-gray-500')
            for case in items:
                with ui.card().classes('w-full'):
                    with ui.row().classes('items-center gap-3 w-full no-wrap'):
                        ui.badge(case.get('method', ''), color='primary').classes('w-16 justify-center')
                        with ui.column().classes('gap-0 grow'):
                            ui.label(case['name']).classes('font-semibold')
                            extra_tags = [t for t in case.get('tags', []) if t != 'auto-explorado']
                            tail = f' · {", ".join(extra_tags)}' if extra_tags else ''
                            ui.label(f'{case.get("path", "")} · {len(case.get("assertions", []))} aserciones{tail}').classes('font-mono text-sm text-gray-500')
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
        render()


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
                           'headers': {}, 'query': {}, 'body': None, 'extract': [], 'tags': []}
        module_id = base.get('module_id') or (module or None)
        if module and not current and op >= 0:
            selected_module = core.get('modules', module)
            if selected_module and op < len(selected_module['operations']):
                operation = selected_module['operations'][op]
                base.update({'name': f'{operation["method"]} {operation["path"]}', 'method': operation['method'], 'path': operation['path'],
                             'tags': operation.get('tags', [])})
        rules = [dict(r) for r in base.get('assertions', [])]
        extracts = [dict(r) for r in base.get('extract', [])]
        headers = {k: str(v) for k, v in (base.get('headers') or {}).items()}
        query = {k: str(v) for k, v in (base.get('query') or {}).items()}
        variables = {k: str(v) for k, v in (base.get('variables') or {}).items()}
        last_response = {'body': None}   # lo que devolvió la última ejecución de este caso en esta sesión

        def response_paths():
            """(ruta, vista previa) para el picker de JSONPath: de la última ejecución si ya corriste el caso,
            si no de un ejemplo armado con el contrato OpenAPI de la operación elegida (si hay uno)."""
            if last_response['body'] is not None:
                try:
                    return core.json_paths(json.loads(last_response['body']))
                except (TypeError, ValueError):
                    pass
            selected = core.get('modules', module_select.value) if module_select.value else None
            if selected and operation_select.value not in (None, ''):
                operation = selected['operations'][int(operation_select.value)]
                codes = [c for c in operation.get('responses', {}) if str(c).startswith('2')]
                schema = core.operation_response_schema(operation, codes[0]) if codes else None
                if schema:
                    return core.json_paths(core.sample_value_for_schema(schema))
            return []

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
                ui.label('Variables').classes('font-medium')
                ui.label('{{nombre}} propias de este caso (además de las del ambiente — para un valor que se repite en todos los casos de un '
                         'ambiente, decláralo ahí en vez de repetirlo acá en cada caso).').classes('text-xs text-gray-500')
                kv_editor(variables, 'Nombre', 'Valor')
                dynamic_variable_chips()
                body = ui.textarea('Body JSON (opcional; admite {{variables}} dentro de textos)',
                                   value=json.dumps(base['body'], indent=2, ensure_ascii=False) if base.get('body') is not None else '').props('outlined autogrow').classes('w-full font-mono')
            with ui.tab_panel(tab_assert):
                ui.label('Cada aserción se evalúa contra la respuesta. El caso pasa si todas pasan.').classes('text-gray-500 text-sm')
                tests_view = assertion_rows(lambda: rules, get_paths=response_paths)
                with ui.row().classes('gap-2'):
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
                        tests_view.refresh()
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
            # Parte de lo guardado (current): conserva campos que este formulario no edita — variables, el mapeo
            # de Chat y su transcripción, environment_id — en vez de perderlos cada vez que se guarda desde acá.
            # `cases.py` no tenía Variables hasta ahora, así que guardar un caso con variables puestas desde Chat
            # o desde el editor embebido en una Suite las borraba en silencio en cuanto se volvía a guardar aquí.
            item = {**(current or {}), 'name': name.value.strip(), 'type': 'api', 'project_id': pid, 'module_id': module_select.value, 'method': method.value,
                    'path': path.value.strip(), 'timeout': timeout.value or 20, 'body': data,
                    'headers': {k: v for k, v in headers.items() if k.strip()}, 'query': {k: v for k, v in query.items() if k.strip()},
                    'variables': {k: v for k, v in variables.items() if k.strip()},
                    'assertions': rules, 'extract': [dict(r, name=r['name'].strip()) for r in extracts], 'tags': base.get('tags', [])}
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
                result = await run_case(saved, env_select.value)
                last_response['body'] = (result.get('response') or {}).get('body')
                tests_view.refresh()
                if not current:
                    ui.navigate.to(f'/cases/edit?id={saved["id"]}')
            ui.button('Guardar', icon='save', on_click=guard(lambda: (save(), ui.navigate.to('/cases')))).props('color=primary')
            ui.button('Guardar y ejecutar', icon='play_arrow', on_click=guard(save_and_run)).props('outline color=positive')
            ui.button('Volver', on_click=lambda: ui.navigate.to('/cases')).props('flat')
