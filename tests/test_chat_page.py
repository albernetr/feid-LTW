"""Chat: a standalone screen to converse live with a chatbot/conversational API, one turn at a time."""
import asyncio
from app import core, automation


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
    await user.should_see('✓ Guardado como «Turno 1»')                 # the per-turn button is gone once it's saved

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
