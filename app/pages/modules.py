from nicegui import ui, run
from .. import core, explorer, automation
from .common import frame, guard, confirm, empty_state, require_project, read_upload

MAX_SPEC_BYTES = core.MAX_SPEC_BYTES
KIND_LABELS = {'backend': 'Backend', 'frontend': 'Frontend'}


def _env_note(pid, module):
    env, created = core.ensure_environment_for_module(pid, module)
    if not env:
        return ''
    return f' Ambiente «{env["name"]}» {"creado" if created else "reutilizado"} con {env["base_url"]}.'


@ui.page('/modules')
def modules_list():
    with frame('Componentes', '/modules'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        with ui.card().classes('w-full'):
            ui.label('Importar contrato').classes('text-lg font-semibold')
            ui.label('Para un backend con contrato publicado. JSON o YAML; solo se resuelven referencias $ref locales (#/…), las externas se rechazan.').classes('text-gray-500 text-sm')
            url = ui.input('URL del contrato, de su página de Swagger UI o un enlace de GitHub').props('outlined dense').classes('w-full')
            ui.label('Acepta el enlace directo al .json/.yaml, la página de Swagger UI / Redoc (se busca el contrato enlazado) o un enlace github.com/…/blob/….').classes('text-xs text-gray-500')

            async def from_url():
                module = await run.io_bound(core.import_openapi_url, url.value, pid)
                duplicates = [m for m in core.list_project_items('modules', pid) if m['id'] != module['id'] and m.get('source_url') == module.get('source_url')]
                dup_note = f' Ya había {len(duplicates)} componente(s) con este mismo origen en el proyecto: revisa si quieres eliminar el anterior.' if duplicates else ''
                ui.notify(f'Importado «{module["name"]}»: {len(module["operations"])} operaciones. Origen: {module["source_url"]}.{_env_note(pid, module)}{dup_note}',
                          type='warning' if duplicates else 'positive', multi_line=True)
                ui.navigate.to(f'/modules/edit?id={module["id"]}')
            ui.button('Importar desde URL', icon='cloud_download', on_click=guard(from_url)).props('color=primary')

            async def upload(event):
                try:
                    raw = await read_upload(event)
                    module = core.import_openapi(raw.decode('utf-8'), pid)
                    duplicates = [m for m in core.list_project_items('modules', pid)
                                  if m['id'] != module['id'] and m['name'] == module['name'] and m.get('version') == module.get('version')]
                    dup_note = f' Ya había {len(duplicates)} componente(s) con el mismo nombre y versión: revisa si quieres eliminar el anterior.' if duplicates else ''
                    ui.notify(f'Importado «{module["name"]}»: {len(module["operations"])} operaciones.{_env_note(pid, module)}{dup_note}',
                              type='warning' if duplicates else 'positive', multi_line=True)
                    ui.navigate.to(f'/modules/edit?id={module["id"]}')
                except Exception as exc:
                    ui.notify(str(exc), type='negative', multi_line=True)
            ui.upload(label='O arrastra un archivo OpenAPI (.json/.yaml)', on_upload=upload, auto_upload=True,
                      max_file_size=MAX_SPEC_BYTES).props('accept=.json,.yaml,.yml flat bordered').classes('w-full')

        with ui.card().classes('w-full'):
            ui.label('Crear componente manualmente').classes('text-lg font-semibold')
            ui.label('Para un frontend, o un backend sin contrato publicado: un nombre, un tipo y, si ya lo tienes, el ambiente donde vive. '
                     'Sin catálogo de operaciones (no hay contrato que leer); puedes seguir creando Casos directamente.').classes('text-gray-500 text-sm')
            with ui.row().classes('items-end gap-3 w-full'):
                manual_name = ui.input('Nombre').props('outlined dense').classes('grow').mark('component-name')
                manual_kind = ui.select(KIND_LABELS, value='backend', label='Tipo').props('outlined dense').classes('w-40').mark('component-kind')
                envs_here = core.list_project_items('environments', pid)
                manual_env = ui.select({e['id']: e['name'] for e in envs_here}, label='Ambiente (opcional)', clearable=True) \
                    .props('outlined dense').classes('w-60').mark('component-env')

            def create_manual():
                component = core.create_component(manual_name.value, pid, manual_kind.value, manual_env.value)
                ui.notify(f'Componente «{component["name"]}» creado', type='positive')
                ui.navigate.to(f'/modules/edit?id={component["id"]}')
            ui.button('Crear componente', icon='add', on_click=guard(create_manual)).props('outline').mark('component-create')

        items = core.list_project_items('modules', pid)
        if not items:
            empty_state('Este proyecto no tiene componentes. Importa un contrato, crea uno manualmente, o crea casos directamente.')
            return

        all_cases = core.list_project_items('cases', pid)
        columns = [
            {'name': 'name', 'label': 'Nombre', 'field': 'name', 'align': 'left', 'sortable': True},
            {'name': 'kind', 'label': 'Tipo', 'field': 'kind', 'align': 'center'},
            {'name': 'operations', 'label': 'Operaciones', 'field': 'operations', 'align': 'center', 'sortable': True},
            {'name': 'environment', 'label': 'Ambiente', 'field': 'environment', 'align': 'left'},
            {'name': 'cases', 'label': 'Casos generados', 'field': 'cases', 'align': 'center', 'sortable': True},
            {'name': 'actions', 'label': '', 'field': 'id', 'align': 'right'},
        ]

        def rows():
            result = []
            for m in items:
                env = core.component_environment(m)
                result.append({'id': m['id'], 'name': m['name'] + (f' · v{m["version"]}' if m.get('version') else ''),
                               'kind': KIND_LABELS.get(m.get('type', 'backend'), m.get('type', 'backend')),
                               'operations': len(m.get('operations') or []), 'environment': env['name'] if env else '—',
                               'has_env': bool(env), 'cases': sum(1 for c in all_cases if c.get('module_id') == m['id'])})
            return result

        table = ui.table(columns=columns, rows=rows(), row_key='id', pagination=15).classes('w-full').mark('modules-table')
        table.props('flat bordered')
        table.add_slot('body-cell-kind', '''<q-td :props="props"><q-badge :color="props.value === 'Frontend' ? 'purple' : 'blue-grey'">{{ props.value }}</q-badge></q-td>''')
        table.add_slot('body-cell-environment', r'''
            <q-td :props="props">
                <q-badge v-if="props.row.has_env" color="positive">{{ props.value }}</q-badge>
                <span v-else class="text-grey-5 text-caption">sin registrar</span>
            </q-td>
        ''')
        table.add_slot('body-cell-cases', r'''
            <q-td :props="props">
                <q-chip v-if="props.value" dense size="sm" color="blue-1" text-color="dark">{{ props.value }}</q-chip>
                <span v-else class="text-grey-5">—</span>
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
                    ui.notify(f'No se puede eliminar: {len(used)} caso(s) usan este componente', type='negative', multi_line=True)
                    return
                core.delete('modules', row['id'])
                ui.notify('Componente eliminado', type='positive')
                ui.navigate.reload()
            confirm(f'¿Eliminar el componente «{row["name"]}»?', attempt)
        table.on('deleteModule', on_delete)
        ui.label('Haz clic en una fila para ver su ambiente, explorarlo y sus casos; elimina directamente con el icono.').classes('text-sm text-gray-500')


@ui.page('/modules/edit')
def module_detail(id: str = ''):
    with frame('Componente', '/modules'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        module = core.get('modules', id) if id else None
        if not module or module.get('project_id') != pid:
            ui.label('Este componente ya no existe en el proyecto activo.').classes('text-amber-700')
            return
        ui.link('← Volver a Componentes', '/modules').classes('text-sm')
        is_manual = bool(module.get('manual'))
        kind = module.get('type', 'backend')
        operations = module.get('operations') or []

        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('widgets' if kind == 'frontend' else 'api', color='primary').classes('text-2xl')
                ui.label(module['name']).classes('text-xl font-semibold')
                ui.badge(KIND_LABELS.get(kind, kind), color='purple' if kind == 'frontend' else 'blue-grey')
                if module.get('version'):
                    ui.badge(f'v{module["version"]}', color='grey-6')
                if operations:
                    ui.label(f'{len(operations)} operaciones').classes('text-sm text-gray-500')
            if module.get('source_url'):
                ui.label(f'Origen: {module["source_url"]}').classes('text-xs text-gray-500 font-mono')

            if is_manual:
                ui.separator().classes('my-2')
                with ui.row().classes('items-end gap-3 w-full'):
                    edit_name = ui.input('Nombre', value=module['name']).props('outlined dense').classes('grow').mark('component-edit-name')
                    edit_kind = ui.select(KIND_LABELS, value=kind, label='Tipo').props('outlined dense').classes('w-40').mark('component-edit-kind')
                    envs_here = core.list_project_items('environments', pid)
                    edit_env = ui.select({e['id']: e['name'] for e in envs_here}, value=module.get('environment_id'),
                                         label='Ambiente', clearable=True).props('outlined dense').classes('w-60').mark('component-edit-env')

                def save_manual():
                    core.update_component(module['id'], edit_name.value, edit_kind.value, edit_env.value)
                    ui.notify('Componente actualizado', type='positive')
                    ui.navigate.to(f'/modules/edit?id={module["id"]}')
                ui.button('Guardar cambios', icon='save', on_click=guard(save_manual)).props('dense no-caps color=primary').mark('component-save')

            def remove(m=module):
                used = [c for c in core.list_items('cases') if c.get('module_id') == m['id']]
                if used:
                    raise ValueError(f'No se puede eliminar: {len(used)} caso(s) usan este componente')
                core.delete('modules', m['id'])
                ui.notify('Componente eliminado', type='positive')
                ui.navigate.to('/modules')
            ui.button('Eliminar componente', icon='delete', on_click=lambda: confirm(f'¿Eliminar el componente «{module["name"]}»?', remove)) \
                .props('flat dense color=negative mt-2').mark('module-delete')

        # ------------------------------------------------------------ environment
        env = core.component_environment(module)
        base = core.module_base_url(module)
        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('dns', color='primary')
                ui.label('Ambiente').classes('font-semibold')
            if env:
                with ui.row().classes('items-center gap-2'):
                    ui.icon('check_circle', color='positive').classes('text-sm')
                    ui.label(f'«{env["name"]}» · {env["base_url"]}').classes('text-sm text-gray-700')
                    ui.button('Abrir ambiente', icon='open_in_new', on_click=lambda: ui.navigate.to(f'/environments/edit?id={env["id"]}')) \
                        .props('flat dense size=sm no-caps')
            elif is_manual:
                ui.label('Aún no está ligado a ningún ambiente: edítalo arriba para elegir uno.').classes('text-sm text-gray-500')
            elif base:
                ui.label(f'Servidor declarado: {base}').classes('text-sm text-gray-600')

                def make_env(m=module):
                    new_env, created = core.ensure_environment_for_module(pid, m)
                    ui.notify(f'Ambiente «{new_env["name"]}» {"creado" if created else "ya existía"} con {new_env["base_url"]}', type='positive')
                    ui.navigate.reload()
                ui.button('Crear ambiente con esta URL', icon='add', on_click=guard(make_env)).props('dense no-caps color=primary')
            else:
                ui.label('El contrato no declara un servidor absoluto; crea o elige el ambiente a mano en Ambientes.').classes('text-sm text-amber-700')
                if module.get('servers') and any('{' in (server.get('url') or '') for server in module['servers']):
                    ui.label('(declara variables de servidor sin resolver, p. ej. «{entorno}»)').classes('text-xs text-amber-700')

        # ------------------------------------------------------------ exploration / frontend hint
        if kind == 'frontend':
            with ui.card().classes('w-full bg-purple-50'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('info', color='purple')
                    ui.label('Este componente es un frontend: sus pruebas son Casos UI (pasos de navegador), no se generan desde aquí.').classes('text-sm text-gray-700')
                ui.button('Ir a Casos UI', icon='web', on_click=lambda: ui.navigate.to('/ui-cases')).props('flat dense no-caps color=primary')
        elif not operations:
            with ui.card().classes('w-full'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('info', color='grey')
                    ui.label('Este componente no tiene un catálogo de operaciones (no se importó un contrato): la exploración automática no aplica aquí.').classes('text-sm text-gray-600')
                ui.button('Crear un caso API para este componente', icon='add', on_click=lambda: ui.navigate.to(f'/cases/edit?module={module["id"]}')).props('flat dense no-caps color=primary')
        else:
            with ui.card().classes('w-full'):
                with ui.row().classes('items-center gap-2'):
                    ui.icon('travel_explore', color='primary')
                    ui.label('Exploración automática').classes('font-semibold')
                ui.label('Lee el contrato, identifica qué operaciones son seguras de probar (GET), consigue identificadores reales de otros '
                         'listados y arma las aserciones a partir de lo que el contrato declara. Solo lecturas: nada que escriba se ejecuta aquí, '
                         'y el resultado no se guarda hasta que lo confirmes.').classes('text-xs text-gray-500')
                envs = core.list_project_items('environments', pid)
                if not envs:
                    ui.label('Registra un ambiente primero.').classes('text-xs text-amber-700')
                else:
                    env_select = ui.select({e['id']: e['name'] for e in envs}, value=(env or envs[0])['id'], label='Ambiente').props('outlined dense').classes('w-64')
                    with ui.row().classes('items-end gap-2'):
                        header_name = ui.input('Cabecera (opcional)', value='Authorization').props('outlined dense').classes('w-48')
                        header_value = ui.input('Valor', placeholder='Bearer {{secret:NOMBRE}} o un valor literal').props('outlined dense').classes('grow')
                    ui.label('Si el servicio exige autenticación, pega aquí el token para esta exploración (nunca se guarda tal cual: usa '
                             '{{secret:NOMBRE}}). El ambiente también se usa si ya tiene su propia autenticación configurada.').classes('text-xs text-gray-500')
                    E = {'result': None}
                    result_box = ui.column().classes('w-full gap-2')

                    async def explore():
                        explore_env = core.get('environments', env_select.value)
                        header_key = (header_name.value or '').strip()
                        if header_key and not (header_value.value or '').strip():
                            ui.notify(f'Escribiste el nombre de la cabecera «{header_key}» pero el valor está vacío: no se enviará.', type='warning')
                        extra_headers = {header_key: header_value.value} if header_key and (header_value.value or '').strip() else {}
                        plan = await run.io_bound(explorer.discover, module, explore_env, extra_headers)
                        if not plan['ready']:
                            ui.notify('Nada que ejecutar: ' + (f'{len(plan["blocked"])} operación(es) sin datos para resolver sus parámetros.' if plan['blocked'] else
                                                                'el componente no tiene lecturas (GET) sin autenticación.'), type='warning')
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
                            E['result'] = await run.io_bound(explorer.run_plan, plan, module, pid, explore_env, extra_headers=extra_headers, on_progress=progress.append, cancel=token)
                        finally:
                            timer.cancel()
                            dialog.close()
                        result_box.clear()
                        with result_box:
                            ui.code(explorer.narrate(module, E['result'], core.get('projects', pid)['name']), language='markdown').classes('w-full').style('max-height:50vh;overflow:auto')
                            if E['result']['results']:
                                ui.button('Guardar como casos', icon='save', on_click=guard(save_results)).props('dense size=sm no-caps color=primary')

                    def save_results():
                        saved = explorer.save_generated_cases(E['result'], pid)
                        ui.notify(f'{len(saved)} caso(s) guardados/actualizados en «Casos API» (etiqueta «{explorer.GENERATED_TAG}»)', type='positive')
                        ui.navigate.reload()
                    ui.button('Explorar automáticamente', icon='travel_explore', on_click=guard(explore)).props('dense no-caps color=primary').mark('module-explore')

        # ------------------------------------------------------------ cases generated from this component
        module_cases = [c for c in core.list_project_items('cases', pid) if c.get('module_id') == module['id']]
        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('http', color='primary')
                ui.label(f'Casos de este componente ({len(module_cases)})').classes('font-semibold')
            if not module_cases:
                ui.label('Ninguno todavía.').classes('text-sm text-gray-400')
            else:
                for c in module_cases[:8]:
                    with ui.row().classes('items-center gap-2 w-full cursor-pointer hover:bg-gray-50').on('click', lambda _, cid=c['id']: ui.navigate.to(f'/cases/edit?id={cid}')):
                        ui.badge(c.get('method', ''), color='primary').classes('w-16 justify-center')
                        ui.label(c.get('path', '')).classes('font-mono text-sm')
                        ui.label(c['name']).classes('text-sm text-gray-600 grow truncate')
                if len(module_cases) > 8:
                    ui.label(f'y {len(module_cases) - 8} más… revísalos todos en Casos API.').classes('text-xs text-gray-400')

        # ------------------------------------------------------------ operations (manual case creation)
        if operations:
            ui.label('Elegir una operación manualmente').classes('text-lg font-semibold mt-2')
            columns = [
                {'name': 'method', 'label': 'Método', 'field': 'method', 'align': 'left'},
                {'name': 'path', 'label': 'Ruta', 'field': 'path', 'align': 'left'},
                {'name': 'summary', 'label': 'Resumen', 'field': 'summary', 'align': 'left'},
                {'name': 'actions', 'label': '', 'field': 'index', 'align': 'right'},
            ]
            op_rows = [{'index': i, 'method': op['method'], 'path': op['path'], 'summary': op.get('summary', '')} for i, op in enumerate(operations)]
            op_table = ui.table(columns=columns, rows=op_rows, row_key='index', pagination=20).classes('w-full').mark('module-operations-table')
            op_table.props('flat bordered')
            op_table.add_slot('body-cell-method', '''<q-td :props="props"><q-badge color="primary">{{ props.value }}</q-badge></q-td>''')
            op_table.add_slot('body-cell-path', '''<q-td :props="props"><span class="font-mono text-sm">{{ props.value }}</span></q-td>''')
            op_table.add_slot('body-cell-actions', r'''
                <q-td :props="props" class="text-right" @click.stop>
                    <q-btn flat dense size="sm" no-caps icon="add" label="Crear caso" color="primary" @click="$parent.$emit('createCase', props.row)" />
                </q-td>
            ''')
            op_table.on('createCase', lambda e: ui.navigate.to(f'/cases/edit?module={module["id"]}&op={e.args["index"]}'))
