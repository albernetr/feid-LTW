from nicegui import ui
from .. import core
from .common import frame, guard, confirm, empty_state, require_project, status_badge, fmt_time, protected_page


@protected_page('/features')
def features_list():
    with frame('Funcionalidades', '/features'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.label('Capacidades de negocio que puede cruzar varios componentes/módulos. Cada una se valida con uno o más Flujos.').classes('text-sm text-gray-500')
        ui.button('Nueva funcionalidad', icon='add', on_click=lambda: ui.navigate.to('/features/edit')).props('color=primary')

        items = core.list_project_items('features', pid)
        if not items:
            empty_state('Este proyecto no tiene funcionalidades. Crea una (p. ej. «Checkout») y liga los Flujos que la validan.')
            return

        columns = [
            {'name': 'name', 'label': 'Nombre', 'field': 'name', 'align': 'left', 'sortable': True},
            {'name': 'external_ref', 'label': 'Referencia externa', 'field': 'external_ref', 'align': 'left'},
            {'name': 'health', 'label': 'Salud', 'field': 'health', 'align': 'center'},
            {'name': 'actions', 'label': '', 'field': 'id', 'align': 'right'},
        ]

        def rows():
            result = []
            for f in items:
                health = core.feature_health(f['id'])
                result.append({'id': f['id'], 'name': f['name'], 'external_ref': f.get('external_ref', '') or '—',
                               'health': f'{health["passing"]}/{health["total"]}' if health['total'] else 'sin flujos',
                               'has_data': health['total'] > 0, 'all_pass': health['total'] and health['passing'] == health['total']})
            return result

        table = ui.table(columns=columns, rows=rows(), row_key='id', pagination=15).classes('w-full').mark('features-table')
        table.props('flat bordered')
        table.add_slot('body-cell-health', r'''
            <q-td :props="props">
                <q-badge v-if="!props.row.has_data" color="grey-5">{{ props.value }}</q-badge>
                <q-badge v-else :color="props.row.all_pass ? 'positive' : 'negative'">{{ props.value }}</q-badge>
            </q-td>
        ''')
        table.add_slot('body-cell-actions', r'''
            <q-td :props="props" class="text-right" @click.stop>
                <q-btn flat dense round icon="chevron_right" color="grey-8" @click="$parent.$emit('viewFeature', props.row)">
                    <q-tooltip>Ver detalle</q-tooltip>
                </q-btn>
                <q-btn flat dense round icon="delete" color="negative" @click="$parent.$emit('deleteFeature', props.row)">
                    <q-tooltip>Eliminar</q-tooltip>
                </q-btn>
            </q-td>
        ''')
        table.on('rowClick', lambda e: ui.navigate.to(f'/features/edit?id={e.args[1]["id"]}'))
        table.on('viewFeature', lambda e: ui.navigate.to(f'/features/edit?id={e.args["id"]}'))

        def on_delete(e):
            row = e.args

            def attempt():
                core.delete_feature(row['id'])
                ui.notify('Funcionalidad eliminada', type='positive')
                ui.navigate.reload()
            confirm(f'¿Eliminar la funcionalidad «{row["name"]}»?', attempt)
        table.on('deleteFeature', on_delete)
        ui.label('Haz clic en una fila para ver sus flujos y su salud; elimina directamente con el icono (solo si no tiene flujos ligados).').classes('text-sm text-gray-500')


@protected_page('/features/edit')
def feature_detail(id: str = ''):
    with frame('Funcionalidad' if id else 'Nueva funcionalidad', '/features'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.link('← Volver a Funcionalidades', '/features').classes('text-sm')

        current = core.get('features', id) if id else None
        if id and (current is None or current.get('project_id') != pid):
            ui.label('Esta funcionalidad ya no existe en el proyecto activo.').classes('text-amber-700')
            return

        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('flag', color='primary').classes('text-2xl')
                ui.label(current['name'] if current else 'Nueva funcionalidad').classes('text-xl font-semibold')

            name = ui.input('Nombre', value=(current or {}).get('name', '')).props('outlined dense').classes('w-full').mark('feature-name')
            description = ui.textarea('Descripción (opcional)', value=(current or {}).get('description', '')).props('outlined dense autogrow').classes('w-full')
            external_ref = ui.input('Referencia externa (opcional)', value=(current or {}).get('external_ref', ''),
                                     placeholder='p. ej. ID de Feature en Azure DevOps o Jira').props('outlined dense').classes('w-full')

            def save():
                if current:
                    core.update_feature(current['id'], name.value, description.value or '', external_ref.value or '')
                    ui.notify('Funcionalidad actualizada', type='positive')
                    ui.navigate.to(f'/features/edit?id={current["id"]}')
                else:
                    feature = core.create_feature(name.value, pid, description.value or '', external_ref.value or '')
                    ui.notify('Funcionalidad creada', type='positive')
                    ui.navigate.to(f'/features/edit?id={feature["id"]}')
            ui.button('Guardar cambios' if current else 'Crear funcionalidad', icon='save', on_click=guard(save)).props('color=primary mt-2').mark('feature-save')

            if current:
                def remove(f=current):
                    core.delete_feature(f['id'])
                    ui.notify('Funcionalidad eliminada', type='positive')
                    ui.navigate.to('/features')
                ui.button('Eliminar funcionalidad', icon='delete', on_click=lambda: confirm(f'¿Eliminar la funcionalidad «{current["name"]}»?', remove)) \
                    .props('flat dense color=negative mt-2').mark('feature-delete')

        if not current:
            return

        health = core.feature_health(current['id'])
        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('playlist_play', color='primary')
                ui.label(f'Flujos que la validan ({health["total"]})').classes('font-semibold')
                if health['total']:
                    ui.badge(f'{health["passing"]}/{health["total"]} pasan', color='positive' if health['passing'] == health['total'] else 'negative')
            if not health['rows']:
                ui.label('Ninguno todavía. Liga un Flujo desde su propio editor.').classes('text-sm text-gray-400')
            else:
                for row in health['rows']:
                    suite, last = row['suite'], row['last_run']
                    with ui.row().classes('items-center gap-2 w-full cursor-pointer hover:bg-gray-50').on('click', lambda _, sid=suite['id']: ui.navigate.to(f'/suites/edit?id={sid}')):
                        if last:
                            status_badge(last['status'])
                            ui.label(fmt_time(last.get('started_at'))).classes('text-xs text-gray-400')
                        else:
                            ui.badge('Sin ejecutar', color='grey-5')
                        ui.label(suite['name']).classes('text-sm text-gray-700 grow truncate')
