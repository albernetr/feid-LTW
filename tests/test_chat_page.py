"""Chat: a standalone screen to converse live with a chatbot/conversational API, one turn at a time."""
import asyncio
from app import core, automation
from app.pages.chat_page import parse_option_labels


def test_parse_option_labels_accepts_common_shapes():
    assert parse_option_labels([{'id': 'si', 'label': 'Sí'}, {'id': 'no', 'label': 'No'}]) == ['Sí', 'No']
    assert parse_option_labels(['Sí', 'No']) == ['Sí', 'No']                       # strings sueltos, sin envoltorio
    assert parse_option_labels([{'id': 'si'}, {'value': 'no'}]) == ['si', 'no']    # sin label: cae a value/id
    assert parse_option_labels([]) == []
    assert parse_option_labels(None) == []                                        # la ruta no apuntaba a una lista
    assert parse_option_labels('no es una lista') == []


async def test_chat_page_converses_live_and_saves_the_transcript_as_a_suite(user, chat_app):
    """Opening a case whose chat mapping is already configured goes straight to the conversation (no setup step).
    Typing is a real multi-turn exchange, not a scripted suite: the thread id carries itself forward. 'Guardar
    como suite' then freezes exactly what you typed into a replayable regression, chained with the same enrich
    mechanism any other suite uses."""
    project = core.create_project('Chat')
    env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
    case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                               'path': '/api/chat/messages', 'headers': {}, 'query': {},
                               'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}},
                               'assertions': [{'type': 'status', 'expected': 200}],
                               'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                        'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta'}})
    core.set_active_project(project['id'])
    await user.open(f'/chat?case={case["id"]}')
    await user.should_see('Hilo:')
    user.find(marker='chat-input').type('Hola')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¡Gracias por aceptar!', retries=30)         # the send runs as a background task (real HTTP round trip)
    user.find(marker='chat-input').type('Quiero un seguro de vida')
    user.find(marker='chat-send').click()
    await user.should_see('¿Cuál es el nombre completo', retries=30)
    user.find(marker='chat-actions-toggle').click()                    # despliega las acciones de la conversación (ocultas detrás de «+»)
    await user.should_see(marker='chat-save-suite', retries=30)
    user.find(marker='chat-save-suite').click()
    await asyncio.sleep(1)                                             # guard()'s wrapper runs as a background task too, and now saves two turns in a loop
    suites = core.list_project_items('suites', project['id'])
    assert len(suites) == 1
    steps = core.suite_steps(suites[0])
    assert [core.get('cases', s['case_id'])['name'] for s in steps] == ['Turno 1: Hola', 'Turno 2: Quiero un seguro de vida']
    assert core.get('cases', steps[0]['case_id'])['body']['message'] == 'Hola'
    assert steps[0]['enrich'] == []                                    # first turn starts a fresh thread
    assert steps[1]['enrich'] == [{'action': 'set', 'target': 'body', 'path': '$.conversation_id',
                                    'source': {'type': 'step', 'step': steps[0]['alias'], 'path': '$.thread_id'}}]
    result = automation.execute_suite(suites[0])                       # the saved transcript replays cleanly, thread id and all
    assert result['status'] == 'passed', result


async def test_first_turn_keeps_a_preset_thread_id_instead_of_blanking_it(user, chat_app):
    """The first turn of a new conversation has no thread id yet (S['thread_id'] is empty) — but the Body base
    template might already put something useful at that same path (e.g. {{seq}}, for an id the caller assigns
    instead of letting the bot invent one). That shouldn't be wiped to '' just because it's turn one; only a path
    with nothing there at all falls back to empty."""
    project = core.create_project('Preset id')
    env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
    case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                               'path': '/api/chat/messages', 'headers': {}, 'query': {},
                               'body': {'message': '', 'conversation_id': 'PRESET-{{seq}}', 'attributes': {'consent': True}},
                               'assertions': [{'type': 'status', 'expected': 200}],
                               'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                        'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta'}})
    core.set_active_project(project['id'])
    await user.open(f'/chat?case={case["id"]}')
    await user.should_see('Hilo:')
    user.find(marker='chat-input').type('Hola')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¡Gracias por aceptar!', retries=30)
    assert core.get('cases', case['id'])['chat_session']['thread_id'].startswith('PRESET-')   # not blanked, and not a bot-made uuid either


async def test_chat_page_resumes_a_conversation_from_the_same_case(user, chat_app):
    """Closing the tab (or just reloading) doesn't lose the conversation: the transcript and thread id are saved on
    the case after every turn, and reopening it restores the chat exactly where it was left — not just the mapping,
    which was the only thing that used to survive a reload."""
    project = core.create_project('Resume')
    env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
    case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                               'path': '/api/chat/messages', 'headers': {}, 'query': {},
                               'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}},
                               'assertions': [{'type': 'status', 'expected': 200}],
                               'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                        'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta'}})
    core.set_active_project(project['id'])
    await user.open(f'/chat?case={case["id"]}')
    user.find(marker='chat-input').type('Hola')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¡Gracias por aceptar!', retries=30)
    stored = core.get('cases', case['id'])['chat_session']
    assert stored['messages'][0] == {'who': 'user', 'text': 'Hola'} and stored['thread_id']       # persisted after just one turn
    await user.open(f'/chat?case={case["id"]}')                        # simulates closing and reopening the page
    await user.should_see('Hola')
    await user.should_see('¡Gracias por aceptar!')
    user.find(marker='chat-input').type('Quiero un seguro de vida')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¿Cuál es el nombre completo', retries=30)   # the bot remembers too: same thread id, so it's turn 2, not a new conversation
    assert len(core.get('cases', case['id'])['chat_session']['messages']) == 4


async def test_chat_page_saves_one_turn_at_a_time(user, chat_app):
    """Each exchange can be frozen into a case right when it happens, without waiting for the conversation to end —
    and a turn saved this way isn't offered again, while the suite keeps growing with the next ones."""
    project = core.create_project('PerTurn')
    env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
    case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                               'path': '/api/chat/messages', 'headers': {}, 'query': {},
                               'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}},
                               'assertions': [{'type': 'status', 'expected': 200}],
                               'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                        'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta'}})
    core.set_active_project(project['id'])
    await user.open(f'/chat?case={case["id"]}')
    user.find(marker='chat-input').type('Hola')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¡Gracias por aceptar!', retries=30)
    await user.should_see(marker='chat-save-turn-0')
    user.find(marker='chat-save-turn-0').click()
    await asyncio.sleep(0.5)
    suites = core.list_project_items('suites', project['id'])
    assert len(suites) == 1 and len(core.suite_steps(suites[0])) == 1
    await user.should_not_see(marker='chat-save-turn-0')                # the per-turn button is gone once it's saved

    user.find(marker='chat-input').type('Quiero un seguro de vida')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¿Cuál es el nombre completo', retries=30)
    user.find(marker='chat-save-turn-2').click()                       # turn index 2: the second user message in the transcript
    await asyncio.sleep(0.5)
    steps = core.suite_steps(core.get('suites', suites[0]['id']))
    assert len(steps) == 2
    assert steps[1]['enrich'] == [{'action': 'set', 'target': 'body', 'path': '$.conversation_id',
                                    'source': {'type': 'step', 'step': steps[0]['alias'], 'path': '$.thread_id'}}]
    result = automation.execute_suite(core.get('suites', suites[0]['id']))
    assert result['status'] == 'passed', result


async def test_chat_page_saves_a_reusable_template_for_new_conversations(user, chat_app):
    """«Guardar configuración» turns the current endpoint setup (URL/headers/body/mapeo) into a named template.
    Picking it later from «Plantilla» loads that same setup but always starts a blank conversation — so starting a
    new conversation against a bot you already configured doesn't mean retyping everything again."""
    project = core.create_project('Templates')
    env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
    case = core.save('cases', {'name': 'Bot de seguros', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                               'path': '/api/chat/messages', 'headers': {}, 'query': {},
                               'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}},
                               'assertions': [{'type': 'status', 'expected': 200}],
                               'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                        'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta'}})
    core.set_active_project(project['id'])
    await user.open(f'/chat?case={case["id"]}')
    await user.should_see('Hilo:')
    user.find(marker='chat-input').type('Hola')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¡Gracias por aceptar!', retries=30)
    user.find(marker='chat-activate').click()
    await user.should_see('la vas a encontrar en «Plantilla»')
    assert core.get('cases', case['id'])['chat_template'] is True

    await user.open('/chat')                                              # a brand new session: nothing pre-loaded
    await user.should_see('Completa el mapeo en')
    user.find(marker='chat-template-picker').click()
    user.find(target='Bot de seguros', marker='chat-template-picker').click()
    await user.should_see('Escribe el primer mensaje abajo.')              # config loaded, conversation starts blank
    user.find(marker='chat-input').type('Hola de nuevo')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¡Gracias por aceptar!', retries=30)             # same endpoint config works right away
    assert core.get('cases', case['id'])['chat_session']['messages'][0]['text'] == 'Hola de nuevo'


async def test_chat_turn_offers_detail_and_evidence_without_persisting_the_run_doc(user, chat_app):
    """Cada turno respondido por el bot puede abrir el mismo diálogo de detalle (show_run) que usa el resto de la
    app, con la evidencia descargable (HTML/PDF/Word/Markdown) — aunque el chat nunca guarda la corrida en el
    Historial (persist=False). El run_doc completo vive solo en memoria (S['runs']): lo que SÍ se persiste en el
    caso (chat_session.messages) no debe inflarse con él."""
    project = core.create_project('Evidencia chat')
    env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
    case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                               'path': '/api/chat/messages', 'headers': {}, 'query': {},
                               'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}},
                               'assertions': [{'type': 'status', 'expected': 200}],
                               'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                        'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta'}})
    core.set_active_project(project['id'])
    await user.open(f'/chat?case={case["id"]}')
    user.find(marker='chat-input').type('Hola')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¡Gracias por aceptar!', retries=30)
    await user.should_see(marker='chat-evidence-1')                    # turno 0: usuario, turno 1: respuesta del bot
    user.find(marker='chat-evidence-1').click()
    await user.should_see('Descargar evidencia:')
    await user.should_see('HTML')

    stored = core.get('cases', case['id'])['chat_session']['messages'][1]
    assert 'run' not in stored and 'request' not in stored and 'response' not in stored   # no se infla lo persistido


async def test_every_turn_shows_its_own_request_response_panel_inline(user, chat_app):
    """«Petición / Respuesta» debajo de cada turno, no solo del último (como ya hacía el panel de más abajo) ni
    solo detrás de «Ver detalle y evidencia» (que exige abrir un diálogo). Se arma con el mismo run_doc en
    memoria (S['runs']) que ya usa la evidencia por turno."""
    project = core.create_project('Peticion por turno')
    env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
    case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                               'path': '/api/chat/messages', 'headers': {}, 'query': {},
                               'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}},
                               'assertions': [],
                               'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                        'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta'}})
    core.set_active_project(project['id'])
    await user.open(f'/chat?case={case["id"]}')
    user.find(marker='chat-input').type('Hola')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¡Gracias por aceptar!', retries=30)
    user.find(marker='chat-input').type('Quiero un seguro de vida')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¿Cuál es el nombre completo', retries=30)

    await user.should_see(marker='chat-reqres-1')   # turno 0: usuario, turno 1: respuesta del bot
    await user.should_see(marker='chat-reqres-3')   # turno 2: usuario, turno 3: respuesta del bot
    user.find(marker='chat-reqres-1').click()
    await user.should_see('Enviado')
    await user.should_see('"message": "Hola"')
    await user.should_see('Recibido')
    await user.should_see('¡Gracias por aceptar!')
    user.find(marker='chat-reqres-3').click()
    await user.should_see('"message": "Quiero un seguro de vida"')


async def test_chat_turn_shows_as_passed_when_the_endpoint_has_no_assertions_configured(user, chat_app):
    """La pantalla de Chat no tiene editor de aserciones (solo headers/body/mapeo): un endpoint armado desde cero
    ahí, como lo haría cualquier persona, llega a core.execute_api sin ninguna. Ese motor marca 'failed' cuando un
    caso no trae aserciones (nada quedó confirmado — ver core.py y tests/test_lab.py), que es correcto para un caso
    guardado pero engañoso para un turno de chat en vivo: una respuesta HTTP sin error sí fue un turno exitoso."""
    project = core.create_project('Sin aserciones')
    env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
    case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                               'path': '/api/chat/messages', 'headers': {}, 'query': {},
                               'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}},
                               'assertions': [],   # como lo deja la pantalla de Chat: no tiene editor de aserciones
                               'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                        'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta'}})
    core.set_active_project(project['id'])
    await user.open(f'/chat?case={case["id"]}')
    await user.should_see('Hilo:')
    user.find(marker='chat-input').type('Hola')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¡Gracias por aceptar!', retries=30)
    await user.should_see(marker='chat-evidence-1')
    user.find(marker='chat-evidence-1').click()
    await user.should_see('Descargar evidencia:')
    await user.should_not_see('Falló')         # un HTTP 200 sin aserciones no es un turno fallido en el chat


async def test_chat_conversation_evidence_covers_every_selected_turn_with_its_request_and_response(user, chat_app):
    """«Evidencia de la conversación» arma UN solo reporte con los turnos elegidos (todos por defecto) — y cada
    turno incluido trae su propia petición/respuesta, igual que el detalle de un turno suelto, no solo el status."""
    project = core.create_project('Evidencia conversación')
    env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
    case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                               'path': '/api/chat/messages', 'headers': {}, 'query': {},
                               'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}},
                               'assertions': [],
                               'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                        'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta'}})
    core.set_active_project(project['id'])
    await user.open(f'/chat?case={case["id"]}')
    user.find(marker='chat-input').type('Hola')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¡Gracias por aceptar!', retries=30)
    user.find(marker='chat-input').type('Quiero un seguro de vida')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¿Cuál es el nombre completo', retries=30)

    user.find(marker='chat-actions-toggle').click()                    # despliega las acciones de la conversación (ocultas detrás de «+»)
    await user.should_see(marker='chat-evidence-all', retries=30)
    user.find(marker='chat-evidence-all').click()
    await user.should_see('Evidencia de la conversación')
    await user.should_see(marker='chat-evidence-all-cb-1')          # turno 0: usuario, turno 1: respuesta del bot
    await user.should_see(marker='chat-evidence-all-cb-3')          # turno 2: usuario, turno 3: respuesta del bot

    user.find(marker='chat-evidence-all-html').click()
    await user.should_see('Evidencia generada')


async def test_chat_shows_quick_reply_options_as_clickable_buttons_that_send_the_choice(user, chat_app):
    """Cuando el bot manda botones de respuesta rápida (p. ej. $.conversation.replies[0].options: [{id, label}, ...]),
    se pintan como botones debajo de esa respuesta — tocar uno manda su texto como el próximo mensaje, igual que si
    lo hubieras tipeado. `options_path` es opcional y configurable (no hardcodeado), porque el campo cambia de bot
    en bot — sample_app/chat_server.py solo manda opciones en el primer turno, como un bot real."""
    project = core.create_project('Opciones de respuesta')
    env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
    case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                               'path': '/api/chat/messages', 'headers': {}, 'query': {},
                               'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}},
                               'assertions': [],
                               'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                        'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta',
                                        'options_path': '$.conversation.replies[0].options'}})
    core.set_active_project(project['id'])
    await user.open(f'/chat?case={case["id"]}')
    user.find(marker='chat-input').type('Hola')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¡Gracias por aceptar!', retries=30)

    await user.should_see(marker='chat-option-1-0')
    await user.should_see('Sí')
    await user.should_see('No')
    user.find(marker='chat-option-1-0').click()
    await user.should_see('¿Cuál es el nombre completo', retries=30)   # el bot avanzó: recibió "Sí" como mensaje
    assert core.get('cases', case['id'])['chat_session']['messages'][2] == {'who': 'user', 'text': 'Sí'}


async def test_replay_resends_prior_turns_with_a_fresh_thread_and_replaces_them(user, chat_app):
    """«Reproducir conversación», sin «paso a paso»: vuelve a mandar al bot lo que ya se había escrito, con un
    hilo nuevo (el bot no lo conoce, así que arranca una conversación distinta de verdad) — y lo que se ve en
    pantalla se reemplaza por lo que realmente llega esta vez, no queda al lado de lo viejo."""
    project = core.create_project('Reproducir')
    env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
    case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                               'path': '/api/chat/messages', 'headers': {}, 'query': {},
                               'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}},
                               'assertions': [],
                               'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                        'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta'}})
    core.set_active_project(project['id'])
    await user.open(f'/chat?case={case["id"]}')
    user.find(marker='chat-input').type('Hola')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¡Gracias por aceptar!', retries=30)
    user.find(marker='chat-input').type('Quiero un seguro de vida')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¿Cuál es el nombre completo', retries=30)
    old_thread = core.get('cases', case['id'])['chat_session']['thread_id']

    user.find(marker='chat-actions-toggle').click()          # despliega las acciones de la conversación (ocultas detrás de «+»)
    await user.should_see(marker='chat-replay', retries=30)
    user.find(marker='chat-replay').click()
    await user.should_see(marker='chat-replay-stepmode', retries=30)
    user.find(marker='chat-replay-stepmode').click()         # apaga «paso a paso»: arranca reproduciendo seguido
    user.find(marker='chat-replay-confirm').click()
    # El clic dispara el handler async del botón (dialog.close() + await run_replay(...)) como una tarea aparte
    # del test — no hay nada que `await`ar acá, así que se espera a que lo persistido se estabilice en los 2
    # turnos (el ritmo de reproducción incluye una pausa de 0.6s entre turnos).
    # La conversación original YA tenía estos 2 mismos turnos antes de reproducir — sondear solo «¿hay 2 mensajes
    # de usuario?» daría un falso positivo instantáneo con el estado viejo, antes de que la reproducción (que
    # primero vacía la sesión) alcance a tocar nada. Hay que esperar a las DOS señales de que es la tanda nueva:
    # el hilo ya cambió Y los textos vuelven a estar completos (run_replay vacía S['messages'] al arrancar).
    stored = None
    for _ in range(50):
        stored = core.get('cases', case['id'])['chat_session']
        user_texts = [t['text'] for t in stored['messages'] if t['who'] == 'user']
        if stored['thread_id'] != old_thread and user_texts == ['Hola', 'Quiero un seguro de vida']:
            break
        await asyncio.sleep(0.2)
    assert stored['thread_id'] != old_thread                 # el bot lo trató como una conversación distinta
    user_texts = [t['text'] for t in stored['messages'] if t['who'] == 'user']
    assert user_texts == ['Hola', 'Quiero un seguro de vida']   # se reprodujeron ambos, sin duplicarse ni perderse


async def test_replay_step_by_step_pauses_between_turns_until_told_to_continue(user, chat_app):
    """«Paso a paso»: arranca pausado ANTES del primer turno (como una casetera parada, no a mitad de la cinta) —
    cada turno, incluido el primero, espera un ▶ o ⏭ antes de mandarse."""
    project = core.create_project('Reproducir paso a paso')
    env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
    case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                               'path': '/api/chat/messages', 'headers': {}, 'query': {},
                               'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}},
                               'assertions': [],
                               'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                        'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta'}})
    core.set_active_project(project['id'])
    await user.open(f'/chat?case={case["id"]}')
    user.find(marker='chat-input').type('Hola')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¡Gracias por aceptar!', retries=30)
    user.find(marker='chat-input').type('Quiero un seguro de vida')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¿Cuál es el nombre completo', retries=30)

    user.find(marker='chat-actions-toggle').click()          # despliega las acciones de la conversación (ocultas detrás de «+»)
    await user.should_see(marker='chat-replay', retries=30)
    user.find(marker='chat-replay').click()
    await user.should_see(marker='chat-replay-stepmode', retries=30)   # «paso a paso» queda tildado por defecto
    user.find(marker='chat-replay-confirm').click()
    await user.should_see(marker='chat-replay-step', retries=30)   # arrancó pausado, antes de mandar nada
    await user.should_not_see('¡Gracias por aceptar!')             # la sesión vieja ya se vació — no quedó nada de antes

    user.find(marker='chat-replay-step').click()                   # ⏭ turno 1
    await user.should_see('¡Gracias por aceptar!', retries=30)
    await asyncio.sleep(0.5)
    await user.should_not_see('¿Cuál es el nombre completo')    # …pero se detuvo antes de mandar el turno 2
    await user.should_see(marker='chat-replay-step')

    user.find(marker='chat-replay-step').click()               # ⏭ turno 2
    await user.should_see('¿Cuál es el nombre completo', retries=30)
    await asyncio.sleep(0.3)
    await user.should_not_see(marker='chat-replay-step')        # terminó: el control de reproducción desaparece


async def test_replay_skip_moves_on_without_resending_the_recorded_text(user, chat_app):
    """«Saltar» (⏩): cuando ya respondiste ese paso vos mismo, a mano, con un texto distinto del grabado — no
    hay que dejar que la reproducción repita la pregunta grabada; tiene que saltarla y seguir con la próxima."""
    project = core.create_project('Reproducir con salto')
    env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
    case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                               'path': '/api/chat/messages', 'headers': {}, 'query': {},
                               'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}},
                               'assertions': [],
                               'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                        'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta'}})
    core.set_active_project(project['id'])
    await user.open(f'/chat?case={case["id"]}')
    user.find(marker='chat-input').type('Hola')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¡Gracias por aceptar!', retries=30)
    user.find(marker='chat-input').type('Quiero un seguro de vida')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¿Cuál es el nombre completo', retries=30)

    user.find(marker='chat-actions-toggle').click()
    await user.should_see(marker='chat-replay', retries=30)
    user.find(marker='chat-replay').click()
    await user.should_see(marker='chat-replay-stepmode', retries=30)
    user.find(marker='chat-replay-confirm').click()
    await user.should_see(marker='chat-replay-skip', retries=30)   # pausado antes del turno 1 ("Hola")

    user.find(marker='chat-replay-skip').click()                   # salta "Hola" sin reenviarlo
    await asyncio.sleep(0.3)
    await user.should_not_see('¡Gracias por aceptar!')             # no se mandó: ninguna respuesta del bot todavía
    await user.should_see(marker='chat-replay-step')                # sigue pausado, ahora antes del turno 2

    user.find(marker='chat-replay-step').click()                    # este sí se manda ("Quiero un seguro de vida")
    await asyncio.sleep(0.5)
    stored = core.get('cases', case['id'])['chat_session']
    user_texts = [t['text'] for t in stored['messages'] if t['who'] == 'user']
    assert user_texts == ['Quiero un seguro de vida']   # "Hola" nunca se reenvió — saltado de verdad, no solo oculto


async def test_replay_can_resume_from_a_saved_flow_without_retyping(user, chat_app):
    """«Retomar un Flujo guardado»: arranca una conversación en vivo nueva a partir de los turnos de un Flujo que
    ya se había guardado, sin tener que volver a tipear cada mensaje."""
    project = core.create_project('Reproducir desde flujo')
    env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
    case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                               'path': '/api/chat/messages', 'headers': {}, 'query': {},
                               'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}},
                               'assertions': [],
                               'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                        'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta'}})
    core.set_active_project(project['id'])
    await user.open(f'/chat?case={case["id"]}')
    user.find(marker='chat-input').type('Hola')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¡Gracias por aceptar!', retries=30)
    user.find(marker='chat-actions-toggle').click()          # despliega las acciones de la conversación (ocultas detrás de «+»)
    await user.should_see(marker='chat-save-suite', retries=30)
    user.find(marker='chat-save-suite').click()
    await asyncio.sleep(0.5)
    suite = core.list_project_items('suites', project['id'])[0]

    user.find(marker='chat-replay-suite').click()
    await user.should_see(marker='chat-replay-suite-picker', retries=30)
    user.find(marker='chat-replay-suite-picker').click()
    await user.should_see(suite['name'])
    user.find(target=suite['name'], marker='chat-replay-suite-picker').click()
    user.find(marker='chat-replay-suite-stepmode').click()     # apaga «paso a paso»
    user.find(marker='chat-replay-suite-confirm').click()
    await user.should_see('¡Gracias por aceptar!', retries=40)
    await asyncio.sleep(0.3)
    stored = core.get('cases', case['id'])['chat_session']
    assert [t['text'] for t in stored['messages'] if t['who'] == 'user'] == ['Hola']


async def test_chat_page_without_a_case_asks_for_the_mapping_first(user, chat_app):
    """A fresh chat (no saved case) needs the four paths confirmed before it will send anything — typing and
    pressing Enter beforehand is a no-op, not a request against an unconfigured mapping."""
    project = core.create_project('Chat libre')
    core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
    core.set_active_project(project['id'])
    await user.open('/chat')
    await user.should_see('Completa el mapeo en')
    user.find(marker='chat-url').type(chat_app.url + '/api/chat/messages')
    user.find(marker='chat-input').type('Hola')
    user.find(marker='chat-input').trigger('keydown.enter')
    await asyncio.sleep(0.3)
    await user.should_see('Completa el mapeo en')                     # still waiting on the mapping: nothing was sent, no bubble appeared
