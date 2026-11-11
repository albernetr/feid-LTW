import base64
import copy
import re
import tempfile
from pathlib import Path
from nicegui import ui, run
from .. import core, llm, spec_report
from .common import frame, guard, confirm, empty_state, require_project, fmt_time, status_badge, read_upload, open_evidence_in_new_tab, protected_page, remembered, render_template_tree, doc_typography, live_doc_html, typography_button
from .test_case_specs import STATUS_LABELS as SPEC_STATUS_LABELS, TYPE_LABELS as SPEC_TYPE_LABELS

STATUS_LABELS = {'draft': 'Borrador', 'ready': 'Lista', 'done': 'Terminada'}
STORY_STATUSES = ('draft', 'ready', 'done')
IMPORT_TEXT_EXTENSIONS = ('.md', '.txt', '.csv', '.json')

# Hilos del Asistente de IA embebido, uno por historia (o 'new' para el borrador sin guardar todavía) — en
# memoria, nunca persistido, mismo espíritu que ASSISTANT_CHAT de chat_page.py pero separado por registro: acá
# se navega de una historia a otra todo el tiempo, y un solo hilo global mostraría la charla equivocada.
ASSISTANT_THREADS = {}


async def _render_spec_download(data, kind):
    """Mismo espíritu que render_evidence de common.py, para los reportes de la Especificación."""
    if kind == 'pdf':
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'r.pdf'
            await run.io_bound(spec_report.render_spec_pdf, spec_report.render_spec_html(data), target)
            return target.read_bytes()
    if kind == 'docx':
        return await run.io_bound(spec_report.render_spec_docx, data)
    if kind == 'md':
        return spec_report.render_spec_markdown(data).encode('utf-8')
    return spec_report.render_spec_html(data).encode('utf-8')


def _stem(text):
    return re.sub(r'[\\/:*?"<>|]+', '_', text).replace(' ', '_')


async def _preview_story_report(story, template):
    html_text = spec_report.render_spec_html(spec_report.build_story_report_data(story, template))
    filename = f'{story["id"]}-spec-preview.html'
    (core.ARTIFACTS / filename).write_text(html_text, encoding='utf-8')
    open_evidence_in_new_tab(story['id'], filename)


async def _download_story_report(story, template, kind):
    content = await _render_spec_download(spec_report.build_story_report_data(story, template), kind)
    ui.download(content, f'{_stem(story["title"])}.{kind}')
    ui.notify('Reporte generado', type='positive')


def _output_templates(pid):
    return [t for t in core.list_items('spec_templates') if t.get('kind') == 'output' and t.get('applies_to') == 'report'
            and (t.get('project_id') is None or t.get('project_id') == pid)]


def _open_export_matrix_dialog(pid):
    templates = _output_templates(pid)
    with ui.dialog() as dialog, ui.card().classes('w-96'):
        ui.label('Exportar matriz de trazabilidad').classes('text-lg font-semibold')
        ui.label('Toda la Especificación del proyecto: Historias, Criterios y Casos de prueba, con su estado.').classes('text-sm text-gray-500')
        default_tpl = next((t['id'] for t in templates if 'trazabilidad' in t['name'].lower()), templates[0]['id'] if templates else None)
        template_select = ui.select({t['id']: t['name'] for t in templates}, value=default_tpl, label='Plantilla de salida').props('outlined dense').classes('w-full').mark('matrix-export-template')
        kind_select = ui.select({'html': 'HTML', 'pdf': 'PDF', 'docx': 'Word', 'md': 'Markdown'}, value='html', label='Formato').props('outlined dense').classes('w-full')

        async def do_export():
            data = spec_report.build_test_matrix_report_data(pid, core.get('spec_templates', template_select.value) if template_select.value else None)
            content = await _render_spec_download(data, kind_select.value)
            ui.download(content, f'matriz_trazabilidad.{kind_select.value}')
            dialog.close()
        with ui.row().classes('w-full justify-end gap-2 mt-2'):
            ui.button('Cancelar', on_click=dialog.close).props('flat')
            ui.button('Exportar', icon='download', on_click=guard(do_export)).props('color=primary').mark('matrix-export-confirm')
    dialog.open()


def _open_import_dialog(pid):
    """Texto pegado, un archivo (.md/.txt/.csv/.json) o una imagen, y/o una URL — se combinan en una sola fuente
    para generate_from_source(); el resultado (HU + Casos de prueba candidatos) se revisa acá mismo antes de
    confirmar. Nada se guarda hasta «Confirmar importación» — mismo espíritu que portable.py (preview primero)."""
    source = {'image_b64': None, 'image_media_type': None, 'image_name': None}
    bundle = {'result': None}

    with ui.dialog() as dialog, ui.card().classes('w-full').style('max-width:640px'):
        ui.label('Importar desde texto, archivo, imagen o URL').classes('text-lg font-semibold')
        ui.label('Arma un borrador de Historia de usuario + Casos de prueba — lo revisás acá antes de que se guarde algo.').classes('text-sm text-gray-500')

        text_area = ui.textarea('Texto fuente (pegalo, o cargalo con el archivo/URL de abajo)').props('outlined autogrow').classes('w-full').mark('story-import-text')

        async def on_text_file(event):
            # Nunca guard(): on_upload necesita el evento, y guard() jamás lo reenvía (su (*args, **kwargs)
            # hace que NiceGUI crea que no espera argumentos) — mismo try/except que ya usa chat_page.py
            # para su propio subidor de contexto.
            try:
                ext = Path(event.file.name).suffix.lower()
                if ext not in IMPORT_TEXT_EXTENSIONS:
                    raise ValueError(f'Extensión no soportada «{ext or event.file.name}» — usa .md, .txt, .csv o .json')
                raw = await read_upload(event)
                try:
                    text_area.set_value(raw.decode('utf-8'))
                except UnicodeDecodeError as exc:
                    raise ValueError(f'No se pudo leer «{event.file.name}» como texto (¿no es UTF-8?)') from exc
            except Exception as exc:
                ui.notify(str(exc) or type(exc).__name__, type='negative', multi_line=True)
        ui.upload(label='Archivo de texto (.md/.txt/.csv/.json)', on_upload=on_text_file, auto_upload=True) \
            .props('flat bordered accept=".md,.txt,.csv,.json"').classes('w-full')

        image_label = ui.label('').classes('text-xs text-gray-500')

        async def on_image(event):
            try:
                raw = await read_upload(event)
                source['image_b64'] = base64.b64encode(raw).decode('ascii')
                source['image_media_type'] = event.file.content_type or 'image/png'
                source['image_name'] = event.file.name
                image_label.set_text(f'Imagen cargada: {event.file.name}')
            except Exception as exc:
                ui.notify(str(exc) or type(exc).__name__, type='negative', multi_line=True)
        ui.upload(label='O una imagen (captura, diagrama, HU escrita a mano)', on_upload=on_image, auto_upload=True) \
            .props('flat bordered accept="image/*"').classes('w-full').mark('story-import-image')

        with ui.row().classes('w-full gap-2 items-center'):
            url_input = ui.input('O una URL').props('outlined dense').classes('grow').mark('story-import-url')

            async def fetch_url():
                text = await run.io_bound(core.fetch_url_text, url_input.value)
                text_area.set_value(text)
                ui.notify('Texto traído de la URL', type='positive')
            ui.button('Traer texto', on_click=guard(fetch_url)).props('outline dense').mark('story-import-fetch-url')

        preview_box = ui.column().classes('w-full gap-2')

        @ui.refreshable
        def preview_view():
            if not bundle['result']:
                return
            story, cases = bundle['result']['story'], bundle['result']['test_cases']
            with ui.card().classes('w-full bg-blue-50').props('flat'):
                ui.label('Vista previa').classes('font-semibold')
                ui.label(f'Historia: {story["title"]}').classes('text-sm font-medium')
                for c in story['criteria']:
                    ui.label(f'• {c["text"]}').classes('text-xs text-gray-600 ml-3')
                if cases:
                    ui.label(f'{len(cases)} caso(s) de prueba:').classes('text-sm font-medium mt-2')
                    for tc in cases:
                        ui.label(f'• {tc["title"]}').classes('text-xs text-gray-600 ml-3')

                def confirm_import():
                    saved_story = core.create_user_story(story['title'], pid, story['as_a'], story['i_want'], story['so_that'],
                                                          None, 'medium', story['criteria'], source='import')
                    for tc in cases:
                        core.create_test_case_spec(tc['title'], pid, story_id=saved_story['id'], preconditions=tc['preconditions'],
                                                   steps=tc['steps'], priority=tc['priority'], type=tc['type'], source='import')
                    dialog.close()
                    ui.notify(f'Importado: 1 historia + {len(cases)} caso(s) de prueba', type='positive')
                    ui.navigate.to(f'/stories/edit?id={saved_story["id"]}')
                ui.button('Confirmar importación', icon='check', on_click=guard(confirm_import)).props('color=primary').mark('story-import-confirm')
        preview_view()

        async def generate():
            result = await run.io_bound(llm.generate_from_source, text_area.value, source['image_b64'], source['image_media_type'] or 'image/png')
            if not result['valid']:
                raise ValueError('; '.join(result['errors']) or 'El modelo no devolvió una propuesta válida')
            bundle['result'] = result
            preview_view.refresh()
        with ui.row().classes('w-full justify-end gap-2 mt-2'):
            ui.button('Cancelar', on_click=dialog.close).props('flat')
            ui.button('Generar propuesta', icon='auto_awesome', on_click=guard(generate)).props('color=primary').mark('story-import-generate')
    dialog.open()


@protected_page('/stories')
def stories_list():
    with frame('Historias de usuario', '/stories', doc_style=True):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.label('Lo que se quiere lograr y por qué, antes de escribir ningún caso de prueba. Cada una puede ligarse a una Funcionalidad.').classes('text-sm text-gray-500')
        with ui.row().classes('gap-2'):
            ui.button('Nueva historia', icon='add', on_click=lambda: ui.navigate.to('/stories/edit')).props('color=primary')
            ui.button('Importar', icon='upload_file', on_click=lambda: _open_import_dialog(pid)).props('outline color=primary').mark('stories-import')
            ui.button('Exportar matriz', icon='table_view', on_click=lambda: _open_export_matrix_dialog(pid)).props('outline color=primary').mark('stories-export-matrix')

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
    title_text = 'Historia de usuario' if id else 'Nueva historia de usuario'
    with frame(title_text, '/stories', full_width=True, doc_style=True):
        if not require_project():
            return
        pid = core.get_active_project_id()
        compact, set_compact = remembered('story_layout_compact', default=True)
        assistant_location, set_assistant_location_pref = remembered('story_assistant_location', default='bottom')
        center_mode, set_center_mode_pref = remembered('story_center_mode', default='tabs')
        main_split_value, set_main_split_value_pref = remembered('story_split_width', default=75)
        S = {'assistant_location': assistant_location, 'center_mode': center_mode,
             'center_open': ['document'] + (['assistant'] if assistant_location == 'center' else []),
             'fields_collapsed': False, 'active_field_tab': 'general'}
        drag_state = {'key': None}

        def handle_rail_click(key):
            """Clic en el ícono YA activo del riel de "Campos" colapsa/expande el panel de detalle (el riel de
            iconos se queda fijo) — mismo patrón que la barra lateral de VS Code. Clic en OTRO ícono cambia de
            pestaña y siempre la deja expandida. Al colapsar, además, el separador se corre solo para devolverle
            ese ancho al panel central — si no, el riel quedaba pegado a la izquierda con un hueco en blanco al
            lado (el resto de lo que antes ocupaba el panel de detalle, ahora vacío dentro de la misma columna)."""
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

        def add_to_center(key):
            if not key or key in S['center_open']:
                return
            if len(S['center_open']) >= 3:
                ui.notify('Ya tenés 3 paneles abiertos en el centro — cerrá uno primero', type='warning')
                return
            S['center_open'].append(key)
            center_area.refresh()

        def remove_from_center(key):
            if key == 'document' or key not in S['center_open']:
                return
            if key == 'assistant':
                set_assistant_location('bottom')   # ya saca 'assistant' de center_open y refresca todo lo necesario
                return
            S['center_open'].remove(key)
            center_area.refresh()

        current = core.get('user_stories', id) if id else None
        if id and (current is None or current.get('project_id') != pid):
            with ui.column().classes('w-full p-4 gap-2'):
                ui.link('← Volver a Historias de usuario', '/stories').classes('text-sm')
                ui.label('Esta historia ya no existe en el proyecto activo.').classes('text-amber-700')
            return

        d = {'criteria': [dict(c) for c in (current or {}).get('criteria', [])],
             'dor': [dict(i) for i in (current or {}).get('definition_of_ready', [])],
             'dod': [dict(i) for i in (current or {}).get('definition_of_done', [])],
             'custom': copy.deepcopy((current or {}).get('custom_fields') or {}),
             # Metadatos de registro (Decisión 1: nunca gobernados por la plantilla) — viven en su propia
             # pestaña fija del riel ("General", ver fields_section), que SÍ se reconstruye entera cada vez que
             # cambia la plantilla de entrada (como cualquier otra pestaña) — por eso cada widget se re-crea
             # leyendo de ACÁ (no de `current` directamente), para no perder una edición sin guardar todavía.
             'meta': {'title': (current or {}).get('title', ''), 'feature_id': (current or {}).get('feature_id'),
                      'priority': (current or {}).get('priority', 'medium'), 'status': (current or {}).get('status', 'draft'),
                      'story_points': (current or {}).get('story_points'), 'assigned_to': (current or {}).get('assigned_to'),
                      'depends_on': (current or {}).get('depends_on', [])}}
        other_stories = [s for s in core.list_project_items('user_stories', pid) if not current or s['id'] != current['id']]

        # Linealidad plantilla <-> sección: cuál de estos widgets existe de verdad depende de qué grupos/campos
        # trae la plantilla de ENTRADA elegida (ver fields_section() más abajo) — ninguno es obligatorio, así
        # que todo lo que se lee más abajo (document_view, save(), el Asistente de IA) pasa por `_v()`/
        # `_safe_refresh()` en vez de asumir que el widget existe.
        as_a = i_want = so_that = content_box = None
        business_rules = assumptions = risks = out_of_scope = None
        criteria_rows = dor_rows = dod_rows = None
        title = feature = priority = status = story_points = assigned_to = depends_on = input_template = None

        def _v(el):
            return el.value if el else ''

        def _safe_refresh(fn):
            if fn:
                fn.refresh()

        def _set_meta(widget, key, value):
            # Los metadatos de registro (título/prioridad/...) ahora también los gobierna la plantilla — un
            # widget puede no existir si la plantilla elegida no los incluye. Si existe, set_value() dispara su
            # on_value_change y ESO actualiza d['meta']; si no, hay que escribir ahí directamente para no perder
            # el dato (p. ej. el Asistente de IA proponiendo un título con "Formato libre" activo).
            if widget:
                widget.set_value(value)
            else:
                d['meta'][key] = value

        # Asistente de IA: estado + render definidos ACÁ (antes de armar los paneles) para poder montarlo en dos
        # lugares físicos distintos (columna derecha, o abajo a lo ancho) sin duplicar nada — cada mount es un
        # @ui.refreshable chico que solo decide SI renderiza acá; nunca reconstruye los campos de "Campos"
        # (title/as_a/criterios/etc. no se tocan al mover el Asistente, por eso no hace falta recargar la página).
        thread_key = current['id'] if current else 'new'
        thread = ASSISTANT_THREADS.setdefault(thread_key, [])
        draft_cases = {'items': None}

        def _apply_story_draft(story, errors):
            if not story:
                raise ValueError('; '.join(errors) or 'El modelo no devolvió una historia válida')
            if content_box is not None and input_template:   # el Asistente siempre genera Como/Quiero/Para — si está en modo "Formato libre", vuelve al modo estructurado
                structured = next((t for t in input_templates if {'as_a', 'i_want', 'so_that'} & core.template_field_keys(t.get('body'))), None)
                if structured:
                    input_template.set_value(structured['id'])
                    fields_section.refresh()
            _set_meta(title, 'title', story['title'])
            if as_a:
                as_a.set_value(story['as_a'])
            if i_want:
                i_want.set_value(story['i_want'])
            if so_that:
                so_that.set_value(story['so_that'])
            d['criteria'] = [{'text': c.get('text', ''), 'given': c.get('given', ''), 'when': c.get('when', ''),
                              'then': c.get('then', ''), 'status': 'pending'} for c in story['criteria']]
            d['dor'] = [{'text': t, 'done': False} for t in (story.get('definition_of_ready') or [])]
            d['dod'] = [{'text': t, 'done': False} for t in (story.get('definition_of_done') or [])]
            if business_rules:
                business_rules.set_value(story.get('business_rules', ''))
            if assumptions:
                assumptions.set_value(story.get('assumptions', ''))
            if risks:
                risks.set_value(story.get('risks', ''))
            if out_of_scope:
                out_of_scope.set_value(story.get('out_of_scope', ''))
            _safe_refresh(criteria_rows)
            _safe_refresh(dor_rows)
            _safe_refresh(dod_rows)
            document_view.refresh()

        def render_assistant_body():
            @ui.refreshable
            def assistant_view():
                if not thread:
                    ui.label('Describí la historia que querés, o pedile que refine/enriquezca la de arriba.').classes('text-sm text-gray-400')
                for turn in thread:
                    with ui.chat_message(name='Vos' if turn['who'] == 'user' else 'Asistente', sent=turn['who'] == 'user').classes('w-full'):
                        ui.label(turn['text']).style('white-space:pre-wrap')
            assistant_view()

            @ui.refreshable
            def draft_cases_view():
                if not draft_cases['items']:
                    return
                with ui.card().classes('w-full bg-blue-50').props('flat'):
                    ui.label(f'{len(draft_cases["items"])} caso(s) de prueba propuestos').classes('font-semibold')
                    checks = []
                    for tc in draft_cases['items']:
                        c = ui.checkbox(tc['title'], value=True).mark('story-draft-case')
                        checks.append((c, tc))
                        ui.label(f'{len(tc["steps"])} paso(s) · {SPEC_TYPE_LABELS.get(tc["type"], tc["type"])} · '
                                f'{core.PRIORITY_LABELS.get(tc["priority"], tc["priority"])}').classes('text-xs text-gray-500 ml-8')

                    def create_selected():
                        made = 0
                        for check, tc in checks:
                            if check.value:
                                core.create_test_case_spec(tc['title'], pid, story_id=current['id'], feature_id=current.get('feature_id'),
                                                           preconditions=tc['preconditions'], steps=tc['steps'],
                                                           priority=tc['priority'], type=tc['type'], source='ai')
                                made += 1
                        draft_cases['items'] = None
                        ui.notify(f'{made} caso(s) de prueba creado(s)', type='positive')
                        ui.navigate.to(f'/stories/edit?id={current["id"]}')
                    with ui.row().classes('gap-2'):
                        ui.button('Crear seleccionados', icon='add', on_click=guard(create_selected)).props('dense color=primary').mark('story-create-draft-cases')
                        ui.button('Descartar', on_click=lambda: (draft_cases.__setitem__('items', None), draft_cases_view.refresh())).props('flat dense')
            draft_cases_view()

            async def send(box):
                text = (box.value or '').strip()
                if not text:
                    return
                box.value = ''
                thread.append({'who': 'user', 'text': text})
                assistant_view.refresh()
                lowered = text.lower()
                try:
                    if any(k in lowered for k in llm.SPEC_GENERATE_CASES_KEYWORDS):
                        if not current:
                            raise ValueError('Guardá la historia primero para poder generar sus Casos de prueba.')
                        envs = core.list_project_items('environments', pid)
                        result = await run.io_bound(llm.generate_test_cases, current, None, envs[0] if envs else None)
                        if not result['valid']:
                            raise ValueError('; '.join(result['errors']))
                        draft_cases['items'] = result['test_cases']
                        draft_cases_view.refresh()
                        reply = f'Generé {len(result["test_cases"])} caso(s) de prueba candidatos — elegí cuáles crear, arriba.'
                    elif any(k in lowered for k in llm.SPEC_REFINE_KEYWORDS):
                        item = {'title': d['meta']['title'], 'as_a': _v(as_a), 'i_want': _v(i_want), 'so_that': _v(so_that),
                               'criteria': d['criteria'], 'definition_of_ready': [i['text'] for i in d['dor']],
                               'definition_of_done': [i['text'] for i in d['dod']], 'business_rules': _v(business_rules),
                               'assumptions': _v(assumptions), 'risks': _v(risks), 'out_of_scope': _v(out_of_scope)}
                        result = await run.io_bound(llm.refine_spec_item, 'user_story', item, text)
                        _apply_story_draft(result['item'], result['errors'])
                        reply = 'Refiné la historia — revisá los cambios arriba y guardá si te sirven.'
                    elif any(k in lowered for k in llm.SPEC_GENERATE_STORY_KEYWORDS) or not d['meta']['title'].strip():
                        selected_feature = core.get('features', d['meta']['feature_id']) if d['meta']['feature_id'] else None
                        result = await run.io_bound(llm.generate_user_story, text, selected_feature)
                        _apply_story_draft(result['story'], result['errors'])
                        reply = 'Generé una propuesta — revisala arriba (título, Como/Quiero/Para y criterios) y guardá si te sirve.'
                    else:
                        context = {'kind': 'historia de usuario', 'current': {'title': d['meta']['title'], 'as_a': _v(as_a),
                                   'i_want': _v(i_want), 'so_that': _v(so_that), 'criteria': [c['text'] for c in d['criteria']]}}
                        reply = await run.io_bound(llm.spec_chat_reply, thread[:-1], text, context)
                except (llm.LLMError, ValueError) as exc:
                    reply = f'No pude: {exc}'
                thread.append({'who': 'assistant', 'text': reply})
                assistant_view.refresh()

            with ui.row().classes('w-full items-center gap-2'):
                box = ui.input(placeholder='Generá una HU, pedile que la refine, o que genere sus Casos de prueba…') \
                    .props('outlined dense').classes('grow').mark('story-assistant-input')
                box.on('keydown.enter', lambda: send(box))
                ui.button(icon='send', on_click=lambda: send(box)).props('round dense color=primary').mark('story-assistant-send')

        def render_assistant_card():
            with ui.row().classes('items-center gap-2'):
                ui.icon('smart_toy', color='primary')
                ui.label('Asistente de IA').classes('font-semibold')
                ui.icon('info', size='xs', color='grey').classes('cursor-help').tooltip(
                    'Pedile que genere una historia desde una descripción, que la refine o enriquezca, o — si ya '
                    'está guardada — que genere sus Casos de prueba. Lo que proponga queda arriba, para revisar '
                    'antes de guardar/crear; nunca se guarda solo.')
            render_assistant_body()

        @ui.refreshable
        def assistant_right_mount():
            if S['assistant_location'] != 'right':
                return
            with ui.card().classes('w-full').mark('story-assistant-card-right').style('overflow:visible' if compact else ''):
                render_assistant_card()

        @ui.refreshable
        def assistant_bottom_mount():
            if S['assistant_location'] != 'bottom':
                return
            with ui.card().classes('w-full').mark('story-assistant-card-bottom').style('overflow:visible' if compact else ''):
                render_assistant_card()

        def export_menu_button():
            """Botón compacto al lado del título — antes era una tarjeta aparte a todo lo ancho; con una HU
            llena (muchos criterios, DoR/DoD, contexto de negocio) esa tarjeta quedaba lejos, al final de todo."""
            output_templates = _output_templates(pid)
            with ui.button(icon='ios_share').props('flat round dense').mark('story-export-menu').tooltip('Exportar'):
                with ui.menu().props('anchor="bottom right" self="top right"'):
                    with ui.column().classes('p-3 gap-2').style('min-width:280px'):
                        if not output_templates:
                            ui.label('No hay plantillas de salida disponibles.').classes('text-sm text-gray-400')
                        else:
                            default_tpl = next((t['id'] for t in output_templates if 'detallada' in t['name'].lower()), output_templates[0]['id'])
                            export_template = ui.select({t['id']: t['name'] for t in output_templates}, value=default_tpl,
                                                        label='Plantilla de salida').props('outlined dense').classes('w-full').mark('story-export-template')
                            tpl = lambda: core.get('spec_templates', export_template.value)   # noqa: E731
                            with ui.row().classes('gap-1').style('flex-wrap:wrap'):
                                ui.button('Vista previa', icon='open_in_new', on_click=guard(lambda: _preview_story_report(current, tpl()))).props('flat dense no-caps').mark('story-export-preview')
                                ui.button('HTML', icon='download', on_click=guard(lambda: _download_story_report(current, tpl(), 'html'))).props('flat dense no-caps')
                                ui.button('PDF', icon='picture_as_pdf', on_click=guard(lambda: _download_story_report(current, tpl(), 'pdf'))).props('flat dense no-caps')
                                ui.button('Word', icon='description', on_click=guard(lambda: _download_story_report(current, tpl(), 'docx'))).props('flat dense no-caps').mark('story-export-docx')
                                ui.button('Markdown', icon='code', on_click=guard(lambda: _download_story_report(current, tpl(), 'md'))).props('flat dense no-caps')

        def toggle_compact():
            set_compact(not compact)
            ui.navigate.reload()

        ASSISTANT_LOCATION_ICONS = {'bottom': 'border_bottom', 'right': 'border_right', 'center': 'tab'}
        ASSISTANT_LOCATION_LABELS = {'bottom': 'Abajo, a todo el ancho', 'right': 'En el panel derecho (Campos)', 'center': 'Como pestaña del panel central'}

        def set_assistant_location(loc):
            if loc == 'center' and 'assistant' not in S['center_open'] and len(S['center_open']) >= 3:
                ui.notify('Ya tenés 3 paneles abiertos en el centro — cerrá uno primero', type='warning')
                return
            old = S['assistant_location']
            S['assistant_location'] = loc
            set_assistant_location_pref(loc)
            if old == 'center' and loc != 'center' and 'assistant' in S['center_open']:
                S['center_open'].remove('assistant')
            if loc == 'center' and 'assistant' not in S['center_open']:
                S['center_open'].append('assistant')
            assistant_right_mount.refresh()
            assistant_bottom_mount.refresh()
            center_area.refresh()
            assistant_position_button.refresh()

        def toggle_center_mode():
            S['center_mode'] = 'split' if S['center_mode'] == 'tabs' else 'tabs'
            set_center_mode_pref(S['center_mode'])
            center_mode_button.refresh()
            center_area.refresh()

        # Layout: documento al centro/izquierda, campos a la derecha, con un separador ajustable entre los dos
        # (ui.splitter en vez del ui.row + order-1/order-2 de antes — igual de necesario que Campos esté
        # definido primero en el código porque document_view lee title/as_a/etc., pero con splitter el orden
        # VISUAL ya no depende de clases CSS: entrar primero a `.after` y después a `.before` alcanza). También:
        # preferencias que el usuario alterna a mano y el navegador recuerda — compacto (sin scroll de página,
        # ocupa toda la altura, cada panel scrollea el suyo — mismo recipe que Chat/Espacio de trabajo) vs. con
        # scroll completo de toda la página; y dónde vive el Asistente de IA (abajo a lo ancho, en el panel
        # derecho, o como pestaña del panel central). Exportar es un botón compacto al lado del título — con una
        # HU llena (muchos criterios, DoR/DoD, contexto de negocio) una tarjeta aparte quedaba lejos, al final.
        with ui.column().classes('w-full p-4 gap-4 ltw-doc'):
            with ui.row().classes('w-full items-center justify-between no-wrap'):
                with ui.row().classes('items-center gap-2'):
                    with ui.column().classes('gap-0'):
                        ui.link('← Volver a Historias de usuario', '/stories').classes('text-sm')
                        ui.label(title_text).classes('ltw-doc-title text-2xl font-semibold')
                    if current:
                        ui.button(icon='tab', on_click=lambda: ui.navigate.to(f'/stories/view?id={current["id"]}', new_tab=True)) \
                            .props('flat round dense').mark('story-open-viewer').tooltip('Abrir el visor interactivo del reporte')
                        export_menu_button()
                with ui.row().classes('gap-1 shrink-0'):
                    ui.button(icon='fullscreen_exit' if compact else 'fullscreen', on_click=toggle_compact) \
                        .props('flat round dense').mark('story-toggle-compact') \
                        .tooltip('Cambiar a modo con scroll completo' if compact else 'Cambiar a modo compacto (sin scroll, ancho completo)')
                    @ui.refreshable
                    def assistant_position_button():
                        with ui.button(icon=ASSISTANT_LOCATION_ICONS[S['assistant_location']]) \
                                .props('flat round dense').mark('story-toggle-assistant-position').tooltip('Dónde mostrar el Asistente de IA'):
                            with ui.menu():
                                for loc in ('bottom', 'right', 'center'):
                                    ui.menu_item(ASSISTANT_LOCATION_LABELS[loc], on_click=lambda loc=loc: set_assistant_location(loc)) \
                                        .mark(f'story-assistant-location-{loc}')
                    assistant_position_button()
                    @ui.refreshable
                    def center_mode_button():
                        ui.button(icon='vertical_split' if S['center_mode'] == 'tabs' else 'view_column', on_click=toggle_center_mode) \
                            .props('flat round dense').mark('story-toggle-center-mode') \
                            .tooltip('Ver los paneles del centro uno al lado del otro' if S['center_mode'] == 'tabs' else 'Volver a verlos en pestañas')
                    center_mode_button()
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

                                # Carrilera vertical de pestañas (solo iconos + tooltip, rail a la derecha) — mismo
                                # patrón que el panel derecho de Chat/Espacio de trabajo. El panel de detalle (a la
                                # izquierda del riel) es el que crece/se achica con el separador — el riel se queda
                                # fijo en 56px — y clickear el ícono YA activo lo colapsa/expande (estilo VS Code).
                                # justify-content:flex-end — así el riel queda pegado a la derecha tanto si el
                                # panel de detalle está expandido (ocupa flex:1, el riel ya queda al final) como
                                # colapsado (display:none lo saca del flujo: sin esto, el riel —único hijo visible—
                                # se iría pegado a la izquierda, dejando un hueco en blanco a su derecha).
                                #
                                # Plantilla de ENTRADA elegida: a diferencia de antes (un if/else fijo entre Como/
                                # Quiero/Para y un textarea libre), ahora gobierna de verdad qué secciones existen,
                                # con qué etiqueta/ícono y en qué orden — cada GRUPO de primer nivel de su `body` es
                                # una pestaña del riel de abajo (ver fields_section()/core.template_top_level_groups).
                                # Esto incluye los METADATOS de registro (Título/Prioridad/Estado/...): ya no viven
                                # en una pestaña fija — son campos conocidos más, que la plantilla ubica donde
                                # quiera (las 4 plantillas por defecto los agrupan en su propio grupo "General",
                                # pero una plantilla propia podría no incluir alguno, agruparlos distinto, o
                                # ponerlos a dos columnas con Ancho=Mitad).
                                input_templates = [t for t in core.list_items('spec_templates') if t.get('kind') == 'input' and t.get('applies_to') == 'user_story'
                                                  and (t.get('project_id') is None or t.get('project_id') == pid)]
                                # Qué plantilla elegir al (re)abrir la historia: la que se guardó la última vez
                                # que se guardó la historia (`input_template_id`), si todavía existe entre las
                                # visibles del proyecto — si no (historias viejas, de antes de que esto se
                                # guardara), el heurístico de siempre por forma de contenido.
                                saved_tpl_id = (current or {}).get('input_template_id')
                                has_content = bool((current or {}).get('content'))
                                default_tpl_id = (saved_tpl_id if any(t['id'] == saved_tpl_id for t in input_templates) else None) or \
                                    next((t['id'] for t in input_templates if has_content and 'content' in core.template_field_keys(t.get('body'))),
                                        next((t['id'] for t in input_templates if not has_content and {'as_a', 'i_want', 'so_that'} & core.template_field_keys(t.get('body'))),
                                             input_templates[0]['id'] if input_templates else None))

                                # La plantilla elegida es, ella misma, lo que decide qué pestañas existen — así que
                                # su selector queda FUERA del riel que gobierna: siempre visible, nunca se puede
                                # perder de vista por más que la plantilla activa no la mencione en su árbol.
                                input_template = ui.select({t['id']: t['name'] for t in input_templates}, value=default_tpl_id, label='Plantilla de entrada') \
                                    .props('outlined dense').classes('w-full mt-2').mark('story-input-template') if input_templates else None

                                field_panels = None
                                known_renderers = {}

                                def render_title():
                                    nonlocal title
                                    title = ui.input('Título', value=d['meta']['title']).props('outlined dense').classes('w-full') \
                                        .mark('story-title').on_value_change(lambda e: (d['meta'].__setitem__('title', e.value), document_view.refresh()))
                                known_renderers['title'] = render_title

                                def render_feature():
                                    nonlocal feature
                                    features = core.list_project_items('features', pid)
                                    feature = ui.select({f['id']: f['name'] for f in features}, value=d['meta']['feature_id'],
                                                        label='Funcionalidad (opcional)', clearable=True).props('outlined dense').classes('w-full').mark('story-feature') \
                                        .on_value_change(lambda e: d['meta'].__setitem__('feature_id', e.value))
                                known_renderers['feature_id'] = render_feature

                                def render_priority():
                                    nonlocal priority
                                    priority = ui.select(core.PRIORITY_LABELS, value=d['meta']['priority'], label='Prioridad') \
                                        .props('outlined dense').classes('w-full').on_value_change(lambda e: (d['meta'].__setitem__('priority', e.value), document_view.refresh()))
                                known_renderers['priority'] = render_priority

                                def render_status():
                                    nonlocal status
                                    status = ui.select(STATUS_LABELS, value=d['meta']['status'], label='Estado').props('outlined dense').classes('w-full') \
                                        .on_value_change(lambda e: d['meta'].__setitem__('status', e.value))
                                known_renderers['status'] = render_status

                                def render_story_points():
                                    nonlocal story_points
                                    story_points = ui.number('Story points', value=d['meta']['story_points'], min=0, format='%.0f') \
                                        .props('outlined dense').classes('w-full').mark('story-points') \
                                        .on_value_change(lambda e: (d['meta'].__setitem__('story_points', e.value), document_view.refresh()))
                                known_renderers['story_points'] = render_story_points

                                def render_assigned_to():
                                    nonlocal assigned_to
                                    users = core.list_items('users')
                                    assigned_to = ui.select({u['id']: f'{u.get("first_name", "")} {u.get("last_name", "")}'.strip() or u.get('email', '') for u in users},
                                                            value=d['meta']['assigned_to'], label='Asignado a (opcional)', clearable=True) \
                                        .props('outlined dense').classes('w-full').mark('story-assigned-to') \
                                        .on_value_change(lambda e: d['meta'].__setitem__('assigned_to', e.value))
                                known_renderers['assigned_to'] = render_assigned_to

                                def render_depends_on():
                                    nonlocal depends_on
                                    depends_on = ui.select({s['id']: s['title'] for s in other_stories}, multiple=True, value=d['meta']['depends_on'],
                                                           label='Depende de (opcional)', clearable=True).props('outlined dense use-chips').classes('w-full') \
                                        .mark('story-depends-on').on_value_change(lambda e: (d['meta'].__setitem__('depends_on', e.value), document_view.refresh()))
                                known_renderers['depends_on'] = render_depends_on

                                def render_as_a():
                                    nonlocal as_a
                                    as_a = ui.input('Como (rol)', value=(current or {}).get('as_a', '')).props('outlined dense').classes('w-full').mark('story-as-a').on_value_change(lambda e: document_view.refresh())
                                known_renderers['as_a'] = render_as_a

                                def render_i_want():
                                    nonlocal i_want
                                    i_want = ui.input('Quiero (acción o funcionalidad)', value=(current or {}).get('i_want', '')).props('outlined dense').classes('w-full').on_value_change(lambda e: document_view.refresh())
                                known_renderers['i_want'] = render_i_want

                                def render_so_that():
                                    nonlocal so_that
                                    so_that = ui.input('Para (beneficio o razón)', value=(current or {}).get('so_that', '')).props('outlined dense').classes('w-full').on_value_change(lambda e: document_view.refresh())
                                known_renderers['so_that'] = render_so_that

                                def render_content():
                                    nonlocal content_box
                                    content_box = ui.textarea('Contenido (formato libre)', value=(current or {}).get('content', '')).props('outlined dense autogrow') \
                                        .classes('w-full').mark('story-content').on_value_change(lambda e: document_view.refresh())
                                known_renderers['content'] = render_content

                                @ui.refreshable
                                def criteria_rows():
                                    if not d['criteria']:
                                        ui.label('Ninguno todavía.').classes('text-sm text-gray-400')
                                    for c in d['criteria']:
                                        with ui.column().classes('w-full gap-1 p-2 border rounded').style('border-color:#e5e7eb'):
                                            with ui.row().classes('items-center gap-2 w-full no-wrap'):
                                                # on_value_change: SOLO actualiza el dict (dispara en cada tecla — un
                                                # criteria_rows.refresh() acá reconstruiría el input a mitad de tipeo y
                                                # se perdería lo que falte escribir). blur: recién ahí se refresca la
                                                # OTRA copia en vivo (centro/derecha), cuando este campo ya no tiene el
                                                # foco — así las dos vistas quedan iguales sin romper el tipeo normal.
                                                ui.input('Resumen del escenario', value=c.get('text', '')).props('outlined dense').classes('grow').mark('story-criterion-text') \
                                                    .on_value_change(lambda e, c=c: (c.__setitem__('text', e.value), document_view.refresh())) \
                                                    .on('blur', lambda: criteria_rows.refresh())
                                                ui.select({'pending': 'Pendiente', 'met': 'Cumplido'}, value=c.get('status', 'pending')) \
                                                    .props('outlined dense').classes('w-32').on_value_change(lambda e, c=c: (c.__setitem__('status', e.value), document_view.refresh(), criteria_rows.refresh()))
                                                ui.button(icon='delete', on_click=lambda _, c=c: (d['criteria'].remove(c), criteria_rows.refresh(), document_view.refresh())) \
                                                    .props('flat round dense color=negative')
                                            ui.textarea('Dado (contexto inicial)', value=c.get('given', '')).props('outlined dense autogrow').classes('w-full').mark('story-criterion-given') \
                                                .on_value_change(lambda e, c=c: (c.__setitem__('given', e.value), document_view.refresh())) \
                                                .on('blur', lambda: criteria_rows.refresh())
                                            ui.textarea('Cuando (acción)', value=c.get('when', '')).props('outlined dense autogrow').classes('w-full').mark('story-criterion-when') \
                                                .on_value_change(lambda e, c=c: (c.__setitem__('when', e.value), document_view.refresh())) \
                                                .on('blur', lambda: criteria_rows.refresh())
                                            ui.textarea('Entonces (resultado esperado)', value=c.get('then', '')).props('outlined dense autogrow').classes('w-full').mark('story-criterion-then') \
                                                .on_value_change(lambda e, c=c: (c.__setitem__('then', e.value), document_view.refresh())) \
                                                .on('blur', lambda: criteria_rows.refresh())

                                def render_criteria_panel():
                                    criteria_rows()
                                    ui.button('Agregar criterio', icon='add', on_click=lambda: (d['criteria'].append({'text': '', 'given': '', 'when': '', 'then': '', 'status': 'pending'}),
                                              criteria_rows.refresh(), document_view.refresh())).props('outline dense color=primary').mark('story-add-criterion')
                                known_renderers['criteria'] = render_criteria_panel

                                def checklist_editor(key, mark_prefix):
                                    @ui.refreshable
                                    def rows():
                                        if not d[key]:
                                            ui.label('Ninguno todavía.').classes('text-sm text-gray-400')
                                        for item in d[key]:
                                            with ui.row().classes('items-center gap-2 w-full no-wrap'):
                                                ui.checkbox(value=item.get('done', False)).on_value_change(lambda e, item=item: (item.__setitem__('done', e.value), document_view.refresh()))
                                                ui.input(value=item.get('text', '')).props('outlined dense').classes('grow').mark(f'{mark_prefix}-text') \
                                                    .on_value_change(lambda e, item=item: (item.__setitem__('text', e.value), document_view.refresh()))
                                                ui.button(icon='delete', on_click=lambda _, item=item: (d[key].remove(item), rows.refresh(), document_view.refresh())) \
                                                    .props('flat round dense color=negative')
                                    rows()
                                    ui.button('Agregar', icon='add', on_click=lambda: (d[key].append({'text': '', 'done': False}), rows.refresh(), document_view.refresh())) \
                                        .props('outline dense color=primary').mark(f'{mark_prefix}-add')
                                    return rows

                                def render_definition_of_ready():
                                    nonlocal dor_rows
                                    ui.label('Definición de Listo').classes('font-semibold')
                                    dor_rows = checklist_editor('dor', 'story-dor')
                                known_renderers['definition_of_ready'] = render_definition_of_ready

                                def render_definition_of_done():
                                    nonlocal dod_rows
                                    ui.label('Definición de Hecho').classes('font-semibold')
                                    dod_rows = checklist_editor('dod', 'story-dod')
                                known_renderers['definition_of_done'] = render_definition_of_done

                                def render_business_rules():
                                    nonlocal business_rules
                                    business_rules = ui.textarea('Reglas de negocio', value=(current or {}).get('business_rules', '')).props('outlined dense autogrow') \
                                        .classes('w-full').mark('story-business-rules').on_value_change(lambda e: document_view.refresh())
                                known_renderers['business_rules'] = render_business_rules

                                def render_assumptions():
                                    nonlocal assumptions
                                    assumptions = ui.textarea('Supuestos', value=(current or {}).get('assumptions', '')).props('outlined dense autogrow') \
                                        .classes('w-full').mark('story-assumptions').on_value_change(lambda e: document_view.refresh())
                                known_renderers['assumptions'] = render_assumptions

                                def render_risks():
                                    nonlocal risks
                                    risks = ui.textarea('Riesgos', value=(current or {}).get('risks', '')).props('outlined dense autogrow') \
                                        .classes('w-full').mark('story-risks').on_value_change(lambda e: document_view.refresh())
                                known_renderers['risks'] = render_risks

                                def render_out_of_scope():
                                    nonlocal out_of_scope
                                    out_of_scope = ui.textarea('Fuera de alcance', value=(current or {}).get('out_of_scope', '')).props('outlined dense autogrow') \
                                        .classes('w-full').mark('story-out-of-scope').on_value_change(lambda e: document_view.refresh())
                                known_renderers['out_of_scope'] = render_out_of_scope

                                def render_tests_panel():
                                    if not current:
                                        ui.label('Guardá la historia primero para poder ligarle Casos de prueba.').classes('text-sm text-gray-400')
                                    else:
                                        coverage = core.story_coverage(current['id'])
                                        with ui.row().classes('items-center gap-2 w-full'):
                                            ui.label(f'Matriz de pruebas — {coverage["total"]} caso(s) ligado(s)').classes('font-semibold')
                                            if coverage['automated']:
                                                ui.badge(f'{coverage["passing"]}/{coverage["automated"]} automatizados pasan',
                                                         color='positive' if coverage['passing'] == coverage['automated'] else 'negative')
                                        ui.button('Nuevo caso de prueba desde esta historia', icon='add',
                                                  on_click=lambda: ui.navigate.to(f'/test-specs/edit?story_id={current["id"]}')).props('outline dense color=primary')
                                        if not coverage['rows']:
                                            ui.label('Ninguno todavía.').classes('text-sm text-gray-400')
                                        else:
                                            for row in coverage['rows']:
                                                spec, last_run = row['spec'], row['last_run']
                                                with ui.row().classes('items-center gap-2 w-full cursor-pointer hover:bg-gray-50') \
                                                        .on('click', lambda _, sid=spec['id']: ui.navigate.to(f'/test-specs/edit?id={sid}')):
                                                    if last_run:
                                                        status_badge(last_run['status'])
                                                    else:
                                                        ui.badge(SPEC_STATUS_LABELS.get(spec.get('status'), spec.get('status', 'draft')), color='positive' if spec.get('status') == 'automated' else 'grey')
                                                    ui.label(spec['title']).classes('text-sm text-gray-700 grow truncate')
                                                    if last_run:
                                                        ui.label(fmt_time(last_run.get('started_at'))).classes('text-xs text-gray-400')
                                known_renderers['linked_test_cases'] = render_tests_panel

                                # Riel 100% dinámico: un grupo de primer nivel del `body` de la plantilla de
                                # entrada elegida = una pestaña (ícono/tooltip = los del grupo) — ver
                                # core.template_top_level_groups. Ya no hay ninguna pestaña fija: los metadatos
                                # de registro son, para esto, un grupo más (las 4 plantillas por defecto los
                                # agrupan en su propio "General", ver core.DEFAULT_SPEC_TEMPLATES). Sin plantilla
                                # alguna (caso borde, no debería pasar: todo proyecto adopta las 7 por defecto),
                                # cae a un único grupo con Título + Como/Quiero/Para.
                                @ui.refreshable
                                def fields_section():
                                    nonlocal field_panels
                                    tpl = core.get('spec_templates', input_template.value) if input_template and input_template.value else None
                                    groups = core.template_top_level_groups(tpl.get('body')) if tpl else [
                                        {'id': 'general', 'label': 'General', 'icon': 'edit_note', 'children': [
                                            {'kind': 'field', 'field_key': 'title', 'field_type': None, 'label': 'Título'},
                                            {'kind': 'field', 'field_key': 'as_a', 'field_type': None, 'label': 'Como (rol)'},
                                            {'kind': 'field', 'field_key': 'i_want', 'field_type': None, 'label': 'Quiero (acción o funcionalidad)'},
                                            {'kind': 'field', 'field_key': 'so_that', 'field_type': None, 'label': 'Para (beneficio o razón)'}]}]
                                    if not any(g['id'] == S['active_field_tab'] for g in groups):
                                        S['active_field_tab'] = groups[0]['id'] if groups else 'general'
                                    with ui.row().classes('w-full no-wrap gap-0').style('min-height:420px;justify-content:flex-end'):
                                        with ui.tab_panels(None, value=S['active_field_tab']).props('vertical').style('flex:1 1 0;min-width:0;padding:16px') as field_panels:
                                            for group in groups:
                                                with ui.tab_panel(group['id']).classes('gap-3 p-0'):
                                                    render_template_tree(group['children'], d['custom'], known_renderers, on_change=lambda: document_view.refresh())
                                        # Arrastrables hacia el panel central (soltar ahí los agrega como pestaña propia,
                                        # sin dejar de vivir acá) — ondragstart además de .on('dragstart', ...) porque
                                        # algunos navegadores exigen un dataTransfer.setData() para iniciar el arrastre.
                                        # Cualquier pestaña del riel es arrastrable — ya no una lista especial fija.
                                        with ui.tabs().props('vertical dense no-caps').classes('shrink-0').style('width:56px;border-left:1px solid #e5e7eb') as field_rail:
                                            for group in groups:
                                                tip = f'{group["label"]} (arrastrable al centro)' if len(groups) > 1 else group['label']
                                                ui.tab(group['id'], label='', icon=group['icon'] or 'folder').tooltip(tip).mark(f'story-rail-{group["id"]}') \
                                                    .props(f'draggable=true ondragstart="event.dataTransfer.setData(\'text/plain\',\'{group["id"]}\')"') \
                                                    .on('dragstart', lambda gid=group['id']: drag_state.__setitem__('key', gid)) \
                                                    .on('click', lambda gid=group['id']: handle_rail_click(gid))
                                        field_panels.bind_value_from(field_rail, 'value')
                                        field_rail.set_value(S['active_field_tab'])
                                fields_section()

                                def _on_input_template_change(e):
                                    fields_section.refresh()
                                    rebuild_center_panels()
                                    center_area.refresh()
                                    document_view.refresh()
                                if input_template:
                                    input_template.on_value_change(_on_input_template_change)

                                def save():
                                    if current:
                                        core.update_user_story(current['id'], d['meta']['title'], _v(as_a), _v(i_want), _v(so_that),
                                                               d['meta']['feature_id'], d['meta']['priority'], d['criteria'], d['meta']['status'],
                                                               definition_of_ready=d['dor'], definition_of_done=d['dod'], depends_on=d['meta']['depends_on'],
                                                               story_points=d['meta']['story_points'], assigned_to=d['meta']['assigned_to'],
                                                               business_rules=_v(business_rules), assumptions=_v(assumptions),
                                                               risks=_v(risks), out_of_scope=_v(out_of_scope), content=_v(content_box), custom_fields=d['custom'],
                                                               input_template_id=input_template.value if input_template else None)
                                        ui.notify('Historia actualizada', type='positive')
                                        ui.navigate.to(f'/stories/edit?id={current["id"]}')
                                    else:
                                        story = core.create_user_story(d['meta']['title'], pid, _v(as_a), _v(i_want), _v(so_that), d['meta']['feature_id'], d['meta']['priority'], d['criteria'],
                                                                       definition_of_ready=d['dor'], definition_of_done=d['dod'], depends_on=d['meta']['depends_on'],
                                                                       story_points=d['meta']['story_points'], assigned_to=d['meta']['assigned_to'],
                                                                       business_rules=_v(business_rules), assumptions=_v(assumptions),
                                                                       risks=_v(risks), out_of_scope=_v(out_of_scope), content=_v(content_box), custom_fields=d['custom'],
                                                                       input_template_id=input_template.value if input_template else None)
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

                            assistant_right_mount()

                    with main_split.before:
                        # Sin overflow:auto propio — ahora cada panel_card scrollea el suyo (abajo). Si esta
                        # columna TAMBIÉN tuviera su propio scroll, aparecían dos scrollbars superpuestas cuando
                        # hay un solo panel abierto (el de esta columna y el de la tarjeta, ambos de más).
                        with ui.column().classes('w-full gap-4 min-w-0').style('height:100%' if compact else ''):
                            @ui.refreshable
                            def document_view():
                                ui.label(d['meta']['title'] or 'Nueva historia de usuario').classes('text-2xl font-bold')
                                story_titles = {s['id']: s['title'] for s in other_stories}
                                # El documento muestra SOLO lo que la plantilla de entrada elegida define, en su
                                # orden (core.iter_template_fields) — incluidos sus campos personalizados y los
                                # metadatos de registro (priority/story_points/depends_on: ya no son fijos, son
                                # campos conocidos más — si la plantilla no los incluye, no aparecen).
                                tpl = core.get('spec_templates', input_template.value) if input_template and input_template.value else None
                                fields = list(core.iter_template_fields(tpl.get('body'))) if tpl else \
                                    [{'kind': 'field', 'field_key': k, 'field_type': None} for k in ('as_a', 'i_want', 'so_that')]
                                fragment = spec_report.render_story_view_html({
                                    'as_a': _v(as_a), 'i_want': _v(i_want), 'so_that': _v(so_that), 'content': _v(content_box),
                                    'priority': d['meta']['priority'],
                                    'story_points': int(d['meta']['story_points']) if d['meta']['story_points'] not in (None, '') else None,
                                    'criteria': d['criteria'], 'definition_of_ready': d['dor'], 'definition_of_done': d['dod'],
                                    'business_rules': _v(business_rules), 'assumptions': _v(assumptions), 'risks': _v(risks),
                                    'out_of_scope': _v(out_of_scope),
                                    'dependency_titles': [story_titles[sid] for sid in (d['meta']['depends_on'] or []) if sid in story_titles],
                                }, fields, d['custom'])
                                ui.html(live_doc_html(fragment, doc_typography()[0])).classes('w-full')

                            # Panel central: registro de contenidos posibles (clave -> etiqueta, ícono, render).
                            # "document" siempre está; "assistant" entra/sale según su ubicación elegida (menú);
                            # cualquier pestaña dinámica del riel de la derecha entra solo arrastrada hasta acá
                            # (sigue viviendo ahí también — esto solo agrega una SEGUNDA vista en vivo del mismo
                            # contenido, mismo `known_renderers`). Hasta 3 a la vez; en modo "pestañas" se ven de a
                            # una (la barra se oculta si solo hay una abierta, y esa única pestaña scrollea como
                            # "todo el centro"); en modo "dividido" se ven lado a lado con separadores ajustables y
                            # CADA panel scrollea el suyo por separado. Se reconstruye (no se reasigna — center_area
                            # ya la tiene cerrada como variable libre) cada vez que cambia la plantilla de entrada,
                            # ver fields_section()/_on_input_template_change más arriba.
                            CENTER_PANELS = {}

                            def rebuild_center_panels():
                                CENTER_PANELS.clear()
                                CENTER_PANELS['document'] = ('Documento', 'description', document_view)
                                CENTER_PANELS['assistant'] = ('Asistente de IA', 'smart_toy', render_assistant_body)
                                tpl = core.get('spec_templates', input_template.value) if input_template and input_template.value else None
                                groups = core.template_top_level_groups(tpl.get('body')) if tpl else []
                                for group in groups:
                                    CENTER_PANELS[group['id']] = (group['label'], group['icon'] or 'folder',
                                        (lambda g=group: render_template_tree(g['children'], d['custom'], known_renderers, on_change=lambda: document_view.refresh())))
                            rebuild_center_panels()

                            def panel_card(key):
                                label, icon, render = CENTER_PANELS[key]
                                with ui.card().classes('w-full').mark('story-document' if key == 'document' else f'story-center-{key}') \
                                        .style('height:100%;overflow:auto' if compact else ''):
                                    if key != 'document':
                                        with ui.row().classes('items-center justify-between w-full'):
                                            with ui.row().classes('items-center gap-1'):
                                                ui.icon(icon, size='xs', color='grey')
                                                ui.label(label).classes('text-xs text-gray-500')
                                            ui.button(icon='close', on_click=lambda k=key: remove_from_center(k)) \
                                                .props('flat round dense size=sm').mark(f'story-center-close-{key}')
                                    render()

                            def nested_split(keys):
                                if len(keys) == 1:
                                    panel_card(keys[0])
                                    return
                                with ui.splitter(value=round(100 / len(keys))).classes('w-full').style('height:100%' if compact else '') as sp:
                                    with sp.before:
                                        panel_card(keys[0])
                                    with sp.after:
                                        nested_split(keys[1:])

                            @ui.refreshable
                            def center_area():
                                open_keys = [k for k in S['center_open'] if k in CENTER_PANELS] or ['document']
                                # flex:1 (no height:100%+overflow:auto) para repartirse el alto con el Asistente
                                # cuando va abajo, SIN tener scroll propio — eso ya lo hace cada panel_card, y
                                # tenerlo acá también duplicaba la scrollbar cuando solo hay un panel abierto.
                                with ui.column().classes('w-full gap-0').style('flex:1 1 0;min-height:0;overflow:hidden' if compact else '') \
                                        .on('dragover.prevent', lambda: None) \
                                        .on('drop', lambda: add_to_center(drag_state['key'])):
                                    if S['center_mode'] == 'split' and len(open_keys) >= 2:
                                        nested_split(open_keys[:3])
                                    elif len(open_keys) == 1:
                                        panel_card(open_keys[0])
                                    else:
                                        with ui.tabs().props('dense no-caps').classes('w-full') as center_tabs:
                                            for key in open_keys:
                                                label, icon, _ = CENTER_PANELS[key]
                                                ui.tab(key, label=label, icon=icon)
                                        with ui.tab_panels(center_tabs, value=open_keys[0]).classes('w-full').style('height:100%' if compact else ''):
                                            for key in open_keys:
                                                with ui.tab_panel(key).classes('p-0').style('height:100%' if compact else ''):
                                                    panel_card(key)
                                # En modo compacto, el Asistente (cuando va abajo) vive ACÁ, dentro de esta misma
                                # columna que ya scrollea su propio contenido — si se quedara fuera del `div` de
                                # altura fija (como en modo con scroll) la página entera volvería a tener scroll,
                                # porque ya de por sí el área de dos columnas ocupa casi toda la altura disponible.
                                if compact:
                                    assistant_bottom_mount()
                            center_area()

            if not compact:
                assistant_bottom_mount()
