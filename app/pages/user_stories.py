import base64
from pathlib import Path
from nicegui import ui, run
from .. import core, llm
from .common import frame, guard, confirm, empty_state, require_project, fmt_time, status_badge, read_upload, protected_page

STATUS_LABELS = {'draft': 'Borrador', 'ready': 'Lista', 'done': 'Terminada'}
STORY_STATUSES = ('draft', 'ready', 'done')
IMPORT_TEXT_EXTENSIONS = ('.md', '.txt', '.csv', '.json')

# Hilos del Asistente de IA embebido, uno por historia (o 'new' para el borrador sin guardar todavía) — en
# memoria, nunca persistido, mismo espíritu que ASSISTANT_CHAT de chat_page.py pero separado por registro: acá
# se navega de una historia a otra todo el tiempo, y un solo hilo global mostraría la charla equivocada.
ASSISTANT_THREADS = {}


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
    with frame('Historias de usuario', '/stories'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.label('Lo que se quiere lograr y por qué, antes de escribir ningún caso de prueba. Cada una puede ligarse a una Funcionalidad.').classes('text-sm text-gray-500')
        with ui.row().classes('gap-2'):
            ui.button('Nueva historia', icon='add', on_click=lambda: ui.navigate.to('/stories/edit')).props('color=primary')
            ui.button('Importar', icon='upload_file', on_click=lambda: _open_import_dialog(pid)).props('outline color=primary').mark('stories-import')

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

        # ------------------------------------------------------------ Asistente de IA (Fase 2)
        thread_key = current['id'] if current else 'new'
        thread = ASSISTANT_THREADS.setdefault(thread_key, [])
        draft_cases = {'items': None}

        def _apply_story_draft(story, errors):
            if not story:
                raise ValueError('; '.join(errors) or 'El modelo no devolvió una historia válida')
            title.set_value(story['title'])
            as_a.set_value(story['as_a'])
            i_want.set_value(story['i_want'])
            so_that.set_value(story['so_that'])
            d['criteria'] = [{'text': c['text'], 'status': 'pending'} for c in story['criteria']]
            criteria_rows.refresh()

        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('smart_toy', color='primary')
                ui.label('Asistente de IA').classes('font-semibold')
                ui.icon('info', size='xs', color='grey').classes('cursor-help').tooltip(
                    'Pedile que genere una historia desde una descripción, que la refine o enriquezca, o — si ya '
                    'está guardada — que genere sus Casos de prueba. Lo que proponga queda arriba, para revisar '
                    'antes de guardar/crear; nunca se guarda solo.')

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
                        ui.label(f'{len(tc["steps"])} paso(s) · {tc["type"]} · {tc["priority"]}').classes('text-xs text-gray-500 ml-8')

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
                        item = {'title': title.value, 'as_a': as_a.value, 'i_want': i_want.value, 'so_that': so_that.value,
                               'criteria': [c['text'] for c in d['criteria']]}
                        result = await run.io_bound(llm.refine_spec_item, 'user_story', item, text)
                        _apply_story_draft(result['item'], result['errors'])
                        reply = 'Refiné la historia — revisá los cambios arriba y guardá si te sirven.'
                    elif any(k in lowered for k in llm.SPEC_GENERATE_STORY_KEYWORDS) or not title.value.strip():
                        selected_feature = core.get('features', feature.value) if feature.value else None
                        result = await run.io_bound(llm.generate_user_story, text, selected_feature)
                        _apply_story_draft(result['story'], result['errors'])
                        reply = 'Generé una propuesta — revisala arriba (título, Como/Quiero/Para y criterios) y guardá si te sirve.'
                    else:
                        context = {'kind': 'historia de usuario', 'current': {'title': title.value, 'as_a': as_a.value,
                                   'i_want': i_want.value, 'so_that': so_that.value, 'criteria': [c['text'] for c in d['criteria']]}}
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

        if not current:
            return

        coverage = core.story_coverage(current['id'])
        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('checklist', color='primary')
                ui.label(f'Matriz de pruebas — Casos ligados ({coverage["total"]})').classes('font-semibold')
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
                            ui.badge(spec.get('status', 'draft'), color='positive' if spec.get('status') == 'automated' else 'grey')
                        ui.label(spec['title']).classes('text-sm text-gray-700 grow truncate')
                        if last_run:
                            ui.label(fmt_time(last_run.get('started_at'))).classes('text-xs text-gray-400')
