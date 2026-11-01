from nicegui import ui
from .. import core
from .common import frame, guard, confirm, empty_state, require_project


@ui.page('/module-groups')
def module_groups_list():
    with frame('Módulos', '/module-groups'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.label('Agrupan los componentes por dominio o propiedad técnica: quién es dueño y dónde vive cada pieza de la solución.').classes('text-sm text-gray-500')
        ui.button('Nuevo módulo', icon='add', on_click=lambda: ui.navigate.to('/module-groups/edit')).props('color=primary')

        items = core.list_project_items('module_groups', pid)
        if not items:
            empty_state('Este proyecto no tiene módulos. Un módulo agrupa componentes relacionados (p. ej. «Pagos», «Identidad»).')
            return

        all_components = core.list_project_items('modules', pid)
        columns = [
            {'name': 'name', 'label': 'Nombre', 'field': 'name', 'align': 'left', 'sortable': True},
            {'name': 'description', 'label': 'Descripción', 'field': 'description', 'align': 'left'},
            {'name': 'components', 'label': 'Componentes', 'field': 'components', 'align': 'center', 'sortable': True},
            {'name': 'actions', 'label': '', 'field': 'id', 'align': 'right'},
        ]

        def rows():
            return [{'id': g['id'], 'name': g['name'], 'description': g.get('description', '') or '—',
                      'components': sum(1 for m in all_components if g['id'] in core.component_module_group_ids(m))} for g in items]

        table = ui.table(columns=columns, rows=rows(), row_key='id', pagination=15).classes('w-full').mark('module-groups-table')
        table.props('flat bordered')
        table.add_slot('body-cell-components', r'''
            <q-td :props="props">
                <q-chip v-if="props.value" dense size="sm" color="blue-1" text-color="dark">{{ props.value }}</q-chip>
                <span v-else class="text-grey-5">—</span>
            </q-td>
        ''')
        table.add_slot('body-cell-actions', r'''
            <q-td :props="props" class="text-right" @click.stop>
                <q-btn flat dense round icon="chevron_right" color="grey-8" @click="$parent.$emit('viewGroup', props.row)">
                    <q-tooltip>Ver detalle</q-tooltip>
                </q-btn>
                <q-btn flat dense round icon="delete" color="negative" @click="$parent.$emit('deleteGroup', props.row)">
                    <q-tooltip>Eliminar</q-tooltip>
                </q-btn>
            </q-td>
        ''')
        table.on('rowClick', lambda e: ui.navigate.to(f'/module-groups/edit?id={e.args[1]["id"]}'))
        table.on('viewGroup', lambda e: ui.navigate.to(f'/module-groups/edit?id={e.args["id"]}'))

        def on_delete(e):
            row = e.args

            def attempt():
                core.delete_module_group(row['id'])
                ui.notify('Módulo eliminado', type='positive')
                ui.navigate.reload()
            confirm(f'¿Eliminar el módulo «{row["name"]}»?', attempt)
        table.on('deleteGroup', on_delete)
        ui.label('Haz clic en una fila para ver sus componentes; elimina directamente con el icono (solo si no tiene componentes ligados).').classes('text-sm text-gray-500')


@ui.page('/module-groups/edit')
def module_group_detail(id: str = ''):
    with frame('Módulo' if id else 'Nuevo módulo', '/module-groups'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.link('← Volver a Módulos', '/module-groups').classes('text-sm')

        current = core.get('module_groups', id) if id else None
        if id and (current is None or current.get('project_id') != pid):
            ui.label('Este módulo ya no existe en el proyecto activo.').classes('text-amber-700')
            return

        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('account_tree', color='primary').classes('text-2xl')
                ui.label(current['name'] if current else 'Nuevo módulo').classes('text-xl font-semibold')

            name = ui.input('Nombre', value=(current or {}).get('name', '')).props('outlined dense').classes('w-full').mark('module-group-name')
            description = ui.textarea('Descripción (opcional)', value=(current or {}).get('description', '')).props('outlined dense autogrow').classes('w-full')

            def save():
                if current:
                    core.update_module_group(current['id'], name.value, description.value or '')
                    ui.notify('Módulo actualizado', type='positive')
                    ui.navigate.to(f'/module-groups/edit?id={current["id"]}')
                else:
                    group = core.create_module_group(name.value, pid, description.value or '')
                    ui.notify('Módulo creado', type='positive')
                    ui.navigate.to(f'/module-groups/edit?id={group["id"]}')
            ui.button('Guardar cambios' if current else 'Crear módulo', icon='save', on_click=guard(save)).props('color=primary mt-2').mark('module-group-save')

            if current:
                def remove(g=current):
                    core.delete_module_group(g['id'])
                    ui.notify('Módulo eliminado', type='positive')
                    ui.navigate.to('/module-groups')
                ui.button('Eliminar módulo', icon='delete', on_click=lambda: confirm(f'¿Eliminar el módulo «{current["name"]}»?', remove)) \
                    .props('flat dense color=negative mt-2').mark('module-group-delete')

        if not current:
            return

        components = [m for m in core.list_project_items('modules', pid) if current['id'] in core.component_module_group_ids(m)]
        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('widgets', color='primary')
                ui.label(f'Componentes de este módulo ({len(components)})').classes('font-semibold')
            if not components:
                ui.label('Ninguno todavía. Liga un componente desde su propio detalle.').classes('text-sm text-gray-400')
            else:
                for m in components:
                    backend, frontend = core.component_flags(m)
                    with ui.row().classes('items-center gap-2 w-full cursor-pointer hover:bg-gray-50').on('click', lambda _, mid=m['id']: ui.navigate.to(f'/modules/edit?id={mid}')):
                        ui.badge(core.component_kind_label(m), color='teal' if (backend and frontend) else ('purple' if frontend else 'blue-grey'))
                        ui.label(m['name']).classes('text-sm text-gray-700 grow truncate')
                        ui.label(core.COMPONENT_STATUS_LABELS.get(m.get('status', 'development'), '')).classes('text-xs text-gray-500')
