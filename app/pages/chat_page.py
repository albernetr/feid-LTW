"""Chat: conversar en vivo con un chatbot/API conversacional, un mensaje a la vez — en vez de armar los turnos de
antemano como una suite. Pantalla propia (no una pestaña más del Espacio de trabajo), con el mismo layout de tres
paneles que ya usa `workspace_page.py`: izquierda (conversaciones/flujos guardados), centro (la conversación en
vivo), derecha (parámetros + el asistente de IA) — calcado a propósito, no un diseño nuevo."""
import asyncio
import copy
import datetime as dt
import json
from pathlib import Path
from nicegui import ui, run
from .. import core, workspace as ws, evidence_report, llm
from .common import frame, guard, protected_page, show_run, render_evidence, read_upload, open_evidence_in_new_tab, STATUS_LABEL
from .widgets import kv_rows, dynamic_variable_chips

CONTEXT_FILE_EXTENSIONS = ('.md', '.txt', '.csv')

HTTP_METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']
HEADER_SUGGESTIONS = (('+ Content-Type', 'Content-Type', 'application/json'), ('+ Accept', 'Accept', 'application/json'), ('+ Bearer', 'Authorization', 'Bearer {{secret:TOKEN}}'))


def parse_option_labels(raw):
    """Opciones de respuesta rápida del bot (botones) a una lista de textos para mostrar y tocar. El nombre del
    campo con el texto cambia de bot en bot, así que se prueba una lista de nombres comunes en orden; un string
    suelto en la lista (sin envoltorio) se usa tal cual."""
    if not isinstance(raw, list):
        return []
    labels = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            labels.append(item.strip())
        elif isinstance(item, dict):
            for key in ('label', 'text', 'title', 'name', 'value', 'id'):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    labels.append(value.strip())
                    break
    return labels


@protected_page('/chat')
def chat_route(case: str = ''):
    with frame('Chat', '/chat', wide=True):
        build(preset_case_id=case)


def build(preset_case_id=None):
    projects_by_id = {p['id']: p['name'] for p in core.list_items('projects')}
    all_envs = [e for e in core.list_items('environments') if e.get('name')]
    d = ws.new_draft()
    S = {'messages': [], 'thread_id': '', 'last_request': None, 'last_response': None, 'suite_id': None, 'runs': {}, 'replay': None, 'ai_run': None}
    # S['runs']: índice de turno -> run_doc completo (petición/respuesta/aserciones), para «Ver detalle y evidencia».
    # Solo en memoria — nunca entra a persist_session(), que guarda S['messages'] tal cual: una transcripción larga
    # con el run_doc completo de cada turno (cuerpos de petición/respuesta incluidos) infla el caso guardado.
    # S['replay']: None o un dict en curso {'index', 'total', 'mode': 'play'|'step', 'resume': asyncio.Event,
    # 'cancelled'} mientras «Reproducir conversación» va mandando turnos ya escritos (o los de un Flujo guardado)
    # contra el bot, uno por uno, con controles de reproducir/pausar/paso/detener — nunca se persiste.
    # S['ai_run']: None o un dict en curso {'phase': 'preset'|'ai', 'turn', 'max_turns', 'mode': 'play'|'step',
    # 'cancelled', 'draft', 'stop_reason'} mientras «Conversación conducida por IA» (ver run_ai_conversation) va
    # generando turnos — el turno sugerido queda precargado y EDITABLE en la barra de escribir normal (no se manda
    # solo salvo en modo «de corrido»): confirmar es, literalmente, mandar ese mensaje como cualquier otro.
    W = {}

    def resolve_project():
        project_id = core.get_active_project_id()
        if not project_id:
            raise ValueError('Elige un proyecto activo arriba a la derecha antes de guardar')
        return project_id

    def persistent_env(project_id, env):
        if d['env_id']:
            return core.environment_for_project(core.get('environments', d['env_id']), project_id)
        return core.ensure_environment_for_url(project_id, env['base_url'] + '/')[0]

    def persist_session():
        """Guarda la transcripción (mensajes, hilo, suite en progreso) en el caso, para poder retomarla más tarde
        tal como quedó — no solo la configuración del mapeo, que ya se guarda aparte al activarla."""
        source = d.get('source') or {}
        if source.get('type') != 'case':
            return
        existing = core.get('cases', source['id'])
        if existing is None:
            return
        core.save('cases', {**existing, 'chat_session': {'thread_id': S['thread_id'], 'messages': S['messages'], 'suite_id': S['suite_id']}})

    def sync_url():
        """Refleja el caso activo en la URL del navegador (sin recargar la página — `history.replaceState`, no
        `ui.navigate.to`). Si no se hace esto, la URL se queda en «/chat» pelado mientras toda la conversación
        vive solo en memoria del lado del servidor: si el socket se cae más de los 3s que NiceGUI espera por
        defecto para reconectar (típico cuando la pestaña queda inactiva un rato — no al estar escribiendo, que
        mantiene tráfico), el navegador reconecta pero el servidor ya no reconoce a ese cliente y fuerza una
        recarga completa — y esa recarga cae en «/chat» sin caso, como si fuera la primera vez, aunque la
        conversación sigue intacta en la base. Con la URL sincronizada, esa recarga (forzada o un F5 cualquiera)
        vuelve a pasar por `preset_case_id` y restaura todo tal como quedó."""
        source = d.get('source') or {}
        case_id = source.get('id') if source.get('type') == 'case' else None
        ui.navigate.history.replace(f'/chat?case={case_id}' if case_id else '/chat')

    def load_case(case_doc, resume=True):
        """resume=False carga la configuración (headers/body/variables/mapeo) pero arranca una conversación en
        blanco — así una plantilla sirve para empezar muchas conversaciones nuevas sin heredar la anterior."""
        env_id = case_doc.get('environment_id') or ''
        if env_id and core.get('environments', env_id) is None:
            env_id = ''
        if not env_id:
            envs = core.list_project_items('environments', case_doc.get('project_id'))
            env_id = envs[0]['id'] if len(envs) == 1 else ''
        d.clear()
        d.update(ws.draft_from_case(case_doc, env_id))
        d['hu_text'] = case_doc.get('hu_text') or ''   # workspace.draft_from_case no sabe de esto (es propio del chat)
        d['feature_id'] = case_doc.get('feature_id')
        d['context_data'] = case_doc.get('context_data')   # un .csv cargado «solo para esta exploración» (Fase 5)
        session = (case_doc.get('chat_session') or {}) if resume else {}
        S.update(messages=list(session.get('messages') or []), thread_id=session.get('thread_id') or '',
                 suite_id=session.get('suite_id'), last_request=None, last_response=None)
        refresh_all()
        sync_url()
        if not env_id:
            ui.notify('Elige el ambiente donde quieres conversar', type='info')

    def start_from_template(case_doc):
        load_case(case_doc, resume=False)
        ui.notify(f'Plantilla «{case_doc["name"]}» cargada: conversación nueva', type='positive')

    def new_chat():
        d.clear()
        d.update(ws.new_draft())
        S.update(messages=[], thread_id='', last_request=None, last_response=None, suite_id=None)
        refresh_all()
        sync_url()

    def refresh_all():
        for name in ('params_view', 'chat_view', 'debug_view', 'case_picker', 'template_picker', 'thread_label', 'left_panel'):
            if name in W:
                W[name].refresh()

    if preset_case_id:
        existing = core.get('cases', preset_case_id)
        if existing:
            load_case(existing)

    # ------------------------------------------------------------ contexto adicional (Fase 5, y ahora también
    # usado por el chat libre con el Asistente — Fase A siguiente): sacado a nivel de build() para que tanto
    # Parámetros como la pestaña Asistente de IA lo llamen sin duplicar nada. Lee/escribe el widget vivo de la
    # Historia de usuario a través de W (si Parámetros ya se renderizó — siempre, están todos los tabs montados
    # de entrada), para no pisar un texto que la persona esté escribiendo a mano ahí mismo.
    def _context_data_summary():
        data = d.get('context_data')
        if not data:
            return 'Sin datos cargados para esta exploración.'
        return f'Datos cargados para esta exploración: «{data.get("source", "")}» ({len(data.get("rows") or [])} fila(s))'

    def csv_offer_dialog(filename, columns, rows):
        with ui.dialog() as dlg, ui.card().classes('w-[480px] max-w-full'):
            ui.label(f'«{filename}»: {len(rows)} fila(s), columnas: {", ".join(columns)}').classes('text-sm')
            ui.label('¿Cómo lo usamos?').classes('text-sm text-gray-600')
            name_input = ui.input('Nombre del Conjunto de datos', value=Path(filename).stem) \
                .props('outlined dense').classes('w-full').mark('chat-context-csv-name')

            def use_once():
                d['context_data'] = {'columns': columns, 'rows': rows, 'source': filename}
                if 'context_data_label' in W:
                    W['context_data_label'].set_text(_context_data_summary())
                ui.notify('Datos disponibles para esta exploración (se guardan junto al caso al activar)', type='positive')
                dlg.close()

            def save_as_dataset():
                name = (name_input.value or '').strip()
                if not name:
                    raise ValueError('Ponele un nombre al Conjunto de datos')
                core.save_dataset(name, resolve_project(), columns, rows)
                ui.notify(f'Conjunto de datos «{name}» guardado — reusable en cualquier caso/suite del proyecto', type='positive')
                dlg.close()
            with ui.row().classes('justify-end gap-2 w-full pt-2'):
                ui.button('Cancelar', on_click=dlg.close).props('flat')
                ui.button('Solo esta exploración', on_click=guard(use_once)).props('no-caps').mark('chat-context-csv-once')
                ui.button('Guardar como Conjunto de datos', on_click=guard(save_as_dataset)).props('color=primary no-caps').mark('chat-context-csv-save')
        dlg.open()

    def apply_context_file(filename, raw):
        """.md/.txt se suman a la Historia de usuario (completan ese mismo campo, no uno nuevo); .csv ofrece,
        a demanda, usarlo solo para esta exploración o guardarlo como Conjunto de datos — nunca se decide
        solo. Mismo tope de tamaño que ya usan los Conjuntos de datos. Llamable desde Parámetros o desde el
        chat del Asistente de IA (Fase A) — por eso no vive adentro de ningún @ui.refreshable puntual."""
        ext = Path(filename).suffix.lower()
        if ext not in CONTEXT_FILE_EXTENSIONS:
            raise ValueError(f'Extensión no soportada «{ext or filename}» — usa .md, .txt o .csv')
        if len(raw) > core.MAX_DATASET_BYTES:
            raise ValueError(f'El archivo pesa más de {core.MAX_DATASET_BYTES // 1_000_000} MB')
        if ext == '.csv':
            columns, rows = core.parse_dataset_file(filename, raw)
            csv_offer_dialog(filename, columns, rows)
            return
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError as exc:
            raise ValueError(f'No se pudo leer «{filename}» como texto (¿no es UTF-8?)') from exc
        hu_widget = W.get('hu_text')
        existing = ((hu_widget.value if hu_widget else d.get('hu_text')) or '').strip()
        new_value = (existing + '\n\n' if existing else '') + text.strip()
        if hu_widget:
            hu_widget.set_value(new_value)
        else:
            d['hu_text'] = new_value
        ui.notify(f'«{filename}» sumado a la Historia de usuario / criterios — no olvides «Guardar configuración»', type='positive')

    async def on_context_upload(event):
        try:
            raw = await read_upload(event)
            apply_context_file(event.file.name, raw)
        except ValueError as exc:
            ui.notify(str(exc), type='negative', multi_line=True)

    def load_context_from_path(raw_path):
        raw_path = (raw_path or '').strip()
        if not raw_path:
            raise ValueError('Escribí una ruta')
        path = Path(raw_path)
        if not path.is_file():
            raise ValueError(f'No se encontró el archivo «{raw_path}»')
        apply_context_file(path.name, path.read_bytes())

    # ------------------------------------------------------------ parameters (headers + chat mapping) — vive en
    # la pestaña «Parámetros» del panel derecho (ver right_panel más abajo); ya no es un acordeón en el flujo
    # central, pero su contenido es exactamente el mismo.
    @ui.refreshable
    def params_view():
        with ui.column().classes('w-full gap-2 p-3'):
            ui.label('Headers').classes('font-medium text-sm')
            W['headers_view'] = kv_rows(lambda: d['headers'], 'Header', 'Valor', None, HEADER_SUGGESTIONS)
            ui.separator().classes('my-1')
            ui.label('Variables').classes('font-medium text-sm')
            ui.label('Ponés {{nombre}} en el body (o en headers) y cambiás el valor acá cuando quieras, sin tocar el JSON.').classes('text-xs text-gray-500')
            W['variables_view'] = kv_rows(lambda: d['variables'], 'Nombre', 'Valor')
            dynamic_variable_chips()
            ui.separator().classes('my-1')
            ui.label('Body base (JSON)').classes('font-medium text-sm')
            ui.label('Lo que no cambia turno a turno (status, source, campaign, attributes…) — distinto caso a caso. '
                      'Usa {{secret:NOMBRE}} para secretos y {{nombre}} para lo que definiste en Variables.').classes('text-xs text-gray-500')

            def body_changed(event):
                d['body'] = event.value
            ui.codemirror(d.get('body') or '', language='JSON', line_wrapping=True, on_change=body_changed) \
                .classes('w-full').style('height:160px').mark('chat-body')
            ui.separator().classes('my-1')
            ui.label('Mapeo del chat (según el contrato del bot)').classes('font-medium text-sm')
            chat = d.get('chat') or {}
            msg_path = ui.input('Ruta del mensaje saliente', value=chat.get('message_path', '$.message')).props('outlined dense').classes('w-full').mark('chat-msg-path')
            thread_req_path = ui.input('Ruta del id de hilo en la petición', value=chat.get('thread_request_path', '$.conversation_id')) \
                .props('outlined dense').classes('w-full').mark('chat-thread-req-path')
            thread_resp_path = ui.input('Ruta del id de hilo en la respuesta', value=chat.get('thread_response_path', '$.thread_id')) \
                .props('outlined dense').classes('w-full').mark('chat-thread-resp-path')
            reply_path = ui.input('Ruta de la respuesta del bot', value=chat.get('reply_path', '$.respuesta')).props('outlined dense').classes('w-full').mark('chat-reply-path')
            options_path = ui.input('Ruta de las opciones de respuesta (opcional)', value=chat.get('options_path', '')) \
                .props('outlined dense').classes('w-full').mark('chat-options-path') \
                .tooltip('Si el bot manda botones de respuesta rápida, poné la ruta a esa lista — p. ej. $.conversation.replies[0].options. '
                         'Vacío si el bot no los manda.')
            ui.separator().classes('my-1')
            ui.label('Criterio para el veredicto del modelo (opcional)').classes('font-medium text-sm')
            ui.label('El asistente de IA (pestaña «Asistente IA» →) evalúa la conversación contra esto. Si dejás los '
                     'dos vacíos, infiere el objetivo del nombre/notas del caso y de la propia conversación.').classes('text-xs text-gray-500')
            hu_text = ui.textarea('Historia de usuario / criterios de aceptación', value=d.get('hu_text') or '') \
                .props('outlined dense').classes('w-full').mark('chat-hu-text')
            W['hu_text'] = hu_text
            active_project_id = core.get_active_project_id()
            features = core.list_project_items('features', active_project_id) if active_project_id else []
            feature_id = ui.select({f['id']: f['name'] for f in features}, label='O ligar a una Funcionalidad', clearable=True,
                                    value=d.get('feature_id')).props('outlined dense').classes('w-full').mark('chat-feature-id')

            ui.separator().classes('my-1')
            ui.label('Contexto adicional (opcional)').classes('font-medium text-sm')
            ui.label('Un .md/.txt de HU o casos de prueba se suma al criterio de arriba. Un .csv ofrece usarlo '
                      'solo para esta exploración (el Asistente de IA lo ve como datos disponibles al redactar '
                      'turnos) o guardarlo como Conjunto de datos reusable en cualquier caso/suite después.') \
                .classes('text-xs text-gray-500')

            context_data_label = ui.label(_context_data_summary()).classes('text-xs text-gray-600').mark('chat-context-data-summary')
            W['context_data_label'] = context_data_label

            async def on_context_upload(event):
                try:
                    raw = await read_upload(event)
                    apply_context_file(event.file.name, raw)
                except ValueError as exc:
                    ui.notify(str(exc), type='negative', multi_line=True)
            ui.upload(label='Subir archivo (.md/.txt/.csv)', on_upload=on_context_upload, auto_upload=True,
                      max_file_size=core.MAX_DATASET_BYTES).props('accept=.md,.txt,.csv flat bordered').classes('w-full').mark('chat-context-upload')

            with ui.row().classes('w-full items-center gap-2'):
                context_path = ui.input('O cargar por ruta local (.md/.txt/.csv)').props('outlined dense').classes('grow').mark('chat-context-path')

                def load_from_path():
                    load_context_from_path(context_path.value)
                    context_path.set_value('')
                ui.button('Cargar', icon='upload_file', on_click=guard(load_from_path)).props('outline dense no-caps').mark('chat-context-load-path')

            def activate():
                """Guarda la configuración (headers, variables, body base y mapeo) como una plantilla reutilizable —
                un endpoint de chat configurado una vez que después aparece en «Plantilla» para arrancar cualquier
                cantidad de conversaciones nuevas sin tener que volver a cargar nada."""
                fields = {'message_path': msg_path, 'thread_request_path': thread_req_path, 'thread_response_path': thread_resp_path, 'reply_path': reply_path}
                if any(not (f.value or '').strip() for f in fields.values()):
                    raise ValueError('Completa las cuatro rutas')
                if not (d.get('name') or '').strip():
                    raise ValueError('Ponele un nombre a este chat arriba (donde dice «Nombre de este chat») para guardar la plantilla')
                d['chat'] = {name: field.value.strip() for name, field in fields.items()}
                d['chat']['options_path'] = (options_path.value or '').strip()
                d['hu_text'] = hu_text.value.strip()
                d['feature_id'] = feature_id.value
                project_id = resolve_project()
                base, env = ws.build_case(d)
                env_doc = persistent_env(project_id, env)
                source = d.get('source') or {}
                existing = core.get('cases', source['id']) if source.get('type') == 'case' else None
                item = {k: v for k, v in base.items() if k not in ('id', 'updated_at')}
                item.update({'project_id': project_id, 'environment_id': env_doc['id'], 'chat_template': True,
                             'hu_text': d['hu_text'], 'feature_id': d['feature_id'], 'context_data': d.get('context_data')})
                if existing is not None:
                    item['id'] = existing['id']
                    item['chat_session'] = existing.get('chat_session')
                saved = core.save('cases', item)
                d['source'] = {'type': 'case', 'id': saved['id'], 'updated_at': saved.get('updated_at')}
                sync_url()
                ui.notify(f'Plantilla «{saved["name"]}» guardada: la vas a encontrar en «Plantilla» la próxima vez', type='positive')
                W['params_view'].refresh()
                W['template_picker'].refresh()
                if 'left_panel' in W:
                    W['left_panel'].refresh()
                chat_view.refresh()
            ui.button('Guardar configuración', icon='check', on_click=guard(activate)).props('color=primary dense no-caps').mark('chat-activate')
    W['params_view'] = params_view

    # ------------------------------------------------------------ conversation-level actions (no de un turno
    # puntual): guardar lo pendiente como Flujo, evidencia conjunta, reproducir. Se repiten arriba (junto al
    # hilo) y abajo (pegadas a la barra de envío) — antes vivían en una sola fila a mitad de pantalla, que se
    # perdía de vista apenas la conversación crecía; reportado en vivo («quiero las acciones arriba y abajo, al
    # nivel de la barra de envío»). Detrás de un «+» para no ocupar espacio cuando no se están usando.
    ui_state = {'actions_expanded': False}

    def toggle_actions():
        ui_state['actions_expanded'] = not ui_state['actions_expanded']
        W['top_actions'].refresh()
        W['bottom_actions'].refresh()

    def conversation_action_buttons(suffix=''):
        ui.button(icon='playlist_add_check', on_click=guard(lambda: save_all_pending(suite_name.value))) \
            .props('flat dense round size=sm color=primary').mark(f'chat-save-suite{suffix}') \
            .tooltip('Guardar todo lo pendiente como Flujo')
        ui.button(icon='fact_check', on_click=guard(lambda: conversation_evidence_dialog())) \
            .props('flat dense round size=sm color=grey-8').mark(f'chat-evidence-all{suffix}') \
            .tooltip('Evidencia de la conversación (todos los turnos)')
        ui.button(icon='play_circle', on_click=guard(lambda: replay_dialog())) \
            .props('flat dense round size=sm color=grey-8').mark(f'chat-replay{suffix}') \
            .tooltip('Reproducir conversación')
        ui.button(icon='movie', on_click=guard(lambda: replay_from_suite_dialog())) \
            .props('flat dense round size=sm color=grey-8').mark(f'chat-replay-suite{suffix}') \
            .tooltip('Retomar un Flujo guardado')

    @ui.refreshable
    def top_actions():
        with ui.row().classes('items-center gap-1 no-wrap'):
            # Sin guard(): un toggle simple (mismo patrón que `toggle_panel` en turn_actions_row) no necesita
            # programarse como tarea en segundo plano — eso solo demoraba el refresh un tick, invisible a simple
            # vista pero suficiente para que un clic inmediatamente siguiente en un test no encontrara nada.
            ui.button(icon='close' if ui_state['actions_expanded'] else 'add', on_click=toggle_actions) \
                .props('flat dense round size=sm color=grey-8').mark('chat-actions-toggle') \
                .tooltip('Ocultar acciones de la conversación' if ui_state['actions_expanded']
                         else 'Más acciones de la conversación (guardar, evidencia, reproducir)')
            if ui_state['actions_expanded']:
                conversation_action_buttons()
    W['top_actions'] = top_actions

    @ui.refreshable
    def bottom_actions():
        with ui.row().classes('items-center gap-1 no-wrap'):
            ui.button(icon='close' if ui_state['actions_expanded'] else 'add', on_click=toggle_actions) \
                .props('flat dense round size=sm color=grey-8').mark('chat-actions-toggle-bottom') \
                .tooltip('Ocultar acciones de la conversación' if ui_state['actions_expanded']
                         else 'Más acciones de la conversación (guardar, evidencia, reproducir)')
            if ui_state['actions_expanded']:
                conversation_action_buttons('-bottom')
    W['bottom_actions'] = bottom_actions

    # ------------------------------------------------------------ conversation
    @ui.refreshable
    def chat_view():
        if not S['messages'] and not S['replay'] and not S['ai_run']:
            # Si hay una reproducción (o una conversación conducida por IA) en curso, S['messages'] arranca vacío
            # a propósito pero la barra de control tiene que pintarse igual — si no, «paso a paso» queda
            # esperando un clic en un control que nunca aparece.
            with ui.column().classes('w-full items-center justify-center').style('min-height:240px'):
                ui.label('Completa el mapeo en «Parámetros» (panel derecho) y guardalo para empezar a conversar.' if not d.get('chat')
                          else 'Escribe el primer mensaje abajo.').classes('text-sm text-gray-500')
            return
        def turn_request_response_panel(index):
            """Contenedor oculto por defecto con el JSON enviado/recibido de ESTE turno puntual — lo revela un
            ícono compacto (ver turn_actions_row), no una barra de acordeón de ancho completo: esa barra, casi
            vacía mientras está colapsada, fue reportada en vivo como «demasiado espacio perdido»."""
            run_doc = S['runs'][index]
            panel = ui.column().classes('w-full gap-0 pl-1 pt-1')
            panel.visible = False
            with panel:
                sent = (run_doc.get('request') or {}).get('body')
                if sent is not None:
                    ui.label('Enviado').classes('text-xs font-semibold text-gray-500')
                    body_text = sent if isinstance(sent, str) else json.dumps(sent, indent=2, ensure_ascii=False)
                    ui.code(body_text, language='json').classes('w-full').style('max-height:160px;overflow:auto')
                resp_body = (run_doc.get('response') or {}).get('body')
                if resp_body:
                    ui.label('Recibido').classes('text-xs font-semibold text-gray-500')
                    ui.code(resp_body, language='json').classes('w-full').style('max-height:160px;overflow:auto')
                if not sent and not resp_body:
                    ui.label(run_doc.get('error') or 'Sin datos de petición/respuesta para este turno.').classes('text-xs text-gray-500')
            return panel

        def turn_actions_row(index, save_callback=None, saved_turn_number=None):
            """Fila compacta de íconos con leyenda (tooltip) al lado derecho, pegada al turno — reemplaza los
            botones con texto completo (cada uno ocupaba una fila entera) y la barra de acordeón de petición/
            respuesta por un ícono que la revela. «Guardar»/«Ver detalle»/«código» son del MISMO turno (una sola
            llamada HTTP: lo que se mandó + lo que llegó), así que van juntos, a la altura del turno, no cada uno
            en su propia fila. save_callback=None y saved_turn_number=None: no hay nada que guardar (p. ej. un
            error de conexión sin turno de usuario previo)."""
            panel_ref = []
            with ui.row().classes('items-center justify-end gap-0 w-full -mt-1'):
                if saved_turn_number is not None:
                    ui.icon('check_circle', size='xs', color='positive').classes('q-pa-xs') \
                        .tooltip(f'Guardado como «Turno {saved_turn_number}»')
                elif save_callback is not None:
                    ui.button(icon='bookmark_add', on_click=save_callback) \
                        .props('flat dense round size=sm color=primary').mark(f'chat-save-turn-{index - 1}') \
                        .tooltip('Guardar este intercambio como caso')
                if index in S['runs']:
                    ui.button(icon='fact_check', on_click=lambda _, r=S['runs'][index]: show_run(r)) \
                        .props('flat dense round size=sm color=grey-8').mark(f'chat-evidence-{index}') \
                        .tooltip('Ver detalle y evidencia')

                    def toggle_panel(_=None, ref=panel_ref):
                        ref[0].visible = not ref[0].visible
                    ui.button(icon='code', on_click=toggle_panel) \
                        .props('flat dense round size=sm color=grey-8').mark(f'chat-reqres-{index}') \
                        .tooltip('Ver petición/respuesta de este turno')
            if index in S['runs']:
                panel_ref.append(turn_request_response_panel(index))

        if S['replay']:
            replay = S['replay']
            # Botones sin guard()/async: solo tocan el dict y el Event, la corrida real vive en run_replay() (ver
            # más abajo) corriendo aparte — así no importa que este control esté dentro del mismo refrescable que
            # ese bucle va a volver a dibujar en cuanto el replay se despierte.
            def replay_play(_=None, r=replay):
                r['mode'] = 'play'
                r['resume'].set()

            def replay_pause(_=None, r=replay):
                r['mode'] = 'step'

            def replay_step(_=None, r=replay):
                r['mode'] = 'step'
                r['resume'].set()

            def replay_skip(_=None, r=replay):
                # No manda el texto grabado de este paso — para cuando ya lo respondiste vos a mano (distinto de
                # lo grabado) y querés que la reproducción siga con la PRÓXIMA pregunta, no que repita esta.
                r['mode'] = 'step'
                r['skip_current'] = True
                r['resume'].set()

            def replay_stop(_=None, r=replay):
                r['cancelled'] = True
                r['resume'].set()
            with ui.row().classes('items-center gap-2 w-full px-3 py-2 bg-blue-50 rounded-borders'):
                ui.icon('smart_display', color='primary')
                ui.label(f'Reproduciendo turno {replay["index"]} de {replay["total"]}…').classes('text-sm text-primary')
                ui.linear_progress(value=(replay['index'] / replay['total']) if replay['total'] else 0, show_value=False) \
                    .classes('w-32').props('color=primary')
                ui.space()
                ui.button(icon='play_arrow', on_click=replay_play).props('flat dense round size=sm color=primary') \
                    .mark('chat-replay-play').tooltip('Reproducir seguido')
                ui.button(icon='pause', on_click=replay_pause).props('flat dense round size=sm color=primary') \
                    .mark('chat-replay-pause').tooltip('Pausar')
                ui.button(icon='skip_next', on_click=replay_step).props('flat dense round size=sm color=primary') \
                    .mark('chat-replay-step').tooltip('Un paso')
                ui.button(icon='fast_forward', on_click=replay_skip).props('flat dense round size=sm color=warning') \
                    .mark('chat-replay-skip').tooltip('Saltar — ya respondiste esta vos; seguir con la próxima sin reenviar esta')
                ui.button(icon='stop', on_click=replay_stop).props('flat dense round size=sm color=negative') \
                    .mark('chat-replay-stop').tooltip('Detener acá')

        if S['ai_run']:
            ai_run = S['ai_run']

            async def ai_run_play(r=ai_run):
                # Si ya hay un turno sugerido esperando (modo paso a paso), «seguir de corrido» también lo manda
                # ahora tal como está en la caja — si no, el bucle se queda esperando un envío que nadie va a
                # disparar con solo cambiar el modo.
                r['mode'] = 'play'
                if r['draft']:
                    await send_chat_message(box)

            def ai_run_pause(_=None, r=ai_run):
                r['mode'] = 'step'

            def ai_run_stop(_=None, r=ai_run):
                r['cancelled'] = True
            label = (f'IA sugiriendo turno {ai_run["turn"]} de hasta {ai_run["max_turns"]}' if ai_run['phase'] == 'ai'
                     else 'Retomando los turnos del Flujo elegido…')
            if ai_run['draft']:
                label += ' — revisá/editá el mensaje de abajo y mandalo para seguir'
            with ui.row().classes('items-center gap-2 w-full px-3 py-2 bg-purple-50 rounded-borders'):
                ui.icon('smart_toy', color='primary')
                ui.label(label).classes('text-sm text-primary')
                ui.space()
                ui.button(icon='play_arrow', on_click=guard(ai_run_play)).props('flat dense round size=sm color=primary') \
                    .mark('chat-ai-run-play').tooltip('Seguir de corrido (manda cada turno sugerido solo)')
                ui.button(icon='pause', on_click=ai_run_pause).props('flat dense round size=sm color=primary') \
                    .mark('chat-ai-run-pause').tooltip('Pausar y revisar cada turno antes de mandarlo')
                ui.button(icon='stop', on_click=ai_run_stop).props('flat dense round size=sm color=negative') \
                    .mark('chat-ai-run-stop').tooltip('Detener acá')

        with ui.column().classes('w-full gap-1 px-3'):
            for index, turn in enumerate(S['messages']):
                if turn['who'] == 'user':
                    ui.chat_message(turn['text'], sent=True, name='Vos')
                elif turn['who'] == 'bot':
                    ui.chat_message(turn['text'], sent=False, name='Bot', stamp=(f'HTTP {turn["status"]}' if turn.get('status') else None))
                    if turn.get('thread_warning'):
                        ui.label(f'⚠ {turn["thread_warning"]}').classes('text-xs text-amber-700 pl-1')
                    if turn.get('options'):
                        with ui.row().classes('items-center gap-2 pl-1 pt-1 pb-1 flex-wrap'):
                            ui.icon('touch_app', size='xs').classes('text-primary')
                            ui.label('Opciones del bot:').classes('text-xs font-medium text-gray-600')
                            for opt_index, option_label in enumerate(turn['options']):
                                # guard() envuelve el handler en (*args, **kwargs): NiceGUI inspecciona esa firma
                                # (no la del lambda de adentro) para decidir si lo llama con el evento de clic o sin
                                # nada, y *args no cuenta como "espera argumentos" — lo llama sin ninguno. Por eso
                                # el lambda no puede tener un parámetro posicional obligatorio (p. ej. `_`): si lo
                                # tuviera, la llamada sin argumentos lo rompe y el clic se pierde en silencio (el
                                # error queda atrapado dentro de guard(), nunca llega a mostrarse como falla).
                                # unelevated+rounded (botón lleno, no outline chico): los "outline dense size=sm"
                                # que se usan para el resto de las acciones del turno (Guardar/Ver detalle) casi no
                                # se distinguían de estos — reportado en vivo como «casi no se notan».
                                ui.button(option_label, on_click=guard(lambda o=option_label: send_chat_message(box, o))) \
                                    .props('unelevated rounded no-caps color=primary').classes('px-4 text-sm') \
                                    .mark(f'chat-option-{index}-{opt_index}') \
                                    .tooltip('Opción de respuesta rápida del bot — tocala para mandarla como tu próximo mensaje')
                    prev = S['messages'][index - 1] if index > 0 else None
                    save_callback = None
                    saved_turn_number = None
                    if prev and prev['who'] == 'user':
                        if prev.get('saved'):
                            saved_turn_number = prev['turn_number']
                        else:
                            def save_this_turn(_=None, i=index - 1):
                                # Sin async: un botón creado dentro de este bucle (anidado en el refrescable del chat) con un
                                # on_click envuelto en guard() (que lo programa como tarea en segundo plano) perdía el clic en
                                # cuanto save_turn_as_case refrescaba chat_view a mitad de camino — reproducido de forma
                                # consistente. Resuelto a mano, igual que guard(), pero ejecutando en el mismo tick del clic.
                                try:
                                    save_turn_as_case(i)
                                except Exception as exc:
                                    ui.notify(str(exc) or type(exc).__name__, type='negative', multi_line=True)
                            save_callback = save_this_turn
                    turn_actions_row(index, save_callback, saved_turn_number)
                else:
                    ui.label(turn['text']).classes('text-xs text-red-700')
                    turn_actions_row(index)
    W['chat_view'] = chat_view

    # ------------------------------------------------------------ last turn, raw (debugging)
    @ui.refreshable
    def debug_view():
        with ui.expansion('Petición / Respuesta (último turno)', icon='code', value=False).classes('w-full'):
            if not S['last_request']:
                ui.label('Aún no enviaste ningún mensaje.').classes('text-xs text-gray-500')
            else:
                ui.label('Enviado').classes('text-xs font-semibold text-gray-500')
                ui.code(json.dumps(S['last_request'], indent=2, ensure_ascii=False), language='json').classes('w-full').style('max-height:160px;overflow:auto')
                ui.label('Recibido').classes('text-xs font-semibold text-gray-500')
                ui.code(S['last_response'] or '', language='json').classes('w-full').style('max-height:160px;overflow:auto')
    W['debug_view'] = debug_view

    def scroll_to_bottom():
        """Sigue la conversación a medida que se arman los turnos — sin esto, en una conversación larga (o al
        reproducir paso a paso) cada mensaje nuevo o cada pausa del reproductor aparece fuera de la pantalla.
        Envuelto en try/except: `ui.run_javascript` resuelve el slot/cliente «actual» a partir de dónde se llamó
        — cuando quien llama es un botón de opción rápida (vive DENTRO del `chat_view` refrescable) y ese mismo
        turno acaba de refrescar `chat_view` (unas líneas antes, en este mismo handler), ese slot ya no existe
        y NiceGUI tira RuntimeError. No vale la pena que una falla al hacer scroll tire abajo el turno entero."""
        try:
            ui.run_javascript('const el = document.querySelector(".ltw-pane"); if (el) el.scrollTo({top: el.scrollHeight, behavior: "smooth"})')
        except RuntimeError:
            pass

    async def send_chat_message(box, preset_text=None):
        """preset_text: lo manda tal cual sin tocar la caja de texto — así un botón de opción rápida (ver
        `turn.get('options')` en chat_view) envía su texto como si lo hubieras tipeado vos."""
        text = (preset_text if preset_text is not None else (box.value or '')).strip()
        chat = d.get('chat')
        if not text:
            return
        if not chat:
            ui.notify('Completa el mapeo del chat en «Parámetros» (panel derecho) y guárdalo antes de conversar', type='warning')
            return
        if preset_text is None:
            box.set_value('')
        try:
            case, env = ws.build_case(d)
        except ValueError as exc:
            S['messages'].append({'who': 'error', 'text': str(exc)})
            chat_view.refresh()
            scroll_to_bottom()
            return
        body = case['body'] if isinstance(case['body'], dict) else {}
        try:
            core.set_path(body, chat['message_path'], text)
            if S['thread_id']:
                core.set_path(body, chat['thread_request_path'], S['thread_id'])
            else:
                # Primer turno de una conversación nueva: si el Body base ya trae algo en esa ruta (p. ej.
                # {{seq:conversacion}} para que el propio chatbot reciba un id armado por nosotros), lo dejamos tal
                # cual en vez de pisarlo con '' — solo se fuerza a vacío cuando esa ruta no existía en el body.
                try:
                    core.extract_path(body, chat['thread_request_path'])
                except core.PathError:
                    core.set_path(body, chat['thread_request_path'], '')
        except ValueError as exc:
            S['messages'] += [{'who': 'user', 'text': text}, {'who': 'error', 'text': f'No se pudo armar la petición: {exc}'}]
            chat_view.refresh()
            scroll_to_bottom()
            return
        S['messages'].append({'who': 'user', 'text': text})
        S['last_request'] = body
        chat_view.refresh()
        debug_view.refresh()
        scroll_to_bottom()
        run_doc = await run.io_bound(core.execute_api, {**case, 'body': body}, env, None, False)
        if run_doc is None:
            # run.io_bound devuelve None (no una excepción) si la llamada se canceló — documentado, no un caso
            # exótico: puede pasar si este turno viene de un diálogo (p. ej. «Reproducir conversación») que ya
            # se cerró. Reintentar en el mismo hilo (bloquea un instante, pero es la llamada de respaldo, no el
            # camino normal) es más simple y correcto que dejar que el turno se pierda en silencio.
            run_doc = core.execute_api({**case, 'body': body}, env, None, False)
        run_doc['case_name'] = f'Chat: {text[:60]}'   # para que el título de la evidencia diga algo, no quede vacío
        if run_doc.get('status') == 'failed' and not run_doc.get('assertions'):
            # core.execute_api marca «failed» cuando el caso no tiene aserciones (sin ellas, nada quedó confirmado —
            # ver app/core.py y tests/test_lab.py). Acá no aplica: un turno de chat en vivo nunca define aserciones
            # por turno (solo las gana al guardarse como caso con «Guardar este intercambio como caso»), así que una
            # respuesta HTTP sin error es un turno exitoso, no un fallo.
            run_doc['status'] = 'passed'
        if run_doc['status'] == 'error':
            S['messages'].append({'who': 'error', 'text': run_doc.get('error') or 'Error de conexión'})
            S['runs'][len(S['messages']) - 1] = run_doc
            S['last_response'] = run_doc.get('error') or ''
            chat_view.refresh()
            debug_view.refresh()
            scroll_to_bottom()
            persist_session()
            return
        S['last_request'] = (run_doc.get('request') or {}).get('body', body)   # con {{variables}} ya resueltas, lo que de verdad viajó
        status = run_doc.get('http_status')
        raw_body = (run_doc.get('response') or {}).get('body', '')
        try:
            S['last_response'] = json.dumps(json.loads(raw_body), indent=2, ensure_ascii=False)
        except (TypeError, ValueError):
            S['last_response'] = raw_body
        try:
            parsed = json.loads(raw_body)
        except (TypeError, ValueError):
            S['messages'].append({'who': 'error', 'text': f'HTTP {status}: la respuesta no es JSON'})
            S['runs'][len(S['messages']) - 1] = run_doc
            chat_view.refresh()
            debug_view.refresh()
            scroll_to_bottom()
            persist_session()
            return
        try:
            reply = core.extract_path(parsed, chat['reply_path'])
        except core.PathError:
            reply = f'(no se encontró «{chat["reply_path"]}» en la respuesta; HTTP {status})'
        thread_warning = None
        try:
            S['thread_id'] = str(core.extract_path(parsed, chat['thread_response_path']))
            W['thread_label'].refresh()
        except core.PathError:
            # Antes se ignoraba en silencio: el hilo se quedaba vacío turno tras turno sin ninguna pista de por qué
            # (el resto del body sale bien porque no depende de esto). Ahora queda marcado junto al turno.
            thread_warning = f'No se encontró «{chat["thread_response_path"]}» en la respuesta: el hilo no avanzó, va a salir vacío en el próximo mensaje.'
        options = []
        options_path = (chat.get('options_path') or '').strip()
        if options_path:
            try:
                options = parse_option_labels(core.extract_path(parsed, options_path))
            except core.PathError:
                pass   # este turno puntual no trajo opciones en esa ruta; no es un error, el resto del turno sale bien igual
        S['messages'].append({'who': 'bot', 'text': reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False),
                               'status': status, 'thread_warning': thread_warning, 'options': options})
        S['runs'][len(S['messages']) - 1] = run_doc
        chat_view.refresh()
        debug_view.refresh()
        scroll_to_bottom()
        persist_session()

    def _build_exploration_path():
        """S['messages'] (lista plana de turnos) → la forma que espera core.save_exploration_tree: un paso por
        turno de usuario, con la opción que tomó (si el bot le había ofrecido alguna justo antes) y, de su propia
        respuesta, el texto y las opciones que ESA MISMA respuesta ofrece — para el turno siguiente, no para
        este (`options_offered` vive en el paso «padre» de la decisión, no en el elegido, para que
        core.pending_branches lo encuentre ahí)."""
        path, prev_offered = [], []
        for turn in S['messages']:
            if turn['who'] == 'user':
                path.append({'message': turn['text'], 'option': turn['text'] if turn['text'] in prev_offered else None,
                              'bot_reply': '', 'options_offered': []})
            elif turn['who'] == 'bot':
                options = turn.get('options') or []
                if path:
                    path[-1]['bot_reply'] = turn.get('text', '')
                    path[-1]['options_offered'] = options
                prev_offered = options
        return path

    def save_turn_as_case(turn_index):
        """Convierte UN intercambio (el mensaje que escribiste + lo que respondió el bot) en un caso, y lo agrega
        como paso a la suite de esta conversación — encadenado al turno guardado anterior, igual que cualquier otra
        suite. No hace falta esperar a terminar de conversar: cada intercambio se puede grabar en el momento.
        `core.save_suite` no acepta crear una suite vacía (exige al menos un caso desde el principio), así que el
        primer turno la crea con su propio paso y los siguientes la actualizan agregando el suyo."""
        turn = S['messages'][turn_index]
        if turn['who'] != 'user' or turn.get('saved'):
            return
        chat = d['chat']
        base, env = ws.build_case(d)
        project_id = resolve_project()
        env_doc = persistent_env(project_id, env)
        existing_suite = core.get('suites', S['suite_id']) if S.get('suite_id') else None
        steps = core.suite_steps(existing_suite) if existing_suite else []
        prev_alias = steps[-1]['alias'] if steps else None
        status = 200
        if turn_index + 1 < len(S['messages']) and S['messages'][turn_index + 1]['who'] == 'bot':
            status = S['messages'][turn_index + 1].get('status') or 200
        body = copy.deepcopy(base['body']) if isinstance(base['body'], dict) else {}
        core.set_path(body, chat['message_path'], turn['text'])
        core.set_path(body, chat['thread_request_path'], '')
        turn_number = sum(1 for t in S['messages'][:turn_index + 1] if t['who'] == 'user')
        item = {k: v for k, v in base.items() if k not in ('id', 'updated_at')}
        item.update({'name': f'Turno {turn_number}: {turn["text"][:40]}', 'project_id': project_id, 'environment_id': env_doc['id'], 'body': body, 'chat': None,
                     'assertions': [{'type': 'status', 'expected': status}, {'type': 'json_exists', 'path': chat['reply_path']},
                                    {'type': 'json_exists', 'path': chat['thread_response_path']}]})
        saved_case = core.save('cases', item)
        alias = f'turno{turn_number}'
        enrich = [] if prev_alias is None else [{'action': 'set', 'target': 'body', 'path': chat['thread_request_path'],
                                                  'source': {'type': 'step', 'step': prev_alias, 'path': chat['thread_response_path']}}]
        steps.append({'case_id': saved_case['id'], 'alias': alias, 'enrich': enrich})
        suite = core.save_suite((suite_name.value or 'Conversación de prueba').strip(), env_doc['id'], [s['case_id'] for s in steps], project_id,
                                id=(existing_suite['id'] if existing_suite else None), steps=steps, chat=chat)
        S['suite_id'] = suite['id']
        turn['saved'], turn['turn_number'] = True, turn_number
        persist_session()
        chat_view.refresh()
        if 'left_panel' in W:
            W['left_panel'].refresh()
        ui.notify(f'Turno {turn_number} guardado en el flujo «{suite["name"]}» ({projects_by_id.get(project_id, "")})', type='positive')
        source = d.get('source') or {}
        if source.get('type') == 'case':
            # El árbol de exploración (Fase 4) vive del lado del caso de chat, no del Flujo puntual — un mismo
            # caso puede terminar con varios Flujos (uno por rama), todos colgando del mismo árbol.
            core.save_exploration_tree(source['id'], project_id, _build_exploration_path(), suite_id=suite['id'])

    def save_all_pending(name):
        pending = [i for i, t in enumerate(S['messages']) if t['who'] == 'user' and not t.get('saved')]
        if not pending:
            raise ValueError('No hay intercambios nuevos por guardar')
        for index in pending:
            save_turn_as_case(index)

    def resolve_verdict_context():
        """Las tres fuentes de criterio para el veredicto del modelo, en orden: HU escrita a mano, Funcionalidad
        ligada, o (a falta de las dos) el nombre del caso — lo demás lo infiere el propio prompt de
        llm.judge_conversation. Devuelve (texto, de dónde salió, para mostrarlo y que no sea una caja negra)."""
        hu = (d.get('hu_text') or '').strip()
        if hu:
            return hu, 'historia de usuario / criterios escritos'
        feature_id = d.get('feature_id')
        if feature_id:
            feature = core.get('features', feature_id)
            if feature and (feature.get('description') or '').strip():
                return feature['description'].strip(), f'Funcionalidad «{feature["name"]}»'
        name = (d.get('name') or '').strip()
        return (f'Nombre del caso: {name}' if name else ''), 'inferido de la conversación (sin HU ni Funcionalidad)'

    def context_data_prompt_note():
        """Texto adicional para la instrucción de la IA con las filas de un .csv cargado «solo para esta
        exploración» (Fase 5, panel Parámetros → «Contexto adicional») — para que el modelo elija valores
        realistas al redactar un turno en vez de inventarlos. Vacío si no se cargó nada."""
        data = d.get('context_data')
        rows = (data or {}).get('rows') or []
        if not rows:
            return ''
        columns = data.get('columns') or []
        sample = rows[:10]
        lines = [' | '.join(str(row.get(c, '')) for c in columns) for row in sample]
        more = f' (y {len(rows) - len(sample)} fila(s) más)' if len(rows) > len(sample) else ''
        return (f'Datos de prueba disponibles — «{data.get("source", "")}»{more}, elegí valores realistas de '
                f'acá cuando haga falta en vez de inventarlos:\n' + ' | '.join(columns) + '\n' + '\n'.join(lines))

    def conversation_evidence_dialog():
        """Un solo lugar para la evidencia de TODA la conversación (no turno a turno): elegís qué turnos entran
        —todos, por defecto— y descargás un único HTML/PDF/Word/Markdown con la petición/respuesta de cada uno,
        igual que ya muestra «Ver detalle y evidencia» por turno. Los run_doc salen de S['runs'] (en memoria, nunca
        persistidos — igual que la evidencia de un solo turno). También se puede pedir, antes de descargar, que el
        modelo argumente si la conversación completa (S['messages']) pasa o no — el veredicto viaja con el reporte."""
        indices = sorted(S['runs'].keys())
        if not indices:
            ui.notify('Todavía no hay ningún turno con petición/respuesta para incluir', type='info')
            return
        checked = {i: True for i in indices}
        V = {'verdict': None, 'busy': False}
        context_text, context_source = resolve_verdict_context()
        with ui.dialog() as dialog, ui.card().classes('w-[640px] max-w-full'):
            ui.label('Evidencia de la conversación').classes('text-lg font-semibold')
            ui.label('Elegí qué turnos incluir en el reporte (todos, por defecto).').classes('text-sm text-gray-600')
            with ui.column().classes('w-full gap-0').style('max-height:50vh;overflow:auto'):
                for index in indices:
                    turn_run = S['runs'][index]
                    status_word = STATUS_LABEL.get(turn_run.get('status'), turn_run.get('status'))
                    label = f'{turn_run.get("case_name") or f"Turno {index}"} · {status_word}'
                    cb = ui.checkbox(label, value=True).mark(f'chat-evidence-all-cb-{index}')
                    cb.on_value_change(lambda e, i=index: checked.__setitem__(i, e.value))
            ui.separator().classes('my-1')

            async def ask_verdict():
                V['busy'] = True
                verdict_view.refresh()
                try:
                    V['verdict'] = await run.io_bound(llm.judge_conversation, S['messages'], context_text)
                except llm.LLMError as exc:
                    ui.notify(str(exc), type='negative', multi_line=True)
                finally:
                    V['busy'] = False
                    verdict_view.refresh()

            @ui.refreshable
            def verdict_view():
                ui.label(f'Criterio del veredicto: {context_source}').classes('text-xs text-gray-500')
                state = llm.status()
                if V['verdict']:
                    icon, color = ('check_circle', 'positive') if V['verdict']['pass'] else ('cancel', 'negative')
                    with ui.row().classes('items-center gap-2'):
                        ui.icon(icon, color=color)
                        ui.label('Pasa' if V['verdict']['pass'] else 'No pasa').classes('font-medium')
                    ui.label(V['verdict']['reasoning']).classes('text-sm text-gray-700').mark('chat-verdict-reasoning')
                ui.button('Pedir veredicto al modelo', icon='psychology', on_click=guard(ask_verdict)) \
                    .props('flat dense no-caps').mark('chat-ask-verdict').set_enabled(state['ready'] and not V['busy'])
                if not state['ready']:
                    ui.label(state['problem']).classes('text-xs text-gray-500')
            verdict_view()
            ui.separator().classes('my-1')

            async def download(kind):
                chosen = [S['runs'][i] for i in indices if checked[i]]
                if not chosen:
                    ui.notify('Elegí al menos un turno', type='warning')
                    return
                title = (suite_name.value or d.get('name') or 'Conversación').strip()
                data = evidence_report.build_multi_report_data(title, chosen, llm_verdict=V['verdict'])
                content, _ = await render_evidence(data, kind)
                ui.download(content, f'{title.replace(" ", "_")}.{kind}')
                ui.notify('Evidencia generada', type='positive')
                dialog.close()

            async def view_in_tab():
                chosen = [S['runs'][i] for i in indices if checked[i]]
                if not chosen:
                    ui.notify('Elegí al menos un turno', type='warning')
                    return
                title = (suite_name.value or d.get('name') or 'Conversación').strip()
                data = evidence_report.build_multi_report_data(title, chosen, llm_verdict=V['verdict'])
                html = evidence_report.render_evidence_html(data)
                view_id = core.uid()
                filename = f'{view_id}-view.html'
                (core.ARTIFACTS / filename).write_text(html, encoding='utf-8')
                open_evidence_in_new_tab(view_id, filename)
                dialog.close()

            async def save_to_folder():
                chosen = [S['runs'][i] for i in indices if checked[i]]
                if not chosen:
                    ui.notify('Elegí al menos un turno', type='warning')
                    return
                title = (suite_name.value or d.get('name') or 'Conversación').strip()
                data = evidence_report.build_multi_report_data(title, chosen, llm_verdict=V['verdict'])
                html = evidence_report.render_evidence_html(data)
                stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
                target = core.save_evidence_file(f'{title.replace(" ", "_")}-{stamp}.html', html)
                ui.notify(f'Evidencia guardada en {target}', type='positive', multi_line=True)
                dialog.close()
            with ui.row().classes('items-center gap-2 pt-2'):
                ui.label('Descargar:').classes('text-sm text-gray-600')
                ui.button('Ver en pestaña nueva', icon='open_in_new', on_click=guard(view_in_tab)).props('flat dense no-caps').mark('chat-evidence-view-tab')
                ui.button('Guardar en mi carpeta', icon='folder', on_click=guard(save_to_folder)).props('flat dense no-caps').mark('chat-evidence-save-folder')
                ui.button('HTML', icon='download', on_click=guard(lambda: download('html'))).props('flat dense no-caps').mark('chat-evidence-all-html')
                ui.button('PDF', icon='picture_as_pdf', on_click=guard(lambda: download('pdf'))).props('flat dense no-caps')
                ui.button('Word', icon='description', on_click=guard(lambda: download('docx'))).props('flat dense no-caps')
                ui.button('Markdown', icon='code', on_click=guard(lambda: download('md'))).props('flat dense no-caps')
            with ui.row().classes('justify-end w-full pt-1'):
                ui.button('Cerrar', on_click=dialog.close).props('flat')
        dialog.open()

    async def run_replay(texts, start_playing, new_thread):
        """Manda, en orden, cada texto de `texts` como si lo hubieras tipeado vos. new_thread=True arranca con el
        hilo vacío (una conversación que el bot no conoce — la forma habitual de «reproducir», para que el bot
        la reconstruya de cero); False reusa el hilo actual (el que esté en «Hilo:»), para re-verificar los mismos
        turnos SOBRE la conversación que ya tenía el bot. Reemplaza lo mostrado: bajo un hilo nuevo las respuestas
        viejas ya no son ciertas, así que no tiene sentido dejarlas al lado. start_playing=False arranca pausado
        (paso a paso); los controles (▶ ⏸ ⏭ ⏹) que aparecen mientras tanto permiten cambiar de modo o detener en
        cualquier momento, como en un reproductor."""
        if not texts:
            ui.notify('No hay turnos para reproducir', type='warning')
            return
        # Un hilo nuevo es una conversación distinta para el bot — también lo es para «guardar»: sin este reset,
        # el próximo «Guardar todo lo pendiente» intenta fusionar los turnos nuevos en el Flujo de la corrida
        # anterior y choca con un alias ya usado («turno1» repetido) apenas el número de turno vuelve a coincidir.
        S.update(messages=[], runs={}, thread_id='' if new_thread else S['thread_id'], suite_id=None if new_thread else S['suite_id'])
        W['thread_label'].refresh()
        persist_session()
        replay = {'index': 0, 'total': len(texts), 'mode': 'play' if start_playing else 'step',
                  'resume': asyncio.Event(), 'cancelled': False, 'skip_current': False}
        S['replay'] = replay
        chat_view.refresh()
        for i, text in enumerate(texts):
            replay['index'] = i + 1
            chat_view.refresh()
            scroll_to_bottom()
            if replay['mode'] != 'play':
                replay['resume'].clear()
                await replay['resume'].wait()
            if replay['cancelled']:
                break
            if replay['skip_current']:
                # El texto grabado de ESTE paso no se manda — asume que ya lo respondiste vos a mano (ver
                # replay_skip en chat_view) y sigue con el próximo texto grabado.
                replay['skip_current'] = False
                continue
            try:
                await send_chat_message(box, text)
            except Exception as exc:
                ui.notify(f'No se pudo reproducir el turno {i + 1}: {exc}', type='negative', multi_line=True)
                break
            if replay['cancelled']:
                break
            if replay['mode'] == 'play' and i + 1 < len(texts):
                await asyncio.sleep(0.6)   # ritmo visible, como ir adelantando un cassette, no instantáneo
        S['replay'] = None
        chat_view.refresh()

    def replay_dialog():
        """«Reproducir conversación»: reenvía al bot, en orden, los turnos que ya escribiste (sin volver a
        tipearlos) — útil cuando el hilo quedó viejo/vencido del lado del bot, o para retomar desde un punto
        anterior y seguir distinto a partir de ahí."""
        user_turns = [(i, t['text']) for i, t in enumerate(S['messages']) if t['who'] == 'user']
        if not user_turns:
            ui.notify('Todavía no escribiste ningún mensaje para reproducir', type='info')
            return
        with ui.dialog() as dialog, ui.card().classes('w-[480px] max-w-full'):
            ui.label('Reproducir conversación').classes('text-lg font-semibold')
            ui.label('Vuelve a mandar, en orden, lo que ya escribiste (sin tipearlo de nuevo) — reemplaza lo que '
                      'haya de acá para adelante.').classes('text-sm text-gray-600')
            options = {i: f'Turno {n + 1}: {text[:40]}' for n, (i, text) in enumerate(user_turns)}
            upto = ui.select(options, value=user_turns[-1][0], label='Reproducir hasta') \
                .props('outlined dense options-dense').classes('w-full').mark('chat-replay-upto')
            new_thread = ui.checkbox('Usar un hilo nuevo (el bot arranca de cero)', value=True).mark('chat-replay-newthread')
            step_mode = ui.checkbox('Empezar pausado (paso a paso)', value=True).mark('chat-replay-stepmode')

            async def start():
                chosen = upto.value
                texts = [text for i, text in user_turns if i <= chosen]
                start_playing, use_new_thread = not step_mode.value, new_thread.value
                dialog.close()
                await run_replay(texts, start_playing, use_new_thread)
            with ui.row().classes('justify-end gap-2 w-full pt-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat')
                ui.button('Reproducir', icon='play_circle', on_click=guard(start)).props('color=primary no-caps').mark('chat-replay-confirm')
        dialog.open()

    def _extract_texts_from_suite(suite_doc):
        """Usa el mapeo con el que se guardó el propio Flujo (independiente de qué chat esté abierto en
        pantalla); solo cae al mapeo del chat actual para Flujos guardados antes de que esto existiera."""
        chat = suite_doc.get('chat') or d.get('chat') or {}
        message_path = chat.get('message_path')
        if not message_path:
            return []
        texts = []
        for step in core.suite_steps(suite_doc):
            case = core.get('cases', step['case_id'])
            if not case:
                continue
            try:
                value = core.extract_path(case.get('body') or {}, message_path)
            except core.PathError:
                continue
            if isinstance(value, str) and value:
                texts.append(value)
        return texts

    def replay_from_suite_dialog(preselected_suite_id=None):
        """Retomar un Flujo ya guardado (del proyecto activo) como punto de partida de una conversación en vivo
        — reconstruye sus turnos mandándolos de verdad, sin tener que volver a tipear cada uno. `preselected_suite_id`:
        quien llama (p. ej. una fila del panel izquierdo, «Flujos») ya sabe cuál — se lo deja elegido de entrada,
        sin tener que volver a buscarlo en el desplegable."""
        project_id = core.get_active_project_id()
        suites = core.list_project_items('suites', project_id) if project_id else []
        if not suites:
            ui.notify('No hay Flujos guardados en el proyecto activo', type='info')
            return
        with ui.dialog() as dialog, ui.card().classes('w-[480px] max-w-full'):
            ui.label('Retomar un Flujo guardado').classes('text-lg font-semibold')
            ui.label('Reproduce en vivo, en orden, los mensajes de ese Flujo — reemplaza la conversación actual.') \
                .classes('text-sm text-gray-600')
            default_value = preselected_suite_id if any(s['id'] == preselected_suite_id for s in suites) else None
            picker = ui.select({s['id']: s['name'] for s in suites}, value=default_value, label='Flujo') \
                .props('outlined dense options-dense').classes('w-full').mark('chat-replay-suite-picker')
            new_thread = ui.checkbox('Usar un hilo nuevo (el bot arranca de cero)', value=True).mark('chat-replay-suite-newthread')
            step_mode = ui.checkbox('Empezar pausado (paso a paso)', value=True).mark('chat-replay-suite-stepmode')

            async def start():
                if not picker.value:
                    raise ValueError('Elige un Flujo')
                suite_doc = core.get('suites', picker.value)
                texts = _extract_texts_from_suite(suite_doc)
                if not texts:
                    raise ValueError('Ese Flujo no tiene turnos compatibles con su mapeo de chat (revisa «Ruta del mensaje saliente» al guardarlo)')
                if not d.get('chat') and suite_doc.get('chat'):
                    # Este chat todavía no tiene su propio mapeo guardado (p. ej. uno nuevo, sin "Guardar
                    # configuración"): toma el del Flujo que se está retomando, para poder seguir conversando
                    # en vivo después de la reproducción sin que se pierdan los mensajes silenciosamente.
                    d['chat'] = copy.deepcopy(suite_doc['chat'])
                    W['params_view'].refresh()
                start_playing, use_new_thread = not step_mode.value, new_thread.value
                dialog.close()
                await run_replay(texts, start_playing, use_new_thread)
            with ui.row().classes('justify-end gap-2 w-full pt-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat')
                ui.button('Reproducir', icon='play_circle', on_click=guard(start)).props('color=primary no-caps').mark('chat-replay-suite-confirm')
        dialog.open()

    # ------------------------------------------------------------ conversación conducida por el modelo: arranca
    # de cero (o retoma un Flujo guardado, turno a turno fijo, igual que replay_from_suite_dialog) y a partir de
    # ahí el modelo va sugiriendo cada turno de «vos» (llm.suggest_next_turn) hasta `max_turns` o hasta que el
    # propio modelo diga que ya terminó. Reusa a propósito la barra de escribir normal como mecanismo de
    # aprobación: en modo paso a paso, el turno sugerido queda precargado ahí — editable como cualquier borrador
    # — y mandarlo (Enter o el botón de enviar, sin nada nuevo que aprender) es lo que hace avanzar el bucle; no
    # hace falta un botón de «confirmar» aparte. «De corrido» manda cada turno solo, con el mismo ritmo visible
    # que ya usa «Reproducir conversación» — salvo que el bot haya ofrecido opciones y el modelo no haya elegido
    # ninguna con claridad: ahí pausa igual, para que decida una persona (nunca inventa una opción que el bot no
    # ofreció). Al cortar (por el motivo que sea), si quedaron turnos nuevos sin guardar, se ofrece guardarlos de
    # una como Flujo — así una corrida autónoma larga no se pierde por no haber tocado el botón de siempre.
    def _offered_options():
        return S['messages'][-1].get('options') or [] if S['messages'] and S['messages'][-1]['who'] == 'bot' else []

    async def run_ai_conversation(preset_texts, start_playing, new_thread, max_turns, instruction, data_goals, unattended=False):
        """`unattended=True` (ver run_tree_branches, Fase 4): sin nadie mirando, una pausa forzada por falta de
        una opción clara (ver más abajo) se trata como un motivo más para CORTAR esa rama, no para esperar para
        siempre a que alguien la apruebe."""
        # Mismo motivo que en run_replay: un hilo nuevo no debe heredar el suite_id de la corrida anterior, o el
        # guardado automático de acá choca con un alias de paso ya usado («turno1» repetido). Si NO es un hilo
        # nuevo («seguir en el hilo actual»), no se toca nada de esto — de lo contrario «seguir» se vería igual
        # que «empezar de cero», borrando de la pantalla lo que la persona ya venía conversando a mano (el Chat
        # libre con el Asistente, Fase A, arranca justo así: de corrido o paso a paso sobre la conversación tal
        # como está, no desde cero).
        if new_thread:
            S.update(messages=[], runs={}, thread_id='', suite_id=None)
        W['thread_label'].refresh()
        persist_session()
        ai_run = {'phase': 'preset' if preset_texts else 'ai', 'turn': 0, 'max_turns': max_turns,
                  'mode': 'play' if start_playing else 'step', 'cancelled': False, 'draft': None, 'stop_reason': None,
                  # Vivas, no cerradas por valor: el chat libre con el Asistente (Fase A) las edita mientras la
                  # corrida está en curso, y cada vuelta del bucle de abajo lee la versión más reciente.
                  'instruction': instruction, 'data_goals': list(data_goals or [])}
        S['ai_run'] = ai_run
        chat_view.refresh()

        async def wait_for_a_sent_turn(draft):
            """Precarga `draft` en la barra de escribir y espera a que SALGA un turno nuevo — sin importar cómo:
            Enter/enviar con el texto tal cual, editado, o incluso una opción rápida tocada en su lugar. No hace
            falta enganchar nada dentro de send_chat_message: contar S['messages'] alcanza y no acopla dos
            funciones que no necesitan saber una de la otra."""
            ai_run['draft'] = draft
            box.set_value(draft)
            chat_view.refresh()
            scroll_to_bottom()
            assistant_chat_view.refresh()   # el ícono rápido «mandar turno sugerido» del mini-chat también depende del draft
            scroll_assistant_chat_to_bottom()
            count = len(S['messages'])
            while len(S['messages']) == count and not ai_run['cancelled']:
                await asyncio.sleep(0.2)
            ai_run['draft'] = None

        for text in preset_texts:
            if ai_run['cancelled']:
                break
            if ai_run['mode'] != 'play':
                await wait_for_a_sent_turn(text)
                continue
            await send_chat_message(box, text)
            await asyncio.sleep(0.6)
        if not ai_run['cancelled']:
            ai_run['phase'] = 'ai'
            for turn_n in range(max_turns):
                if ai_run['cancelled']:
                    break
                ai_run['turn'] = turn_n + 1
                chat_view.refresh()
                # context_data_prompt_note() se recalcula en cada vuelta (no una vez al arrancar): si el chat
                # del Asistente carga un .csv nuevo a mitad de camino («solo esta exploración»), el turno
                # siguiente ya lo ve — sin esto, un dato cargado después de iniciar la corrida quedaba sin usar.
                live_instruction = '\n\n'.join(p for p in (ai_run['instruction'], context_data_prompt_note()) if p)
                try:
                    suggestion = await run.io_bound(llm.suggest_next_turn, S['messages'], live_instruction, ai_run['data_goals'])
                    if suggestion is None:
                        # run.io_bound devuelve None (no una excepción) si la llamada se canceló — mismo caso
                        # documentado en send_chat_message; reintentar en el mismo hilo es la llamada de respaldo.
                        suggestion = llm.suggest_next_turn(S['messages'], live_instruction, ai_run['data_goals'])
                except llm.LLMError as exc:
                    ai_run['stop_reason'] = f'el modelo no pudo sugerir el próximo turno: {exc}'
                    break
                if suggestion['done']:
                    collected = suggestion['collected']
                    ai_run['stop_reason'] = 'el modelo dio la conversación por terminada' + \
                        (f' — datos obtenidos: {", ".join(f"{k}={v}" for k, v in collected.items())}' if collected else '')
                    break
                draft = (suggestion['option'] or suggestion['text']).strip()
                if not draft:
                    ai_run['stop_reason'] = 'el modelo no sugirió ningún texto para este turno'
                    break
                needs_human = bool(_offered_options()) and not suggestion['option']
                if ai_run['mode'] == 'play' and not needs_human:
                    await send_chat_message(box, draft)
                    if turn_n + 1 < max_turns:
                        await asyncio.sleep(0.6)
                    continue
                if needs_human and unattended:
                    ai_run['stop_reason'] = 'el bot ofreció opciones y el modelo no eligió ninguna con claridad (corrida sin supervisión: se corta acá)'
                    break
                # No se toca ai_run['mode'] acá: si estaba «de corrido», la pausa es solo para ESTE turno
                # ambiguo — en cuanto se manda, el turno siguiente retoma «de corrido» solo (antes quedaba en
                # «paso a paso» para siempre, reportado en vivo: «funciona para un único paso, pero no para que
                # los haga todos»). Si el usuario pausa a mano mientras espera, eso sí cambia ai_run['mode'] —
                # ver ai_run_pause — y ESO se respeta.
                await wait_for_a_sent_turn(draft)
            else:
                if not ai_run['stop_reason'] and not ai_run['cancelled']:
                    ai_run['stop_reason'] = f'se alcanzó el máximo de {max_turns} turnos'
        stop_reason = ai_run['stop_reason']
        S['ai_run'] = None
        chat_view.refresh()
        assistant_chat_view.refresh()
        ui.notify('Conversación conducida por IA detenida.' if ai_run['cancelled'] else f'Conversación conducida por IA terminada: {stop_reason}',
                   type='info' if ai_run['cancelled'] else 'positive')
        pending = [i for i, t in enumerate(S['messages']) if t['who'] == 'user' and not t.get('saved')]
        if pending:
            try:
                save_all_pending(suite_name.value)
            except Exception as exc:
                ui.notify(f'No se pudo guardar el Flujo automáticamente: {exc}', type='warning')

    # ------------------------------------------------------------ árbol de exploración (Fase 4): cada vez que una
    # conversación conducida por IA (o cualquier guardado turno a turno) pasa por un punto donde el bot ofreció
    # opciones, lo que NO se tomó queda anotado — ver core.save_exploration_tree, llamado desde save_turn_as_case
    # — como rama pendiente de ese mismo árbol (uno por caso de chat, acumulado entre corridas). «Ejecutar todas
    # las ramificaciones» retoma cada una (reproduce fijo hasta el punto de bifurcación, manda la alternativa, y
    # sigue con el modelo libre) y la guarda como un Flujo propio — en cola, una por vez, nunca en paralelo.
    async def run_tree_branches(tree, max_branches, max_turns, dialog=None):
        if S['ai_run'] or S['replay']:
            raise ValueError('Ya hay una conversación en curso en esta pantalla — esperá a que termine.')
        pending = core.pending_branches(tree['root'])[:max_branches]
        if not pending:
            ui.notify('No hay ramas pendientes para ejecutar', type='info')
            return
        if dialog:
            dialog.close()
        base_name = (suite_name.value or 'Conversación de prueba').strip()
        instruction = (tree.get('instructions') or '').strip() or 'Seguí la conversación de forma razonable hacia un cierre.'
        data_goals = tree.get('data_goals') or []
        for branch_path, option in pending:
            preset_texts = [node['message'] for node in branch_path] + [option]
            suite_name.set_value(f'{base_name} — rama: {option}')
            await run_ai_conversation(preset_texts, True, True, max_turns, instruction, data_goals, unattended=True)   # new_thread=True ya resetea suite_id
        suite_name.set_value(base_name)
        ui.notify(f'Ejecutadas {len(pending)} rama(s) pendiente(s) — revisá «Flujos» en el panel izquierdo.', type='positive')

    def exploration_tree_dialog():
        source = d.get('source') or {}
        if source.get('type') != 'case':
            ui.notify('Guardá este chat como caso («Guardar configuración» en Parámetros) para tener un árbol de exploración', type='info')
            return
        project_id = core.get_active_project_id()
        tree = core.exploration_tree_for_case(source['id'], project_id) if project_id else None
        if not tree:
            ui.notify('Todavía no se guardó ningún turno desde esta conversación — no hay árbol para mostrar', type='info')
            return
        pending = core.pending_branches(tree['root'])
        with ui.dialog() as dialog, ui.card().classes('w-[640px] max-w-full'):
            ui.label('Árbol de exploración').classes('text-lg font-semibold')
            ui.label(f'{len(pending)} rama(s) sin explorar — opciones que el bot ofreció y todavía no se probaron.').classes('text-sm text-gray-600')
            with ui.column().classes('w-full gap-0 pt-2').style('max-height:45vh;overflow:auto'):
                def render(node, depth):
                    taken = {child.get('option') for child in node['children']}
                    for child in node['children']:
                        with ui.row().classes('items-center gap-1').style(f'padding-left:{depth * 18}px'):
                            ui.icon('check_circle' if child.get('suite_id') else 'forum', size='xs',
                                     color='positive' if child.get('suite_id') else None).classes('text-gray-400 shrink-0')
                            ui.label(child['message']).classes('text-sm')
                        render(child, depth + 1)
                    for option in (node.get('options_offered') or []):
                        if option not in taken:
                            with ui.row().classes('items-center gap-1').style(f'padding-left:{(depth + 1) * 18}px'):
                                ui.icon('alt_route', size='xs', color='warning')
                                ui.label(f'«{option}» — sin explorar').classes('text-sm text-amber-700')
                render(tree['root'], 0)
            ui.separator().classes('my-2')
            with ui.row().classes('items-center gap-3'):
                max_branches = ui.number('Máximo de ramas a correr ahora', value=(min(len(pending), 5) or 1), min=1, max=max(len(pending), 1)) \
                    .props('outlined dense').classes('w-56').mark('chat-tree-max-branches')
                max_turns = ui.number('Máximo de turnos por rama', value=12, min=1, max=50).props('outlined dense').classes('w-48').mark('chat-tree-max-turns')
            with ui.row().classes('justify-end gap-2 w-full pt-2'):
                ui.button('Cerrar', on_click=dialog.close).props('flat').mark('chat-tree-close')
                ui.button('Ejecutar todas las ramificaciones', icon='alt_route',
                          on_click=guard(lambda: run_tree_branches(tree, int(max_branches.value), int(max_turns.value), dialog))) \
                    .props('color=primary no-caps').mark('chat-tree-run-all').set_enabled(bool(pending) and llm.status()['ready'])
        dialog.open()

    def ai_conversation_dialog():
        project_id = core.get_active_project_id()
        suites = core.list_project_items('suites', project_id) if project_id else []
        state = llm.status()
        with ui.dialog() as dialog, ui.card().classes('w-[560px] max-w-full'):
            ui.label('Conversación conducida por IA').classes('text-lg font-semibold')
            ui.label('El modelo escribe cada turno de «vos» siguiendo el objetivo que le des — revisalo paso a '
                      'paso o dejalo correr de corrido.').classes('text-sm text-gray-600')
            if not state['ready']:
                ui.label(state['problem']).classes('text-xs text-gray-500')
            instruction = ui.textarea('Instrucción inicial (objetivo, qué probar, opciones preferidas en ciertos puntos…)',
                                       value=ASSISTANT_CHAT['pending_instruction']) \
                .props('outlined dense').classes('w-full').mark('chat-ai-run-instruction')
            data_goals_input = ui.textarea('Objetivo de datos a obtener (opcional, uno por línea — p. ej. «id del lead»)') \
                .props('outlined dense').classes('w-full').mark('chat-ai-run-data-goals')
            resume_picker = ui.select({'': '— Empezar de cero —', **{s['id']: s['name'] for s in suites}}, value='', label='Retomar un Flujo guardado (opcional)') \
                .props('outlined dense options-dense').classes('w-full').mark('chat-ai-run-resume-picker')
            max_turns = ui.number('Máximo de turnos a generar', value=12, min=1, max=50).props('outlined dense').classes('w-56').mark('chat-ai-run-max-turns')
            new_thread = ui.checkbox('Usar un hilo nuevo (el bot arranca de cero)', value=True).mark('chat-ai-run-newthread')
            step_mode = ui.checkbox('Empezar pausado (revisar cada turno antes de mandarlo)', value=True).mark('chat-ai-run-stepmode')

            async def start():
                if not instruction.value.strip():
                    raise ValueError('Escribí una instrucción inicial (el objetivo de la conversación)')
                if not llm.status()['ready']:
                    raise ValueError('El asistente de IA no está configurado — revisá Modelos de IA')
                preset_texts = []
                if resume_picker.value:
                    suite_doc = core.get('suites', resume_picker.value)
                    preset_texts = _extract_texts_from_suite(suite_doc)
                    if not d.get('chat') and suite_doc.get('chat'):
                        d['chat'] = copy.deepcopy(suite_doc['chat'])
                        W['params_view'].refresh()
                elif not d.get('chat'):
                    raise ValueError('Completa el mapeo del chat en «Parámetros» antes de arrancar de cero')
                data_goals = [line.strip() for line in (data_goals_input.value or '').splitlines() if line.strip()]
                start_playing, use_new_thread = not step_mode.value, new_thread.value
                ASSISTANT_CHAT['pending_instruction'] = ''   # ya se consumió acá — no hace falta que siga precargando el próximo diálogo
                dialog.close()
                await run_ai_conversation(preset_texts, start_playing, use_new_thread, int(max_turns.value or 1), instruction.value.strip(), data_goals)
            with ui.row().classes('justify-end gap-2 w-full pt-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat')
                ui.button('Iniciar', icon='smart_toy', on_click=guard(start)).props('color=primary no-caps').mark('chat-ai-run-confirm').set_enabled(state['ready'])
        dialog.open()

    # ------------------------------------------------------------ asistente de IA (panel derecho): veredicto
    # sobre la conversación tal como está AHORA (no hace falta terminarla ni abrir «Evidencia de la conversación»
    # primero) y análisis de lo recorrido hasta acá — ambos a demanda, nunca automáticos. Estado propio (AI),
    # independiente del de la Fase 1 dentro del diálogo de evidencia: pedirlo desde un lado no completa el otro,
    # a propósito — son dos accesos al mismo mecanismo, no un único resultado compartido.
    AI = {'verdict': None, 'busy': False}

    async def ask_ai_verdict(mode):
        AI['busy'] = True
        ai_verdict_view.refresh()
        try:
            context_text, _ = resolve_verdict_context()
            AI['verdict'] = await run.io_bound(llm.judge_conversation, S['messages'], context_text, mode)
        except llm.LLMError as exc:
            ui.notify(str(exc), type='negative', multi_line=True)
        finally:
            AI['busy'] = False
            ai_verdict_view.refresh()

    @ui.refreshable
    def ai_verdict_view():
        context_text, context_source = resolve_verdict_context()
        ui.label(f'Criterio en uso: {context_source}').classes('text-xs text-gray-500').mark('chat-ai-context-source')
        state = llm.status()
        if not state['ready']:
            ui.label(state['problem']).classes('text-xs text-gray-500')
        if not S['messages']:
            ui.label('Todavía no hay conversación para evaluar.').classes('text-xs text-gray-500')
        with ui.row().classes('gap-2'):
            ui.button('Pedir veredicto', icon='psychology', on_click=guard(lambda: ask_ai_verdict('final'))) \
                .props('outline dense no-caps').mark('chat-ai-ask-verdict') \
                .set_enabled(state['ready'] and not AI['busy'] and bool(S['messages']))
            ui.button('Analizar hasta acá', icon='travel_explore', on_click=guard(lambda: ask_ai_verdict('ongoing'))) \
                .props('outline dense no-caps').mark('chat-ai-ask-ongoing') \
                .set_enabled(state['ready'] and not AI['busy'] and bool(S['messages'])) \
                .tooltip('Revisa lo recorrido hasta ahora — no es un cierre definitivo, es para ir viendo si va bien encaminada')
        if AI['verdict']:
            icon, color = ('check_circle', 'positive') if AI['verdict']['pass'] else ('cancel', 'negative')
            with ui.row().classes('items-center gap-2 pt-1'):
                ui.icon(icon, color=color)
                ui.label('Pasa' if AI['verdict']['pass'] else 'No pasa').classes('font-medium')
            ui.label(AI['verdict']['reasoning']).classes('text-sm text-gray-700').mark('chat-ai-verdict-reasoning')

    # ------------------------------------------------------------ chat libre con el Asistente de IA: charla DE
    # VERDAD con el modelo (llm.assistant_reply), no una respuesta fija por palabra clave — puede responder
    # preguntas, anotar algo para después, o directamente seguir la conversación actual con el bot (un turno
    # puntual para revisar, o varios de corrido si se lo pedís así). Mini-hilo propio (ASSISTANT_CHAT), separado
    # de S['messages'] (esa es la charla CON EL BOT, no con el Asistente) — nunca persistido. Reconoce una orden
    # de captura/video por palabra clave antes de llamar al modelo, sin gastar una llamada solo para clasificar
    # eso — barato y determinístico (sigue sin acción real detrás: ver BACKLOG.md, Fase D).
    ASSISTANT_CHAT = {'messages': [], 'pending_instruction': ''}
    CAPTURE_KEYWORDS = ('captura', 'screenshot')
    VIDEO_KEYWORDS = ('video', 'grabar', 'grabación', 'grabacion')
    ASSISTANT_CHAT_MAX_TURNS = 12

    def scroll_assistant_chat_to_bottom():
        """Mismo truco que scroll_to_bottom() (más arriba) pero apuntado al scroll PROPIO del mini-chat, no al
        del panel entero — sin esto, cada mensaje nuevo queda fuera de la vista y hay que bajar a mano."""
        try:
            ui.run_javascript('const el = document.querySelector(".assistant-chat-scroll"); '
                               'if (el) el.scrollTo({top: el.scrollHeight, behavior: "smooth"})')
        except RuntimeError:
            pass

    def _assistant_say(reply):
        ASSISTANT_CHAT['messages'].append({'who': 'assistant', 'text': reply})
        assistant_chat_view.refresh()
        scroll_assistant_chat_to_bottom()

    async def handle_assistant_message(text):
        text = (text or '').strip()
        if not text:
            return
        ASSISTANT_CHAT['messages'].append({'who': 'user', 'text': text})
        assistant_chat_view.refresh()
        scroll_assistant_chat_to_bottom()
        lowered = text.lower()
        if any(k in lowered for k in CAPTURE_KEYWORDS):
            _assistant_say('Las capturas por instrucción todavía no están disponibles acá — van en una fase siguiente.')
            return
        if any(k in lowered for k in VIDEO_KEYWORDS):
            _assistant_say('Grabar video por instrucción todavía no está disponible acá — va en una fase siguiente.')
            return
        state = llm.status()
        if not state['ready']:
            _assistant_say(f'No puedo responder todavía: {state["problem"]}')
            return
        history = ASSISTANT_CHAT['messages'][:-1]   # sin el mensaje que se acaba de sumar, va aparte como `text`
        try:
            result = await run.io_bound(llm.assistant_reply, S['messages'], history, text, bool(S['ai_run']))
            if result is None:   # cancelada (ver send_chat_message) — reintentar en el mismo hilo de respaldo
                result = llm.assistant_reply(S['messages'], history, text, bool(S['ai_run']))
        except llm.LLMError as exc:
            _assistant_say(f'No pude responder: {exc}')
            return
        _assistant_say(result['reply'])
        instruction = result['instruction'].strip()
        action = result['action']
        if action == 'continue' and (S['ai_run'] or S['replay']):
            action = 'note'   # ya hay algo corriendo acá mismo — no se puede arrancar otra cosa encima
        if S['ai_run']:
            if instruction:
                S['ai_run']['instruction'] = (S['ai_run']['instruction'] + '\n\n' + instruction).strip()
            if action == 'continue' and result['autopilot'] and S['ai_run']['mode'] != 'play':
                S['ai_run']['mode'] = 'play'
                if S['ai_run']['draft']:
                    await send_chat_message(box)
        elif action == 'continue':
            if not d.get('chat'):
                _assistant_say('Para eso primero hace falta completar el mapeo del chat en «Parámetros».')
            else:
                await run_ai_conversation([], result['autopilot'], False, ASSISTANT_CHAT_MAX_TURNS, instruction or text, [])
        elif instruction:
            ASSISTANT_CHAT['pending_instruction'] = (ASSISTANT_CHAT['pending_instruction'] + '\n\n' + instruction).strip()

    @ui.refreshable
    def assistant_chat_view():
        if ASSISTANT_CHAT['messages']:
            with ui.column().classes('w-full gap-1 grow assistant-chat-scroll').style('overflow-y:auto;overflow-x:hidden;min-height:0'):
                for turn in ASSISTANT_CHAT['messages']:
                    ui.chat_message(turn['text'], sent=(turn['who'] == 'user'), name='Vos' if turn['who'] == 'user' else 'Asistente') \
                        .classes('text-sm w-full').style('max-width:100%;overflow-wrap:break-word')
        else:
            ui.label('Escribile algo al Asistente — pregunta, instrucción, o pedile que siga la conversación.') \
                .classes('text-xs text-gray-400 grow')
        if S['ai_run'] and S['ai_run']['draft']:
            with ui.row().classes('items-center gap-1'):
                ui.label('Turno sugerido esperando —').classes('text-xs text-gray-500')
                ui.button(icon='send', on_click=guard(lambda: send_chat_message(box))) \
                    .props('flat dense round size=sm color=primary').mark('chat-assistant-send-draft') \
                    .tooltip('Mandar ya el turno sugerido (podés editarlo antes, abajo en la conversación)')
        with ui.row().classes('w-full items-center gap-1 no-wrap'):
            assistant_input = ui.input(placeholder='Decile algo al Asistente (pregunta, instrucción, «seguí vos»…)') \
                .props('outlined dense').classes('grow').mark('chat-assistant-input')
            assistant_input.on('keydown.enter', guard(lambda: handle_assistant_message(assistant_input.value)))
            ui.button(icon='send', on_click=guard(lambda: handle_assistant_message(assistant_input.value))) \
                .props('flat dense round color=primary').mark('chat-assistant-send')

        async def on_assistant_upload(event):
            try:
                raw = await read_upload(event)
                apply_context_file(event.file.name, raw)
            except ValueError as exc:
                ui.notify(str(exc), type='negative', multi_line=True)
        ui.upload(label='Subir archivo (.md/.txt/.csv)', on_upload=on_assistant_upload, auto_upload=True,
                  max_file_size=core.MAX_DATASET_BYTES).props('accept=.md,.txt,.csv flat bordered dense').classes('w-full').mark('chat-assistant-upload')

    def section_header(title, info, marker=None):
        """Título + un ícono «i» con la explicación larga como tooltip (al pasar el mouse) — en vez de un
        párrafo fijo debajo de cada título, que en un panel angosto consume mucho alto todo el tiempo."""
        with ui.row().classes('items-center gap-1'):
            ui.label(title).classes('font-medium text-sm')
            icon = ui.icon('info', size='xs', color='grey').classes('cursor-help').tooltip(info)
            if marker:
                icon.mark(marker)

    def ai_tab():
        with ui.column().classes('w-full gap-2 p-3'):
            section_header('Asistente de IA', 'Evalúa la conversación contra el criterio configurado en «Parámetros» — '
                            'a demanda, nunca automático después de cada turno.')
            ai_verdict_view()
            ui.separator().classes('my-1')
            section_header('Conversación conducida por IA', 'El modelo escribe cada turno de «vos» siguiendo un '
                            'objetivo que le des — paso a paso (editable antes de mandarlo) o de corrido.')
            ui.button('Iniciar conversación conducida por IA', icon='smart_toy', on_click=guard(lambda: ai_conversation_dialog())) \
                .props('outline dense no-caps').mark('chat-ai-tab-run-open').set_enabled(llm.status()['ready'])
            ui.separator().classes('my-1')
            section_header('Árbol de exploración', 'Las opciones que el bot ofreció y no se tomaron en ninguna '
                            'corrida guardada desde acá — para correrlas todas después, una por una.')
            ui.button('Ver árbol de exploración', icon='alt_route', on_click=guard(lambda: exploration_tree_dialog())) \
                .props('outline dense no-caps').mark('chat-tree-open')

    def assistant_chat_tab():
        with ui.column().classes('w-full gap-2 p-3 h-full'):
            section_header('Hablale al Asistente',
                            'Charla libre con el Asistente — responde preguntas, anota instrucciones o datos para '
                            'después, y puede seguir él mismo la conversación actual con el bot si se lo pedís '
                            '(un turno puntual para revisar, o varios de corrido). También podés subir un archivo '
                            'de contexto en cualquier momento, incluso con una Conversación conducida por IA ya en curso.',
                            marker='chat-assistant-info')
            assistant_chat_view()

    # ------------------------------------------------------------ panel izquierdo: conversaciones y Flujos
    # guardados en el proyecto activo — mismo patrón de pestañas que ya usa workspace_page.py, pero sin
    # «Historial»: el Chat no persiste turno a turno a propósito (para poder explorar sin quedar registrado),
    # así que acá no hay un equivalente real a eso.
    @ui.refreshable
    def left_panel():
        with ui.tabs().props('dense align=justify').classes('w-full') as left_tabs:
            t_conv = ui.tab('Conversaciones', icon='forum')
            t_flows = ui.tab('Flujos', icon='playlist_play')
        with ui.tab_panels(left_tabs, value=t_conv).classes('w-full'):
            with ui.tab_panel(t_conv).classes('p-2 gap-0'):
                project_id = core.get_active_project_id()
                cases = sorted((c for c in core.list_project_items('cases', project_id) if c.get('chat')) if project_id else [],
                                key=lambda c: (c.get('name') or '').lower())
                if not cases:
                    ui.label('No hay conversaciones guardadas en este proyecto.').classes('text-xs text-gray-500')
                for case in cases:
                    with ui.row().classes('w-full items-center gap-1 cursor-pointer hover:bg-gray-100 rounded px-1 py-1 no-wrap') \
                            .on('click', lambda _, c=case: load_case(c)).mark(f'chat-left-case-{case["id"]}'):
                        ui.icon('forum', size='xs').classes('text-gray-400 shrink-0')
                        ui.label(case['name']).classes('text-sm truncate')
            with ui.tab_panel(t_flows).classes('p-2 gap-0'):
                project_id = core.get_active_project_id()
                # Solo Flujos con mapeo propio (ver «Retomar un Flujo guardado»): los que no lo tienen son suites
                # de API comunes, no algo que haya salido de una conversación — listarlos acá confundiría.
                suites = sorted((s for s in core.list_project_items('suites', project_id) if s.get('chat')) if project_id else [],
                                 key=lambda s: (s.get('name') or '').lower())
                if not suites:
                    ui.label('No hay Flujos guardados desde una conversación en este proyecto.').classes('text-xs text-gray-500')
                for suite in suites:
                    with ui.row().classes('w-full items-center gap-1 cursor-pointer hover:bg-gray-100 rounded px-1 py-1 no-wrap') \
                            .on('click', lambda _, s=suite: replay_from_suite_dialog(s['id'])).mark(f'chat-left-flow-{suite["id"]}'):
                        ui.icon('playlist_play', size='xs').classes('text-gray-400 shrink-0')
                        ui.label(suite['name']).classes('text-sm truncate')
    W['left_panel'] = left_panel

    # ------------------------------------------------------------ panel central: todo lo que antes ocupaba toda
    # la pantalla — selector de caso/plantilla, ambiente/método/URL, hilo, conversación y barra de escribir.
    def center_panel():
        with ui.row().classes('w-full items-center gap-2 no-wrap px-3 pt-2'):
            ui.icon('forum', color='primary', size='sm')
            ui.input(placeholder='Nombre de este chat').props('borderless dense').classes('text-lg font-medium grow').bind_value(d, 'name')

            @ui.refreshable
            def template_picker():
                project_id = core.get_active_project_id()
                templates = [c for c in core.list_project_items('cases', project_id) if c.get('chat_template')] if project_id else []
                options = {'': 'Elegir plantilla…', **{c['id']: c['name'] for c in templates}}
                ui.select(options, value='', label='Plantilla', on_change=lambda e: start_from_template(core.get('cases', e.value)) if e.value else None) \
                    .props('outlined dense options-dense').classes('w-48').mark('chat-template-picker') \
                    .tooltip('Endpoint configurado una vez (URL, headers, body, mapeo) para arrancar conversaciones nuevas sin recargarlo cada vez')
            W['template_picker'] = template_picker
            template_picker()

            @ui.refreshable
            def case_picker():
                project_id = core.get_active_project_id()
                # Solo casos con mapeo de chat configurado: los «Turno N: …» que genera cada suite al guardar una
                # conversación son casos API comunes (chat=None, un paso suelto dentro del flujo) y no se pueden
                # retomar como chat — listarlos acá solo confundía (el chat quedaba en blanco al elegir uno).
                cases = [c for c in core.list_project_items('cases', project_id) if c.get('chat')] if project_id else []
                options = {'': 'Caso nuevo (sin guardar)', **{c['id']: c['name'] for c in cases}}
                ui.select(options, value='', label='Retomar conversación', on_change=lambda e: load_case(core.get('cases', e.value)) if e.value else None) \
                    .props('outlined dense options-dense').classes('w-56').tooltip('Continúa una conversación guardada exactamente donde quedó')
            W['case_picker'] = case_picker
            case_picker()
            ui.button(icon='note_add', on_click=guard(new_chat)).props('flat round dense').tooltip('Nuevo chat en blanco (otro endpoint)')
        with ui.row().classes('w-full items-center gap-2 no-wrap px-3'):
            ui.select({'': 'URL completa', **{e['id']: f'{projects_by_id.get(e.get("project_id"), "sin proyecto")} · {e["name"]}' for e in all_envs}}, label='Ambiente') \
                .props('outlined dense options-dense').classes('w-48').bind_value(d, 'env_id')
            ui.select(HTTP_METHODS, label='Método').props('outlined dense').classes('w-24').bind_value(d, 'method').mark('chat-method')
            scheme = ui.select(['https', 'http'], label='Proto.').props('outlined dense').classes('w-20').bind_value(d, 'scheme')
            scheme.bind_visibility_from(d, 'env_id', backward=lambda v: not v)
            ui.input(placeholder='ejemplo.com/api/chat/messages').props('outlined dense').classes('grow').bind_value(d, 'url').mark('chat-url')
        with ui.row().classes('items-center gap-2 w-full px-3 pt-1 no-wrap'):
            ui.label('Hilo:').classes('text-xs text-gray-500')

            @ui.refreshable
            def thread_label():
                ui.input(placeholder='(nuevo)', value=S['thread_id']).props('outlined dense').classes('w-56 font-mono text-xs') \
                    .on_value_change(lambda e: S.__setitem__('thread_id', (e.value or '').strip())).mark('chat-thread-id') \
                    .tooltip('Editalo para continuar un hilo puntual o forzar uno nuevo antes de enviar')
            W['thread_label'] = thread_label
            thread_label()
            ui.space()

            def reset_conversation():
                S.update(messages=[], thread_id='', last_request=None, last_response=None, suite_id=None, runs={})
                persist_session()
                refresh_all()
            ui.button('Reiniciar conversación', icon='restart_alt', on_click=guard(reset_conversation)) \
                .props('flat dense size=sm no-caps').tooltip('Borra los mensajes y el hilo; conserva la configuración')
        with ui.row().classes('items-center gap-2 w-full px-3 pb-1 no-wrap'):
            suite_name = ui.input('Nombre del flujo', value='Conversación de prueba').props('outlined dense').classes('w-56').mark('chat-suite-name')
            top_actions()
            ui.label('Guardá cada intercambio por separado con el botón que aparece debajo de cada respuesta.').classes('text-xs text-gray-500')
        chat_view()
        debug_view()
        with ui.row().classes('items-center gap-1 w-full px-3 py-2 no-wrap bg-white').style('position:sticky;bottom:0;border-top:1px solid #e5e7eb'):
            bottom_actions()
            box = ui.input(placeholder='Escribe un mensaje…').props('outlined dense').classes('grow').mark('chat-input')
            box.on('keydown.enter', lambda: send_chat_message(box))
            ui.button(icon='send', on_click=guard(lambda: send_chat_message(box))).props('dense round color=primary').classes('shrink-0').mark('chat-send')
        return suite_name, box

    # ------------------------------------------------------------ panel derecho: parámetros + asistente de IA,
    # como una carrilera vertical de pestañas — mismo patrón que la columna derecha de workspace_page.py.
    def right_panel():
        with ui.row().classes('w-full h-full no-wrap gap-0'):
            with ui.tab_panels(None, value='Params').props('vertical').style('flex:1 1 0;min-width:0;overflow:auto;height:100%') as panels:
                with ui.tab_panel('Params').classes('p-0'):
                    params_view()
                with ui.tab_panel('Asistente').classes('p-0'):
                    ai_tab()
                with ui.tab_panel('ChatAsistente').classes('p-0 h-full'):
                    assistant_chat_tab()
            with ui.tabs().props('vertical dense no-caps').classes('shrink-0').style('width:56px;border-left:1px solid #e5e7eb') as rail:
                ui.tab('Params', label='', icon='tune').tooltip('Parámetros').mark('chat-rail-Params')
                ui.tab('Asistente', label='', icon='smart_toy').tooltip('Asistente de IA').mark('chat-rail-Asistente')
                ui.tab('ChatAsistente', label='', icon='forum').tooltip('Hablale al Asistente').mark('chat-rail-ChatAsistente')
            panels.bind_value_from(rail, 'value')
            rail.set_value('Params')

    # ------------------------------------------------------------ layout: tres paneles, mismo patrón que
    # workspace_page.py (splitter anidado, cada panel con la clase `.ltw-pane` para scrollear por su cuenta).
    with ui.element('div').classes('w-full').style('height: calc(100vh - 50px)'):
        with ui.splitter(value=18, limits=(12, 35)).classes('w-full').style('height:100%') as outer:
            with outer.before:
                with ui.element('div').classes('ltw-pane'):
                    left_panel()
            with outer.after:
                with ui.splitter(value=72, limits=(35, 90)).classes('w-full').style('height:100%') as inner:
                    with inner.before:
                        with ui.element('div').classes('ltw-pane').style('display:flex;flex-direction:column'):
                            suite_name, box = center_panel()
                    with inner.after:
                        with ui.element('div').classes('ltw-pane'):
                            right_panel()
