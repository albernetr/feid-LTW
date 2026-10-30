from nicegui import ui
from .. import core, automation
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
                result.append({'id': project['id'], 'base_name': project['name'], 'dup': dup,
                               'name': project['name'] + (f'  {dup}' if dup else ''),
                               'description': project.get('description', '') or '—',
                               'resources': summary, 'resource_list': resource_list or [{'label': 'sin recursos', 'count': None}],
                               'active': is_active})
            return result

        table = ui.table(columns=columns, rows=rows(), row_key='id', pagination=15).classes('w-full').mark('projects-table')
        table.props('flat bordered')
        table.add_slot('body-cell-name', r'''
            <q-td :props="props">
                <span :class="props.row.active ? 'text-weight-bold text-primary' : ''">{{ props.row.base_name }}</span>
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
        table.add_slot('body-cell-active', '''<q-td :props="props"><q-badge v-if="props.value" color="primary">Activo</q-badge></q-td>''')
        table.add_slot('body-cell-actions', r'''
            <q-td :props="props" class="text-right" @click.stop>
                <q-btn v-if="!props.row.active" flat dense round icon="check" color="primary"
                       @click="$parent.$emit('selectProject', props.row)">
                    <q-tooltip>Seleccionar</q-tooltip>
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

        def on_delete(e):
            row = e.args

            def do_delete():
                core.delete_project(row['id'])
                ui.notify('Proyecto eliminado', type='positive')
                ui.navigate.reload()
            confirm(f'¿Eliminar el proyecto «{row["base_name"]}»? Solo es posible si no tiene recursos.', do_delete)
        table.on('deleteProject', on_delete)

        ui.label('Haz clic en una fila (o en editar) para ver el detalle; selecciona o elimina directamente con los iconos.').classes('text-sm text-gray-500')

        def refresh(_=None):
            query = (search.value or '').strip().lower()
            table.rows = [r for r in rows() if not query or query in r['name'].lower()]
            table.update()
        search.on_value_change(refresh)


def _resource_card(project, icon, title, table_name, route, render_item):
    entries = core.list_project_items(table_name, project['id'])
    with ui.card().classes('flex-1 min-w-[280px]'):
        with ui.row().classes('items-center justify-between w-full no-wrap'):
            with ui.row().classes('items-center gap-2'):
                ui.icon(icon, color='primary')
                ui.label(f'{title} ({len(entries)})').classes('font-semibold')

            def goto(r=route):
                core.set_active_project(project['id'])
                ui.navigate.to(r)
            ui.button('Ver todos', icon='open_in_new', on_click=guard(goto)).props('flat dense size=sm no-caps').mark(f'project-goto-{table_name}')
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

        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.label(current['name'] if current else 'Nuevo proyecto').classes('text-xl font-semibold')
                if is_active:
                    ui.badge('Activo', color='primary')
            name = ui.input('Nombre', value=(current or {}).get('name', '')).props('outlined dense').classes('w-full').mark('project-name')
            description = ui.textarea('Descripción (opcional)', value=(current or {}).get('description', '')).props('outlined dense autogrow').classes('w-full')

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

        if not current:
            return

        ui.label('Contenido del proyecto').classes('text-lg font-semibold mt-2')
        with ui.row().classes('w-full gap-4 flex-wrap'):
            _resource_card(current, 'api', 'Módulos', 'modules', '/modules',
                            lambda m: f'{m["name"]} · {len(m.get("operations", []))} operaciones')
            _resource_card(current, 'dns', 'Ambientes', 'environments', '/environments',
                            lambda e: f'{e["name"]} · {e.get("base_url", "")}')
            _resource_card(current, 'http', 'Casos', 'cases', '/cases',
                            lambda c: f'{c["name"]} · {"UI" if c.get("type") == "ui" else c.get("method", "API")}')
            _resource_card(current, 'playlist_play', 'Suites', 'suites', '/suites',
                            lambda s: f'{s["name"]} · {len(core.suite_steps(s))} paso(s)')
            _resource_card(current, 'schedule', 'Programaciones', 'schedules', '/schedules',
                            lambda s: automation.describe_schedule(s))
