from nicegui import ui
from .. import core
from .common import frame, guard, confirm, empty_state

RESOURCE_LABELS = (('modules', 'módulos'), ('environments', 'ambientes'), ('cases', 'casos'),
                    ('suites', 'suites'), ('schedules', 'programaciones'), ('taps', 'taps'))


@ui.page('/projects')
def projects_list():
    with frame('Proyectos', '/projects'):
        active_id = core.get_active_project_id()
        items = core.list_items('projects')

        with ui.row().classes('items-center gap-3 w-full'):
            ui.button('Nuevo proyecto', icon='add', on_click=lambda: ui.navigate.to('/projects/edit')).props('color=primary')
            search = ui.input('Buscar por nombre').props('outlined dense clearable').classes('w-72').mark('project-search')

        if not items:
            empty_state('Aún no hay proyectos. Crea el primero para empezar.')
            return

        if active_id and any(not i.get('project_id') for t in ('modules', 'environments', 'cases', 'suites', 'schedules') for i in core.list_items(t)):
            def adopt():
                ui.notify('Recursos asignados: ' + str(core.adopt_unassigned(active_id)), type='positive')
                ui.navigate.reload()
            with ui.card().classes('w-full bg-amber-50'):
                ui.label('Hay recursos de versiones anteriores sin proyecto; no aparecen al filtrar por proyecto.')
                ui.button('Asignarlos al proyecto activo', icon='drive_file_move', on_click=guard(adopt)).props('outline')

        name_counts = {}
        for p in items:
            key = p['name'].strip().lower()
            name_counts[key] = name_counts.get(key, 0) + 1

        columns = [
            {'name': 'name', 'label': 'Nombre', 'field': 'name', 'align': 'left', 'sortable': True},
            {'name': 'description', 'label': 'Descripción', 'field': 'description', 'align': 'left'},
            {'name': 'resources', 'label': 'Recursos', 'field': 'resources', 'align': 'left'},
            {'name': 'active', 'label': 'Activo', 'field': 'active', 'align': 'center', 'sortable': True},
        ]

        def rows():
            result = []
            for project in items:
                stats = core.project_stats(project['id'])
                summary = ' · '.join(f'{label} {stats[key]}' for key, label in RESOURCE_LABELS if stats[key]) or 'sin recursos'
                duplicated = name_counts.get(project['name'].strip().lower(), 0) > 1
                name = project['name'] + (f'  #{project["id"][:8]}' if duplicated else '')
                result.append({'id': project['id'], 'name': name, 'description': project.get('description', '') or '—',
                               'resources': summary, 'active': 'Sí' if project['id'] == active_id else ''})
            return result

        table = ui.table(columns=columns, rows=rows(), row_key='id', pagination=15).classes('w-full').mark('projects-table')
        table.props('flat bordered')
        table.add_slot('body-cell-active', '''<q-td :props="props"><q-badge v-if="props.value" color="primary">Activo</q-badge></q-td>''')
        table.on('rowClick', lambda e: ui.navigate.to(f'/projects/edit?id={e.args[1]["id"]}'))
        ui.label('Haz clic en una fila para ver el detalle, editarlo, seleccionarlo o eliminarlo.').classes('text-sm text-gray-500')

        def refresh(_=None):
            query = (search.value or '').strip().lower()
            table.rows = [r for r in rows() if not query or query in r['name'].lower()]
            table.update()
        search.on_value_change(refresh)


@ui.page('/projects/edit')
def project_edit(id: str = ''):
    with frame('Proyecto' if id else 'Nuevo proyecto', '/projects'):
        ui.link('← Volver a Proyectos', '/projects').classes('text-sm')
        current = core.get('projects', id) if id else None
        if id and current is None:
            ui.label('Este proyecto ya no existe.').classes('text-amber-700')
            return
        active_id = core.get_active_project_id()
        is_active = bool(current) and current['id'] == active_id

        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.label(current['name'] if current else 'Nuevo proyecto').classes('text-xl font-semibold')
                if is_active:
                    ui.badge('Activo', color='primary')
            name = ui.input('Nombre', value=(current or {}).get('name', '')).props('outlined dense').classes('w-full').mark('project-name')
            description = ui.textarea('Descripción (opcional)', value=(current or {}).get('description', '')).props('outlined dense autogrow').classes('w-full')

            if current:
                stats = core.project_stats(current['id'])
                ui.label('Recursos: ' + (' · '.join(f'{label} {stats[key]}' for key, label in RESOURCE_LABELS if stats[key]) or 'sin recursos todavía')).classes('text-sm text-gray-500')

            def save():
                if current:
                    core.update_project(current['id'], name.value or '', description.value or '')
                    ui.notify('Proyecto actualizado', type='positive')
                    ui.navigate.to(f'/projects/edit?id={current["id"]}')
                else:
                    project = core.create_project(name.value or '', description.value or '')
                    core.set_active_project(project['id'])
                    ui.notify('Proyecto creado y seleccionado', type='positive')
                    ui.navigate.to(f'/projects/edit?id={project["id"]}')

            def select():
                core.set_active_project(current['id'])
                ui.navigate.reload()

            def remove():
                core.delete_project(current['id'])
                ui.notify('Proyecto eliminado', type='positive')
                ui.navigate.to('/projects')

            with ui.row().classes('gap-2'):
                ui.button('Guardar cambios' if current else 'Crear proyecto', icon='save', on_click=guard(save)).props('color=primary').mark('project-save')
                if current and not is_active:
                    ui.button('Seleccionar', icon='check', on_click=guard(select)).props('outline').mark('project-select')
                if current:
                    ui.button('Eliminar', icon='delete', on_click=lambda: confirm(
                        f'¿Eliminar el proyecto «{current["name"]}»? Solo es posible si no tiene recursos.', remove)).props('outline color=negative').mark('project-delete')
