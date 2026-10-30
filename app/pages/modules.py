from nicegui import ui, run
from .. import core, explorer, automation
from .common import frame, guard, confirm, empty_state, require_project, read_upload

MAX_SPEC_BYTES = core.MAX_SPEC_BYTES


def _env_note(pid, module):
    env, created = core.ensure_environment_for_module(pid, module)
    if not env:
        return ''
    return f' Ambiente «{env["name"]}» {"creado" if created else "reutilizado"} con {env["base_url"]}.'


def _matching_environment(pid, base):
    if not base:
        return None
    return next((e for e in core.list_project_items('environments', pid) if e.get('base_url', '').rstrip('/') == base.rstrip('/')), None)


@ui.page('/modules')
def modules_list():
    with frame('Módulos (contratos OpenAPI / Swagger)', '/modules'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        with ui.card().classes('w-full'):
            ui.label('Importar contrato').classes('text-lg font-semibold')
            ui.label('JSON o YAML. Solo se resuelven referencias $ref locales (#/…); las externas se rechazan.').classes('text-gray-500 text-sm')
            url = ui.input('URL del contrato, de su página de Swagger UI o un enlace de GitHub').props('outlined dense').classes('w-full')
            ui.label('Acepta el enlace directo al .json/.yaml, la página de Swagger UI / Redoc (se busca el contrato enlazado) o un enlace github.com/…/blob/….').classes('text-xs text-gray-500')

            async def from_url():
                module = await run.io_bound(core.import_openapi_url, url.value, pid)
                duplicates = [m for m in core.list_project_items('modules', pid) if m['id'] != module['id'] and m.get('source_url') == module.get('source_url')]
                dup_note = f' Ya había {len(duplicates)} módulo(s) con este mismo origen en el proyecto: revisa si quieres eliminar el anterior.' if duplicates else ''
                ui.notify(f'Importado «{module["name"]}»: {len(module["operations"])} operaciones. Origen: {module["source_url"]}.{_env_note(pid, module)}{dup_note}',
                          type='warning' if duplicates else 'positive', multi_line=True)
                ui.navigate.reload()
            ui.button('Importar desde URL', icon='cloud_download', on_click=guard(from_url)).props('color=primary')

            async def upload(event):
                try:
                    raw = await read_upload(event)
                    module = core.import_openapi(raw.decode('utf-8'), pid)
                    duplicates = [m for m in core.list_project_items('modules', pid)
                                  if m['id'] != module['id'] and m['name'] == module['name'] and m.get('version') == module.get('version')]
                    dup_note = f' Ya había {len(duplicates)} módulo(s) con el mismo nombre y versión: revisa si quieres eliminar el anterior.' if duplicates else ''
                    ui.notify(f'Importado «{module["name"]}»: {len(module["operations"])} operaciones.{_env_note(pid, module)}{dup_note}',
                              type='warning' if duplicates else 'positive', multi_line=True)
                    ui.navigate.reload()
                except Exception as exc:
                    ui.notify(str(exc), type='negative', multi_line=True)
            ui.upload(label='O arrastra un archivo OpenAPI (.json/.yaml)', on_upload=upload, auto_upload=True,
                      max_file_size=MAX_SPEC_BYTES).props('accept=.json,.yaml,.yml flat bordered').classes('w-full')

        items = core.list_project_items('modules', pid)
        if not items:
            empty_state('Este proyecto no tiene módulos. Importa un contrato o crea casos manualmente.')
            return

        envs = core.list_project_items('environments', pid)
        with ui.card().classes('w-full'):
            ui.label('Exploración automática').classes('text-lg font-semibold')
            ui.label('Lee el contrato, identifica qué operaciones son seguras de probar (GET), consigue identificadores reales de otros '
                     'listados y arma las aserciones a partir de lo que el contrato declara. Solo lecturas: nada que escriba se ejecuta aquí, '
                     'y el resultado no se guarda en el proyecto hasta que lo confirmes.').classes('text-xs text-gray-500')
            if not envs:
                ui.label('Registra un ambiente primero.').classes('text-xs text-amber-700')
            else:
                with ui.row().classes('items-end gap-2'):
                    module_select = ui.select({m['id']: m['name'] for m in items}, value=items[0]['id'], label='Módulo').props('outlined dense').classes('w-64')
                    env_select = ui.select({e['id']: e['name'] for e in envs}, value=envs[0]['id'], label='Ambiente').props('outlined dense').classes('w-64')
                with ui.row().classes('items-end gap-2'):
                    header_name = ui.input('Cabecera (opcional)', value='Authorization').props('outlined dense').classes('w-48')
                    header_value = ui.input('Valor', placeholder='Bearer {{secret:NOMBRE}} o un valor literal').props('outlined dense').classes('grow')
                ui.label('Si el servicio exige autenticación, pega aquí el token para esta exploración (se usa en las peticiones, nunca se guarda tal cual: usa '
                         '{{secret:NOMBRE}} para no pegar el valor directamente). El ambiente también se usa si ya tiene su propia autenticación configurada.').classes('text-xs text-gray-500')
                E = {'result': None, 'module': None}
                result_box = ui.column().classes('w-full gap-2')

                async def explore():
                    module = core.get('modules', module_select.value)
                    env = core.get('environments', env_select.value)
                    header_key = (header_name.value or '').strip()
                    if header_key and not (header_value.value or '').strip():
                        ui.notify(f'Escribiste el nombre de la cabecera «{header_key}» pero el valor está vacío: no se enviará.', type='warning')
                    extra_headers = {header_key: header_value.value} if header_key and (header_value.value or '').strip() else {}
                    plan = await run.io_bound(explorer.discover, module, env, extra_headers)
                    if not plan['ready']:
                        ui.notify('Nada que ejecutar: ' + (f'{len(plan["blocked"])} operación(es) sin datos para resolver sus parámetros.' if plan['blocked'] else
                                                            'el módulo no tiene lecturas (GET) sin autenticación.'), type='warning')
                        return
                    token = automation.new_cancel_token()
                    progress = []
                    with ui.dialog().props('persistent') as dialog, ui.card().classes('w-96'):
                        ui.label(f'Explorando «{module["name"]}»').classes('text-lg font-semibold')
                        bar = ui.linear_progress(value=0, show_value=False)
                        status = ui.label(f'0 de {len(plan["ready"])} operación(es)').classes('text-gray-600 text-sm')

                        def cancel():
                            token.set()
                            status.set_text('Cancelando tras la petición en curso…')
                        ui.button('Cancelar', icon='stop', on_click=cancel).props('outline color=negative')
                    dialog.open()

                    def tick():
                        status.set_text(f'{len(progress)} de {len(plan["ready"])} operación(es)')
                        bar.set_value(len(progress) / len(plan['ready']))
                    timer = ui.timer(0.3, tick)
                    try:
                        E['result'] = await run.io_bound(explorer.run_plan, plan, module, pid, env, extra_headers=extra_headers, on_progress=progress.append, cancel=token)
                    finally:
                        timer.cancel()
                        dialog.close()
                    E['module'] = module
                    result_box.clear()
                    with result_box:
                        ui.code(explorer.narrate(module, E['result'], core.get('projects', pid)['name']), language='markdown').classes('w-full').style('max-height:50vh;overflow:auto')
                        if E['result']['results']:
                            ui.button('Guardar como casos', icon='save', on_click=guard(save_results)).props('dense size=sm no-caps color=primary')

                def save_results():
                    saved = explorer.save_generated_cases(E['result'], pid)
                    ui.notify(f'{len(saved)} caso(s) guardados/actualizados en «Casos API» (etiqueta «{explorer.GENERATED_TAG}»)', type='positive')
                ui.button('Explorar automáticamente', icon='travel_explore', on_click=guard(explore)).props('dense no-caps color=primary')

        columns = [
            {'name': 'name', 'label': 'Nombre', 'field': 'name', 'align': 'left', 'sortable': True},
            {'name': 'operations', 'label': 'Operaciones', 'field': 'operations', 'align': 'center', 'sortable': True},
            {'name': 'origin', 'label': 'Origen', 'field': 'origin', 'align': 'left'},
            {'name': 'environment', 'label': 'Ambiente', 'field': 'environment', 'align': 'left'},
            {'name': 'actions', 'label': '', 'field': 'id', 'align': 'right'},
        ]

        def rows():
            result = []
            for m in items:
                base = core.module_base_url(m)
                env = _matching_environment(pid, base)
                result.append({'id': m['id'], 'name': m['name'] + (f' · v{m["version"]}' if m.get('version') else ''),
                               'operations': len(m['operations']), 'origin': m.get('source_url') or 'Subido',
                               'environment': env['name'] if env else ('sin registrar' if base else '—'),
                               'has_env': bool(env)})
            return result

        table = ui.table(columns=columns, rows=rows(), row_key='id', pagination=15).classes('w-full').mark('modules-table')
        table.props('flat bordered')
        table.add_slot('body-cell-origin', '''<q-td :props="props"><span class="font-mono text-xs text-gray-600">{{ props.value }}</span></q-td>''')
        table.add_slot('body-cell-environment', r'''
            <q-td :props="props">
                <q-badge v-if="props.row.has_env" color="positive">{{ props.value }}</q-badge>
                <span v-else class="text-grey-5 text-caption">{{ props.value }}</span>
            </q-td>
        ''')
        table.add_slot('body-cell-actions', r'''
            <q-td :props="props" class="text-right" @click.stop>
                <q-btn flat dense round icon="chevron_right" color="grey-8" @click="$parent.$emit('viewModule', props.row)">
                    <q-tooltip>Ver detalle</q-tooltip>
                </q-btn>
                <q-btn flat dense round icon="delete" color="negative" @click="$parent.$emit('deleteModule', props.row)">
                    <q-tooltip>Eliminar</q-tooltip>
                </q-btn>
            </q-td>
        ''')
        table.on('rowClick', lambda e: ui.navigate.to(f'/modules/edit?id={e.args[1]["id"]}'))
        table.on('viewModule', lambda e: ui.navigate.to(f'/modules/edit?id={e.args["id"]}'))

        def on_delete(e):
            row = e.args

            def attempt():
                used = [c for c in core.list_items('cases') if c.get('module_id') == row['id']]
                if used:
                    ui.notify(f'No se puede eliminar: {len(used)} caso(s) usan este módulo', type='negative', multi_line=True)
                    return
                core.delete('modules', row['id'])
                ui.notify('Módulo eliminado', type='positive')
                ui.navigate.reload()
            confirm(f'¿Eliminar el módulo «{row["name"]}»?', attempt)
        table.on('deleteModule', on_delete)
        ui.label('Haz clic en una fila para ver sus operaciones; elimina directamente con el icono.').classes('text-sm text-gray-500')


@ui.page('/modules/edit')
def module_detail(id: str = ''):
    with frame('Módulo', '/modules'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        module = core.get('modules', id) if id else None
        if not module or module.get('project_id') != pid:
            ui.label('Este módulo ya no existe en el proyecto activo.').classes('text-amber-700')
            return
        ui.link('← Volver a Módulos', '/modules').classes('text-sm')

        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('api', color='primary').classes('text-2xl')
                ui.label(module['name']).classes('text-xl font-semibold')
                if module.get('version'):
                    ui.badge(f'v{module["version"]}', color='grey-6')
            ui.label(f'{len(module["operations"])} operaciones').classes('text-sm text-gray-500')
            if module.get('source_url'):
                ui.label(f'Origen: {module["source_url"]}').classes('text-xs text-gray-500 font-mono')

            ui.separator().classes('my-2')
            base = core.module_base_url(module)
            if base:
                existing_env = _matching_environment(pid, base)

                def make_env(m=module):
                    env, created = core.ensure_environment_for_module(pid, m)
                    ui.notify(f'Ambiente «{env["name"]}» {"creado" if created else "ya existía"} con {env["base_url"]}', type='positive')
                    if created:
                        ui.navigate.reload()
                with ui.row().classes('items-center gap-2'):
                    ui.label(f'Servidor declarado: {base}').classes('text-sm text-gray-700')
                    if existing_env:
                        ui.label(f'· ambiente «{existing_env["name"]}» ya registrado').classes('text-sm text-positive')
                    else:
                        ui.button('Crear ambiente con esta URL', icon='dns', on_click=guard(make_env)).props('flat dense size=sm no-caps color=primary')
            elif module.get('servers') and any('{' in (server.get('url') or '') for server in module['servers']):
                ui.label('El contrato declara variables de servidor sin resolver (p. ej. «{entorno}»); crea el ambiente a mano.').classes('text-sm text-amber-700')

            ui.separator().classes('my-2')

            def remove(m=module):
                used = [c for c in core.list_items('cases') if c.get('module_id') == m['id']]
                if used:
                    raise ValueError(f'No se puede eliminar: {len(used)} caso(s) usan este módulo')
                core.delete('modules', m['id'])
                ui.notify('Módulo eliminado', type='positive')
                ui.navigate.to('/modules')
            ui.button('Eliminar módulo', icon='delete', on_click=lambda: confirm(f'¿Eliminar el módulo «{module["name"]}»?', remove)).props('outline color=negative').mark('module-delete')

        ui.label('Operaciones').classes('text-lg font-semibold mt-2')
        columns = [
            {'name': 'method', 'label': 'Método', 'field': 'method', 'align': 'left'},
            {'name': 'path', 'label': 'Ruta', 'field': 'path', 'align': 'left'},
            {'name': 'summary', 'label': 'Resumen', 'field': 'summary', 'align': 'left'},
            {'name': 'actions', 'label': '', 'field': 'index', 'align': 'right'},
        ]
        rows = [{'index': i, 'method': op['method'], 'path': op['path'], 'summary': op.get('summary', '')} for i, op in enumerate(module['operations'])]
        op_table = ui.table(columns=columns, rows=rows, row_key='index', pagination=20).classes('w-full').mark('module-operations-table')
        op_table.props('flat bordered')
        op_table.add_slot('body-cell-method', '''<q-td :props="props"><q-badge color="primary">{{ props.value }}</q-badge></q-td>''')
        op_table.add_slot('body-cell-path', '''<q-td :props="props"><span class="font-mono text-sm">{{ props.value }}</span></q-td>''')
        op_table.add_slot('body-cell-actions', r'''
            <q-td :props="props" class="text-right" @click.stop>
                <q-btn flat dense size="sm" no-caps icon="add" label="Crear caso" color="primary" @click="$parent.$emit('createCase', props.row)" />
            </q-td>
        ''')
        op_table.on('createCase', lambda e: ui.navigate.to(f'/cases/edit?module={module["id"]}&op={e.args["index"]}'))
