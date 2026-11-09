from nicegui import ui, run
from .. import core, llm
from .common import frame, guard, confirm, empty_state, require_project, protected_page

STATUS_LABELS = {'draft': 'Borrador', 'ready': 'Listo', 'automated': 'Automatizado'}
TYPE_LABELS = {'functional': 'Funcional', 'regression': 'Regresión', 'smoke': 'Smoke', 'exploratory': 'Exploratorio'}

# Mismo espíritu que ASSISTANT_THREADS de user_stories.py: un hilo por caso de prueba (o 'new'), en memoria.
ASSISTANT_THREADS = {}


@protected_page('/test-specs')
def test_specs_list():
    with frame('Casos de prueba', '/test-specs'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.label('El plan (precondición, pasos, resultado esperado) antes de automatizar — independiente de si alguna vez se automatiza.').classes('text-sm text-gray-500')
        ui.button('Nuevo caso de prueba', icon='add', on_click=lambda: ui.navigate.to('/test-specs/edit')).props('color=primary')

        items = core.list_project_items('test_case_specs', pid)
        if not items:
            empty_state('Este proyecto no tiene casos de prueba (especificación) todavía.')
            return

        stories = {s['id']: s['title'] for s in core.list_project_items('user_stories', pid)}
        columns = [
            {'name': 'title', 'label': 'Título', 'field': 'title', 'align': 'left', 'sortable': True},
            {'name': 'story', 'label': 'Historia', 'field': 'story', 'align': 'left'},
            {'name': 'type', 'label': 'Tipo', 'field': 'type', 'align': 'left'},
            {'name': 'priority', 'label': 'Prioridad', 'field': 'priority', 'align': 'left'},
            {'name': 'status', 'label': 'Estado', 'field': 'status', 'align': 'left'},
            {'name': 'actions', 'label': '', 'field': 'id', 'align': 'right'},
        ]

        def rows():
            return [{'id': s['id'], 'title': s['title'], 'story': stories.get(s.get('story_id'), '—'),
                     'type': TYPE_LABELS.get(s.get('type'), s.get('type')), 'priority': core.PRIORITY_LABELS.get(s.get('priority'), s.get('priority')),
                     'status': STATUS_LABELS.get(s.get('status'), s.get('status'))} for s in items]

        table = ui.table(columns=columns, rows=rows(), row_key='id', pagination=15).classes('w-full').mark('test-specs-table')
        table.props('flat bordered')
        table.add_slot('body-cell-actions', r'''
            <q-td :props="props" class="text-right" @click.stop>
                <q-btn flat dense round icon="chevron_right" color="grey-8" @click="$parent.$emit('viewSpec', props.row)">
                    <q-tooltip>Ver detalle</q-tooltip>
                </q-btn>
                <q-btn flat dense round icon="delete" color="negative" @click="$parent.$emit('deleteSpec', props.row)">
                    <q-tooltip>Eliminar</q-tooltip>
                </q-btn>
            </q-td>
        ''')
        table.on('rowClick', lambda e: ui.navigate.to(f'/test-specs/edit?id={e.args[1]["id"]}'))
        table.on('viewSpec', lambda e: ui.navigate.to(f'/test-specs/edit?id={e.args["id"]}'))

        def on_delete(e):
            row = e.args

            def attempt():
                core.delete_test_case_spec(row['id'])
                ui.notify('Caso de prueba eliminado', type='positive')
                ui.navigate.reload()
            confirm(f'¿Eliminar el caso de prueba «{row["title"]}»?', attempt)
        table.on('deleteSpec', on_delete)


@protected_page('/test-specs/edit')
def test_spec_detail(id: str = '', story_id: str = ''):
    with frame('Caso de prueba' if id else 'Nuevo caso de prueba', '/test-specs'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.link('← Volver a Casos de prueba', '/test-specs').classes('text-sm')

        current = core.get('test_case_specs', id) if id else None
        if id and (current is None or current.get('project_id') != pid):
            ui.label('Este caso de prueba ya no existe en el proyecto activo.').classes('text-amber-700')
            return

        d = {'steps': [dict(s) for s in (current or {}).get('steps', [])]}

        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('checklist', color='primary').classes('text-2xl')
                ui.label(current['title'] if current else 'Nuevo caso de prueba').classes('text-xl font-semibold')

            title = ui.input('Título', value=(current or {}).get('title', '')).props('outlined dense').classes('w-full').mark('spec-title')
            with ui.row().classes('w-full gap-3'):
                stories = core.list_project_items('user_stories', pid)
                default_story = (current or {}).get('story_id') or (story_id or None)
                story = ui.select({s['id']: s['title'] for s in stories}, value=default_story,
                                  label='Historia de usuario (opcional)', clearable=True).props('outlined dense').classes('w-60').mark('spec-story')
                features = core.list_project_items('features', pid)
                feature = ui.select({f['id']: f['name'] for f in features}, value=(current or {}).get('feature_id'),
                                    label='Funcionalidad (opcional)', clearable=True).props('outlined dense').classes('w-60')
            with ui.row().classes('w-full gap-3'):
                priority = ui.select(core.PRIORITY_LABELS, value=(current or {}).get('priority', 'medium'), label='Prioridad').props('outlined dense').classes('w-40')
                type_ = ui.select(TYPE_LABELS, value=(current or {}).get('type', 'functional'), label='Tipo').props('outlined dense').classes('w-44')
                cases = core.list_project_items('cases', pid)
                linked = ui.select({c['id']: c['name'] for c in cases}, value=(current or {}).get('linked_case_id'),
                                   label='Caso API/UI automatizado (opcional)', clearable=True).props('outlined dense').classes('w-64').mark('spec-linked-case')

            preconditions = ui.textarea('Precondición', value=(current or {}).get('preconditions', '')).props('outlined dense autogrow').classes('w-full')

            ui.separator().classes('my-2')
            ui.label('Pasos de ejecución y resultado esperado').classes('font-semibold')

            @ui.refreshable
            def step_rows():
                if not d['steps']:
                    ui.label('Ninguno todavía.').classes('text-sm text-gray-400')
                for index, s in enumerate(d['steps']):
                    with ui.row().classes('items-center gap-2 w-full no-wrap'):
                        ui.label(str(index + 1)).classes('w-6 text-gray-500')
                        ui.input('Paso', value=s.get('action', '')).props('outlined dense').classes('grow').mark('spec-step-action').on_value_change(lambda e, s=s: s.__setitem__('action', e.value))
                        ui.input('Resultado esperado', value=s.get('expected', '')).props('outlined dense').classes('grow').mark('spec-step-expected').on_value_change(lambda e, s=s: s.__setitem__('expected', e.value))
                        ui.button(icon='delete', on_click=lambda _, s=s: (d['steps'].remove(s), step_rows.refresh())).props('flat round dense color=negative')
            step_rows()
            ui.button('Agregar paso', icon='add', on_click=lambda: (d['steps'].append({'action': '', 'expected': ''}), step_rows.refresh())).props('outline dense color=primary').mark('spec-add-step')

            def save():
                if current:
                    core.update_test_case_spec(current['id'], title.value, story.value, feature.value, preconditions.value,
                                               d['steps'], priority.value, type_.value, linked.value)
                    ui.notify('Caso de prueba actualizado', type='positive')
                    ui.navigate.to(f'/test-specs/edit?id={current["id"]}')
                else:
                    spec = core.create_test_case_spec(title.value, pid, story.value, feature.value, preconditions.value,
                                                       d['steps'], priority.value, type_.value, linked.value)
                    ui.notify('Caso de prueba creado', type='positive')
                    ui.navigate.to(f'/test-specs/edit?id={spec["id"]}')
            ui.button('Guardar cambios' if current else 'Crear caso de prueba', icon='save', on_click=guard(save)).props('color=primary mt-2').mark('spec-save')

            if current:
                def remove(s=current):
                    core.delete_test_case_spec(s['id'])
                    ui.notify('Caso de prueba eliminado', type='positive')
                    ui.navigate.to('/test-specs')
                ui.button('Eliminar caso de prueba', icon='delete', on_click=lambda: confirm(f'¿Eliminar el caso de prueba «{current["title"]}»?', remove)) \
                    .props('flat dense color=negative mt-2').mark('spec-delete')

        # ------------------------------------------------------------ Asistente de IA (Fase 2)
        thread_key = current['id'] if current else 'new'
        thread = ASSISTANT_THREADS.setdefault(thread_key, [])
        candidates = {'items': None}

        def _apply_case_draft(tc, errors):
            if not tc:
                raise ValueError('; '.join(errors) or 'El modelo no devolvió un caso de prueba válido')
            title.set_value(tc['title'])
            preconditions.set_value(tc['preconditions'])
            priority.set_value(tc['priority'])
            type_.set_value(tc['type'])
            d['steps'] = [dict(s) for s in tc['steps']]
            step_rows.refresh()

        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('smart_toy', color='primary')
                ui.label('Asistente de IA').classes('font-semibold')
                ui.icon('info', size='xs', color='grey').classes('cursor-help').tooltip(
                    'Pedile que genere candidatos (desde la Historia ligada, o desde una descripción), o que '
                    'refine el caso de arriba. Lo que proponga queda para revisar antes de guardar/crear.')

            @ui.refreshable
            def assistant_view():
                if not thread:
                    ui.label('Pedile que genere casos de prueba, o que refine el de arriba.').classes('text-sm text-gray-400')
                for turn in thread:
                    with ui.chat_message(name='Vos' if turn['who'] == 'user' else 'Asistente', sent=turn['who'] == 'user').classes('w-full'):
                        ui.label(turn['text']).style('white-space:pre-wrap')
            assistant_view()

            @ui.refreshable
            def candidates_view():
                if not candidates['items']:
                    return
                with ui.card().classes('w-full bg-blue-50').props('flat'):
                    ui.label(f'{len(candidates["items"])} candidato(s) — elegí uno para cargarlo arriba').classes('font-semibold')
                    for tc in candidates['items']:
                        with ui.row().classes('items-center gap-2 w-full no-wrap'):
                            ui.label(f'{tc["title"]} — {len(tc["steps"])} paso(s) · {tc["type"]} · {tc["priority"]}').classes('text-sm grow')

                            def use(tc=tc):
                                _apply_case_draft(tc, [])
                                candidates['items'] = None
                                candidates_view.refresh()
                            ui.button('Usar este', on_click=guard(use)).props('flat dense size=sm color=primary').mark('spec-use-candidate')
                    ui.button('Descartar todos', on_click=lambda: (candidates.__setitem__('items', None), candidates_view.refresh())).props('flat dense')
            candidates_view()

            async def send(box):
                text = (box.value or '').strip()
                if not text:
                    return
                box.value = ''
                thread.append({'who': 'user', 'text': text})
                assistant_view.refresh()
                lowered = text.lower()
                try:
                    if any(k in lowered for k in llm.SPEC_REFINE_KEYWORDS):
                        item = {'title': title.value, 'preconditions': preconditions.value, 'steps': d['steps'],
                               'priority': priority.value, 'type': type_.value}
                        result = await run.io_bound(llm.refine_spec_item, 'test_case', item, text)
                        _apply_case_draft(result['item'], result['errors'])
                        reply = 'Refiné el caso de prueba — revisá los cambios arriba y guardá si te sirven.'
                    elif any(k in lowered for k in llm.SPEC_GENERATE_CASES_KEYWORDS) or not title.value.strip():
                        linked_story = core.get('user_stories', story.value) if story.value else None
                        envs = core.list_project_items('environments', pid)
                        result = await run.io_bound(llm.generate_test_cases, linked_story,
                                                    None if linked_story else [{'text': text}], envs[0] if envs else None)
                        if not result['valid']:
                            raise ValueError('; '.join(result['errors']))
                        candidates['items'] = result['test_cases']
                        candidates_view.refresh()
                        reply = f'Generé {len(result["test_cases"])} candidato(s) — elegí uno abajo para cargarlo arriba.'
                    else:
                        context = {'kind': 'caso de prueba', 'current': {'title': title.value, 'preconditions': preconditions.value, 'steps': d['steps']}}
                        reply = await run.io_bound(llm.spec_chat_reply, thread[:-1], text, context)
                except (llm.LLMError, ValueError) as exc:
                    reply = f'No pude: {exc}'
                thread.append({'who': 'assistant', 'text': reply})
                assistant_view.refresh()

            with ui.row().classes('w-full items-center gap-2'):
                box = ui.input(placeholder='Generá candidatos, o pedile que refine el caso de arriba…') \
                    .props('outlined dense').classes('grow').mark('spec-assistant-input')
                box.on('keydown.enter', lambda: send(box))
                ui.button(icon='send', on_click=lambda: send(box)).props('round dense color=primary').mark('spec-assistant-send')
