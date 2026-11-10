"""The optional model assistant, against a fake model server (no tokens, no network)."""
import asyncio
import json
import pytest
from app import core, llm, agent
from sample_app.fake_llm import FakeLLM


@pytest.fixture
def fake():
    with FakeLLM() as server:
        yield server


def configure(fake, **extra):
    config = {'preset': 'local', 'protocol': 'openai', 'base_url': fake.url + '/v1', 'model': 'modelo-demo', 'auth': 'none', **extra}
    return llm.save_config(config)


def failing_run(sample_app):
    env = core.save('environments', {'name': 'e', 'base_url': sample_app.url, 'variables': {}, 'auth': {'type': 'none'}})
    case = core.save('cases', {'name': 'items', 'method': 'GET', 'path': '/api/items', 'headers': {}, 'query': {}, 'body': None, 'assertions': [{'type': 'status', 'expected': 500}],
                               'variables': {}, 'extract': [], 'timeout': 10})
    run = core.execute_api(case, env)
    return agent.failure_from_run(run)


def test_not_configured_means_not_ready():
    state = llm.status()
    assert not state['ready'] and 'Sin configurar' in state['problem']
    with pytest.raises(llm.LLMError):
        llm.ask('s', 'u')


def test_local_model_needs_no_key_and_works(fake):
    configure(fake)
    assert llm.status()['ready'] and llm.status()['local']
    assert llm.test_connection()['reply'] == 'OK'
    sent = fake.requests[0]
    assert sent['path'] == '/v1/chat/completions' and 'authorization' not in sent['headers']
    assert sent['body']['messages'][0]['role'] == 'system'


def test_config_validation():
    for bad in ({'base_url': 'ftp://x', 'model': 'm'}, {'base_url': 'http://x', 'model': ''}, {'base_url': 'http://x', 'model': 'm', 'timeout': 1}, {'base_url': 'http://x', 'model': 'm', 'protocol': 'raro'}):
        with pytest.raises(ValueError):
            llm.save_config(bad)


def test_key_goes_to_the_credential_store_not_the_settings(fake):
    configure(fake, auth='bearer')
    llm.save_config({**llm.get_config(), 'auth': 'bearer'}, api_key='sk-secreto-123')
    assert core.secret_get(llm.KEY_SECRET) == 'sk-secreto-123'
    assert 'sk-secreto-123' not in json.dumps(core.get('settings', llm.SETTING))
    assert llm.test_connection()['ok']
    assert fake.requests[-1]['headers']['authorization'] == 'Bearer sk-secreto-123'


def test_wrong_key_is_reported_clearly(fake):
    fake.server.required_key = 'Bearer bueno'
    llm.save_config({**llm.get_config(), 'preset': 'local', 'base_url': fake.url + '/v1', 'model': 'modelo-demo', 'auth': 'bearer'}, api_key='malo')
    with pytest.raises(llm.LLMError, match='rechazó las credenciales'):
        llm.test_connection()


def test_missing_key_when_auth_required():
    llm.save_config({'preset': 'openai', 'base_url': 'http://127.0.0.1:9/v1', 'model': 'm', 'auth': 'bearer'})
    assert 'Falta la clave' in llm.status()['problem']


def test_unknown_model_unreachable_server_and_server_error(fake):
    llm.save_config({'base_url': fake.url + '/v1', 'model': 'otro', 'auth': 'none'})
    with pytest.raises(llm.LLMError, match='modelo'):
        llm.test_connection()
    configure(fake)
    fake.server.status = 500
    with pytest.raises(llm.LLMError, match='HTTP 500'):
        llm.test_connection()
    llm.save_config({'base_url': 'http://127.0.0.1:1/v1', 'model': 'm', 'auth': 'none', 'timeout': 5})
    with pytest.raises(llm.LLMError, match='No se pudo conectar'):
        llm.test_connection()


def test_cloud_is_blocked_until_explicitly_allowed():
    cloud = {'preset': 'openai', 'base_url': 'https://api.openai.com/v1', 'model': 'm', 'auth': 'none'}
    llm.save_config(cloud)
    assert not llm.status()['ready'] and 'fuera de esta máquina' in llm.status()['problem']
    with pytest.raises(llm.LLMError, match='fuera de esta máquina'):
        llm.ask('s', 'u')
    llm.save_config({**cloud, 'allow_cloud': True})
    assert llm.status()['ready'] and llm.status()['local'] is False
    assert llm.is_local('http://localhost:11434/v1') and llm.is_local('http://host.docker.internal:12434') and not llm.is_local('https://foo.openai.azure.com/openai/v1')


def test_anthropic_protocol(fake):
    llm.save_config({'preset': 'anthropic', 'protocol': 'anthropic', 'base_url': fake.url, 'model': 'modelo-demo', 'auth': 'x-api-key', 'allow_cloud': True}, api_key='k-ant')
    assert llm.test_connection()['reply'] == 'OK'
    sent = fake.requests[-1]
    assert sent['path'] == '/v1/messages' and sent['headers']['x-api-key'] == 'k-ant' and sent['headers']['anthropic-version']
    assert sent['body']['system'] and sent['body']['messages'][0]['role'] == 'user'


def test_azure_style_key_header(fake):
    llm.save_config({'preset': 'foundry', 'base_url': fake.url + '/openai/v1', 'model': 'modelo-demo', 'auth': 'api-key', 'allow_cloud': True}, api_key='az-key')
    llm.test_connection()
    assert fake.requests[-1]['headers']['api-key'] == 'az-key' and 'authorization' not in fake.requests[-1]['headers']


def test_reasoning_tags_are_stripped(fake):
    configure(fake)
    fake.queue('<think>pensando…</think>Respuesta final')
    assert llm.ask('s', 'u') == 'Respuesta final'


def test_explain_failure_sends_the_brief_without_secrets(fake, sample_app):
    configure(fake)
    core.secret_set('TOKEN_X', 'valor-ultra-secreto')
    failure = failing_run(sample_app)
    failure['brief_markdown'] += '\nAuthorization: Bearer valor-ultra-secreto'
    system, user = llm.explain_messages(failure)
    assert 'valor-ultra-secreto' not in user and '«secreto»' in user and 'debilit' in system
    answer = llm.explain_failure(failure)
    assert 'Qué pasó' in answer
    assert 'valor-ultra-secreto' not in json.dumps(fake.requests[-1]['body'])


def test_generate_spec_validates_and_is_importable(fake):
    configure(fake)
    result = llm.generate_spec('probar el health check')
    assert result['valid'] and result['attempts'] == 1 and result['spec']['cases'][0]['path'] == '/health'
    project = agent.ensure_project('Generado')
    assert len(agent.import_spec(result['spec'], project)['cases']) == 1


def test_generate_spec_repairs_once_then_gives_up(fake):
    configure(fake)
    bad = json.dumps({'format': 'ltw.spec/1', 'cases': [{'name': 'x', 'method': 'FETCH', 'path': '/a'}]})
    good = json.dumps({'format': 'ltw.spec/1', 'cases': [{'name': 'x', 'method': 'GET', 'path': '/a'}]})
    fake.queue(bad, good)
    result = llm.generate_spec('algo')
    assert result['valid'] and result['attempts'] == 2
    assert '$.cases[0].method' in fake.requests[-1]['body']['messages'][-1]['content']
    fake.queue('no es json', bad)
    failed = llm.generate_spec('algo')
    assert not failed['valid'] and failed['errors'] and failed['attempts'] == 2
    with pytest.raises(llm.LLMError):
        llm.generate_spec('   ')


def test_generate_uses_the_contract_digest(fake):
    configure(fake)
    module = core.parse_openapi('openapi: 3.0.0\ninfo: {title: Tienda, version: "1"}\npaths:\n  /api/items:\n    post:\n      summary: Crear\n      requestBody:\n        content:\n          application/json:\n            schema: {type: object, properties: {name: {type: string}}}\n      responses: {"201": {description: ok}}\n')
    llm.generate_spec('crear items', module=module, environment_names=['tienda'])
    sent = fake.requests[-1]['body']['messages'][-1]['content']
    assert 'POST /api/items' in sent and 'name:string' in sent and 'tienda' in sent


async def test_workspace_assistant_screen_off_then_configured_then_generates(user, fake):
    await user.open('/workspace')
    user.find('rail-Agente').click()
    await user.should_see('Asistente sin configurar')
    await user.should_see('Conexión directa (sin registrar)')
    # configure through the module (the form shares it) and re-open: the assistant is on and says it is local
    configure(fake)
    await user.open('/workspace')
    user.find('rail-Agente').click()
    await user.should_see('modelo-demo · modelo local')
    await user.should_see('los datos no salen de esta máquina')
    user.find('Qué quieres probar').type('probar el health check')
    user.find('Generar especificación').click()
    await asyncio.sleep(1.5)  # the model call runs in a worker thread
    await user.should_see('Especificación válida')
    await user.should_see('Importar todo al proyecto')


def test_registered_models_switch_without_mixing_keys(fake):
    a = llm.save_profile({'name': 'A', 'preset': 'local', 'protocol': 'openai', 'base_url': fake.url + '/v1', 'model': 'modelo-a', 'auth': 'bearer'}, api_key='key-a')
    b = llm.save_profile({'name': 'B', 'preset': 'local', 'protocol': 'openai', 'base_url': fake.url + '/v1', 'model': 'modelo-b', 'auth': 'none'})
    assert {p['name'] for p in llm.list_profiles()} == {'A', 'B'}

    llm.activate_profile(a['id'])
    assert llm.active_profile_id() == a['id']
    assert llm.get_config()['model'] == 'modelo-a'
    assert core.secret_get(llm.KEY_SECRET) == 'key-a'

    llm.activate_profile(b['id'])
    assert llm.get_config()['model'] == 'modelo-b'
    assert core.secret_get(llm.KEY_SECRET) is None, "switching to a key-less profile must not keep the previous profile's key"

    with pytest.raises(ValueError):
        llm.save_profile({'name': 'B', 'preset': 'local', 'protocol': 'openai', 'base_url': fake.url + '/v1', 'model': 'x', 'auth': 'none'})  # duplicate name

    llm.delete_profile(a['id'])
    assert a['id'] not in {p['id'] for p in llm.list_profiles()}
    assert core.secret_get(llm.profile_secret_name(a['id'])) is None


CHAT_MESSAGES = [{'who': 'user', 'text': 'Hola, quiero cotizar un seguro'},
                  {'who': 'bot', 'text': '¡Gracias por aceptar! ¿Qué tipo de seguro buscás?'},
                  {'who': 'user', 'text': 'Seguro de vida para mi esposa'},
                  {'who': 'bot', 'text': '¿Cuál es el nombre completo de la persona a asegurar?'}]


def test_judge_conversation_parses_the_models_verdict(fake):
    configure(fake)
    fake.queue(json.dumps({'pass': True, 'reasoning': 'El bot pidió el tipo de seguro y el nombre de la persona a asegurar, como esperaba la HU.'}))
    result = llm.judge_conversation(CHAT_MESSAGES, 'El bot debe pedir tipo de seguro y nombre del asegurado.')
    assert result['pass'] is True
    assert 'tipo de seguro' in result['reasoning']
    sent = fake.requests[-1]['body']['messages'][-1]['content']
    assert 'El bot debe pedir tipo de seguro' in sent and 'Vos: Hola, quiero cotizar un seguro' in sent and 'Bot: ¡Gracias por aceptar!' in sent


def test_judge_conversation_without_explicit_context_still_sends_the_transcript(fake):
    configure(fake)
    fake.queue(json.dumps({'pass': False, 'reasoning': 'La conversación no llegó a una conclusión clara.'}))
    result = llm.judge_conversation(CHAT_MESSAGES, '')
    assert result['pass'] is False
    system, user = llm.verdict_messages(CHAT_MESSAGES, '')
    assert 'Criterio contra el que evaluar' not in user   # sin contexto explícito, no se manda una sección vacía
    assert 'inferilo' in system                            # pero el system prompt ya le dice que infiera


def test_judge_conversation_raises_a_clear_error_when_the_model_does_not_return_json(fake):
    configure(fake)
    fake.queue('no sé qué decir')
    with pytest.raises(llm.LLMError, match='no es el JSON esperado'):
        llm.judge_conversation(CHAT_MESSAGES, 'algún criterio')


def test_judge_conversation_requires_at_least_one_turn(fake):
    configure(fake)
    with pytest.raises(llm.LLMError, match='No hay turnos'):
        llm.judge_conversation([], 'algún criterio')


def test_judge_conversation_redacts_secrets_from_the_transcript(fake):
    configure(fake)
    core.secret_set('TOKEN_Y', 'otro-secreto-123')
    fake.queue(json.dumps({'pass': True, 'reasoning': 'ok'}))
    messages = CHAT_MESSAGES + [{'who': 'bot', 'text': 'Tu token es otro-secreto-123'}]
    llm.judge_conversation(messages, '')
    assert 'otro-secreto-123' not in json.dumps(fake.requests[-1]['body'])


def test_suggest_next_turn_parses_free_text(fake):
    configure(fake)
    fake.queue(json.dumps({'text': 'Seguro de auto', 'option': None, 'done': False, 'collected': {}}))
    result = llm.suggest_next_turn(CHAT_MESSAGES, 'Cotizar un seguro de auto.')
    assert result == {'text': 'Seguro de auto', 'option': None, 'done': False, 'collected': {}}
    sent = fake.requests[-1]['body']['messages'][-1]['content']
    assert 'Cotizar un seguro de auto.' in sent and 'Vos: Hola, quiero cotizar un seguro' in sent


def test_suggest_next_turn_picks_an_offered_option_by_its_exact_text(fake):
    configure(fake)
    messages = CHAT_MESSAGES + [{'who': 'bot', 'text': '¿Preferís mensual o anual?', 'options': ['Mensual', 'Anual']}]
    fake.queue(json.dumps({'text': '', 'option': 'Anual', 'done': False, 'collected': {}}))
    result = llm.suggest_next_turn(messages, 'Elegí siempre el plan anual.')
    assert result['option'] == 'Anual'
    sent = fake.requests[-1]['body']['messages'][-1]['content']
    assert 'Mensual | Anual' in sent   # el modelo necesita ver las opciones ofrecidas, tal cual, para elegir una


def test_suggest_next_turn_reports_data_already_collected_and_when_to_stop(fake):
    configure(fake)
    fake.queue(json.dumps({'text': '', 'option': None, 'done': True, 'collected': {'nombre': 'Ana'}}))
    result = llm.suggest_next_turn(CHAT_MESSAGES, 'Conseguí el nombre del asegurado.', data_goals=['nombre del asegurado'])
    assert result['done'] is True and result['collected'] == {'nombre': 'Ana'}
    sent = fake.requests[-1]['body']['messages'][-1]['content']
    assert 'nombre del asegurado' in sent


def test_suggest_next_turn_raises_a_clear_error_when_the_model_does_not_return_json(fake):
    configure(fake)
    fake.queue('no sé qué decir')
    with pytest.raises(llm.LLMError, match='no es el JSON esperado'):
        llm.suggest_next_turn(CHAT_MESSAGES, 'algún objetivo')


API_RUN = {'id': 'r1', 'type': 'api', 'case_name': 'Crear pedido', 'http_status': 422,
           'request': {'method': 'POST', 'url': 'http://x/api/items', 'body': {'name': ''}},
           'response': {'body': '{"error": "name is required"}'},
           'assertions': [{'rule': {'type': 'status', 'expected': 201}, 'passed': False, 'actual': 422}]}

UI_RUN = {'id': 'r2', 'type': 'ui', 'case_name': 'Login UI',
          'steps': [{'index': 0, 'action': 'navigate', 'passed': True}, {'index': 1, 'action': 'fill', 'passed': True},
                    {'index': 2, 'action': 'assert_visible', 'passed': False}]}


def test_judge_run_parses_the_models_verdict_for_an_api_run(fake):
    configure(fake)
    fake.queue(json.dumps({'pass': False, 'reasoning': 'La aserción de status esperaba 201 y llegó 422 — el caso no pasa.'}))
    result = llm.judge_run(API_RUN, 'El endpoint debe crear el pedido y devolver 201.')
    assert result['pass'] is False
    assert '422' in result['reasoning']
    sent = fake.requests[-1]['body']['messages'][-1]['content']
    assert 'Crear pedido' in sent and 'POST http://x/api/items' in sent and 'FALLÓ' in sent


def test_judge_run_formats_ui_steps_instead_of_request_response(fake):
    configure(fake)
    fake.queue(json.dumps({'pass': False, 'reasoning': 'El tercer paso no encontró el elemento esperado.'}))
    result = llm.judge_run(UI_RUN, '')
    assert result['pass'] is False
    sent = fake.requests[-1]['body']['messages'][-1]['content']
    assert 'Paso 1: navigate — OK' in sent and 'Paso 3: assert_visible — FALLÓ' in sent


def test_judge_run_raises_a_clear_error_when_the_model_does_not_return_json(fake):
    configure(fake)
    fake.queue('no sé qué decir')
    with pytest.raises(llm.LLMError, match='no es el JSON esperado'):
        llm.judge_run(API_RUN, 'algún criterio')


def test_judge_run_requires_a_run(fake):
    configure(fake)
    with pytest.raises(llm.LLMError, match='No hay corrida'):
        llm.judge_run(None, 'algún criterio')


# --------------------------------------------------------------------------- Especificación: generar/refinar HU y
# Casos de prueba, chat libre (Fase 2)

def test_generate_user_story_validates_and_cleans_criteria(fake):
    configure(fake)
    fake.queue(json.dumps({'title': 'Pagar', 'as_a': 'cliente', 'i_want': 'pagar', 'so_that': 'comprar',
                          'criteria': ['veo confirmación', '  ', 'recibo un email']}))
    result = llm.generate_user_story('una historia para pagar')
    assert result['valid'] and result['attempts'] == 1
    assert [c['text'] for c in result['story']['criteria']] == ['veo confirmación', 'recibo un email']
    with pytest.raises(llm.LLMError):
        llm.generate_user_story('   ')


def test_generate_user_story_repairs_once_then_gives_up(fake):
    configure(fake)
    fake.queue('no es json', json.dumps({'title': 'Pagar'}))
    result = llm.generate_user_story('algo')
    assert result['valid'] and result['attempts'] == 2
    fake.queue('no es json', 'tampoco')
    failed = llm.generate_user_story('algo')
    assert not failed['valid'] and failed['attempts'] == 2


def test_generate_user_story_includes_the_feature_in_the_prompt(fake):
    configure(fake)
    fake.queue(json.dumps({'title': 'x'}))
    llm.generate_user_story('algo', feature={'name': 'Checkout', 'description': 'pagos'})
    sent = fake.requests[-1]['body']['messages'][-1]['content']
    assert 'Checkout' in sent


def test_generate_user_story_cleans_gherkin_criteria_and_business_context(fake):
    configure(fake)
    fake.queue(json.dumps({
        'title': 'Pagar', 'as_a': 'cliente', 'i_want': 'pagar', 'so_that': 'comprar',
        'criteria': [{'text': 'Pago válido', 'given': 'una tarjeta válida', 'when': 'confirma el pago', 'then': 'se aprueba'},
                     'sin estructurar', {'given': '', 'when': '', 'then': ''}],
        'definition_of_ready': ['Mockups aprobados', '  ', 'Dependencias resueltas'],
        'definition_of_done': ['Pruebas pasando'],
        'business_rules': 'Solo tarjetas propias', 'assumptions': 'El banco responde rápido',
        'risks': 'Picos de tráfico', 'out_of_scope': 'No cubre cuotas'}))
    result = llm.generate_user_story('una historia para pagar')
    assert result['valid']
    story = result['story']
    assert len(story['criteria']) == 2   # el criterio vacío del todo se descarta
    assert story['criteria'][0] == {'text': 'Pago válido', 'given': 'una tarjeta válida', 'when': 'confirma el pago', 'then': 'se aprueba'}
    assert story['criteria'][1] == {'text': 'sin estructurar', 'given': '', 'when': '', 'then': ''}
    assert story['definition_of_ready'] == ['Mockups aprobados', 'Dependencias resueltas']
    assert story['definition_of_done'] == ['Pruebas pasando']
    assert story['business_rules'] == 'Solo tarjetas propias' and story['assumptions'] == 'El banco responde rápido'
    assert story['risks'] == 'Picos de tráfico' and story['out_of_scope'] == 'No cubre cuotas'


def test_generate_test_cases_from_criteria_describes_gherkin_scenarios_in_the_prompt(fake):
    configure(fake)
    fake.queue(json.dumps({'test_cases': [{'title': 'x'}]}))
    llm.generate_test_cases(criteria=[{'text': 'Pago válido', 'given': 'una tarjeta válida', 'when': 'confirma el pago', 'then': 'se aprueba la compra'}])
    sent = fake.requests[-1]['body']['messages'][-1]['content']
    assert 'Dado una tarjeta válida, cuando confirma el pago, entonces se aprueba la compra' in sent


def test_generate_test_cases_from_story_or_criteria_requires_at_least_one(fake):
    configure(fake)
    with pytest.raises(llm.LLMError, match='una historia de usuario o al menos un criterio'):
        llm.generate_test_cases()
    fake.queue(json.dumps({'test_cases': [{'title': 'Caso 1'}, {'title': 'Caso 2', 'priority': 'bogus', 'type': 'bogus'}]}))
    result = llm.generate_test_cases(criteria=[{'text': 'veo confirmación'}])
    assert result['valid'] and len(result['test_cases']) == 2
    assert result['test_cases'][1]['priority'] == 'medium' and result['test_cases'][1]['type'] == 'functional'   # valor inválido cae al default


def test_generate_test_cases_from_a_story_includes_its_criteria_and_the_environment(fake):
    configure(fake)
    fake.queue(json.dumps({'test_cases': [{'title': 'Caso 1'}]}))
    story = {'title': 'Pagar', 'as_a': 'cliente', 'i_want': 'pagar', 'so_that': 'comprar', 'criteria': [{'text': 'veo confirmación'}]}
    llm.generate_test_cases(story=story, environment={'name': 'qa', 'base_url': 'https://qa.example.com'})
    sent = fake.requests[-1]['body']['messages'][-1]['content']
    assert 'Pagar' in sent and 'veo confirmación' in sent and 'qa.example.com' in sent


def test_generate_test_cases_rejects_an_empty_list(fake):
    configure(fake)
    fake.queue(json.dumps({'test_cases': []}))
    result = llm.generate_test_cases(criteria=[{'text': 'x'}])
    assert not result['valid']


def test_refine_spec_item_user_story_and_test_case(fake):
    configure(fake)
    fake.queue(json.dumps({'title': 'Pagar', 'as_a': 'cliente', 'i_want': 'pagar', 'so_that': 'comprar', 'criteria': ['más específico']}))
    result = llm.refine_spec_item('user_story', {'title': 'Pagar'}, 'hacelo más específico')
    assert result['valid'] and result['item']['criteria'][0]['text'] == 'más específico'

    fake.queue(json.dumps({'title': 'Pago válido', 'preconditions': 'sesión iniciada', 'steps': [], 'priority': 'high', 'type': 'functional'}))
    result = llm.refine_spec_item('test_case', {'title': 'Pago válido'}, 'agregá la precondición')
    assert result['valid'] and result['item']['preconditions'] == 'sesión iniciada'

    with pytest.raises(ValueError):
        llm.refine_spec_item('bogus', {}, 'x')
    with pytest.raises(llm.LLMError, match='qué querés refinar'):
        llm.refine_spec_item('user_story', {'title': 'x'}, '   ')


def test_spec_chat_reply_is_plain_text_and_carries_context(fake):
    configure(fake)
    fake.queue('Te recomiendo agregar un criterio sobre el caso negativo.')
    reply = llm.spec_chat_reply([], '¿qué le falta a esta historia?', {'kind': 'historia de usuario', 'current': {'title': 'Pagar'}})
    assert reply == 'Te recomiendo agregar un criterio sobre el caso negativo.'
    sent = fake.requests[-1]['body']['messages'][-1]['content']
    assert 'Pagar' in sent
    with pytest.raises(llm.LLMError):
        llm.spec_chat_reply([], '   ')


# --------------------------------------------------------------------------- importar: texto y/o imagen (Fase 3)

def test_generate_from_source_requires_text_or_image(fake):
    configure(fake)
    with pytest.raises(llm.LLMError, match='texto, una imagen'):
        llm.generate_from_source()


def test_generate_from_source_from_text_only_builds_a_plain_string_message(fake):
    configure(fake)
    fake.queue(json.dumps({'story': {'title': 'Pagar', 'criteria': ['veo confirmación']}, 'test_cases': [{'title': 'Caso 1'}]}))
    result = llm.generate_from_source(text='El cliente debe poder pagar con tarjeta.')
    assert result['valid'] and result['story']['title'] == 'Pagar' and len(result['test_cases']) == 1
    sent = fake.requests[-1]['body']['messages'][-1]['content']
    assert isinstance(sent, str) and 'pagar con tarjeta' in sent   # sin imagen: el contenido sigue siendo texto plano


def test_generate_from_source_with_an_image_sends_a_vision_content_block(fake):
    configure(fake)
    fake.queue(json.dumps({'story': {'title': 'Pagar'}, 'test_cases': []}))
    image_b64 = 'ZmFrZS1wbmc='   # 'fake-png' en base64, el contenido real no importa para este test
    result = llm.generate_from_source(image_b64=image_b64)
    assert result['valid'] and result['story']['title'] == 'Pagar' and result['test_cases'] == []
    sent = fake.requests[-1]['body']['messages'][-1]['content']
    assert isinstance(sent, list)
    image_block = next(b for b in sent if b['type'] != 'text')
    assert image_block['type'] == 'image_url' and image_b64 in image_block['image_url']['url']   # protocolo openai por default


def test_generate_from_source_with_an_image_uses_the_anthropic_block_shape(fake):
    configure(fake, protocol='anthropic', auth='none')
    fake.queue(json.dumps({'story': {'title': 'Pagar'}, 'test_cases': []}))
    llm.generate_from_source(text='algo', image_b64='ZmFrZS1wbmc=', image_media_type='image/jpeg')
    sent = fake.requests[-1]['body']['messages'][-1]['content']
    image_block = next(b for b in sent if b['type'] != 'text')
    assert image_block == {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': 'ZmFrZS1wbmc='}}


def test_generate_from_source_rejects_a_bundle_without_a_valid_story(fake):
    configure(fake)
    fake.queue('no es json', json.dumps({'story': {}}))
    result = llm.generate_from_source(text='algo')
    assert not result['valid'] and result['attempts'] == 2
