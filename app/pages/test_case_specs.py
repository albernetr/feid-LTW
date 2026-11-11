import copy
from nicegui import ui, run
from .. import core, llm, spec_report
from .common import frame, guard, confirm, empty_state, require_project, protected_page, render_template_tree, doc_typography, live_doc_html, typography_button, remembered

STATUS_LABELS = {'draft': 'Borrador', 'ready': 'Listo', 'automated': 'Automatizado'}
TYPE_LABELS = {'functional': 'Funcional', 'regression': 'Regresión', 'smoke': 'Smoke', 'exploratory': 'Exploratorio'}

# Mismo espíritu que ASSISTANT_THREADS de user_stories.py: un hilo por caso de prueba (o 'new'), en memoria.
ASSISTANT_THREADS = {}


@protected_page('/test-specs')
def test_specs_list():
    with frame('Casos de prueba', '/test-specs', doc_style=True):
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
    with frame('Caso de prueba' if id else 'Nuevo caso de prueba', '/test-specs', full_width=True, doc_style=True):
        if not require_project():
            return
        pid = core.get_active_project_id()
        # Mismo layout que Historias de usuario/Plantillas (ver user_stories.py::story_detail,
        # spec_templates.py::spec_template_detail): vista previa en vivo al centro-izquierda, "Campos" a la
        # derecha con riel de pestañas gobernado por la plantilla de entrada elegida, separador ajustable,
        # colapsable con un clic en el ícono ya activo, modo compacto/scroll completo.
        compact, set_compact = remembered('spec_layout_compact', default=True)
        main_split_value, set_main_split_value_pref = remembered('spec_split_width', default=75)
        S = {'active_field_tab': 'general', 'fields_collapsed': False}

        def handle_rail_click(key):
            if S['active_field_tab'] == key:
                S['fields_collapsed'] = not S['fields_collapsed']
            else:
                S['active_field_tab'] = key
                S['fields_collapsed'] = False
            field_panels.set_visibility(not S['fields_collapsed'])
            if S['fields_collapsed']:
                S['split_before_collapse'] = main_split.value
                main_split.set_value(95)
            else:
                main_split.set_value(S.get('split_before_collapse', main_split_value))

        def toggle_compact():
            set_compact(not compact)
            ui.navigate.reload()

        current = core.get('test_case_specs', id) if id else None
        if id and (current is None or current.get('project_id') != pid):
            with ui.column().classes('w-full p-4 gap-2'):
                ui.link('← Volver a Casos de prueba', '/test-specs').classes('text-sm')
                ui.label('Este caso de prueba ya no existe en el proyecto activo.').classes('text-amber-700')
            return

        d = {'steps': [dict(s) for s in (current or {}).get('steps', [])],
            'custom': copy.deepcopy((current or {}).get('custom_fields') or {}),
            # Metadatos de registro: ya no están aparte — son campos conocidos más, que la plantilla ubica
            # donde quiera (ver core.DEFAULT_SPEC_TEMPLATES, grupo "General"). Igual se guardan acá, no en
            # `current` directamente: el widget de cada uno se re-crea entero cada vez que cambia la plantilla
            # elegida (como cualquier otro campo de un grupo), y así no se pierde una edición sin guardar.
            'meta': {'title': (current or {}).get('title', ''), 'story_id': (current or {}).get('story_id') or (story_id or None),
                     'feature_id': (current or {}).get('feature_id'), 'priority': (current or {}).get('priority', 'medium'),
                     'type': (current or {}).get('type', 'functional'), 'linked_case_id': (current or {}).get('linked_case_id')}}
        preconditions = None
        title = story = feature = priority = type_ = linked = input_template = None

        def _v(el):
            return el.value if el else ''

        def _set_meta(widget, key, value):
            # Ver el comentario equivalente en user_stories.py — un widget de metadatos puede no existir si la
            # plantilla elegida no lo incluye.
            if widget:
                widget.set_value(value)
            else:
                d['meta'][key] = value

        with ui.column().classes('w-full p-4 gap-4 ltw-doc'):
            with ui.row().classes('w-full items-center justify-between no-wrap'):
                with ui.column().classes('gap-0'):
                    ui.link('← Volver a Casos de prueba', '/test-specs').classes('text-sm')
                    ui.label('Caso de prueba' if current else 'Nuevo caso de prueba').classes('ltw-doc-title text-2xl font-semibold')
                with ui.row().classes('gap-1 shrink-0'):
                    if current:
                        ui.button(icon='tab', on_click=lambda: ui.navigate.to(f'/test-specs/view?id={current["id"]}', new_tab=True)) \
                            .props('flat round dense').mark('spec-open-viewer').tooltip('Abrir el visor interactivo del reporte')
                    ui.button(icon='fullscreen_exit' if compact else 'fullscreen', on_click=toggle_compact) \
                        .props('flat round dense').mark('spec-toggle-compact') \
                        .tooltip('Cambiar a modo con scroll completo' if compact else 'Cambiar a modo compacto (sin scroll, ancho completo)')
                    typography_button(lambda: document_view.refresh())

            with ui.element('div').classes('w-full').style('height: calc(100vh - 210px)' if compact else ''):
                with ui.splitter(value=main_split_value, limits=(40, 96), on_change=lambda e: set_main_split_value_pref(e.value)) \
                        .classes('w-full').style('height:100%' if compact else '') as main_split:
                    with main_split.after:
                        with ui.column().classes('w-full gap-4').style('height:100%;overflow:auto' if compact else ''):
                            with ui.card().classes('w-full p-0').style('overflow:visible' if compact else ''):
                                with ui.row().classes('items-center gap-2 p-4 pb-0'):
                                    ui.icon('edit_note', color='primary').classes('text-2xl')
                                    ui.label('Campos').classes('text-xl font-semibold')

                                with ui.column().classes('w-full gap-3 p-4 pt-2'):
                                    # Plantilla de ENTRADA elegida: cada grupo de primer nivel de su `body` es una
                                    # pestaña del riel (ver core.template_top_level_groups) — incluidos los
                                    # metadatos de registro (Título/Historia/.../Caso ligado), que son campos
                                    # conocidos más, no fijos fuera de toda plantilla (ver core.DEFAULT_SPEC_
                                    # TEMPLATES, grupo "General"). Su selector queda afuera del riel que gobierna:
                                    # siempre visible, no puede desaparecer por más que la plantilla activa no lo
                                    # mencione en su árbol (ver el comentario equivalente en user_stories.py).
                                    input_templates = [t for t in core.list_items('spec_templates') if t.get('kind') == 'input' and t.get('applies_to') == 'test_case'
                                                      and (t.get('project_id') is None or t.get('project_id') == pid)]
                                    saved_tpl_id = (current or {}).get('input_template_id')
                                    default_tpl_id = saved_tpl_id if any(t['id'] == saved_tpl_id for t in input_templates) else \
                                        (input_templates[0]['id'] if input_templates else None)
                                    input_template = ui.select({t['id']: t['name'] for t in input_templates}, value=default_tpl_id, label='Plantilla de entrada') \
                                        .props('outlined dense').classes('w-full mt-2').mark('spec-input-template') if input_templates else None

                                    field_panels = None
                                    known_renderers = {}

                                    def render_title():
                                        nonlocal title
                                        title = ui.input('Título', value=d['meta']['title']).props('outlined dense').classes('w-full') \
                                            .mark('spec-title').on_value_change(lambda e: (d['meta'].__setitem__('title', e.value), document_view.refresh()))
                                    known_renderers['title'] = render_title

                                    def render_story():
                                        nonlocal story
                                        stories = core.list_project_items('user_stories', pid)
                                        story = ui.select({s['id']: s['title'] for s in stories}, value=d['meta']['story_id'],
                                                          label='Historia de usuario (opcional)', clearable=True).props('outlined dense').classes('w-full').mark('spec-story') \
                                            .on_value_change(lambda e: d['meta'].__setitem__('story_id', e.value))
                                    known_renderers['story_id'] = render_story

                                    def render_feature():
                                        nonlocal feature
                                        features = core.list_project_items('features', pid)
                                        feature = ui.select({f['id']: f['name'] for f in features}, value=d['meta']['feature_id'],
                                                            label='Funcionalidad (opcional)', clearable=True).props('outlined dense').classes('w-full') \
                                            .on_value_change(lambda e: d['meta'].__setitem__('feature_id', e.value))
                                    known_renderers['feature_id'] = render_feature

                                    def render_priority():
                                        nonlocal priority
                                        priority = ui.select(core.PRIORITY_LABELS, value=d['meta']['priority'], label='Prioridad').props('outlined dense').classes('w-full') \
                                            .on_value_change(lambda e: d['meta'].__setitem__('priority', e.value))
                                    known_renderers['priority'] = render_priority

                                    def render_type():
                                        nonlocal type_
                                        type_ = ui.select(TYPE_LABELS, value=d['meta']['type'], label='Tipo').props('outlined dense').classes('w-full') \
                                            .on_value_change(lambda e: d['meta'].__setitem__('type', e.value))
                                    known_renderers['type'] = render_type

                                    def render_linked():
                                        nonlocal linked
                                        cases = core.list_project_items('cases', pid)
                                        linked = ui.select({c['id']: c['name'] for c in cases}, value=d['meta']['linked_case_id'],
                                                           label='Caso API/UI automatizado (opcional)', clearable=True).props('outlined dense').classes('w-full').mark('spec-linked-case') \
                                            .on_value_change(lambda e: d['meta'].__setitem__('linked_case_id', e.value))
                                    known_renderers['linked_case_id'] = render_linked

                                    def render_preconditions():
                                        nonlocal preconditions
                                        preconditions = ui.textarea('Precondición', value=(current or {}).get('preconditions', '')).props('outlined dense autogrow') \
                                            .classes('w-full').mark('spec-preconditions').on_value_change(lambda e: document_view.refresh())
                                    known_renderers['preconditions'] = render_preconditions

                                    @ui.refreshable
                                    def step_rows():
                                        if not d['steps']:
                                            ui.label('Ninguno todavía.').classes('text-sm text-gray-400')
                                        for index, s in enumerate(d['steps']):
                                            with ui.row().classes('items-start gap-2 w-full no-wrap'):
                                                ui.label(str(index + 1)).classes('w-6 text-gray-500 pt-3')
                                                ui.textarea('Paso', value=s.get('action', '')).props('outlined dense autogrow').classes('grow').mark('spec-step-action') \
                                                    .on_value_change(lambda e, s=s: (s.__setitem__('action', e.value), document_view.refresh()))
                                                ui.textarea('Resultado esperado', value=s.get('expected', '')).props('outlined dense autogrow').classes('grow').mark('spec-step-expected') \
                                                    .on_value_change(lambda e, s=s: (s.__setitem__('expected', e.value), document_view.refresh()))
                                                ui.button(icon='delete', on_click=lambda _, s=s: (d['steps'].remove(s), step_rows.refresh(), document_view.refresh())) \
                                                    .props('flat round dense color=negative').classes('mt-1')

                                    def render_steps():
                                        ui.label('Pasos de ejecución y resultado esperado').classes('font-semibold')
                                        step_rows()
                                        ui.button('Agregar paso', icon='add', on_click=lambda: (d['steps'].append({'action': '', 'expected': ''}),
                                                  step_rows.refresh(), document_view.refresh())).props('outline dense color=primary').mark('spec-add-step')
                                    known_renderers['steps'] = render_steps

                                    @ui.refreshable
                                    def fields_section():
                                        nonlocal field_panels
                                        tpl = core.get('spec_templates', input_template.value) if input_template and input_template.value else None
                                        groups = core.template_top_level_groups(tpl.get('body')) if tpl else [
                                            {'id': 'general', 'label': 'General', 'icon': 'edit_note', 'children': [
                                                {'kind': 'field', 'field_key': 'title', 'field_type': None, 'label': 'Título'},
                                                {'kind': 'field', 'field_key': 'preconditions', 'field_type': None, 'label': 'Precondición'},
                                                {'kind': 'field', 'field_key': 'steps', 'field_type': None, 'label': 'Pasos de ejecución'}]}]
                                        if not any(g['id'] == S['active_field_tab'] for g in groups):
                                            S['active_field_tab'] = groups[0]['id'] if groups else 'general'
                                        with ui.row().classes('w-full no-wrap gap-0').style('min-height:260px;justify-content:flex-end'):
                                            with ui.tab_panels(None, value=S['active_field_tab']).props('vertical').style('flex:1 1 0;min-width:0;padding:8px 0') as field_panels:
                                                for group in groups:
                                                    with ui.tab_panel(group['id']).classes('gap-3 p-0'):
                                                        render_template_tree(group['children'], d['custom'], known_renderers, on_change=lambda: document_view.refresh())
                                            with ui.tabs().props('vertical dense no-caps').classes('shrink-0').style('width:56px;border-left:1px solid #e5e7eb') as field_rail:
                                                for group in groups:
                                                    ui.tab(group['id'], label='', icon=group['icon'] or 'folder').tooltip(group['label']).mark(f'spec-rail-{group["id"]}') \
                                                        .on('click', lambda gid=group['id']: handle_rail_click(gid))
                                            field_panels.bind_value_from(field_rail, 'value')
                                            field_rail.set_value(S['active_field_tab'])
                                    fields_section()
                                    if input_template:
                                        input_template.on_value_change(lambda e: (fields_section.refresh(), document_view.refresh()))

                                def save():
                                    if current:
                                        core.update_test_case_spec(current['id'], d['meta']['title'], d['meta']['story_id'], d['meta']['feature_id'], _v(preconditions),
                                                                   d['steps'], d['meta']['priority'], d['meta']['type'], d['meta']['linked_case_id'], custom_fields=d['custom'],
                                                                   input_template_id=input_template.value if input_template else None)
                                        ui.notify('Caso de prueba actualizado', type='positive')
                                        ui.navigate.to(f'/test-specs/edit?id={current["id"]}')
                                    else:
                                        spec = core.create_test_case_spec(d['meta']['title'], pid, d['meta']['story_id'], d['meta']['feature_id'], _v(preconditions),
                                                                           d['steps'], d['meta']['priority'], d['meta']['type'], d['meta']['linked_case_id'], custom_fields=d['custom'],
                                                                           input_template_id=input_template.value if input_template else None)
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

                    with main_split.before:
                        with ui.column().classes('w-full gap-4 min-w-0').style('height:100%' if compact else ''):
                            with ui.card().classes('w-full').mark('spec-document').style('height:100%;overflow:auto' if compact else ''):
                                @ui.refreshable
                                def document_view():
                                    ui.label(d['meta']['title'] or 'Nuevo caso de prueba').classes('text-2xl font-bold')
                                    # Solo lo que la plantilla de entrada elegida define, en su orden — incluidos
                                    # los metadatos de registro (priority/type: campos conocidos más, no fijos).
                                    tpl = core.get('spec_templates', input_template.value) if input_template and input_template.value else None
                                    fields = list(core.iter_template_fields(tpl.get('body'))) if tpl else \
                                        [{'kind': 'field', 'field_key': k, 'field_type': None} for k in ('preconditions', 'steps')]
                                    fragment = spec_report.render_test_case_view_html({'preconditions': _v(preconditions), 'steps': d['steps'],
                                                                                       'priority': d['meta']['priority'], 'type': d['meta']['type']}, fields, d['custom'])
                                    ui.html(live_doc_html(fragment, doc_typography()[0])).classes('w-full')
                                document_view()

        # ------------------------------------------------------------ Asistente de IA (Fase 2)
        thread_key = current['id'] if current else 'new'
        thread = ASSISTANT_THREADS.setdefault(thread_key, [])
        candidates = {'items': None}

        def _apply_case_draft(tc, errors):
            if not tc:
                raise ValueError('; '.join(errors) or 'El modelo no devolvió un caso de prueba válido')
            _set_meta(title, 'title', tc['title'])
            if preconditions:
                preconditions.set_value(tc['preconditions'])
            _set_meta(priority, 'priority', tc['priority'])
            _set_meta(type_, 'type', tc['type'])
            d['steps'] = [dict(s) for s in tc['steps']]
            step_rows.refresh()
            document_view.refresh()

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
                            ui.label(f'{tc["title"]} — {len(tc["steps"])} paso(s) · {TYPE_LABELS.get(tc["type"], tc["type"])} · '
                                    f'{core.PRIORITY_LABELS.get(tc["priority"], tc["priority"])}').classes('text-sm grow')

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
                        item = {'title': d['meta']['title'], 'preconditions': _v(preconditions), 'steps': d['steps'],
                               'priority': d['meta']['priority'], 'type': d['meta']['type']}
                        result = await run.io_bound(llm.refine_spec_item, 'test_case', item, text)
                        _apply_case_draft(result['item'], result['errors'])
                        reply = 'Refiné el caso de prueba — revisá los cambios arriba y guardá si te sirven.'
                    elif any(k in lowered for k in llm.SPEC_GENERATE_CASES_KEYWORDS) or not d['meta']['title'].strip():
                        linked_story = core.get('user_stories', d['meta']['story_id']) if d['meta']['story_id'] else None
                        envs = core.list_project_items('environments', pid)
                        result = await run.io_bound(llm.generate_test_cases, linked_story,
                                                    None if linked_story else [{'text': text}], envs[0] if envs else None)
                        if not result['valid']:
                            raise ValueError('; '.join(result['errors']))
                        candidates['items'] = result['test_cases']
                        candidates_view.refresh()
                        reply = f'Generé {len(result["test_cases"])} candidato(s) — elegí uno abajo para cargarlo arriba.'
                    else:
                        context = {'kind': 'caso de prueba', 'current': {'title': d['meta']['title'], 'preconditions': _v(preconditions), 'steps': d['steps']}}
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
