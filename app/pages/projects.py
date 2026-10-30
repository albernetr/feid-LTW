from nicegui import ui
from .. import core, automation
from .common import frame, guard, confirm, empty_state, fmt_time

RESOURCE_LABELS = (('modules', 'módulos'), ('environments', 'ambientes'), ('cases', 'casos'),
                    ('suites', 'suites'), ('schedules', 'programaciones'), ('taps', 'taps'))


def _request_delete(project, on_done):
    """Tries the safe delete first; if the project still has content, offers the destructive cascade
    delete behind a type-the-name confirmation. `on_done()` runs after either one succeeds."""
    def attempt():
        try:
            core.delete_project(project['id'])
            ui.notify('Proyecto eliminado', type='positive')
            on_done()
        except ValueError as exc:
            if str(exc).startswith('No se puede eliminar:'):
                _offer_cascade_delete(project, str(exc), on_done)
            else:
                ui.notify(str(exc), type='negative', multi_line=True)
    confirm(f'¿Eliminar el proyecto «{project["name"]}»? Solo es posible si no tiene recursos.', attempt)


def _offer_cascade_delete(project, message, on_done):
    with ui.dialog() as dialog, ui.card():
        ui.label('Eliminar el proyecto con todo su contenido').classes('font-semibold text-red-700')
        ui.label(message).classes('text-sm text-gray-700')
        ui.label(f'Esto borra TODO lo del proyecto (módulos, ambientes, casos, suites, programaciones, taps e '
                 f'historial de ejecuciones) y no se puede deshacer. Escribe «{project["name"]}» para confirmar.').classes('text-sm text-gray-600')
        phrase = ui.input('Nombre del proyecto').props('outlined dense').mark('project-cascade-phrase')
        with ui.row().classes('justify-end w-full gap-2'):
            ui.button('Cancelar', on_click=dialog.close).props('flat')

            def accept():
                if (phrase.value or '') != project['name']:
                    ui.notify(f'Escribe exactamente «{project["name"]}» para confirmar.', type='warning')
                    return
                dialog.close()
                try:
                    core.delete_project_cascade(project['id'])
                    ui.notify('Proyecto y todo su contenido eliminados', type='positive')
                    on_done()
                except Exception as exc:
                    ui.notify(str(exc) or type(exc).__name__, type='negative', multi_line=True)
            ui.button('Borrar todo y eliminar', on_click=accept, color='negative').mark('project-cascade-accept')
    dialog.open()


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
            {'name': 'status', 'label': 'Estado', 'field': 'status', 'align': 'center', 'sortable': True},
            {'name': 'actions', 'label': '', 'field': 'id', 'align': 'right'},
        ]

        def rows():
            result = []
            for project in items:
                stats = core.project_stats(project['id'])
                resource_list = [{'label': label, 'count': stats[key]} for key, label in RESOURCE_LABELS if stats[key]]
                summary = ' · '.join(f'{r["label"]} {r["count"]}' for r in resource_list) or 'sin recursos'
                duplicated = name_counts.get(project['name'].strip().lower(), 0) > 1
                dup = f'#{project["id"][:8]}' if duplicated else ''
                is_active = project['id'] == active_id
                disabled = bool(project.get('disabled'))
                result.append({'id': project['id'], 'base_name': project['name'], 'dup': dup,
                               'name': project['name'] + (f'  {dup}' if dup else ''),
                               'description': project.get('description', '') or '—',
                               'resources': summary, 'resource_list': resource_list or [{'label': 'sin recursos', 'count': None}],
                               'active': is_active, 'disabled': disabled,
                               'status': 'disabled' if disabled else ('active' if is_active else '')})
            return result

        table = ui.table(columns=columns, rows=rows(), row_key='id', pagination=15).classes('w-full').mark('projects-table')
        table.props('flat bordered')
        table.add_slot('body-cell-name', r'''
            <q-td :props="props">
                <span :class="props.row.active ? 'text-weight-bold text-primary' : (props.row.disabled ? 'text-grey-6' : '')">{{ props.row.base_name }}</span>
                <span v-if="props.row.dup" class="text-grey-6 text-caption q-ml-xs">{{ props.row.dup }}</span>
            </q-td>
        ''')
        table.add_slot('body-cell-resources', r'''
            <q-td :props="props">
                <q-chip v-for="r in props.row.resource_list" :key="r.label" dense size="sm"
                        :color="r.count ? 'blue-1' : 'grey-3'" text-color="dark" class="q-mr-xs">
                    {{ r.count ? r.count + ' ' + r.label : r.label }}
                </q-chip>
            </q-td>
        ''')
        table.add_slot('body-cell-status', r'''
            <q-td :props="props">
                <q-badge v-if="props.value === 'active'" color="primary">Activo</q-badge>
                <q-badge v-else-if="props.value === 'disabled'" color="grey-6">Deshabilitado</q-badge>
            </q-td>
        ''')
        table.add_slot('body-cell-actions', r'''
            <q-td :props="props" class="text-right" @click.stop>
                <q-btn v-if="!props.row.active && !props.row.disabled" flat dense round icon="check" color="primary"
                       @click="$parent.$emit('selectProject', props.row)">
                    <q-tooltip>Seleccionar</q-tooltip>
                </q-btn>
                <q-btn flat dense round :icon="props.row.disabled ? 'unarchive' : 'archive'" color="grey-8"
                       @click="$parent.$emit('toggleProject', props.row)">
                    <q-tooltip>{{ props.row.disabled ? 'Habilitar' : 'Deshabilitar' }}</q-tooltip>
                </q-btn>
                <q-btn flat dense round icon="edit" color="grey-8" @click="$parent.$emit('editProject', props.row)">
                    <q-tooltip>Editar</q-tooltip>
                </q-btn>
                <q-btn flat dense round icon="delete" color="negative" @click="$parent.$emit('deleteProject', props.row)">
                    <q-tooltip>Eliminar</q-tooltip>
                </q-btn>
            </q-td>
        ''')
        table.on('rowClick', lambda e: ui.navigate.to(f'/projects/edit?id={e.args[1]["id"]}'))

        def on_select(e):
            # not wrapped with guard(): its *args/**kwargs signature makes NiceGUI's dispatcher think
            # it takes no arguments, so it would be called with none and the row would never arrive.
            try:
                core.set_active_project(e.args['id'])
                ui.navigate.reload()
            except Exception as exc:
                ui.notify(str(exc) or type(exc).__name__, type='negative', multi_line=True)
        table.on('selectProject', on_select)
        table.on('editProject', lambda e: ui.navigate.to(f'/projects/edit?id={e.args["id"]}'))

        def on_toggle(e):
            try:
                enabling = e.args['disabled']  # row's *current* state before the toggle
                core.set_project_enabled(e.args['id'], enabling)
                ui.notify('Proyecto habilitado' if enabling else 'Proyecto deshabilitado', type='positive')
                ui.navigate.reload()
            except Exception as exc:
                ui.notify(str(exc) or type(exc).__name__, type='negative', multi_line=True)
        table.on('toggleProject', on_toggle)

        def on_delete(e):
            row = e.args
            _request_delete({'id': row['id'], 'name': row['base_name']}, lambda: ui.navigate.reload())
        table.on('deleteProject', on_delete)

        ui.label('Haz clic en una fila (o en editar) para ver el detalle; selecciona, deshabilita o elimina directamente con los iconos.').classes('text-sm text-gray-500')

        def refresh(_=None):
            query = (search.value or '').strip().lower()
            table.rows = [r for r in rows() if not query or query in r['name'].lower()]
            table.update()
        search.on_value_change(refresh)


def _resource_card(project, icon, color, title, table_name, route, render_item):
    entries = core.list_project_items(table_name, project['id'])
    with ui.card().classes('flex-1 min-w-[280px]'):
        with ui.row().classes('items-center justify-between w-full no-wrap'):
            with ui.row().classes('items-center gap-2'):
                ui.avatar(icon, color=color, text_color='white', size='32px')
                with ui.column().classes('gap-0'):
                    ui.label(title).classes('font-semibold leading-tight')
                    ui.label(str(len(entries))).classes('text-xs text-gray-500 leading-tight')

            def goto(r=route):
                core.set_active_project(project['id'])
                ui.navigate.to(r)
            ui.button('Ver todos', icon='open_in_new', on_click=guard(goto)).props('flat dense size=sm no-caps').mark(f'project-goto-{table_name}')
        ui.separator().classes('my-1')
        if not entries:
            ui.label('Ninguno todavía.').classes('text-sm text-gray-400')
        for entry in entries[:5]:
            ui.label(render_item(entry)).classes('text-sm text-gray-700 truncate w-full')
        if len(entries) > 5:
            ui.label(f'y {len(entries) - 5} más…').classes('text-xs text-gray-400')


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
        is_disabled = bool(current) and bool(current.get('disabled'))

        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('folder', color='primary').classes('text-2xl')
                ui.label(current['name'] if current else 'Nuevo proyecto').classes('text-xl font-semibold')
                if is_active:
                    ui.badge('Activo', color='primary')
                if is_disabled:
                    ui.badge('Deshabilitado', color='grey-6')
            if current:
                ui.label(f'Última actualización: {fmt_time(current.get("updated_at"))}').classes('text-xs text-gray-400')

            ui.separator().classes('my-2')
            name = ui.input('Nombre', value=(current or {}).get('name', '')).props('outlined dense').classes('w-full').mark('project-name')
            description = ui.textarea('Descripción (opcional)', value=(current or {}).get('description', '')).props('outlined dense autogrow').classes('w-full')
            if is_disabled:
                with ui.row().classes('items-center gap-2 bg-amber-50 rounded px-3 py-2 w-full'):
                    ui.icon('info', color='warning')
                    ui.label('Este proyecto está deshabilitado: no se puede seleccionar como activo hasta que lo habilites.').classes('text-sm text-amber-800')

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

            def toggle_enabled():
                core.set_project_enabled(current['id'], is_disabled)  # flips: enables if currently disabled
                ui.notify('Proyecto habilitado' if is_disabled else 'Proyecto deshabilitado', type='positive')
                ui.navigate.to(f'/projects/edit?id={current["id"]}')

            with ui.row().classes('gap-2 items-center mt-2'):
                ui.button('Guardar cambios' if current else 'Crear proyecto', icon='save', on_click=guard(save)).props('color=primary').mark('project-save')
                if current and not is_active and not is_disabled:
                    ui.button('Seleccionar', icon='check', on_click=guard(select)).props('outline').mark('project-select')

            if current:
                ui.separator().classes('my-3')
                ui.label('Administración').classes('text-xs font-semibold text-gray-500 uppercase tracking-wide')
                with ui.row().classes('gap-2 items-center mt-1'):
                    ui.button('Habilitar' if is_disabled else 'Deshabilitar', icon='unarchive' if is_disabled else 'archive',
                              on_click=guard(toggle_enabled)).props('outline').mark('project-toggle-enabled')
                    ui.button('Eliminar', icon='delete', on_click=lambda: _request_delete(
                        current, lambda: ui.navigate.to('/projects'))).props('outline color=negative').mark('project-delete')

        if not current:
            return

        ui.label('Contenido del proyecto').classes('text-lg font-semibold mt-2')
        with ui.row().classes('w-full gap-4 flex-wrap'):
            _resource_card(current, 'api', 'blue', 'Módulos', 'modules', '/modules',
                            lambda m: f'{m["name"]} · {len(m.get("operations", []))} operaciones')
            _resource_card(current, 'dns', 'teal', 'Ambientes', 'environments', '/environments',
                            lambda e: f'{e["name"]} · {e.get("base_url", "")}')
            _resource_card(current, 'http', 'indigo', 'Casos', 'cases', '/cases',
                            lambda c: f'{c["name"]} · {"UI" if c.get("type") == "ui" else c.get("method", "API")}')
            _resource_card(current, 'playlist_play', 'deep-orange', 'Suites', 'suites', '/suites',
                            lambda s: f'{s["name"]} · {len(core.suite_steps(s))} paso(s)')
            _resource_card(current, 'schedule', 'purple', 'Programaciones', 'schedules', '/schedules',
                            lambda s: automation.describe_schedule(s))
