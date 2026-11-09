from nicegui import ui
from .. import core
from .common import frame, guard, confirm, empty_state, require_project, fmt_time, protected_page

STATUS_LABELS = {'draft': 'Borrador', 'ready': 'Lista', 'done': 'Terminada'}
STORY_STATUSES = ('draft', 'ready', 'done')


@protected_page('/stories')
def stories_list():
    with frame('Historias de usuario', '/stories'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.label('Lo que se quiere lograr y por qué, antes de escribir ningún caso de prueba. Cada una puede ligarse a una Funcionalidad.').classes('text-sm text-gray-500')
        ui.button('Nueva historia', icon='add', on_click=lambda: ui.navigate.to('/stories/edit')).props('color=primary')

        items = core.list_project_items('user_stories', pid)
        if not items:
            empty_state('Este proyecto no tiene historias de usuario todavía.')
            return

        features = {f['id']: f['name'] for f in core.list_project_items('features', pid)}
        columns = [
            {'name': 'title', 'label': 'Título', 'field': 'title', 'align': 'left', 'sortable': True},
            {'name': 'feature', 'label': 'Funcionalidad', 'field': 'feature', 'align': 'left'},
            {'name': 'priority', 'label': 'Prioridad', 'field': 'priority', 'align': 'left'},
            {'name': 'status', 'label': 'Estado', 'field': 'status', 'align': 'left'},
            {'name': 'criteria', 'label': 'Criterios', 'field': 'criteria', 'align': 'center'},
            {'name': 'actions', 'label': '', 'field': 'id', 'align': 'right'},
        ]

        def rows():
            return [{'id': s['id'], 'title': s['title'], 'feature': features.get(s.get('feature_id'), '—'),
                     'priority': core.PRIORITY_LABELS.get(s.get('priority'), s.get('priority')),
                     'status': STATUS_LABELS.get(s.get('status'), s.get('status')), 'criteria': len(s.get('criteria') or [])}
                    for s in items]

        table = ui.table(columns=columns, rows=rows(), row_key='id', pagination=15).classes('w-full').mark('stories-table')
        table.props('flat bordered')
        table.add_slot('body-cell-actions', r'''
            <q-td :props="props" class="text-right" @click.stop>
                <q-btn flat dense round icon="chevron_right" color="grey-8" @click="$parent.$emit('viewStory', props.row)">
                    <q-tooltip>Ver detalle</q-tooltip>
                </q-btn>
                <q-btn flat dense round icon="delete" color="negative" @click="$parent.$emit('deleteStory', props.row)">
                    <q-tooltip>Eliminar</q-tooltip>
                </q-btn>
            </q-td>
        ''')
        table.on('rowClick', lambda e: ui.navigate.to(f'/stories/edit?id={e.args[1]["id"]}'))
        table.on('viewStory', lambda e: ui.navigate.to(f'/stories/edit?id={e.args["id"]}'))

        def on_delete(e):
            row = e.args

            def attempt():
                core.delete_user_story(row['id'])
                ui.notify('Historia eliminada', type='positive')
                ui.navigate.reload()
            confirm(f'¿Eliminar la historia «{row["title"]}»?', attempt)
        table.on('deleteStory', on_delete)


@protected_page('/stories/edit')
def story_detail(id: str = ''):
    with frame('Historia de usuario' if id else 'Nueva historia de usuario', '/stories'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.link('← Volver a Historias de usuario', '/stories').classes('text-sm')

        current = core.get('user_stories', id) if id else None
        if id and (current is None or current.get('project_id') != pid):
            ui.label('Esta historia ya no existe en el proyecto activo.').classes('text-amber-700')
            return

        d = {'criteria': [dict(c) for c in (current or {}).get('criteria', [])]}

        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('auto_stories', color='primary').classes('text-2xl')
                ui.label(current['title'] if current else 'Nueva historia de usuario').classes('text-xl font-semibold')

            title = ui.input('Título', value=(current or {}).get('title', '')).props('outlined dense').classes('w-full').mark('story-title')
            with ui.row().classes('w-full gap-3'):
                features = core.list_project_items('features', pid)
                feature = ui.select({f['id']: f['name'] for f in features}, value=(current or {}).get('feature_id'),
                                    label='Funcionalidad (opcional)', clearable=True).props('outlined dense').classes('w-60').mark('story-feature')
                priority = ui.select(core.PRIORITY_LABELS, value=(current or {}).get('priority', 'medium'), label='Prioridad').props('outlined dense').classes('w-40')
                status = ui.select(STATUS_LABELS, value=(current or {}).get('status', 'draft'), label='Estado').props('outlined dense').classes('w-40')

            ui.label('Como / Quiero / Para').classes('text-sm text-gray-500 mt-2')
            as_a = ui.input('Como (rol)', value=(current or {}).get('as_a', '')).props('outlined dense').classes('w-full')
            i_want = ui.input('Quiero (acción o funcionalidad)', value=(current or {}).get('i_want', '')).props('outlined dense').classes('w-full')
            so_that = ui.input('Para (beneficio o razón)', value=(current or {}).get('so_that', '')).props('outlined dense').classes('w-full')

            ui.separator().classes('my-2')
            ui.label('Criterios de aceptación').classes('font-semibold')

            @ui.refreshable
            def criteria_rows():
                if not d['criteria']:
                    ui.label('Ninguno todavía.').classes('text-sm text-gray-400')
                for c in d['criteria']:
                    with ui.row().classes('items-center gap-2 w-full no-wrap'):
                        ui.input(value=c['text']).props('outlined dense').classes('grow').mark('story-criterion-text') \
                            .on_value_change(lambda e, c=c: c.__setitem__('text', e.value))
                        ui.select({'pending': 'Pendiente', 'met': 'Cumplido'}, value=c.get('status', 'pending')) \
                            .props('outlined dense').classes('w-36').on_value_change(lambda e, c=c: c.__setitem__('status', e.value))
                        ui.button(icon='delete', on_click=lambda _, c=c: (d['criteria'].remove(c), criteria_rows.refresh())).props('flat round dense color=negative')
            criteria_rows()
            ui.button('Agregar criterio', icon='add',
                      on_click=lambda: (d['criteria'].append({'text': '', 'status': 'pending'}), criteria_rows.refresh())).props('outline dense color=primary').mark('story-add-criterion')

            def save():
                if current:
                    core.update_user_story(current['id'], title.value, as_a.value, i_want.value, so_that.value,
                                           feature.value, priority.value, d['criteria'], status.value)
                    ui.notify('Historia actualizada', type='positive')
                    ui.navigate.to(f'/stories/edit?id={current["id"]}')
                else:
                    story = core.create_user_story(title.value, pid, as_a.value, i_want.value, so_that.value, feature.value, priority.value, d['criteria'])
                    ui.notify('Historia creada', type='positive')
                    ui.navigate.to(f'/stories/edit?id={story["id"]}')
            ui.button('Guardar cambios' if current else 'Crear historia', icon='save', on_click=guard(save)).props('color=primary mt-2').mark('story-save')

            if current:
                def remove(s=current):
                    core.delete_user_story(s['id'])
                    ui.notify('Historia eliminada', type='positive')
                    ui.navigate.to('/stories')
                ui.button('Eliminar historia', icon='delete', on_click=lambda: confirm(f'¿Eliminar la historia «{current["title"]}»?', remove)) \
                    .props('flat dense color=negative mt-2').mark('story-delete')

        if not current:
            return

        specs = [s for s in core.list_project_items('test_case_specs', pid) if s.get('story_id') == current['id']]
        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('checklist', color='primary')
                ui.label(f'Casos de prueba ligados ({len(specs)})').classes('font-semibold')
            ui.button('Nuevo caso de prueba desde esta historia', icon='add',
                      on_click=lambda: ui.navigate.to(f'/test-specs/edit?story_id={current["id"]}')).props('outline dense color=primary')
            if not specs:
                ui.label('Ninguno todavía.').classes('text-sm text-gray-400')
            else:
                for spec in specs:
                    with ui.row().classes('items-center gap-2 w-full cursor-pointer hover:bg-gray-50') \
                            .on('click', lambda _, sid=spec['id']: ui.navigate.to(f'/test-specs/edit?id={sid}')):
                        ui.badge(spec.get('status', 'draft'), color='positive' if spec.get('status') == 'automated' else 'grey')
                        ui.label(spec['title']).classes('text-sm text-gray-700 grow truncate')
