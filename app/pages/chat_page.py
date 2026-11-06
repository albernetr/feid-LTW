"""Chat: conversar en vivo con un chatbot/API conversacional, un mensaje a la vez — en vez de armar los turnos de
antemano como una suite. Pantalla propia (no una pestaña más del Espacio de trabajo) para que el área central sea
la conversación: URL arriba, parámetros en un panel, petición/respuesta cruda en otro, y la barra de escribir abajo
(fija al fondo con position:sticky, para no depender de calcular la altura exacta del encabezado)."""
import asyncio
import copy
import json
from nicegui import ui, run
from .. import core, workspace as ws, evidence_report
from .common import frame, guard, protected_page, show_run, render_evidence, STATUS_LABEL
from .widgets import kv_rows, dynamic_variable_chips

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
    S = {'messages': [], 'thread_id': '', 'last_request': None, 'last_response': None, 'suite_id': None, 'runs': {}, 'replay': None}
    # S['runs']: índice de turno -> run_doc completo (petición/respuesta/aserciones), para «Ver detalle y evidencia».
    # Solo en memoria — nunca entra a persist_session(), que guarda S['messages'] tal cual: una transcripción larga
    # con el run_doc completo de cada turno (cuerpos de petición/respuesta incluidos) infla el caso guardado.
    # S['replay']: None o un dict en curso {'index', 'total', 'mode': 'play'|'step', 'resume': asyncio.Event,
    # 'cancelled'} mientras «Reproducir conversación» va mandando turnos ya escritos (o los de un Flujo guardado)
    # contra el bot, uno por uno, con controles de reproducir/pausar/paso/detener — nunca se persiste.
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
        for name in ('params_view', 'chat_view', 'debug_view', 'case_picker', 'template_picker', 'thread_label'):
            if name in W:
                W[name].refresh()

    if preset_case_id:
        existing = core.get('cases', preset_case_id)
        if existing:
            load_case(existing)

    # ------------------------------------------------------------ top bar
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
        ui.select(HTTP_METHODS, label='Método').props('outlined dense').classes('w-24').bind_value(d, 'method')
        scheme = ui.select(['https', 'http'], label='Proto.').props('outlined dense').classes('w-20').bind_value(d, 'scheme')
        scheme.bind_visibility_from(d, 'env_id', backward=lambda v: not v)
        ui.input(placeholder='ejemplo.com/api/chat/messages').props('outlined dense').classes('grow').bind_value(d, 'url').mark('chat-url')

    # ------------------------------------------------------------ parameters (headers + chat mapping)
    @ui.refreshable
    def params_view():
        with ui.expansion('Parámetros', icon='tune', value=not d.get('chat')).classes('w-full mx-3').style('width:calc(100% - 24px)'):
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
                project_id = resolve_project()
                base, env = ws.build_case(d)
                env_doc = persistent_env(project_id, env)
                source = d.get('source') or {}
                existing = core.get('cases', source['id']) if source.get('type') == 'case' else None
                item = {k: v for k, v in base.items() if k not in ('id', 'updated_at')}
                item.update({'project_id': project_id, 'environment_id': env_doc['id'], 'chat_template': True})
                if existing is not None:
                    item['id'] = existing['id']
                    item['chat_session'] = existing.get('chat_session')
                saved = core.save('cases', item)
                d['source'] = {'type': 'case', 'id': saved['id'], 'updated_at': saved.get('updated_at')}
                sync_url()
                ui.notify(f'Plantilla «{saved["name"]}» guardada: la vas a encontrar en «Plantilla» la próxima vez', type='positive')
                W['params_view'].refresh()
                W['template_picker'].refresh()
                chat_view.refresh()
            ui.button('Guardar configuración', icon='check', on_click=guard(activate)).props('color=primary dense no-caps').mark('chat-activate')
    W['params_view'] = params_view
    params_view()

    # ------------------------------------------------------------ conversation-level actions (no de un turno
    # puntual): guardar lo pendiente como Flujo, evidencia conjunta, reproducir. Se repiten arriba (junto al
    # hilo) y abajo (pegadas a la barra de escribir) — antes vivían en una sola fila a mitad de pantalla, que se
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
        suite_name = ui.input('Nombre del flujo', value='Conversación de prueba').props('outlined dense').classes('w-56')
        top_actions()
        ui.label('Guardá cada intercambio por separado con el botón que aparece debajo de cada respuesta.').classes('text-xs text-gray-500')

    @ui.refreshable
    def chat_view():
        if not S['messages'] and not S['replay']:
            # Si hay una reproducción en curso, S['messages'] arranca vacío a propósito (ver run_replay) pero la
            # barra de control (▶ ⏸ ⏭ ⏹, más abajo) tiene que pintarse igual — si no, «paso a paso» queda
            # esperando un clic en un control que nunca aparece.
            with ui.column().classes('w-full items-center justify-center').style('min-height:240px'):
                ui.label('Completa el mapeo en «Parámetros» y guardalo para empezar a conversar.' if not d.get('chat')
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
    chat_view()

    # ------------------------------------------------------------ last turn, raw (debugging)
    @ui.refreshable
    def debug_view():
        with ui.expansion('Petición / Respuesta (último turno)', icon='code').classes('w-full mx-3').style('width:calc(100% - 24px)'):
            if not S['last_request']:
                ui.label('Aún no enviaste ningún mensaje.').classes('text-xs text-gray-500')
            else:
                ui.label('Enviado').classes('text-xs font-semibold text-gray-500')
                ui.code(json.dumps(S['last_request'], indent=2, ensure_ascii=False), language='json').classes('w-full').style('max-height:160px;overflow:auto')
                ui.label('Recibido').classes('text-xs font-semibold text-gray-500')
                ui.code(S['last_response'] or '', language='json').classes('w-full').style('max-height:160px;overflow:auto')
    W['debug_view'] = debug_view
    debug_view()

    # ------------------------------------------------------------ write & send bar — sticky, always reachable regardless of
    # how tall the content above is (no hardcoded viewport-minus-header math, which broke once against the real header height).
    # Las acciones de la conversación (bottom_actions) van en esta misma fila, al nivel de la barra de envío —
    # su duplicado de arriba (top_actions) queda fuera de vista apenas se scrollea una conversación larga.
    with ui.row().classes('items-center gap-1 w-full px-3 py-2 no-wrap bg-white').style('position:sticky;bottom:0;border-top:1px solid #e5e7eb'):
        bottom_actions()
        box = ui.input(placeholder='Escribe un mensaje…').props('outlined dense').classes('grow').mark('chat-input')
        box.on('keydown.enter', lambda: send_chat_message(box))
        ui.button(icon='send', on_click=guard(lambda: send_chat_message(box))).props('dense round color=primary').classes('shrink-0').mark('chat-send')

    def scroll_to_bottom():
        """Sigue la conversación a medida que se arman los turnos — sin esto, en una conversación larga (o al
        reproducir paso a paso) cada mensaje nuevo o cada pausa del reproductor aparece fuera de la pantalla.
        Envuelto en try/except: `ui.run_javascript` resuelve el slot/cliente «actual» a partir de dónde se llamó
        — cuando quien llama es un botón de opción rápida (vive DENTRO del `chat_view` refrescable) y ese mismo
        turno acaba de refrescar `chat_view` (unas líneas antes, en este mismo handler), ese slot ya no existe
        y NiceGUI tira RuntimeError. No vale la pena que una falla al hacer scroll tire abajo el turno entero."""
        try:
            ui.run_javascript('window.scrollTo({top: document.body.scrollHeight, behavior: "smooth"})')
        except RuntimeError:
            pass

    async def send_chat_message(box, preset_text=None):
        """preset_text: lo manda tal cual sin tocar la caja de texto — así un botón de opción rápida (ver
        `turn.get('options')` en chat_view) envía su texto como si lo hubieras tipeado vos."""
        text = (preset_text if preset_text is not None else (box.value or '')).strip()
        chat = d.get('chat')
        if not text or not chat:
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
                                id=(existing_suite['id'] if existing_suite else None), steps=steps)
        S['suite_id'] = suite['id']
        turn['saved'], turn['turn_number'] = True, turn_number
        persist_session()
        chat_view.refresh()
        ui.notify(f'Turno {turn_number} guardado en el flujo «{suite["name"]}» ({projects_by_id.get(project_id, "")})', type='positive')

    def save_all_pending(name):
        pending = [i for i, t in enumerate(S['messages']) if t['who'] == 'user' and not t.get('saved')]
        if not pending:
            raise ValueError('No hay intercambios nuevos por guardar')
        for index in pending:
            save_turn_as_case(index)

    def conversation_evidence_dialog():
        """Un solo lugar para la evidencia de TODA la conversación (no turno a turno): elegís qué turnos entran
        —todos, por defecto— y descargás un único HTML/PDF/Word/Markdown con la petición/respuesta de cada uno,
        igual que ya muestra «Ver detalle y evidencia» por turno. Los run_doc salen de S['runs'] (en memoria, nunca
        persistidos — igual que la evidencia de un solo turno)."""
        indices = sorted(S['runs'].keys())
        if not indices:
            ui.notify('Todavía no hay ningún turno con petición/respuesta para incluir', type='info')
            return
        checked = {i: True for i in indices}
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
            async def download(kind):
                chosen = [S['runs'][i] for i in indices if checked[i]]
                if not chosen:
                    ui.notify('Elegí al menos un turno', type='warning')
                    return
                title = (suite_name.value or d.get('name') or 'Conversación').strip()
                data = evidence_report.build_multi_report_data(title, chosen)
                content, _ = await render_evidence(data, kind)
                ui.download(content, f'{title.replace(" ", "_")}.{kind}')
                ui.notify('Evidencia generada', type='positive')
                dialog.close()
            with ui.row().classes('items-center gap-2 pt-2'):
                ui.label('Descargar:').classes('text-sm text-gray-600')
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
        S.update(messages=[], runs={}, thread_id='' if new_thread else S['thread_id'])
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
        message_path = (d.get('chat') or {}).get('message_path')
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

    def replay_from_suite_dialog():
        """Retomar un Flujo ya guardado (del proyecto activo) como punto de partida de una conversación en vivo
        — reconstruye sus turnos mandándolos de verdad, sin tener que volver a tipear cada uno."""
        project_id = core.get_active_project_id()
        suites = core.list_project_items('suites', project_id) if project_id else []
        if not suites:
            ui.notify('No hay Flujos guardados en el proyecto activo', type='info')
            return
        with ui.dialog() as dialog, ui.card().classes('w-[480px] max-w-full'):
            ui.label('Retomar un Flujo guardado').classes('text-lg font-semibold')
            ui.label('Reproduce en vivo, en orden, los mensajes de ese Flujo — reemplaza la conversación actual.') \
                .classes('text-sm text-gray-600')
            picker = ui.select({s['id']: s['name'] for s in suites}, label='Flujo') \
                .props('outlined dense options-dense').classes('w-full').mark('chat-replay-suite-picker')
            new_thread = ui.checkbox('Usar un hilo nuevo (el bot arranca de cero)', value=True).mark('chat-replay-suite-newthread')
            step_mode = ui.checkbox('Empezar pausado (paso a paso)', value=True).mark('chat-replay-suite-stepmode')

            async def start():
                if not picker.value:
                    raise ValueError('Elige un Flujo')
                suite_doc = core.get('suites', picker.value)
                texts = _extract_texts_from_suite(suite_doc)
                if not texts:
                    raise ValueError('Ese Flujo no tiene turnos compatibles con el mapeo de este chat (revisa «Ruta del mensaje saliente»)')
                start_playing, use_new_thread = not step_mode.value, new_thread.value
                dialog.close()
                await run_replay(texts, start_playing, use_new_thread)
            with ui.row().classes('justify-end gap-2 w-full pt-2'):
                ui.button('Cancelar', on_click=dialog.close).props('flat')
                ui.button('Reproducir', icon='play_circle', on_click=guard(start)).props('color=primary no-caps').mark('chat-replay-suite-confirm')
        dialog.open()
