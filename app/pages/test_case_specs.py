import copy
from nicegui import ui, run
from .. import assistant_memory, core, llm, spec_report
from ..assistant import AssistantIntent, AssistantProfile, assistant_header, assistant_memory_menu_items, assistant_panel
from .common import frame, guard, confirm, empty_state, require_project, protected_page, render_template_tree, doc_typography, live_doc_html, typography_button, remembered
from ..layouts import Panel, workspace_layout

STATUS_LABELS = {'draft': 'Borrador', 'ready': 'Listo', 'automated': 'Automatizado'}
TYPE_LABELS = {'functional': 'Funcional', 'regression': 'Regresión', 'smoke': 'Smoke', 'exploratory': 'Exploratorio'}


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
            {'name': 'code', 'label': 'Código', 'field': 'code', 'align': 'left', 'sortable': True},
            {'name': 'title', 'label': 'Título', 'field': 'title', 'align': 'left', 'sortable': True},
            {'name': 'story', 'label': 'Historia', 'field': 'story', 'align': 'left'},
            {'name': 'type', 'label': 'Tipo', 'field': 'type', 'align': 'left'},
            {'name': 'priority', 'label': 'Prioridad', 'field': 'priority', 'align': 'left'},
            {'name': 'status', 'label': 'Estado', 'field': 'status', 'align': 'left'},
            {'name': 'actions', 'label': '', 'field': 'id', 'align': 'right'},
        ]

        def rows():
            return [{'id': s['id'], 'code': s.get('code') or '—', 'title': s['title'], 'story': stories.get(s.get('story_id'), '—'),
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
        assistant_location, set_assistant_location_pref = remembered('spec_assistant_location', default='bottom')
        S = {'assistant_location': assistant_location}
        workspace_handle = {'value': None}   # lo llena workspace_area() más abajo (workspace_layout real, Nivel 1)

        # Persistencia de workspace_layout remapeada a la clave vieja de ancho de separador (spec_split_width),
        # para no perder la preferencia ya guardada de nadie con esta migración; center_mode es nuevo (no
        # existía antes ningún panel central), así que ese sí arranca en el default de workspace_layout.
        def get_pref(key, default):
            return remembered('spec_split_width' if key.endswith('_split_value') else key, default)[0]

        def set_pref(key, value):
            remembered('spec_split_width' if key.endswith('_split_value') else key)[1](value)

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
                     'type': (current or {}).get('type', 'functional'), 'linked_case_id': (current or {}).get('linked_case_id'),
                     'criteria_ids': list((current or {}).get('criteria_ids') or [])}}
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

        ASSISTANT_LOCATION_ICONS = {'bottom': 'border_bottom', 'right': 'border_right', 'center': 'tab'}
        ASSISTANT_LOCATION_LABELS = {'bottom': 'Abajo, a todo el ancho', 'right': 'En el panel derecho (Campos)', 'center': 'Como pestaña del panel central'}

        # Asistente de IA: estado + render definidos ACÁ (antes de armar los paneles y el header) para poder
        # montarlo en dos lugares físicos distintos (columna derecha, o abajo a lo ancho), o arrastrarlo al
        # centro como otra pestaña más — mismo patrón que user_stories.py::render_assistant_body.
        memory = assistant_memory.get_adapter()
        thread_key = f'test_case_spec:{current["id"] if current else "new"}'
        thread = memory.load(thread_key)
        candidates = {'items': None}
        candidates_view = None   # @ui.refreshable recreado fresco en cada render_assistant_body() más abajo —
        # ver el comentario equivalente (y el bug que corrige) en user_stories.py::story_detail

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

        async def _handle_refine(text):
            item = {'title': d['meta']['title'], 'preconditions': _v(preconditions), 'steps': d['steps'],
                   'priority': d['meta']['priority'], 'type': d['meta']['type']}
            result = await run.io_bound(llm.refine_spec_item, 'test_case', item, text)
            _apply_case_draft(result['item'], result['errors'])
            return 'Refiné el caso de prueba — revisá los cambios arriba y guardá si te sirven.'

        async def _handle_generate_candidates(text):
            linked_story = core.get('user_stories', d['meta']['story_id']) if d['meta']['story_id'] else None
            envs = core.list_project_items('environments', pid)
            result = await run.io_bound(llm.generate_test_cases, linked_story,
                                        None if linked_story else [{'text': text}], envs[0] if envs else None)
            if not result['valid']:
                raise ValueError('; '.join(result['errors']))
            candidates['items'] = result['test_cases']
            candidates_view.refresh()
            return f'Generé {len(result["test_cases"])} candidato(s) — elegí uno abajo para cargarlo arriba.'

        async def _handle_chat(text, history):
            context = {'kind': 'caso de prueba', 'current': {'title': d['meta']['title'], 'preconditions': _v(preconditions), 'steps': d['steps']}}
            return await run.io_bound(llm.spec_chat_reply, history, text, context)

        async def _handle_check_coherence(text):
            if not d['meta']['story_id'] or not d['meta']['criteria_ids']:
                raise ValueError('Para validar coherencia primero ligá una Historia y marcá al menos un criterio en el panel «Criterios».')
            linked_story = core.get('user_stories', d['meta']['story_id'])
            linked_criteria = [c for c in linked_story['criteria'] if c['id'] in d['meta']['criteria_ids']]
            case = {'preconditions': _v(preconditions), 'steps': d['steps']}
            return await run.io_bound(llm.check_test_case_coherence, linked_criteria, case, text)

        PROFILE = AssistantProfile(
            name='spec',
            placeholder='Generá candidatos, o pedile que refine el caso de arriba…',
            empty_hint='Pedile que genere candidatos (desde la Historia ligada, o desde una descripción), que refine el '
                       'caso de arriba, o que valide coherencia (si ya ligaste criterios en el panel «Criterios»).',
            tooltip=('Pedile que genere candidatos (desde la Historia ligada, o desde una descripción), que refine el '
                     'caso de arriba, o que valide coherencia entre los criterios ligados y los pasos. Lo que proponga '
                     'queda para revisar antes de guardar/crear.'),
            intents=[
                AssistantIntent(keywords=llm.SPEC_REFINE_KEYWORDS, handler=_handle_refine),
                AssistantIntent(keywords=llm.SPEC_COHERENCE_KEYWORDS, handler=_handle_check_coherence),
                AssistantIntent(keywords=llm.SPEC_GENERATE_CASES_KEYWORDS, handler=_handle_generate_candidates,
                                also_match=lambda text: not d['meta']['title'].strip()),
            ],
            fallback=_handle_chat,
            catch=(llm.LLMError, ValueError),
        )

        def render_assistant_body():
            nonlocal candidates_view

            @ui.refreshable
            def candidates_view():
                if not candidates['items']:
                    return
                with ui.card().classes('w-full shrink-0 bg-blue-50').props('flat'):
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

            assistant_panel(PROFILE, thread=thread, memory=memory, thread_key=thread_key, candidates=candidates_view)

        def _on_memory_menu_change():
            thread[:] = memory.load(thread_key)
            assistant_right_mount.refresh()
            assistant_bottom_mount.refresh()
            if S['assistant_location'] == 'center':
                workspace_area.refresh()

        def render_assistant_card():
            assistant_header('Asistente de IA', PROFILE.tooltip)
            render_assistant_body()

        @ui.refreshable
        def assistant_right_mount():
            if S['assistant_location'] != 'right':
                return
            with ui.card().classes('w-full').mark('spec-assistant-card-right').style('overflow:visible' if compact else ''):
                render_assistant_card()

        @ui.refreshable
        def assistant_bottom_mount():
            if S['assistant_location'] != 'bottom':
                return
            with ui.card().classes('w-full').mark('spec-assistant-card-bottom').style('overflow:visible' if compact else ''):
                render_assistant_card()

        def _on_assistant_removed_from_center():
            if S['assistant_location'] == 'center':
                set_assistant_location('bottom')

        def set_assistant_location(loc):
            old = S['assistant_location']
            if old == loc:
                return
            if loc == 'center':
                if not workspace_handle['value'].add_to_center('assistant'):
                    return   # tope de 3 alcanzado; add_to_center ya mostró el aviso
                S['assistant_location'] = loc
                set_assistant_location_pref(loc)
            else:
                S['assistant_location'] = loc
                set_assistant_location_pref(loc)
                if old == 'center':
                    workspace_handle['value'].remove_from_center('assistant')
            assistant_right_mount.refresh()
            assistant_bottom_mount.refresh()
            assistant_position_button.refresh()

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
                    @ui.refreshable
                    def assistant_position_button():
                        with ui.button(icon=ASSISTANT_LOCATION_ICONS[S['assistant_location']]) \
                                .props('flat round dense').mark('spec-toggle-assistant-position').tooltip('Dónde mostrar el Asistente de IA'):
                            with ui.menu():
                                for loc in ('bottom', 'right', 'center'):
                                    ui.menu_item(ASSISTANT_LOCATION_LABELS[loc], on_click=lambda loc=loc: set_assistant_location(loc)) \
                                        .mark(f'spec-assistant-location-{loc}')
                                ui.separator()
                                assistant_memory_menu_items(memory, thread_key, on_change=_on_memory_menu_change)
                    assistant_position_button()

                    def toggle_center_mode_ui():
                        workspace_handle['value'].toggle_center_mode()
                        center_mode_button.refresh()

                    @ui.refreshable
                    def center_mode_button():
                        mode = get_pref('spec_center_mode', 'tabs')
                        ui.button(icon='vertical_split' if mode == 'tabs' else 'view_column', on_click=toggle_center_mode_ui) \
                            .props('flat round dense').mark('spec-toggle-center-mode') \
                            .tooltip('Ver los paneles del centro uno al lado del otro' if mode == 'tabs' else 'Volver a verlos en pestañas')
                    center_mode_button()
                    typography_button(lambda: document_view.refresh())

            # Plantilla de ENTRADA elegida: cada grupo de primer nivel de su `body` es una pestaña del riel (ver
            # core.template_top_level_groups) — incluidos los metadatos de registro (Título/Historia/.../Caso
            # ligado), que son campos conocidos más, no fijos fuera de toda plantilla (ver core.DEFAULT_SPEC_
            # TEMPLATES, grupo "General"). Afecta a los dos lados (riel Y documento), por eso vive arriba de
            # los dos, no metida dentro de la tarjeta "Campos" de un solo lado — y se crea UNA sola vez, fuera
            # del ciclo de refresh de workspace_area, para no perder la selección en curso del usuario cada vez
            # que ese mismo cambio dispara su propio refresh (ver el comentario sobre esto en user_stories.py).
            input_templates = core.visible_templates('input', 'test_case', pid)
            saved_tpl_id = (current or {}).get('input_template_id')
            project_default_id = core.get_default_template_id(pid, 'test_case')
            default_tpl_id = (saved_tpl_id if any(t['id'] == saved_tpl_id for t in input_templates) else None) or \
                (project_default_id if any(t['id'] == project_default_id for t in input_templates) else None) or \
                (input_templates[0]['id'] if input_templates else None)
            if input_templates:
                # Para esta primera versión, un Caso de prueba YA creado no puede cambiar de plantilla de
                # entrada (solo al crearlo) — mismo criterio que Historias de usuario, ver user_stories.py.
                input_template = ui.select({t['id']: t['name'] for t in input_templates}, value=default_tpl_id, label='Plantilla de entrada') \
                    .props('outlined dense' + (' disable' if current else '')).classes('w-full').mark('spec-input-template')

            known_renderers = {}

            def render_title():
                nonlocal title
                title = ui.input('Título', value=d['meta']['title']).props('outlined dense').classes('w-full') \
                    .mark('spec-title').on_value_change(lambda e: (d['meta'].__setitem__('title', e.value), document_view.refresh()))
            known_renderers['title'] = render_title

            def _on_story_change(e):
                d['meta']['story_id'] = e.value
                d['meta']['criteria_ids'] = []   # son criterios de la Historia anterior, ya no aplican
                criteria_panel.refresh()
                document_view.refresh()

            def render_story():
                nonlocal story
                stories = core.list_project_items('user_stories', pid)
                story = ui.select({s['id']: s['title'] for s in stories}, value=d['meta']['story_id'],
                                  label='Historia de usuario (opcional)', clearable=True).props('outlined dense').classes('w-full').mark('spec-story') \
                    .on_value_change(_on_story_change)
            known_renderers['story_id'] = render_story

            def criterion_detail_dialog(criterion):
                """Detalle de solo lectura de UN criterio — se abre antes de decidir si ligarlo (botón «Ver
                más» de criteria_panel), mismo molde que agent_brief/show_run en common.py."""
                with ui.dialog() as dialog, ui.card().classes('w-[560px] max-w-full gap-2'):
                    ui.label(criterion.get('text') or 'Criterio de aceptación').classes('text-lg font-semibold')
                    for label, key in (('Dado (contexto inicial)', 'given'), ('Cuando (acción)', 'when'), ('Entonces (resultado esperado)', 'then')):
                        if criterion.get(key):
                            ui.label(label).classes('text-xs font-semibold text-gray-500 uppercase tracking-wide mt-1')
                            ui.label(criterion[key]).classes('text-sm')
                    ui.label(f'Estado: {"Cumplido" if criterion.get("status") == "met" else "Pendiente"}').classes('text-xs text-gray-500 mt-1')
                    with ui.row().classes('justify-end w-full mt-2'):
                        ui.button('Cerrar', on_click=dialog.close).props('flat')
                dialog.open()

            @ui.refreshable
            def criteria_panel():
                if not d['meta']['story_id']:
                    empty_state('Elegí primero una Historia de usuario.')
                    return
                linked_story = core.get('user_stories', d['meta']['story_id'])
                criteria = (linked_story or {}).get('criteria') or []
                if not criteria:
                    empty_state('Esa Historia todavía no tiene Criterios de aceptación.')
                    return
                def toggle(e, c):
                    if e.value and c['id'] not in d['meta']['criteria_ids']:
                        d['meta']['criteria_ids'].append(c['id'])
                    elif not e.value and c['id'] in d['meta']['criteria_ids']:
                        d['meta']['criteria_ids'].remove(c['id'])
                    document_view.refresh()

                for c in criteria:
                    with ui.row().classes('items-center gap-2 w-full no-wrap'):
                        ui.checkbox(value=c['id'] in d['meta']['criteria_ids']).mark(f'spec-criterion-check-{c["id"]}') \
                            .on_value_change(lambda e, c=c: toggle(e, c))
                        ui.label(c.get('text') or c.get('given') or 'Criterio').classes('text-sm grow truncate')
                        ui.button('Ver más', on_click=lambda _, c=c: criterion_detail_dialog(c)).props('flat dense size=sm color=primary') \
                            .mark(f'spec-criterion-detail-{c["id"]}')

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
            def document_view():
                ui.label(d['meta']['title'] or 'Nuevo caso de prueba').classes('text-2xl font-bold')
                # Solo lo que la plantilla de entrada elegida define, en su orden — incluidos
                # los metadatos de registro (priority/type: campos conocidos más, no fijos).
                tpl = core.get('spec_templates', input_template.value) if input_template and input_template.value else None
                fields = list(core.iter_template_fields(tpl.get('body'))) if tpl else \
                    [{'kind': 'field', 'field_key': k, 'field_type': None} for k in ('preconditions', 'steps')]
                linked_story = core.get('user_stories', d['meta']['story_id']) if d['meta']['story_id'] else None
                linked_story_title, linked_story_fragment, linked_criteria = '', '', None
                if linked_story:
                    # Siempre el título, como referencia — el resto de la Historia (campos + criterios) solo si
                    # la plantilla de este Caso de prueba configuró qué campos traer de ESA plantilla padre (ver
                    # spec_templates.py, sección "Historias relacionadas"); sin configuración, no se asume
                    # mostrar todo. Todo junto queda colapsable (ver render_test_case_view_html).
                    linked_story_title = linked_story['title']
                    echoed_keys = (tpl.get('linked_story_fields') or {}).get(linked_story.get('input_template_id'), []) if tpl else []
                    if echoed_keys:
                        parent_tpl = core.get('spec_templates', linked_story['input_template_id'])
                        echoed_fields = [f for f in core.iter_template_fields(parent_tpl.get('body')) if f.get('field_key') in echoed_keys]
                        linked_story_fragment = spec_report.render_story_view_html(linked_story, echoed_fields, linked_story.get('custom_fields'))
                    linked_criteria = [c for c in (linked_story.get('criteria') or []) if c['id'] in d['meta']['criteria_ids']]
                fragment = spec_report.render_test_case_view_html({'preconditions': _v(preconditions), 'steps': d['steps'],
                                                                   'priority': d['meta']['priority'], 'type': d['meta']['type']}, fields, d['custom'],
                                                                  linked_story_title=linked_story_title, linked_story_fragment=linked_story_fragment,
                                                                  linked_criteria=linked_criteria)
                ui.html(live_doc_html(fragment, doc_typography()[0]), sanitize=False).classes('w-full')

            def save():
                if current:
                    core.update_test_case_spec(current['id'], d['meta']['title'], d['meta']['story_id'], d['meta']['feature_id'], _v(preconditions),
                                               d['steps'], d['meta']['priority'], d['meta']['type'], d['meta']['linked_case_id'], custom_fields=d['custom'],
                                               input_template_id=input_template.value if input_template else None, criteria_ids=d['meta']['criteria_ids'])
                    ui.notify('Caso de prueba actualizado', type='positive')
                    ui.navigate.to(f'/test-specs/edit?id={current["id"]}')
                else:
                    spec = core.create_test_case_spec(d['meta']['title'], pid, d['meta']['story_id'], d['meta']['feature_id'], _v(preconditions),
                                                       d['steps'], d['meta']['priority'], d['meta']['type'], d['meta']['linked_case_id'], custom_fields=d['custom'],
                                                       input_template_id=input_template.value if input_template else None, criteria_ids=d['meta']['criteria_ids'])
                    ui.notify('Caso de prueba creado', type='positive')
                    ui.navigate.to(f'/test-specs/edit?id={spec["id"]}')

            def remove(s=current):
                core.delete_test_case_spec(s['id'])
                ui.notify('Caso de prueba eliminado', type='positive')
                ui.navigate.to('/test-specs')

            def side_extra():
                # Botones sin estado propio (a diferencia del selector de plantilla) — se puede reconstruir
                # tranquilo cada vez que workspace_area se refresca, sin perder nada.
                ui.button('Guardar cambios' if current else 'Crear caso de prueba', icon='save', on_click=guard(save)).props('color=primary').mark('spec-save')
                if current:
                    ui.button('Eliminar caso de prueba', icon='delete', on_click=lambda: confirm(f'¿Eliminar el caso de prueba «{current["title"]}»?', remove)) \
                        .props('flat dense color=negative').mark('spec-delete')

            def build_side_panels():
                tpl = core.get('spec_templates', input_template.value) if input_template and input_template.value else None
                groups = core.template_top_level_groups(tpl.get('body')) if tpl else [
                    {'id': 'general', 'label': 'General', 'icon': 'edit_note', 'children': [
                        {'kind': 'field', 'field_key': 'title', 'field_type': None, 'label': 'Título'},
                        {'kind': 'field', 'field_key': 'preconditions', 'field_type': None, 'label': 'Precondición'},
                        {'kind': 'field', 'field_key': 'steps', 'field_type': None, 'label': 'Pasos de ejecución'}]}]
                panels = [Panel(g['id'], g['label'], g['icon'] or 'folder',
                                (lambda grp=g: render_template_tree(grp['children'], d['custom'], known_renderers, on_change=lambda: document_view.refresh())))
                          for g in groups]
                # "Criterios" no depende de la plantilla (su contenido lo da la Historia ligada, que puede
                # cambiar en caliente) — panel propio, siempre presente, igual que "Documento"/"Asistente".
                panels.append(Panel('criteria', 'Criterios', 'checklist', criteria_panel))
                return panels

            # "document" y "assistant" siempre son ancla de centro (nunca aparecen en el riel) — igual que en
            # user_stories.py; cuáles grupos dinámicos del riel entran al centro lo decide workspace_layout solo
            # (son side_panels, arrastrables por defecto). "assistant" se puede cerrar del centro con su propia
            # "x"; cuando eso pasa, _on_assistant_removed_from_center lo manda de vuelta a "bottom".
            center_anchors = [
                Panel('document', 'Documento', 'description', document_view),
                Panel('assistant', 'Asistente de IA', 'smart_toy', render_assistant_body, on_remove=_on_assistant_removed_from_center),
            ]

            @ui.refreshable
            def workspace_area():
                with ui.element('div').classes('w-full').style('height: calc(100vh - 210px)' if compact else ''):
                    workspace_handle['value'] = workspace_layout(
                        side_panels=build_side_panels(), center_anchors=center_anchors,
                        prefix='spec', get_pref=get_pref, set_pref=set_pref,
                        side_title='Campos', side_icon='edit_note', side_extra=side_extra,
                        side_footer=assistant_right_mount,
                        center_footer=assistant_bottom_mount if compact else None,
                        fill_height=compact,
                    )
            workspace_area()
            if S['assistant_location'] == 'center':
                workspace_handle['value'].add_to_center('assistant')
            if not compact:
                assistant_bottom_mount()

            def _on_input_template_change(e):
                workspace_area.refresh()
                if S['assistant_location'] == 'center':
                    workspace_handle['value'].add_to_center('assistant')
                document_view.refresh()
            if input_template:
                input_template.on_value_change(_on_input_template_change)
