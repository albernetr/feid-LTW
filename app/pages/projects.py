from nicegui import ui
from .. import core
from .common import frame, guard, confirm, empty_state


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
        if active_id and any(not i.get('project_id') for t in ('modules', 'environments', 'cases', 'suites', 'schedules') for i in core.list_items(t)):
            def adopt():
                ui.notify('Recursos asignados: ' + str(core.adopt_unassigned(active_id)), type='positive')
                ui.navigate.reload()
            with ui.card().classes('w-full bg-amber-50'):
                ui.label('Hay recursos de versiones anteriores sin proyecto; no aparecen al filtrar por proyecto.')
                ui.button('Asignarlos al proyecto activo', icon='drive_file_move', on_click=guard(adopt)).props('outline')

        for project in items:
            stats = core.project_stats(project['id'])
            is_active = project['id'] == active_id
            with ui.card().classes('w-full' + (' border-2 border-primary' if is_active else '')):
                with ui.row().classes('items-center gap-2'):
                    ui.label(project['name']).classes('text-lg font-semibold')
                    if is_active:
                        ui.badge('Activo', color='primary')
                edit_name = ui.input('Nombre', value=project['name']).props('outlined dense').classes('w-full')
                edit_description = ui.input('Descripción', value=project.get('description', '')).props('outlined dense').classes('w-full')
                ui.label('Recursos: ' + ' · '.join(f'{label} {stats[key]}' for key, label in (
                    ('modules', 'módulos'), ('environments', 'ambientes'), ('cases', 'casos'), ('suites', 'suites'), ('schedules', 'programaciones')))).classes('text-gray-500 text-sm')
                with ui.row().classes('gap-2'):
                    def save(item=project, n=edit_name, d=edit_description):
                        core.update_project(item['id'], n.value or '', d.value or '')
                        ui.notify('Proyecto actualizado', type='positive')
                        ui.navigate.reload()

                    def select(item=project):
                        core.set_active_project(item['id'])
                        ui.navigate.reload()

                    def remove(item=project):
                        core.delete_project(item['id'])
                        ui.notify('Proyecto eliminado', type='positive')
                        ui.navigate.reload()
                    ui.button('Guardar cambios', icon='save', on_click=guard(save)).props('outline')
                    if not is_active:
                        ui.button('Seleccionar', icon='check', on_click=guard(select)).props('outline')
                    ui.button('Eliminar', icon='delete', on_click=lambda _, i=project, r=remove: confirm(
                        f'¿Eliminar el proyecto «{i["name"]}»? Solo es posible si no tiene recursos.', r)).props('outline color=negative')
