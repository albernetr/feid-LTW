"""Chat: a standalone screen to converse live with a chatbot/conversational API, one turn at a time."""
import asyncio
import json
from app import core, automation, llm
from app.pages.chat_page import parse_option_labels
from nicegui.testing.user_interaction import UserInteraction
from sample_app.fake_llm import FakeLLM


def configure_fake_llm(fake):
    return llm.save_config({'preset': 'local', 'protocol': 'openai', 'base_url': fake.url + '/v1', 'model': 'modelo-demo', 'auth': 'none'})


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
    template_select = user.find(marker='chat-template-picker').elements.pop()
    with user:
        template_select.value = case['id']
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


async def test_chat_saves_and_restores_the_hu_text_and_linked_feature(user, chat_app):
    """El criterio para el veredicto del modelo (HU escrita o Funcionalidad ligada) se guarda con el resto de la
    configuración del chat (Guardar configuración) y se restaura al reabrir ese mismo caso — igual que ya hace
    el mapeo de rutas."""
    project = core.create_project('Criterio de veredicto')
    feature = core.create_feature('Cotizar seguro de vida', project['id'], description='El bot debe pedir tipo de seguro y nombre del asegurado.')
    core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
    core.set_active_project(project['id'])
    await user.open('/chat')
    user.find(marker='chat-url').type(chat_app.url + '/api/chat/messages')
    user.find('Nombre de este chat').type('Chat con criterio')
    user.find(marker='chat-hu-text').type('El bot debe saludar y pedir el tipo de seguro.')
    hu_select = user.find(marker='chat-feature-id').elements.pop()
    with user:
        hu_select.value = feature['id']
    user.find(marker='chat-activate').click()
    await user.should_see('la vas a encontrar en «Plantilla»')
    case_id = core.list_project_items('cases', project['id'])[0]['id']
    saved = core.get('cases', case_id)
    assert saved['hu_text'] == 'El bot debe saludar y pedir el tipo de seguro.'
    assert saved['feature_id'] == feature['id']

    await user.open(f'/chat?case={case_id}')
    await user.should_see(marker='chat-hu-text', retries=30)
    hu_input = user.find(marker='chat-hu-text').elements.pop()
    assert hu_input.value == 'El bot debe saludar y pedir el tipo de seguro.'


async def test_conversation_verdict_button_is_disabled_without_a_configured_model(user, chat_app):
    project = core.create_project('Sin modelo configurado')
    env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
    case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                               'path': '/api/chat/messages', 'headers': {}, 'query': {},
                               'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}}, 'assertions': [],
                               'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                        'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta'}})
    core.set_active_project(project['id'])
    await user.open(f'/chat?case={case["id"]}')
    user.find(marker='chat-input').type('Hola')
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¡Gracias por aceptar!', retries=30)
    user.find(marker='chat-actions-toggle').click()
    await user.should_see(marker='chat-evidence-all', retries=30)
    user.find(marker='chat-evidence-all').click()
    await user.should_see(marker='chat-ask-verdict', retries=30)
    button = user.find(marker='chat-ask-verdict').elements.pop()
    assert button.enabled is False


async def test_conversation_verdict_asks_the_model_and_travels_into_the_evidence(user, chat_app):
    """El veredicto se pide sobre TODA la conversación (S['messages']), no solo los turnos tildados para
    descargar — y el que se obtuvo es el que viaja al reporte al descargarlo."""
    with FakeLLM() as fake:
        configure_fake_llm(fake)
        fake.queue(json.dumps({'pass': True, 'reasoning': 'El bot pidió el tipo de seguro, como esperaba el criterio.'}))
        project = core.create_project('Con modelo configurado')
        env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
        case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                                   'path': '/api/chat/messages', 'headers': {}, 'query': {},
                                   'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}}, 'assertions': [],
                                   'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                            'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta'},
                                   'hu_text': 'El bot debe pedir el tipo de seguro.'})
        core.set_active_project(project['id'])
        await user.open(f'/chat?case={case["id"]}')
        user.find(marker='chat-input').type('Hola')
        user.find(marker='chat-input').trigger('keydown.enter')
        await user.should_see('¡Gracias por aceptar!', retries=30)
        user.find(marker='chat-actions-toggle').click()
        await user.should_see(marker='chat-evidence-all', retries=30)
        user.find(marker='chat-evidence-all').click()
        await user.should_see('historia de usuario / criterios escritos')   # el criterio en uso, no "inferido"
        await user.should_see(marker='chat-ask-verdict', retries=30)        # el diálogo (dentro del splitter anidado)
        user.find(marker='chat-ask-verdict').click()                        # puede tardar un render más en quedar listo
        await user.should_see(marker='chat-verdict-reasoning', retries=30)
        await user.should_see('El bot pidió el tipo de seguro')
        sent = fake.requests[-1]['body']['messages'][-1]['content']
        assert 'El bot debe pedir el tipo de seguro.' in sent and 'Vos: Hola' in sent


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
    # El Flujo se llama igual que el valor por defecto de «Nombre del flujo» (sigue visible detrás del diálogo,
    # en la misma pantalla) — elegir la opción «por el texto» (`find(target=...)`) empataría con ese input y
    # terminaría clickeando el elemento equivocado (gana el de menor id, no el select). Se asigna el valor
    # directo sobre el propio elemento, ya aislado sin ambigüedad por su marcador.
    picker_select = user.find(marker='chat-replay-suite-picker').elements.pop()
    with user:
        picker_select.value = suite['id']
    user.find(marker='chat-replay-suite-stepmode').click()     # apaga «paso a paso»
    user.find(marker='chat-replay-suite-confirm').click()
    await user.should_see('¡Gracias por aceptar!', retries=40)
    await asyncio.sleep(0.3)
    stored = core.get('cases', case['id'])['chat_session']
    assert [t['text'] for t in stored['messages'] if t['who'] == 'user'] == ['Hola']


async def test_replay_from_a_saved_flow_applies_its_own_chat_mapping_to_a_fresh_chat(user, chat_app):
    """El mapeo queda guardado en el propio Flujo, no solo en el chat que estaba abierto al grabarlo — así
    «Retomar un Flujo guardado» funciona en un chat nuevo sin configurar nada a mano, y la conversación se
    puede seguir en vivo después (antes, sin esto, fallaba con «no tiene turnos compatibles» o mandaba
    mensajes en silencio sin mapeo). El Flujo se arma directo con `core.save_suite(chat=...)` — da igual cómo
    haya llegado a tener su propio mapeo; lo que se prueba es qué hace el chat nuevo con él."""
    project = core.create_project('Flujo con su propio mapeo')
    env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
    mapping = {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
               'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta'}
    turn = core.save('cases', {'name': 'Turno 1: Hola', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                               'path': '/api/chat/messages', 'headers': {}, 'query': {},
                               'body': {'message': 'Hola', 'conversation_id': '', 'attributes': {'consent': True}},
                               'assertions': []})
    suite = core.save_suite('Conversación de prueba', env['id'], [turn['id']], project['id'],
                             steps=[{'case_id': turn['id'], 'alias': 'turno1', 'enrich': []}], chat=mapping)
    core.set_active_project(project['id'])

    await user.open('/chat')                                             # chat nuevo, sin caso ni mapeo configurado
    await user.should_see('Completa el mapeo en')
    user.find(marker='chat-url').type(chat_app.url + '/api/chat/messages')  # el endpoint sí hay que ponerlo a mano
    method_select = user.find(marker='chat-method').elements.pop()        # un chat nuevo arranca en GET; el bot espera POST
    with user:
        method_select.value = 'POST'
    user.find(marker='chat-body').type('{"attributes": {"consent": true}}')  # el bot exige attributes.consent
    user.find(marker='chat-actions-toggle').click()
    await user.should_see(marker='chat-replay-suite', retries=30)
    user.find(marker='chat-replay-suite').click()
    await user.should_see(marker='chat-replay-suite-picker', retries=30)
    user.find(marker='chat-replay-suite-picker').click()
    # Mismo motivo que en el test anterior: elegir «por el texto» empataría con el «Nombre del flujo» que se ve
    # detrás del diálogo (los dos muestran «Conversación de prueba»); se asigna el valor directo sobre el select.
    picker_select = user.find(marker='chat-replay-suite-picker').elements.pop()
    with user:
        picker_select.value = suite['id']
    user.find(marker='chat-replay-suite-stepmode').click()                # apaga «paso a paso»
    user.find(marker='chat-replay-suite-confirm').click()
    await user.should_see('¡Gracias por aceptar!', retries=40)            # funcionó sin configurar nada a mano
    user.find(marker='chat-input').type('Quiero un seguro de vida')       # y se puede seguir conversando en vivo
    user.find(marker='chat-input').trigger('keydown.enter')
    await user.should_see('¿Cuál es el nombre completo', retries=30)


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


async def test_ai_conversation_sends_model_suggested_turns_until_it_says_its_done(user, chat_app):
    """«Conversación conducida por IA», de corrido (sin paso a paso): cada turno de «vos» lo escribe el modelo
    (llm.suggest_next_turn) en vez de tipearlo una persona — incluida la opción rápida «Sí» que ofrece el bot en
    su primer turno, que el modelo elige en vez de texto libre. Se detiene solo cuando el modelo dice `done`, y
    lo recorrido queda guardado como Flujo sin tocar «Guardar todo lo pendiente» a mano."""
    with FakeLLM() as fake:
        configure_fake_llm(fake)
        fake.queue(json.dumps({'text': 'Hola', 'option': None, 'done': False, 'collected': {}}))          # turno 1
        fake.queue(json.dumps({'text': '', 'option': 'Sí', 'done': False, 'collected': {}}))               # turno 2: elige la opción rápida ofrecida
        fake.queue(json.dumps({'text': 'Juan Pérez', 'option': None, 'done': False, 'collected': {}}))     # turno 3
        fake.queue(json.dumps({'text': '', 'option': None, 'done': True, 'collected': {'nombre': 'Juan Pérez'}}))  # corta sola
        project = core.create_project('IA de corrido')
        env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
        case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                                   'path': '/api/chat/messages', 'headers': {}, 'query': {},
                                   'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}}, 'assertions': [],
                                   'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                            'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta',
                                            'options_path': '$.conversation.replies[0].options'}})
        core.set_active_project(project['id'])
        await user.open(f'/chat?case={case["id"]}')
        await user.should_see('Hilo:')
        user.find(marker='chat-rail-Asistente').click()
        await user.should_see(marker='chat-ai-tab-run-open', retries=30)
        user.find(marker='chat-ai-tab-run-open').click()
        await user.should_see(marker='chat-ai-run-instruction', retries=30)
        user.find(marker='chat-ai-run-instruction').type('Cotizar un seguro de vida para Juan Pérez.')
        user.find(marker='chat-ai-run-stepmode').click()          # apaga «paso a paso»: de corrido
        user.find(marker='chat-ai-run-confirm').click()
        await user.should_see('Perfecto, en breve un asesor', retries=40)   # llegó hasta el cierre del bot
        stored = core.get('cases', case['id'])['chat_session']
        user_texts = [t['text'] for t in stored['messages'] if t['who'] == 'user']
        assert user_texts == ['Hola', 'Sí', 'Juan Pérez']
        # «Perfecto, en breve…» ya se mostró, pero el bucle todavía tiene que pedirle al modelo el turno siguiente
        # (el que responde done=True) y recién ahí guardar el Flujo — el guardado automático corre después.
        suites = []
        for _ in range(30):
            suites = core.list_project_items('suites', project['id'])
            if suites:
                break
            await asyncio.sleep(0.2)
        assert len(suites) == 1 and len(core.suite_steps(suites[0])) == 3   # se guardó solo, sin tocar «Guardar todo lo pendiente»


async def test_ai_conversation_step_mode_shows_an_editable_draft_before_sending(user, chat_app):
    """Paso a paso: el turno sugerido queda precargado en la barra de escribir normal — editarlo y mandarlo (lo
    de siempre, Enter o el botón de enviar) es lo que hace avanzar la conversación, no un botón aparte."""
    with FakeLLM() as fake:
        configure_fake_llm(fake)
        fake.queue(json.dumps({'text': 'Hola', 'option': None, 'done': False, 'collected': {}}))
        project = core.create_project('IA paso a paso')
        env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
        case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                                   'path': '/api/chat/messages', 'headers': {}, 'query': {},
                                   'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}}, 'assertions': [],
                                   'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                            'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta'}})
        core.set_active_project(project['id'])
        await user.open(f'/chat?case={case["id"]}')
        await user.should_see('Hilo:')
        user.find(marker='chat-rail-Asistente').click()
        await user.should_see(marker='chat-ai-tab-run-open', retries=30)
        user.find(marker='chat-ai-tab-run-open').click()
        await user.should_see(marker='chat-ai-run-instruction', retries=30)
        user.find(marker='chat-ai-run-instruction').type('Saludar y pedir un seguro.')
        user.find(marker='chat-ai-run-confirm').click()            # «paso a paso» queda tildado por defecto
        await user.should_see(marker='chat-ai-run-pause', retries=30)   # la barra de control aparece antes de que llegue el borrador
        box = user.find(marker='chat-input').elements.pop()
        for _ in range(30):
            if box.value == 'Hola':
                break
            await asyncio.sleep(0.1)
        assert box.value == 'Hola'                                  # el borrador sugerido, precargado y editable
        with user:
            box.value = 'Hola, buenas tardes'                        # lo editamos antes de mandarlo
        user.find(marker='chat-input').trigger('keydown.enter')       # mandarlo es lo de siempre, nada nuevo
        await user.should_see('¡Gracias por aceptar!', retries=30)
        stored = core.get('cases', case['id'])['chat_session']
        assert stored['messages'][0] == {'who': 'user', 'text': 'Hola, buenas tardes'}   # salió lo editado, no el borrador original


async def test_ai_conversation_pauses_when_the_bot_offers_options_the_model_does_not_pick(user, chat_app):
    """Si el bot ofrece opciones de respuesta rápida y el modelo no eligió ninguna con claridad (`option` null),
    la conversación pausa igual aunque el modo sea «de corrido» — nunca manda una opción inventada, deja que
    decida una persona."""
    with FakeLLM() as fake:
        configure_fake_llm(fake)
        fake.queue(json.dumps({'text': 'Hola', 'option': None, 'done': False, 'collected': {}}))                      # turno 1: sin opciones todavía
        fake.queue(json.dumps({'text': 'Prefiero no decir', 'option': None, 'done': False, 'collected': {}}))         # turno 2: el bot YA ofreció Sí/No
        project = core.create_project('IA opciones sin elegir')
        env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
        case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                                   'path': '/api/chat/messages', 'headers': {}, 'query': {},
                                   'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}}, 'assertions': [],
                                   'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                            'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta',
                                            'options_path': '$.conversation.replies[0].options'}})
        core.set_active_project(project['id'])
        await user.open(f'/chat?case={case["id"]}')
        await user.should_see('Hilo:')
        user.find(marker='chat-rail-Asistente').click()
        await user.should_see(marker='chat-ai-tab-run-open', retries=30)
        user.find(marker='chat-ai-tab-run-open').click()
        await user.should_see(marker='chat-ai-run-instruction', retries=30)
        user.find(marker='chat-ai-run-instruction').type('Cotizar un seguro, sin preferencia de opciones.')
        user.find(marker='chat-ai-run-stepmode').click()          # pide «de corrido»…
        user.find(marker='chat-ai-run-confirm').click()
        await user.should_see('¡Gracias por aceptar!', retries=30)   # turno 1 sí se mandó solo (no había opciones todavía)
        await user.should_see(marker='chat-ai-run-pause', retries=30)   # …pero el turno 2 quedó pausado igual
        box = user.find(marker='chat-input').elements.pop()
        for _ in range(30):
            if box.value == 'Prefiero no decir':
                break
            await asyncio.sleep(0.1)
        assert box.value == 'Prefiero no decir'
        await user.should_not_see('¿Cuál es el nombre completo')    # no se mandó solo: sigue esperando a una persona


async def test_exploration_tree_tracks_pending_branches_and_runs_them_all(user, chat_app):
    """Una corrida conducida por IA que toma «Sí» en el único punto de opciones dentro del bot de ejemplo deja
    «No» anotado como rama pendiente en el árbol de exploración (core.save_exploration_tree, llamado desde
    save_turn_as_case) — «Ejecutar todas las ramificaciones» la retoma (reproduce «Hola» fijo, manda «No», y
    sigue con el modelo libre) y la guarda como un Flujo propio, aparte del original."""
    with FakeLLM() as fake:
        configure_fake_llm(fake)
        fake.queue(json.dumps({'text': 'Hola', 'option': None, 'done': False, 'collected': {}}))            # corrida original, turno 1
        fake.queue(json.dumps({'text': '', 'option': 'Sí', 'done': False, 'collected': {}}))                 # turno 2: toma «Sí»
        fake.queue(json.dumps({'text': 'Juan Pérez', 'option': None, 'done': False, 'collected': {}}))       # turno 3
        fake.queue(json.dumps({'text': '', 'option': None, 'done': True, 'collected': {}}))                  # corta sola
        fake.queue(json.dumps({'text': 'Carlos Ruiz', 'option': None, 'done': False, 'collected': {}}))      # rama «No», turno (tras el preset)
        fake.queue(json.dumps({'text': '', 'option': None, 'done': True, 'collected': {}}))                  # rama «No», corta sola
        project = core.create_project('Árbol de exploración')
        env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
        case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                                   'path': '/api/chat/messages', 'headers': {}, 'query': {},
                                   'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}}, 'assertions': [],
                                   'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                            'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta',
                                            'options_path': '$.conversation.replies[0].options'}})
        core.set_active_project(project['id'])
        await user.open(f'/chat?case={case["id"]}')
        await user.should_see('Hilo:')
        user.find(marker='chat-rail-Asistente').click()
        await user.should_see(marker='chat-ai-tab-run-open', retries=30)
        user.find(marker='chat-ai-tab-run-open').click()
        await user.should_see(marker='chat-ai-run-instruction', retries=30)
        user.find(marker='chat-ai-run-instruction').type('Cotizar un seguro de vida para Juan Pérez, eligiendo siempre "Sí".')
        user.find(marker='chat-ai-run-stepmode').click()          # de corrido
        user.find(marker='chat-ai-run-confirm').click()
        for _ in range(50):                                        # corrida original completa y guardada como Flujo
            if core.list_project_items('suites', project['id']):
                break
            await asyncio.sleep(0.2)
        suites_before = core.list_project_items('suites', project['id'])
        assert len(suites_before) == 1

        user.find(marker='chat-tree-open').click()
        await user.should_see('«No» — sin explorar', retries=30)    # la opción que el bot ofreció y no se tomó
        user.find(marker='chat-tree-run-all').click()
        await asyncio.sleep(0.3)                                    # guard() corre run_tree_branches como tarea aparte
        user.find(marker='chat-tree-close').click()                 # cierra el diálogo viejo antes de abrir uno nuevo más abajo
        suites_after = []
        for _ in range(80):
            suites_after = core.list_project_items('suites', project['id'])
            if len(suites_after) == 2:
                break
            await asyncio.sleep(0.2)
        assert len(suites_after) == 2                                # la rama «No» se guardó como un Flujo propio, aparte del original
        branch_suite = next(s for s in suites_after if s['id'] not in {s2['id'] for s2 in suites_before})
        branch_texts = [core.get('cases', s['case_id'])['body']['message'] for s in core.suite_steps(branch_suite)]
        assert branch_texts[:2] == ['Hola', 'No']                   # arrancó reproduciendo fijo hasta el punto de bifurcación

        # Chequeo contra los datos (no contra el texto en pantalla): un diálogo cerrado sigue existiendo en el
        # árbol simulado del test harness con su contenido viejo, así que buscar «ya no se ve» ahí sería frágil.
        tree = core.exploration_tree_for_case(case['id'], project['id'])
        assert core.pending_branches(tree['root']) == []              # ya no queda nada pendiente en ese punto


async def test_ai_conversation_with_a_fresh_thread_does_not_collide_with_the_previous_run_s_flow(user, chat_app):
    """Bug encontrado en vivo: arrancar una segunda «Conversación conducida por IA» con hilo nuevo, en el mismo
    chat donde ya se había guardado un Flujo, intentaba fusionar los turnos nuevos en ESE Flujo viejo — y el
    número de turno volvía a empezar en 1, chocando con el alias «turno1» que ya existía ahí. Un hilo nuevo
    también tiene que ser un Flujo nuevo al guardarse."""
    with FakeLLM() as fake:
        configure_fake_llm(fake)
        fake.queue(json.dumps({'text': 'Hola', 'option': None, 'done': False, 'collected': {}}))
        fake.queue(json.dumps({'text': '', 'option': None, 'done': True, 'collected': {}}))
        fake.queue(json.dumps({'text': 'Hola de nuevo', 'option': None, 'done': False, 'collected': {}}))
        fake.queue(json.dumps({'text': '', 'option': None, 'done': True, 'collected': {}}))
        project = core.create_project('IA hilo nuevo dos veces')
        env = core.save('environments', {'name': 'bot', 'project_id': project['id'], 'base_url': chat_app.url, 'variables': {}, 'auth': {'type': 'none'}})
        case = core.save('cases', {'name': 'Enviar mensaje', 'type': 'api', 'project_id': project['id'], 'environment_id': env['id'], 'method': 'POST',
                                   'path': '/api/chat/messages', 'headers': {}, 'query': {},
                                   'body': {'message': '', 'conversation_id': '', 'attributes': {'consent': True}}, 'assertions': [],
                                   'chat': {'message_path': '$.message', 'thread_request_path': '$.conversation_id',
                                            'thread_response_path': '$.thread_id', 'reply_path': '$.respuesta'}})
        core.set_active_project(project['id'])
        await user.open(f'/chat?case={case["id"]}')
        await user.should_see('Hilo:')
        for run_index in range(1, 3):
            user.find(marker='chat-rail-Asistente').click()
            await user.should_see(marker='chat-ai-tab-run-open', retries=30)
            user.find(marker='chat-ai-tab-run-open').click()
            await user.should_see(marker='chat-ai-run-instruction', retries=30)
            # El diálogo anterior (ya cerrado) sigue existiendo en el árbol simulado del test harness, así que
            # `find()` por marcador es ambiguo entre corridas — y `UserInteraction.click()` desempata quedándose
            # con el id MÁS CHICO (el elemento más viejo), al revés de lo que hace falta acá. Apuntamos a mano al
            # más nuevo (id más alto) en cada caso.
            def newest(marker):
                return max(user.find(marker=marker).elements, key=lambda e: e.id)
            instruction_box = newest('chat-ai-run-instruction')
            with user:
                instruction_box.value = 'Saludar.'
            step_checkbox = newest('chat-ai-run-stepmode')
            with user:
                step_checkbox.value = False   # de corrido, no paso a paso
            UserInteraction(user, {newest('chat-ai-run-confirm')}, None).click()
            for _ in range(50):
                if len(core.list_project_items('suites', project['id'])) >= run_index:
                    break
                await asyncio.sleep(0.2)
        suites = core.list_project_items('suites', project['id'])
        assert len(suites) == 2                                       # dos corridas con hilo nuevo -> dos Flujos, no uno fusionado
        for suite in suites:
            assert [step['alias'] for step in core.suite_steps(suite)] == ['turno1']   # cada uno arranca su propio turno1, sin chocar
