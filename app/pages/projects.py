from nicegui import ui
from .. import core
from .common import frame, guard, confirm, empty_state

RESOURCE_LABELS = (('modules', 'módulos'), ('environments', 'ambientes'), ('cases', 'casos'),
                    ('suites', 'suites'), ('schedules', 'programaciones'), ('taps', 'taps'))


@ui.page('/projects')
def projects():
    with frame('Proyectos', '/projects'):
        active_id = core.get_active_project_id()
        with ui.card().classes('w-full'):
            ui.label('Nuevo proyecto').classes('text-lg font-semibold')
            name = ui.input('Nombre').props('outlined dense').classes('w-full')
            description = ui.textarea('Descripción (opcional)').props('outlined dense autogrow').classes('w-full')

            def create():
                project = core.create_project(name.value or '', description.value or '')
                core.set_active_project(project['id'])
                ui.notify('Proyecto creado y seleccionado', type='positive')
                ui.navigate.reload()
            ui.button('Crear proyecto', icon='add', on_click=guard(create)).props('color=primary')

        items = core.list_items('projects')
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

        search = None
        if len(items) > 5:
            search = ui.input('Buscar por nombre').props('outlined dense clearable').classes('w-72').mark('project-search')

        @ui.refreshable
        def project_list():
            query = (search.value or '').strip().lower() if search else ''
            visible = [p for p in items if not query or query in p['name'].lower()]
            if not visible:
                ui.label('Ningún proyecto coincide con la búsqueda.').classes('text-gray-500')
            for project in visible:
                stats = core.project_stats(project['id'])
                is_active = project['id'] == active_id
                duplicated = name_counts.get(project['name'].strip().lower(), 0) > 1
                with ui.card().classes('w-full' + (' border-2 border-primary' if is_active else '')):
                    with ui.row().classes('items-center gap-2 w-full no-wrap'):
                        ui.icon('folder', color='primary' if is_active else 'grey')
                        ui.label(project['name']).classes('text-lg font-semibold')
                        if is_active:
                            ui.badge('Activo', color='primary')
                        if duplicated:
                            ui.label(f'#{project["id"][:8]}').classes('text-xs text-gray-400 font-mono').tooltip(
                                'Hay más de un proyecto con este nombre; usa este identificador para distinguirlos.')
                        ui.space()
                        summary = ' · '.join(f'{label} {stats[key]}' for key, label in RESOURCE_LABELS if stats[key])
                        ui.label(summary or 'Sin recursos todavía').classes('text-gray-500 text-xs')
                    if project.get('description'):
                        ui.label(project['description']).classes('text-sm text-gray-600 truncate w-full')

                    edit_box = ui.column().classes('w-full gap-2 mt-2')
                    edit_box.set_visibility(False)
                    with edit_box:
                        edit_name = ui.input('Nombre', value=project['name']).props('outlined dense').classes('w-full')
                        edit_description = ui.textarea('Descripción', value=project.get('description', '')).props('outlined dense autogrow').classes('w-full')

                        def save(item=project, n=edit_name, d=edit_description):
                            core.update_project(item['id'], n.value or '', d.value or '')
                            ui.notify('Proyecto actualizado', type='positive')
                            ui.navigate.reload()
                        with ui.row().classes('gap-2'):
                            ui.button('Guardar cambios', icon='save', on_click=guard(save)).props('outline').mark(f'project-save-{project["id"]}')
                            ui.button('Cancelar', on_click=lambda box=edit_box: box.set_visibility(False)).props('flat')

                    def select(item=project):
                        core.set_active_project(item['id'])
                        ui.navigate.reload()

                    def remove(item=project):
                        core.delete_project(item['id'])
                        ui.notify('Proyecto eliminado', type='positive')
                        ui.navigate.reload()

                    def toggle_edit(box=edit_box):
                        box.set_visibility(not box.visible)

                    with ui.row().classes('gap-1 mt-1'):
                        if not is_active:
                            ui.button('Seleccionar', icon='check', on_click=guard(select)).props('outline dense size=sm').mark(f'project-select-{project["id"]}')
                        ui.button(icon='edit', on_click=toggle_edit).props('flat dense round').tooltip('Editar').mark(f'project-edit-{project["id"]}')
                        ui.button(icon='delete', on_click=lambda _, i=project, r=remove: confirm(
                            f'¿Eliminar el proyecto «{i["name"]}»? Solo es posible si no tiene recursos.', r)).props(
                            'flat dense round color=negative').tooltip('Eliminar').mark(f'project-delete-{project["id"]}')
        project_list()
        if search:
            search.on_value_change(lambda _: project_list.refresh())
