from urllib.parse import quote
from nicegui import ui, run
from .. import core, explorer, automation, reporting
from .common import frame, guard, confirm, empty_state, require_project, read_upload

MAX_SPEC_BYTES = core.MAX_SPEC_BYTES
STATUS_LABELS = core.COMPONENT_STATUS_LABELS
STATUS_COLORS = {'development': 'grey-6', 'qa': 'amber', 'ready': 'teal', 'production': 'positive'}
RAG_BADGE_COLOR = {'green': 'positive', 'amber': 'warning', 'red': 'negative', 'grey': 'grey-6'}


def _env_note(pid, module):
    env, created = core.ensure_environment_for_module(pid, module)
    if not env:
        return ''
    core.link_component_environment(module['id'], env['id'])
    return f' Ambiente «{env["name"]}» {"creado" if created else "reutilizado"} con {env["base_url"]}.'


def _operations_catalog_table(module, operations, marked=True):
    """Tabla filtrable por etiqueta con TODAS las operaciones (del contrato y las agregadas a mano, marcadas
    aparte) — vive en ambas sub-pestañas de Catálogo (Automático y Manual): el catálogo completo siempre debe
    verse, sin importar qué modo de carga estés usando en ese momento; solo cambia qué más te ofrece cada modo."""
    ui.label('Catálogo de operaciones').classes('text-lg font-semibold mt-2')
    tags_here = core.component_tags(module)
    if tags_here:
        ui.label('Son las mismas etiquetas que el contrato ya declara (las que agrupan los endpoints en Swagger UI): '
                 'úsalas para encontrar algo en un catálogo grande sin tener que crear nada nuevo.').classes('text-xs text-gray-500')
        tag_filter = ui.select({'': f'Todas las etiquetas ({len(tags_here)})', **{t: t for t in tags_here}}, value='', label='Filtrar por etiqueta') \
            .props('outlined dense options-dense').classes('w-64')
        if marked:
            tag_filter.mark('module-tag-filter')
    else:
        tag_filter = None
    columns = [
        {'name': 'method', 'label': 'Método', 'field': 'method', 'align': 'left'},
        {'name': 'path', 'label': 'Ruta', 'field': 'path', 'align': 'left'},
        {'name': 'summary', 'label': 'Resumen', 'field': 'summary', 'align': 'left'},
        {'name': 'tags', 'label': 'Etiquetas', 'field': 'tags', 'align': 'left'},
        {'name': 'actions', 'label': '', 'field': 'index', 'align': 'right'},
    ]

    def op_rows():
        wanted = tag_filter.value if tag_filter else ''
        return [{'index': i, 'method': op['method'], 'path': op['path'], 'summary': op.get('summary', ''),
                'tags': ', '.join(op.get('tags', [])), 'manual': bool(op.get('manual'))}
                for i, op in enumerate(operations) if not wanted or wanted in (op.get('tags') or [])]
    op_table = ui.table(columns=columns, rows=op_rows(), row_key='index', pagination=20).classes('w-full')
    if marked:
        op_table.mark('module-operations-table')
    op_table.props('flat bordered')
    op_table.add_slot('body-cell-method', '''<q-td :props="props"><q-badge color="primary">{{ props.value }}</q-badge></q-td>''')
    op_table.add_slot('body-cell-path', '''<q-td :props="props"><span class="font-mono text-sm">{{ props.value }}</span></q-td>''')
    op_table.add_slot('body-cell-tags', r'''
        <q-td :props="props">
            <span class="text-xs text-grey-7">{{ props.value }}</span>
            <q-badge v-if="props.row.manual" outline color="grey-6" class="q-ml-xs">a mano</q-badge>
        </q-td>
    ''')
    op_table.add_slot('body-cell-actions', r'''
        <q-td :props="props" class="text-right" @click.stop>
            <q-btn flat dense size="sm" no-caps icon="play_arrow" label="Probar" color="grey-8" @click="$parent.$emit('tryOp', props.row)" />
            <q-btn flat dense size="sm" no-caps icon="add" label="Crear caso" color="primary" @click="$parent.$emit('createCase', props.row)" />
        </q-td>
    ''')
    backend_envs = [e for e in core.component_environments(module) if core.environment_flags(e)[0]]
    try_env = backend_envs[0]['id'] if backend_envs else ''
    op_table.on('createCase', lambda e: ui.navigate.to(f'/cases/edit?module={module["id"]}&op={e.args["index"]}'))
    op_table.on('tryOp', lambda e: ui.navigate.to(
        f'/workspace?method={quote(e.args["method"])}&path={quote(e.args["path"], safe="")}&environment={try_env}', new_tab=True))
    if tag_filter:
        def refresh_ops():
            op_table.rows = op_rows()
            op_table.update()
        tag_filter.on_value_change(refresh_ops)


def _manual_operations_card(module, pid):
    """Catálogo manual de endpoints: antes de escribir un Caso completo, deja constancia de que un endpoint
    existe (método, ruta, resumen), con o sin contrato. Se agrega a la misma lista de operaciones que usa un
    contrato importado, así que «Crear caso» funciona igual para ambos. Vive en su propia lista corta (no
    mezclada con las cientos de filas del contrato) para poder encontrar y quitar lo que agregaste sin buscarlo
    entre el resto del catálogo."""
    manual_box = ui.column().classes('w-full gap-1')

    def render_manual():
        current = core.get('modules', module['id'])
        manual_ops = [(i, op) for i, op in enumerate(current.get('operations') or []) if op.get('manual')]
        manual_box.clear()
        with manual_box:
            if manual_ops:
                ui.label(f'Agregados a mano ({len(manual_ops)})').classes('font-semibold mt-2')
                for i, op in manual_ops:
                    with ui.row().classes('items-center gap-2 w-full'):
                        ui.badge(op['method'], color='primary')
                        ui.label(op['path']).classes('font-mono text-sm grow')
                        if op.get('summary'):
                            ui.label(op['summary']).classes('text-xs text-gray-500')
                        ui.button('Crear caso', icon='add', on_click=lambda _, idx=i: ui.navigate.to(
                            f'/cases/edit?module={module["id"]}&op={idx}')).props('flat dense size=sm no-caps')

                        def edit_op(idx=i, current_op=op):
                            with ui.dialog() as edit_dialog, ui.card().classes('w-96'):
                                ui.label('Editar endpoint').classes('font-semibold')
                                e_method = ui.select(list(core.HTTP_METHODS), value=current_op['method'], label='Método').props('outlined dense').classes('w-32')
                                e_path = ui.input('Ruta', value=current_op['path']).props('outlined dense').classes('w-full')
                                e_summary = ui.input('Resumen (opcional)', value=current_op.get('summary', '')).props('outlined dense').classes('w-full')
                                with ui.row().classes('justify-end w-full gap-2'):
                                    ui.button('Cancelar', on_click=edit_dialog.close).props('flat')

                                    def confirm_edit():
                                        core.update_manual_operation(module['id'], idx, e_method.value, e_path.value, e_summary.value)
                                        edit_dialog.close()
                                        ui.notify('Endpoint actualizado', type='positive')
                                        render_manual()
                                    ui.button('Guardar', icon='save', on_click=guard(confirm_edit)).props('color=primary')
                            edit_dialog.open()
                        ui.button(icon='edit', on_click=edit_op).props('flat dense round size=sm')

                        def remove_op(idx=i):
                            core.remove_manual_operation(module['id'], idx)
                            ui.notify('Endpoint eliminado', type='positive')
                            render_manual()
                        ui.button(icon='delete', on_click=remove_op).props('flat dense round size=sm color=negative')
    render_manual()

    with ui.card().classes('w-full'):
        with ui.row().classes('items-center gap-2'):
            ui.icon('add_link', color='primary')
            ui.label('Agregar un endpoint a mano').classes('font-semibold')
        ui.label('Para dejar constancia de que un endpoint existe, aunque todavía no esté en un contrato ni tengas listo el Caso que lo pruebe.') \
            .classes('text-xs text-gray-500')
        with ui.row().classes('items-end gap-3 w-full'):
            op_method = ui.select(list(core.HTTP_METHODS), value='GET', label='Método').props('outlined dense').classes('w-32').mark('component-op-method')
            op_path = ui.input('Ruta', placeholder='/items/{id}').props('outlined dense').classes('grow').mark('component-op-path')
            op_summary = ui.input('Resumen (opcional)').props('outlined dense').classes('grow').mark('component-op-summary')

            def add_operation():
                core.add_manual_operation(module['id'], op_method.value, op_path.value, op_summary.value)
                op_path.value = ''
                op_summary.value = ''
                ui.notify('Endpoint agregado', type='positive')
                render_manual()
            ui.button('Agregar endpoint', icon='add', on_click=guard(add_operation)).props('outline no-caps').mark('component-add-operation')


@ui.page('/modules')
def modules_list():
    with frame('Componentes', '/modules'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.button('Registrar componente', icon='add', on_click=lambda: ui.navigate.to('/modules/edit')).props('color=primary')

        items = core.list_project_items('modules', pid)
        if not items:
            empty_state('Este proyecto no tiene componentes. Regístralos (nombre, lo que exponen, ambiente); el contrato se importa después si expone backend.')
            return

        all_cases = core.list_project_items('cases', pid)
        groups = {g['id']: g['name'] for g in core.list_project_items('module_groups', pid)}
        columns = [
            {'name': 'name', 'label': 'Nombre', 'field': 'name', 'align': 'left', 'sortable': True},
            {'name': 'kind', 'label': 'Tipo', 'field': 'kind', 'align': 'center'},
            {'name': 'group', 'label': 'Módulo', 'field': 'group', 'align': 'left'},
            {'name': 'status', 'label': 'Estado', 'field': 'status', 'align': 'center'},
            {'name': 'maturity', 'label': 'Madurez', 'field': 'maturity', 'align': 'center'},
            {'name': 'operations', 'label': 'Operaciones', 'field': 'operations', 'align': 'center', 'sortable': True},
            {'name': 'environment', 'label': 'Ambiente', 'field': 'environment', 'align': 'left'},
            {'name': 'cases', 'label': 'Casos generados', 'field': 'cases', 'align': 'center', 'sortable': True},
            {'name': 'actions', 'label': '', 'field': 'id', 'align': 'right'},
        ]

        def rows():
            result = []
            for m in items:
                envs = core.component_environments(m)
                maturity = reporting.component_maturity(m['id'])
                result.append({'id': m['id'], 'name': m['name'] + (f' · v{m["version"]}' if m.get('version') else ''),
                               'kind': core.component_kind_label(m),
                               'group': ', '.join(groups[gid] for gid in core.component_module_group_ids(m) if gid in groups) or '—',
                               'status': STATUS_LABELS.get(m.get('status', 'development'), ''), 'status_key': m.get('status', 'development'),
                               'maturity': f'{maturity["passed"]}/{maturity["with_data"]}' if maturity['with_data'] else reporting.RAG['grey'],
                               'maturity_rag': maturity['rag'],
                               'operations': len(m.get('operations') or []), 'environment': ', '.join(e['name'] for e in envs) or '—',
                               'has_env': bool(envs), 'cases': sum(1 for c in all_cases if c.get('module_id') == m['id'])})
            return result

        table = ui.table(columns=columns, rows=rows(), row_key='id', pagination=15).classes('w-full').mark('modules-table')
        table.props('flat bordered')
        table.add_slot('body-cell-kind', '''
            <q-td :props="props">
                <q-badge :color="props.value === 'Frontend' ? 'purple' : (props.value === 'Backend' ? 'blue-grey' : 'teal')">{{ props.value }}</q-badge>
            </q-td>
        ''')
        table.add_slot('body-cell-status', r'''
            <q-td :props="props">
                <q-badge :color="{development: 'grey-6', qa: 'amber', ready: 'teal', production: 'positive'}[props.row.status_key] || 'grey-6'">{{ props.value }}</q-badge>
            </q-td>
        ''')
        table.add_slot('body-cell-maturity', r'''
            <q-td :props="props">
                <q-badge :color="{green: 'positive', amber: 'warning', red: 'negative', grey: 'grey-6'}[props.row.maturity_rag]">{{ props.value }}</q-badge>
                <q-tooltip>Madurez: casos que pasan en su última corrida (semáforo del Resumen ejecutivo)</q-tooltip>
            </q-td>
        ''')
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


def _register_component_form(pid):
    with ui.card().classes('w-full'):
        ui.label('Registra la pieza con lo mínimo: nombre, lo que expone y dónde vive. Si expone backend, el contrato OpenAPI '
                 '(si lo tiene) se importa después, desde la propia pantalla del componente — no hace falta tenerlo a mano todavía.').classes('text-gray-500 text-sm')
        name = ui.input('Nombre').props('outlined dense').classes('w-full').mark('component-name')
        with ui.row().classes('items-center gap-4'):
            backend = ui.checkbox('Expone backend (API)', value=True).mark('component-is-backend')
            frontend = ui.checkbox('Expone frontend (UI)', value=False).mark('component-is-frontend')

        envs_here = core.list_project_items('environments', pid)
        envs_select = ui.select({e['id']: e['name'] for e in envs_here}, label='Ambientes existentes (opcional; puede ser más de uno)',
                                 multiple=True, clearable=True).props('outlined dense use-chips').classes('w-full').mark('component-env')
        new_origin = ui.input('…o un origen nuevo (URL; registra el ambiente de una vez)', placeholder='https://qa.ejemplo.com') \
            .props('outlined dense').classes('w-full').mark('component-new-origin')
        groups_here = core.list_project_items('module_groups', pid)
        group_select = ui.select({g['id']: g['name'] for g in groups_here}, label='Módulos (opcional; puede ser más de uno)',
                                  multiple=True, clearable=True).props('outlined dense use-chips').classes('w-full').mark('component-group')

        def register():
            env_ids = list(envs_select.value or [])
            origin = (new_origin.value or '').strip()
            if origin:
                core.validate_base_url(origin)
                env, _path = core.ensure_environment_for_url(pid, origin)
                if env['id'] not in env_ids:
                    env_ids.append(env['id'])
            component = core.create_component(name.value, pid, backend.value, frontend.value, env_ids, list(group_select.value or []))
            ui.notify(f'Componente «{component["name"]}» registrado', type='positive')
            ui.navigate.to(f'/modules/edit?id={component["id"]}')
        ui.button('Registrar componente', icon='add', on_click=guard(register)).props('color=primary').mark('component-create')


@ui.page('/modules/edit')
def module_detail(id: str = ''):
    with frame('Componente' if id else 'Registrar componente', '/modules'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.link('← Volver a Componentes', '/modules').classes('text-sm')

        if not id:
            _register_component_form(pid)
            return

        module = core.get('modules', id)
        if not module or module.get('project_id') != pid:
            ui.label('Este componente ya no existe en el proyecto activo.').classes('text-amber-700')
            return
        is_manual = bool(module.get('manual'))
        is_backend, is_frontend = core.component_flags(module)
        operations = module.get('operations') or []

        module_cases = [c for c in core.list_project_items('cases', pid) if c.get('module_id') == module['id']]
        dependent_features = core.component_features(module['id'])
        envs = core.component_environments(module)

        # ------------------------------------------------------------ compact header: just orientation (which component), no editing here
        with ui.row().classes('items-center gap-2'):
            ui.icon('widgets' if is_frontend and not is_backend else ('hub' if is_backend and is_frontend else 'api'), color='primary').classes('text-2xl')
            ui.label(module['name']).classes('text-xl font-semibold')
            ui.badge(core.component_kind_label(module), color='teal' if (is_backend and is_frontend) else ('purple' if is_frontend else 'blue-grey'))
            if module.get('version'):
                ui.badge(f'v{module["version"]}', color='grey-6')
            if operations:
                ui.label(f'{len(operations)} operaciones').classes('text-sm text-gray-500')
            maturity = reporting.component_maturity(module['id'])
            with ui.row().classes('items-center gap-1').tooltip('Madurez: casos que pasan en su última corrida (semáforo del Resumen ejecutivo), no una etiqueta manual'):
                ui.badge(f'Madurez: {maturity["passed"]}/{maturity["with_data"]}' if maturity['with_data'] else f'Madurez: {reporting.RAG["grey"]}',
                         color=RAG_BADGE_COLOR[maturity['rag']])

        with ui.tabs().classes('w-full') as tabs:
            tab_summary = ui.tab('Resumen')
            tab_envs = ui.tab('Ambientes' + (f' ({len(envs)})' if envs else ''))
            tab_ops = ui.tab('Catálogo')
            tab_trace = ui.tab('Casos y funcionalidades')
        with ui.tab_panels(tabs, value=tab_summary).classes('w-full'):

            # -------------------------------------------------------- Resumen: identidad editable + clasificación + conteos
            with ui.tab_panel(tab_summary):
                with ui.card().classes('w-full'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('edit', color='primary')
                        ui.label('Identidad').classes('font-semibold')
                    if module.get('source_url'):
                        ui.label(f'Origen: {module["source_url"]}').classes('text-xs text-gray-500 font-mono')
                        if not is_manual:
                            ui.label('El nombre y lo que expone son tuyos para ajustar; las operaciones, la versión y el servidor siguen viniendo del contrato '
                                     '(solo cambian si lo vuelves a importar).').classes('text-xs text-gray-400')
                    edit_name = ui.input('Nombre', value=module['name']).props('outlined dense').classes('w-full').mark('component-edit-name')
                    with ui.row().classes('items-center gap-4'):
                        edit_backend = ui.checkbox('Expone backend (API)', value=is_backend).mark('component-edit-is-backend')
                        edit_frontend = ui.checkbox('Expone frontend (UI)', value=is_frontend).mark('component-edit-is-frontend')

                    def save_identity():
                        core.update_component(module['id'], edit_name.value, edit_backend.value, edit_frontend.value, module.get('environment_ids') or [])
                        ui.notify('Componente actualizado', type='positive')
                        ui.navigate.to(f'/modules/edit?id={module["id"]}')
                    ui.button('Guardar cambios', icon='save', on_click=guard(save_identity)).props('dense no-caps color=primary mt-2').mark('component-save')

                    def remove(m=module):
                        used = [c for c in core.list_items('cases') if c.get('module_id') == m['id']]
                        if used:
                            raise ValueError(f'No se puede eliminar: {len(used)} caso(s) usan este componente')
                        core.delete('modules', m['id'])
                        ui.notify('Componente eliminado', type='positive')
                        ui.navigate.to('/modules')
                    ui.button('Eliminar componente', icon='delete', on_click=lambda: confirm(f'¿Eliminar el componente «{module["name"]}»?', remove)) \
                        .props('flat dense color=negative mt-2').mark('module-delete')

                    other_projects = [p for p in core.list_items('projects') if p['id'] != pid]
                    if other_projects:
                        def open_move_dialog():
                            with ui.dialog() as move_dialog, ui.card():
                                ui.label(f'Mover «{module["name"]}» a otro proyecto').classes('font-semibold')
                                ui.label('Los ambientes y módulos ligados se desvinculan (pertenecen al proyecto actual); '
                                         'bloqueado si el componente ya tiene Casos.').classes('text-xs text-gray-500')
                                target = ui.select({p['id']: p['name'] for p in other_projects}, label='Proyecto destino') \
                                    .props('outlined dense').classes('w-72')
                                with ui.row().classes('justify-end w-full gap-2'):
                                    ui.button('Cancelar', on_click=move_dialog.close).props('flat')

                                    def confirm_move():
                                        if not target.value:
                                            raise ValueError('Elige un proyecto destino')
                                        _, cleared = core.move_component_to_project(module['id'], target.value)
                                        move_dialog.close()
                                        extra = []
                                        if cleared['environments']:
                                            extra.append(f'{cleared["environments"]} ambiente(s) desligado(s)')
                                        if cleared['modules']:
                                            extra.append(f'{cleared["modules"]} módulo(s) desligado(s)')
                                        msg = 'Componente movido.' + ((' ' + ', '.join(extra) + '.') if extra else '')
                                        ui.notify(msg, type='positive', multi_line=True)
                                        ui.navigate.to('/modules')
                                    ui.button('Mover', icon='drive_file_move', on_click=guard(confirm_move)).props('color=primary')
                            move_dialog.open()
                        ui.button('Mover a otro proyecto', icon='drive_file_move', on_click=open_move_dialog) \
                            .props('flat dense no-caps mt-2').mark('component-move-project')
                with ui.card().classes('w-full'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('account_tree', color='primary')
                        ui.label('Clasificación').classes('font-semibold')
                    with ui.row().classes('items-end gap-3 w-full'):
                        groups_here = core.list_project_items('module_groups', pid)
                        group_select = ui.select({g['id']: g['name'] for g in groups_here}, value=core.component_module_group_ids(module),
                                                  label='Módulos', multiple=True, clearable=True) \
                            .props('outlined dense use-chips').classes('grow').mark('component-classify-group')
                        status_select = ui.select(STATUS_LABELS, value=module.get('status', 'development'),
                                                   label='Estado').props('outlined dense').classes('w-60').mark('component-classify-status')

                        def save_classification():
                            core.set_component_classification(module['id'], list(group_select.value or []), status_select.value)
                            ui.notify('Clasificación actualizada', type='positive')
                            ui.navigate.to(f'/modules/edit?id={module["id"]}')
                        ui.button('Guardar clasificación', icon='save', on_click=guard(save_classification)).props('dense no-caps color=primary').mark('component-classify-save')
                    if not groups_here:
                        ui.label('Crea un Módulo para agrupar componentes por dominio o propiedad técnica.').classes('text-xs text-gray-500')
                with ui.row().classes('w-full gap-4 flex-wrap'):
                    for icon, label, count, tab in (('dns', 'Ambientes', len(envs), tab_envs), ('http', 'Casos', len(module_cases), tab_trace),
                                                     ('flag', 'Funcionalidades', len(dependent_features), tab_trace)):
                        with ui.card().classes('flex-1 min-w-[160px] cursor-pointer hover:bg-gray-50').on('click', lambda _, t=tab: tabs.set_value(t)):
                            ui.label(str(count)).classes('text-2xl font-semibold')
                            with ui.row().classes('items-center gap-1'):
                                ui.icon(icon, color='primary').classes('text-sm')
                                ui.label(label).classes('text-sm text-gray-600')

            # -------------------------------------------------------- Ambientes: el mismo desplegable puede vivir en varios (dev/QA/prod…)
            with ui.tab_panel(tab_envs):
                base = core.module_base_url(module)
                with ui.card().classes('w-full'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('dns', color='primary')
                        ui.label(f'Ambientes ({len(envs)})' if envs else 'Ambientes').classes('font-semibold')
                    if envs:
                        def render_conn_result(box, e, result):
                            box.clear()
                            with box:
                                with ui.row().classes('items-center gap-2'):
                                    ui.icon('check_circle' if result['ok'] else 'cancel', color='positive' if result['ok'] else 'negative')
                                    ui.label(f'{e["name"]}: ' + ('arriba' if result['ok'] else 'no se pudo conectar')).classes('text-sm font-semibold')
                                for step in result['steps']:
                                    with ui.row().classes('items-center gap-2 pl-6'):
                                        ui.icon('check' if step['ok'] else 'close', color='positive' if step['ok'] else 'negative', size='xs')
                                        ui.label(f'{step["name"]} · {step["ms"]} ms').classes('w-32 text-xs')
                                        ui.label(step['detail']).classes('text-xs text-gray-600')

                        row_boxes = []

                        def make_verify_one(e, box):
                            async def verify_one():
                                result = await run.io_bound(core.check_connectivity, e['base_url'])
                                render_conn_result(box, e, result)
                            return verify_one

                        for e in envs:
                            with ui.column().classes('gap-0 w-full') as env_block:
                                with ui.row().classes('items-center gap-2'):
                                    ui.icon('check_circle', color='positive').classes('text-sm')
                                    ui.label(f'«{e["name"]}» · {e["base_url"]}').classes('text-sm text-gray-700')
                                    flags = core.environment_flags(e)
                                    if flags != (True, True):
                                        ui.badge(core.environment_kind_label(e), color='purple' if flags == (False, True) else 'blue-grey').props('outline')
                                    ui.button('Abrir ambiente', icon='open_in_new', on_click=lambda _, eid=e['id']: ui.navigate.to(f'/environments/edit?id={eid}')) \
                                        .props('flat dense size=sm no-caps')
                                    verify_button = ui.button('Verificar', icon='wifi_tethering').props('flat dense size=sm no-caps')
                                row_box = ui.column().classes('gap-0 pl-6')
                            verify_button.on_click(guard(make_verify_one(e, row_box)))
                            row_boxes.append(row_box)

                        if len(envs) > 1:
                            async def verify_all():
                                results = await run.io_bound(lambda: [(e, core.check_connectivity(e['base_url'])) for e in envs])
                                for box, (e, result) in zip(row_boxes, results):
                                    render_conn_result(box, e, result)
                            ui.button('Verificar conexión (todos)', icon='wifi_tethering', on_click=guard(verify_all)) \
                                .props('outline dense no-caps mt-1').mark('component-verify-connection')
                    elif base:
                        ui.label(f'Servidor declarado: {base}').classes('text-sm text-gray-600')

                        def make_env(m=module):
                            new_env, created = core.ensure_environment_for_module(pid, m)
                            core.link_component_environment(m['id'], new_env['id'])
                            ui.notify(f'Ambiente «{new_env["name"]}» {"creado" if created else "ya existía"} con {new_env["base_url"]}', type='positive')
                            ui.navigate.reload()
                        ui.button('Crear ambiente con esta URL', icon='add', on_click=guard(make_env)).props('dense no-caps color=primary')
                    else:
                        ui.label('Aún no está ligado a ningún ambiente.').classes('text-sm text-gray-500')
                        if module.get('servers') and any('{' in (server.get('url') or '') for server in module['servers']):
                            ui.label('(el contrato declara variables de servidor sin resolver, p. ej. «{entorno}»)').classes('text-xs text-amber-700')

                    ui.separator().classes('my-2')
                    linked_ids = {e['id'] for e in envs}

                    def _compatible(e):
                        env_backend, env_frontend = core.environment_flags(e)
                        return (is_backend and env_backend) or (is_frontend and env_frontend)
                    all_envs_here = core.list_project_items('environments', pid)
                    # "ligar" means "este desplegable vive aquí": un componente solo-backend ligado a un ambiente solo-frontend sería una
                    # afirmación falsa (y "Verificar conexión" confirmaría "arriba" sobre una URL que no es la de este componente). Se ofrecen
                    # los compatibles, más los ya ligados (para poder quitarlos aunque hayan dejado de coincidir); lo excluido se nombra abajo.
                    candidates = [e for e in all_envs_here if e['id'] in linked_ids or _compatible(e)]
                    excluded = [e for e in all_envs_here if e not in candidates]
                    link_select = ui.select({e['id']: f'{e["name"]} ({core.environment_kind_label(e)})' for e in candidates}, value=[e['id'] for e in envs],
                                             label='Ligar ambientes (dev, QA, prod…)', multiple=True, clearable=True) \
                        .props('outlined dense use-chips').classes('w-full').mark('component-link-envs')
                    if excluded:
                        names = ', '.join(f'«{e["name"]}» ({core.environment_kind_label(e)})' for e in excluded)
                        ui.label(f'No se muestra: {names} — este componente no expone lo que ese(os) ambiente(s) sirve(n). '
                                 'Ajusta el tipo en Ambientes o en Identidad si de verdad debería ligarse.').classes('text-xs text-gray-500')

                    def save_envs():
                        core.set_component_environments(module['id'], link_select.value)
                        ui.notify('Ambientes actualizados', type='positive')
                        ui.navigate.to(f'/modules/edit?id={module["id"]}')
                    ui.button('Guardar ambientes', icon='save', on_click=guard(save_envs)).props('dense no-caps color=primary mt-1').mark('component-save-envs')

            # -------------------------------------------------------- Operaciones: aviso de frontend + exploración/catálogo del lado backend
            with ui.tab_panel(tab_ops):
                if is_frontend:
                    with ui.card().classes('w-full bg-purple-50'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('info', color='purple')
                            ui.label('Este componente expone frontend: sus pruebas de UI son Casos UI (pasos de navegador); las vistas de abajo son solo catálogo, no se graban desde aquí.').classes('text-sm text-gray-700')

                        # Solo ambientes marcados frontend sirven vistas; un componente full-stack también puede tener
                        # ambientes backend ligados, y probar una ruta de pantalla contra esos daría un resultado falso
                        # (ver CHANGELOG): nunca tomar "el primer ambiente ligado" sin filtrar por tipo.
                        frontend_envs = [e for e in envs if core.environment_flags(e)[1]]

                        views_box = ui.column().classes('w-full gap-2')

                        def render_views():
                            views = core.get('modules', module['id']).get('views') or []
                            views_box.clear()
                            with views_box:
                                if not views:
                                    return
                                ui.label(f'Vistas ({len(views)})').classes('font-semibold mt-2')
                                if not frontend_envs:
                                    other = [e for e in envs if e not in frontend_envs]
                                    msg = 'Liga un ambiente frontend (pestaña Ambientes) para poder verificar que cada ruta responda.' if not other else \
                                        f'Los ambientes ligados ({", ".join(e["name"] for e in other)}) no están marcados como frontend; ajústalo en Ambientes o liga uno nuevo.'
                                    ui.label(msg).classes('text-xs text-amber-700')
                                    default_view_env = None
                                    view_env_select = None
                                elif len(frontend_envs) == 1:
                                    default_view_env = frontend_envs[0]
                                    view_env_select = None
                                else:
                                    view_env_select = ui.select({e['id']: e['name'] for e in frontend_envs}, value=frontend_envs[0]['id'],
                                                                 label='Ambiente para verificar vistas').props('outlined dense').classes('w-64 mb-1')
                                    default_view_env = frontend_envs[0]

                                def current_view_env():
                                    return core.get('environments', view_env_select.value) if view_env_select else default_view_env

                                def view_target(v):
                                    env = current_view_env()
                                    return env['base_url'].rstrip('/') + '/' + v.get('path', '').lstrip('/') if env else None

                                def make_verify_view(v, box):
                                    async def verify_view():
                                        target = view_target(v)
                                        box.clear()
                                        with box:
                                            ui.spinner('dots', size='sm')
                                        result = await run.io_bound(automation.check_view, target)
                                        box.clear()
                                        with box:
                                            with ui.row().classes('items-center gap-2'):
                                                ui.icon('check_circle' if result['ok'] else 'cancel', color='positive' if result['ok'] else 'negative').classes('text-sm')
                                                ui.label(result['detail'] + f' — {target}').classes('text-xs')
                                    return verify_view

                                def make_copy_url(v):
                                    def copy_url():
                                        ui.clipboard.write(view_target(v))
                                        ui.notify('URL copiada', type='positive')
                                    return copy_url

                                for i, v in enumerate(views):
                                    with ui.column().classes('gap-0 w-full'):
                                        with ui.row().classes('items-center gap-2 w-full'):
                                            ui.icon('web', color='purple').classes('text-sm')
                                            ui.label(v['name']).classes('text-sm font-medium')
                                            if v.get('path'):
                                                ui.label(v['path']).classes('font-mono text-xs text-gray-500 grow')
                                            else:
                                                ui.space()
                                            if frontend_envs:
                                                ui.button(icon='content_copy', on_click=make_copy_url(v)) \
                                                    .props('flat dense round size=sm').tooltip('Copiar URL completa')
                                                ui.button(icon='open_in_new', on_click=lambda _, vv=v: ui.navigate.to(view_target(vv), new_tab=True)) \
                                                    .props('flat dense round size=sm').tooltip('Abrir en una pestaña nueva')
                                                view_box = ui.column().classes('gap-0')
                                                ui.button('Verificar', icon='wifi_tethering', on_click=guard(make_verify_view(v, view_box))) \
                                                    .props('flat dense size=sm no-caps')
                                            ui.button('Crear caso UI', icon='add', on_click=lambda _, n=v['name'], p=v.get('path', ''): ui.navigate.to(
                                                f'/ui-cases?name={n}&url={p}')).props('flat dense size=sm no-caps')

                                            def remove_view(idx=i):
                                                core.remove_component_view(module['id'], idx)
                                                ui.notify('Vista eliminada', type='positive')
                                                render_views()
                                            ui.button(icon='delete', on_click=remove_view).props('flat dense round size=sm color=negative')
                                        if frontend_envs:
                                            view_box.classes('pl-6')
                        render_views()

                        ui.separator().classes('my-2')
                        with ui.row().classes('items-end gap-3 w-full'):
                            view_name = ui.input('Nombre de la vista', placeholder='Login').props('outlined dense').classes('grow').mark('component-view-name')
                            view_path = ui.input('Ruta (opcional)', placeholder='/login').props('outlined dense').classes('w-48').mark('component-view-path')

                            def add_view():
                                core.add_component_view(module['id'], view_name.value, view_path.value)
                                view_name.value = ''
                                view_path.value = ''
                                ui.notify('Vista agregada', type='positive')
                                render_views()
                            ui.button('Agregar vista', icon='add', on_click=guard(add_view)).props('outline no-caps').mark('component-add-view')
                        ui.label('Documenta pantallas que existen (login, listado, detalle…) aunque todavía no tengas el Caso UI grabado; '
                                 'luego, «Crear caso UI» abre el grabador con la ruta ya puesta.').classes('text-xs text-gray-500')

                        if frontend_envs:
                            async def detect_views():
                                target_env = frontend_envs[0]
                                max_pages = 200 if detect_full.value else 15
                                progress = []
                                with ui.dialog().props('persistent') as scan_dialog, ui.card().classes('w-80'):
                                    ui.label(f'Escaneando «{target_env["name"]}»…').classes('font-semibold')
                                    bar = ui.linear_progress(value=0, show_value=False)
                                    status = ui.label(f'0 de {max_pages} página(s)').classes('text-gray-600 text-sm')
                                scan_dialog.open()

                                def tick():
                                    n = progress[-1] if progress else 0
                                    status.set_text(f'{n} de {max_pages} página(s)')
                                    bar.set_value(min(n / max_pages, 1))
                                timer = ui.timer(0.3, tick)
                                try:
                                    result = await run.io_bound(automation.discover_views, target_env['base_url'], detect_path.value,
                                                                  max_pages, 8000, progress.append)
                                finally:
                                    timer.cancel()
                                    scan_dialog.close()

                                if not result['ok']:
                                    ui.notify(f'No se pudo escanear «{target_env["name"]}»: {result["detail"]}', type='negative', multi_line=True)
                                    return
                                existing = {(v.get('path') or '').rstrip('/') for v in (core.get('modules', module['id']).get('views') or [])}
                                candidates = [v for v in result['views'] if v['path'].rstrip('/') not in existing]
                                if not candidates:
                                    ui.notify('No se encontraron vistas nuevas (o ya están todas catalogadas).', type='warning')
                                    return
                                with ui.dialog() as dialog, ui.card().classes('w-[32rem]'):
                                    ui.label(f'{len(candidates)} vista(s) encontradas en «{target_env["name"]}»').classes('font-semibold')
                                    ui.label('Siguió los enlaces del sitio ya renderizado; elige cuáles agregar al catálogo.').classes('text-xs text-gray-500')
                                    checks = []
                                    with ui.column().classes('w-full max-h-96 overflow-auto gap-1 mt-2'):
                                        for c in candidates:
                                            cb = ui.checkbox(f'{c["title"] or c["path"]} · {c["path"]}', value=True)
                                            checks.append((cb, c))
                                    with ui.row().classes('justify-end w-full gap-2 mt-2'):
                                        ui.button('Cancelar', on_click=dialog.close).props('flat')

                                        def confirm_add():
                                            dialog.close()
                                            added = sum(1 for cb, c in checks if cb.value and
                                                        core.add_component_view(module['id'], c['title'] or c['path'], c['path']))
                                            ui.notify(f'{added} vista(s) agregada(s)', type='positive')
                                            render_views()
                                        ui.button('Agregar seleccionadas', icon='add', on_click=guard(confirm_add)).props('color=primary')
                                dialog.open()
                            with ui.row().classes('items-end gap-3 w-full mt-2'):
                                detect_path = ui.input('Ruta inicial (opcional)', placeholder='/admin').props('outlined dense').classes('w-48') \
                                    .tooltip('Empieza el recorrido ahí en vez de la raíz del sitio — útil para acotarlo a una sección, p. ej. «/admin».')
                                detect_full = ui.checkbox('Escaneo completo (sin límite de 15 páginas)')
                                ui.button('Detectar vistas automáticamente', icon='travel_explore', on_click=guard(detect_views)) \
                                    .props('outline no-caps').mark('component-detect-views')
                            ui.label('Recorre el sitio desde el ambiente ligado siguiendo sus enlaces; no reemplaza una revisión manual, '
                                     'pero ahorra tipearlas una por una. Un escaneo completo puede tardar según el tamaño del sitio.').classes('text-xs text-gray-500')

                if not is_backend:
                    pass
                elif not operations:
                    with ui.card().classes('w-full'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('info', color='grey')
                            ui.label('Este componente no tiene un catálogo de operaciones todavía: la exploración automática no aplica hasta que lo tenga.').classes('text-sm text-gray-600')
                        ui.button('Crear un caso API a mano', icon='add', on_click=lambda: ui.navigate.to(f'/cases/edit?module={module["id"]}')).props('flat dense no-caps')

                    _manual_operations_card(module, pid)

                    with ui.card().classes('w-full'):
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('cloud_download', color='primary')
                            ui.label('Importar contrato').classes('font-semibold')
                        ui.label('Opcional: si este componente tiene un contrato OpenAPI/Swagger publicado, impórtalo para habilitar el catálogo de operaciones '
                                 'y la exploración automática. Nunca cambia el nombre ni la clasificación que ya definiste. Si el contrato declara etiquetas, '
                                 'puedes elegir importar solo algunas en vez de todo el catálogo.').classes('text-xs text-gray-500')
                        contract_url = ui.input('URL del contrato, de su página de Swagger UI o un enlace de GitHub').props('outlined dense').classes('w-full').mark('component-attach-url')
                        ui.label('Acepta el enlace directo al .json/.yaml, la página de Swagger UI / Redoc (se busca el contrato enlazado) o un enlace github.com/…/blob/….').classes('text-xs text-gray-500')

                        def finish_attach(updated):
                            ui.notify(f'Contrato importado: {len(updated["operations"])} operaciones.{_env_note(pid, updated)}', type='positive', multi_line=True)
                            ui.navigate.to(f'/modules/edit?id={module["id"]}')

                        async def offer_tags_then_attach(raw, source_url, attach):
                            tags_found = await run.io_bound(core.contract_tags, raw)
                            if not tags_found:
                                finish_attach(await run.io_bound(attach, None))
                                return
                            with ui.dialog() as dialog, ui.card():
                                ui.label('¿Importar todo el contrato, o solo algunas etiquetas?').classes('font-semibold')
                                ui.label('Deja vacío para importar todas las operaciones.').classes('text-xs text-gray-500')
                                picked = ui.select(tags_found, label='Etiquetas a importar (opcional)', multiple=True, clearable=True) \
                                    .props('outlined dense use-chips').classes('w-80').mark('component-attach-tags')
                                with ui.row().classes('justify-end w-full gap-2'):
                                    ui.button('Cancelar', on_click=dialog.close).props('flat')

                                    async def confirm_attach():
                                        dialog.close()
                                        finish_attach(await run.io_bound(attach, list(picked.value or []) or None))
                                    ui.button('Importar', icon='cloud_download', on_click=guard(confirm_attach)).props('color=primary').mark('component-attach-confirm')
                            dialog.open()

                        async def attach_from_url():
                            fetched = await run.io_bound(core.fetch_openapi, contract_url.value)

                            def do_attach(tags):
                                return core.attach_contract(module['id'], fetched['raw'], source_url=fetched['source_url'], tags=tags)
                            await offer_tags_then_attach(fetched['raw'], fetched['source_url'], do_attach)
                        ui.button('Importar desde URL', icon='cloud_download', on_click=guard(attach_from_url)).props('color=primary').mark('component-attach-from-url')

                        async def attach_upload(event):
                            try:
                                raw = (await read_upload(event)).decode('utf-8')

                                def do_attach(tags):
                                    return core.attach_contract(module['id'], raw, tags=tags)
                                await offer_tags_then_attach(raw, None, do_attach)
                            except Exception as exc:
                                ui.notify(str(exc), type='negative', multi_line=True)
                        ui.upload(label='O arrastra un archivo OpenAPI (.json/.yaml)', on_upload=attach_upload, auto_upload=True,
                                  max_file_size=MAX_SPEC_BYTES).props('accept=.json,.yaml,.yml flat bordered').classes('w-full')
                else:
                    with ui.tabs().classes('w-full') as cat_tabs:
                        tab_cat_auto = ui.tab('Automático')
                        tab_cat_manual = ui.tab('Manual')
                    with ui.tab_panels(cat_tabs, value=tab_cat_auto).classes('w-full'):
                        with ui.tab_panel(tab_cat_auto):
                            with ui.card().classes('w-full'):
                                with ui.row().classes('items-center gap-2'):
                                    ui.icon('travel_explore', color='primary')
                                    ui.label('Exploración automática').classes('font-semibold')
                                ui.label('Lee el contrato, identifica qué operaciones son seguras de probar (GET), consigue identificadores reales de otros '
                                         'listados y arma las aserciones a partir de lo que el contrato declara. Solo lecturas: nada que escriba se ejecuta aquí, '
                                         'y el resultado no se guarda hasta que lo confirmes.').classes('text-xs text-gray-500')
                                all_envs_here = core.list_project_items('environments', pid)
                                explore_envs = [e for e in all_envs_here if core.environment_flags(e)[0]]  # backend-capable only: exploring an OpenAPI contract needs an API, not a frontend dev server
                                if not explore_envs:
                                    msg = 'Registra un ambiente primero.' if not all_envs_here else \
                                        'Ninguno de los ambientes del proyecto está marcado como backend; ajústalo en Ambientes.'
                                    ui.label(msg).classes('text-xs text-amber-700')
                                else:
                                    explore_ids = {e['id'] for e in explore_envs}
                                    preferred = core.component_environment(module)
                                    default_env = preferred if preferred and preferred['id'] in explore_ids else explore_envs[0]
                                    env_select = ui.select({e['id']: e['name'] for e in explore_envs}, value=default_env['id'], label='Ambiente').props('outlined dense').classes('w-64')
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

                            if operations:
                                _operations_catalog_table(module, operations, marked=True)

                        with ui.tab_panel(tab_cat_manual):
                            _manual_operations_card(module, pid)
                            if operations:
                                _operations_catalog_table(module, operations, marked=False)

            # -------------------------------------------------------- Casos y funcionalidades
            with ui.tab_panel(tab_trace):
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

                with ui.card().classes('w-full'):
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('flag', color='primary')
                        ui.label(f'Funcionalidades que dependen de este componente ({len(dependent_features)})').classes('font-semibold')
                    if not dependent_features:
                        ui.label('Ninguna todavía: ninguna Suite con un caso de este componente está ligada a una Funcionalidad.').classes('text-sm text-gray-400')
                    else:
                        ui.label('Si este componente se cae, estas funcionalidades de negocio quedan afectadas.').classes('text-xs text-gray-500')
                        for f in dependent_features:
                            with ui.row().classes('items-center gap-2 w-full cursor-pointer hover:bg-gray-50').on('click', lambda _, fid=f['id']: ui.navigate.to(f'/features/edit?id={fid}')):
                                ui.icon('chevron_right', color='pink')
                                ui.label(f['name']).classes('text-sm text-gray-700 grow truncate')
