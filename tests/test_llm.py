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
