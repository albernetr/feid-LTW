"""Optional language-model assistant. Nothing here runs unless the user configures a connection; without valid credentials/URL the feature stays off.

Two wire protocols cover everything: OpenAI-compatible chat completions (Ollama, Docker Model Runner, LM Studio, vLLM, llama.cpp, Podman, OpenAI,
Azure AI Foundry...) and Anthropic Messages. Plain httpx, no SDKs. The API key lives in the OS credential store like every other secret.
Whatever the model returns is advice: generated specs go through the same validator as any agent spec and nothing is saved without a person accepting it."""
import json
import re
from urllib.parse import urlsplit
import httpx
from . import core, agent

SETTING = 'llm_config'
KEY_SECRET = 'LTW_LLM_API_KEY'
PROTOCOLS = {'openai': 'Compatible con OpenAI (/chat/completions)', 'anthropic': 'Anthropic (/v1/messages)'}
AUTH_STYLES = {'none': 'Sin clave', 'bearer': 'Authorization: Bearer', 'api-key': 'Cabecera api-key (Azure)', 'x-api-key': 'Cabecera x-api-key (Anthropic)'}
LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1', 'host.docker.internal', 'host.containers.internal'}
MAX_PROMPT_CHARS = 14000
MAX_OUTPUT_TOKENS = 4096

PRESETS = {
    'ollama': {'label': 'Ollama (local)', 'protocol': 'openai', 'base_url': 'http://127.0.0.1:11434/v1', 'model': 'llama3.1', 'auth': 'none'},
    'docker': {'label': 'Docker Model Runner (local)', 'protocol': 'openai', 'base_url': 'http://127.0.0.1:12434/engines/v1', 'model': 'ai/llama3.2', 'auth': 'none'},
    'lmstudio': {'label': 'LM Studio (local)', 'protocol': 'openai', 'base_url': 'http://127.0.0.1:1234/v1', 'model': '', 'auth': 'none'},
    'local': {'label': 'Otro servidor local (Podman, vLLM, llama.cpp…)', 'protocol': 'openai', 'base_url': 'http://127.0.0.1:8000/v1', 'model': '', 'auth': 'none'},
    'foundry': {'label': 'Azure AI Foundry / Azure OpenAI', 'protocol': 'openai', 'base_url': 'https://<recurso>.openai.azure.com/openai/v1', 'model': '<nombre del despliegue>', 'auth': 'api-key'},
    'openai': {'label': 'OpenAI (clave de API)', 'protocol': 'openai', 'base_url': 'https://api.openai.com/v1', 'model': '', 'auth': 'bearer'},
    'anthropic': {'label': 'Anthropic (clave de API)', 'protocol': 'anthropic', 'base_url': 'https://api.anthropic.com', 'model': 'claude-sonnet-5-5', 'auth': 'x-api-key'},
    'custom': {'label': 'Personalizado', 'protocol': 'openai', 'base_url': '', 'model': '', 'auth': 'bearer'},
}


class LLMError(RuntimeError):
    """Anything that stops the assistant: not configured, cloud not allowed, unreachable, rejected credentials, unusable answer."""


# --------------------------------------------------------------------------- configuration

def is_local(base_url):
    host = (urlsplit(base_url or '').hostname or '').lower()
    return host in LOCAL_HOSTS or host.endswith('.localhost')


def get_config():
    config = core.get_setting(SETTING) or {}
    return {'preset': config.get('preset', 'ollama'), 'protocol': config.get('protocol', 'openai'), 'base_url': config.get('base_url', ''),
            'model': config.get('model', ''), 'auth': config.get('auth', 'none'), 'allow_cloud': bool(config.get('allow_cloud', False)),
            'timeout': float(config.get('timeout', 120))}


def save_config(config, api_key=None):
    """Stores the connection (without the key). api_key: str replaces it, '' keeps the stored one, None leaves it alone."""
    clean = {'preset': config.get('preset', 'custom'), 'protocol': config.get('protocol', 'openai'), 'base_url': (config.get('base_url') or '').strip(),
             'model': (config.get('model') or '').strip(), 'auth': config.get('auth', 'none'), 'allow_cloud': bool(config.get('allow_cloud', False)),
             'timeout': float(config.get('timeout') or 120)}
    if clean['protocol'] not in PROTOCOLS or clean['auth'] not in AUTH_STYLES:
        raise ValueError('Protocolo o tipo de autenticación no reconocido')
    if not re.match(r'^https?://[^\s/]+', clean['base_url']):
        raise ValueError('La URL debe empezar por http:// o https://')
    if not clean['model']:
        raise ValueError('Indica el modelo (o el nombre del despliegue)')
    if not 5 <= clean['timeout'] <= 600:
        raise ValueError('El tiempo de espera debe estar entre 5 y 600 segundos')
    core.set_setting(SETTING, clean)
    if api_key:
        core.secret_set(KEY_SECRET, api_key)
    return clean


def clear_config():
    core.secret_delete(KEY_SECRET)
    core.delete('settings', SETTING)


# --------------------------------------------------------------------------- registered models (several, switch on demand)
# Each profile is its own saved connection with its own key. "Activating" one copies it into the single live connection
# above (and its key, never leaving two keys live for the same slot) so every existing call (ask/status/explain_failure/
# generate_spec) keeps working unchanged, from anywhere in the app that already uses llm.ask()/llm.status().

ACTIVE_PROFILE_SETTING = 'llm_active_profile'
PROFILE_FIELDS = ('preset', 'protocol', 'base_url', 'model', 'auth', 'allow_cloud', 'timeout')


def profile_secret_name(profile_id):
    return f'LTW_LLM_PROFILE_{profile_id}'


def list_profiles():
    return sorted(core.list_items('llm_profiles'), key=lambda p: (p.get('name') or '').lower())


def get_profile(profile_id):
    return core.get('llm_profiles', profile_id) if profile_id else None


def active_profile_id():
    return core.get_setting(ACTIVE_PROFILE_SETTING)


def save_profile(profile, api_key=None):
    """Registers or updates a named model so it can be picked later without retyping URL/key. api_key: str replaces
    it, falsy leaves the profile's own stored key untouched."""
    profile_id = profile.get('id') or core.uid()
    clean = {'id': profile_id, 'name': (profile.get('name') or '').strip(), 'preset': profile.get('preset', 'custom'),
             'protocol': profile.get('protocol', 'openai'), 'base_url': (profile.get('base_url') or '').strip(),
             'model': (profile.get('model') or '').strip(), 'auth': profile.get('auth', 'none'),
             'allow_cloud': bool(profile.get('allow_cloud', False)), 'timeout': float(profile.get('timeout') or 120)}
    if not clean['name']:
        raise ValueError('Indica un nombre para identificar este modelo (p. ej. «Foundry — GPT-6-Astra»)')
    if clean['protocol'] not in PROTOCOLS or clean['auth'] not in AUTH_STYLES:
        raise ValueError('Protocolo o tipo de autenticación no reconocido')
    if not re.match(r'^https?://[^\s/]+', clean['base_url']):
        raise ValueError('La URL debe empezar por http:// o https://')
    if not clean['model']:
        raise ValueError('Indica el modelo (o el nombre del despliegue)')
    if not 5 <= clean['timeout'] <= 600:
        raise ValueError('El tiempo de espera debe estar entre 5 y 600 segundos')
    if any(p['name'].strip().lower() == clean['name'].lower() for p in list_profiles() if p['id'] != profile_id):
        raise ValueError(f'Ya hay un modelo registrado llamado «{clean["name"]}»')
    core.save('llm_profiles', clean)
    if api_key:
        core.secret_set(profile_secret_name(profile_id), api_key)
    return clean


def delete_profile(profile_id):
    core.secret_delete(profile_secret_name(profile_id))
    core.delete('llm_profiles', profile_id)
    if active_profile_id() == profile_id:
        core.delete('settings', ACTIVE_PROFILE_SETTING)


def activate_profile(profile_id):
    """Makes a registered model the one ask()/status() actually use, copying its key into the single live slot
    so switching never mixes one model's credentials with another's."""
    profile = get_profile(profile_id)
    if not profile:
        raise ValueError('Ese modelo ya no existe; actualiza la lista.')
    key = core.secret_get(profile_secret_name(profile_id))
    if not key:
        core.secret_delete(KEY_SECRET)
    save_config({field: profile[field] for field in PROFILE_FIELDS}, api_key=key or None)
    core.set_setting(ACTIVE_PROFILE_SETTING, profile_id)


def status(config=None):
    """{'ready': bool, 'local': bool|None, 'problem': str|None, 'summary': str} - the single place that decides whether the assistant may be used."""
    config = config or get_config()
    if not config['base_url'] or not config['model']:
        return {'ready': False, 'local': None, 'problem': 'Sin configurar: indica la URL y el modelo.', 'summary': 'Asistente sin configurar'}
    local = is_local(config['base_url'])
    where = 'modelo local' if local else 'servicio en la nube'
    summary = f'{config["model"]} · {where}'
    if config['auth'] != 'none' and not core.secret_get(KEY_SECRET):
        return {'ready': False, 'local': local, 'problem': 'Falta la clave de acceso (o la variable de entorno LTW_LLM_API_KEY).', 'summary': summary}
    if not local and not config['allow_cloud']:
        return {'ready': False, 'local': local, 'problem': 'Este destino no es local: activa «Permitir enviar datos fuera de esta máquina» para usarlo.', 'summary': summary}
    return {'ready': True, 'local': local, 'problem': None, 'summary': summary}


# --------------------------------------------------------------------------- transport

def _endpoint(config):
    base = config['base_url'].rstrip('/')
    if config['protocol'] == 'anthropic':
        return base + ('/messages' if base.endswith('/v1') else '/v1/messages')
    return base + '/chat/completions'


def _headers(config, key):
    headers = {'Content-Type': 'application/json'}
    if config['protocol'] == 'anthropic':
        headers['anthropic-version'] = '2023-06-01'
    if config['auth'] != 'none' and key:
        if config['auth'] == 'bearer':
            headers['Authorization'] = f'Bearer {key}'
        else:
            headers['x-api-key' if config['auth'] == 'x-api-key' else 'api-key'] = key
    return headers


def _payload(config, system, user, max_tokens):
    if config['protocol'] == 'anthropic':
        return {'model': config['model'], 'max_tokens': max_tokens, 'system': system, 'messages': [{'role': 'user', 'content': user}]}
    return {'model': config['model'], 'max_tokens': max_tokens, 'temperature': 0.2, 'stream': False,
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]}


def _text_of(config, data):
    if config['protocol'] == 'anthropic':
        text = ''.join(block.get('text', '') for block in data.get('content', []) if isinstance(block, dict))
    else:
        choices = data.get('choices') or []
        text = ((choices[0].get('message') or {}).get('content') or '') if choices else ''
        if isinstance(text, list):                                                   # some servers return content parts
            text = ''.join(part.get('text', '') for part in text if isinstance(part, dict))
    text = re.sub(r'<think>.*?</think>', '', text or '', flags=re.S).strip()        # reasoning models that inline their thoughts
    if not text:
        raise LLMError('El modelo respondió sin texto. Prueba con otro modelo o revisa su configuración.')
    return text


def _explain_http_error(response, config):
    code = response.status_code
    try:
        detail = response.json()
        detail = (detail.get('error') or detail) if isinstance(detail, dict) else detail
        detail = detail.get('message') if isinstance(detail, dict) else str(detail)
    except ValueError:
        detail = response.text
    detail = (detail or '')[:300]
    if code in (401, 403):
        return f'El servicio rechazó las credenciales (HTTP {code}). Revisa la clave y el tipo de autenticación. {detail}'
    if code == 404:
        return f'No se encontró la ruta o el modelo (HTTP 404). Revisa la URL y el nombre del modelo «{config["model"]}». {detail}'
    if code == 429:
        return f'El servicio limitó las peticiones (HTTP 429). Espera un momento. {detail}'
    return f'El servicio respondió HTTP {code}. {detail}'


def ask(system, user, config=None, max_tokens=MAX_OUTPUT_TOKENS, check=True, key_override=None):
    """One round trip to the configured model. check=False skips the cloud gate (only for the harmless connection test).
    key_override: use this key instead of the one stored for the active connection — for testing a registered model's
    own key before (or without) activating it."""
    config = config or get_config()
    state = status(config)
    if check and not state['ready']:
        raise LLMError(state['problem'])
    if not check and state['problem'] and 'clave' in state['problem'] and key_override is None:
        raise LLMError(state['problem'])
    key = key_override if key_override is not None else (core.secret_get(KEY_SECRET) if config['auth'] != 'none' else None)
    headers = _headers(config, key)
    payload = _payload(config, system, user, max_tokens)
    try:
        response = httpx.post(_endpoint(config), headers=headers, json=payload, timeout=config['timeout'])
        for _ in range(3):  # newer OpenAI-family (reasoning) models reject params older ones accept, and can spend the
            if config['protocol'] != 'openai':                                        # whole token budget "thinking" invisibly, leaving no visible text
                break
            if response.status_code == 400:
                text = response.text
                if 'max_tokens' in payload and 'max_completion_tokens' in text:
                    payload['max_completion_tokens'] = payload.pop('max_tokens')
                elif 'temperature' in payload and "'temperature'" in text:
                    payload.pop('temperature')
                else:
                    break
            elif response.status_code < 400:
                try:
                    choices = (response.json() or {}).get('choices') or []
                except ValueError:
                    break
                cut_off_while_reasoning = choices and choices[0].get('finish_reason') == 'length' and not (choices[0].get('message') or {}).get('content')
                token_field = 'max_completion_tokens' if 'max_completion_tokens' in payload else 'max_tokens'
                if cut_off_while_reasoning and payload.get(token_field, 0) < MAX_OUTPUT_TOKENS:
                    payload[token_field] = MAX_OUTPUT_TOKENS
                else:
                    break
            else:
                break
            response = httpx.post(_endpoint(config), headers=headers, json=payload, timeout=config['timeout'])
    except httpx.TimeoutException:
        raise LLMError(f'El modelo no respondió en {int(config["timeout"])} s. Los modelos locales grandes pueden tardar: sube el tiempo de espera.')
    except httpx.TransportError as exc:
        raise LLMError(f'No se pudo conectar con {config["base_url"]}: ¿está el servidor o el modelo levantado? ({type(exc).__name__})')
    if response.status_code >= 400:
        raise LLMError(_explain_http_error(response, config))
    try:
        return _text_of(config, response.json())
    except ValueError:
        raise LLMError('La respuesta del servicio no es JSON: ¿la URL apunta al endpoint correcto (termina en /v1)?')


def test_connection(config=None, key_override=None):
    """Sends a one-word prompt; carries no workspace data, so it is allowed even when cloud use is not."""
    config = config or get_config()
    text = ask('Responde únicamente con la palabra OK.', 'ping', config, max_tokens=16, check=False, key_override=key_override)
    return {'ok': True, 'reply': text[:80], 'summary': status(config)['summary']}


# --------------------------------------------------------------------------- what leaves the machine

def redact(text):
    """Removes every stored secret value (and the model key) from text about to be sent."""
    for name in list(core.secret_names()) + [KEY_SECRET]:
        value = core.secret_get(name)
        if value and len(value) >= 4:
            text = text.replace(value, '«secreto»')
    return text


def _clip(text, limit=MAX_PROMPT_CHARS):
    return text if len(text) <= limit else text[:limit] + '\n… [recortado]'


EXPLAIN_SYSTEM = (
    'Eres un ingeniero senior de QA y backend. Recibes el informe de una prueba de API que falló, generado por Local Test Workspace. '
    'Responde en español, breve y concreto, con estas secciones en Markdown: **Qué pasó**, **Causa más probable**, **Dónde corregir** y **Siguiente paso**. '
    'Reglas: la corrección va en el servicio, nunca debilitando ni borrando aserciones (salvo que el contrato haya cambiado a propósito, y entonces dilo). '
    'El diagnóstico del informe es heurístico: contrástalo con la evidencia. No inventes archivos ni funciones que no aparezcan en el informe; si falta información, di cuál.')


def explain_messages(failure):
    """(system, user) exactly as they will be sent - the UI shows this before anything leaves the machine."""
    return EXPLAIN_SYSTEM, redact(_clip(failure['brief_markdown']))


def explain_failure(failure, config=None):
    system, user = explain_messages(failure)
    return ask(system, user, config)


# --------------------------------------------------------------------------- generating cases

GENERATE_SYSTEM = f'''Eres un ingeniero de QA. Conviertes una descripción (y, si se da, un resumen de contrato OpenAPI) en una especificación JSON de pruebas de API con formato "ltw.spec/1".
Responde SOLO con un objeto JSON válido, sin texto antes ni después. Estructura:
{{"format": "ltw.spec/1", "name": "...", "environments": [{{"name": "...", "base_url": "http://..."}}],
 "cases": [{{"name": "...", "method": "GET|POST|PUT|PATCH|DELETE", "path": "/ruta", "environment": "...", "headers": {{}}, "query": {{}}, "body": {{}},
   "assertions": [{{"type": "status", "expected": 200}}, {{"type": "json_exists", "path": "$.id"}}], "extract": [{{"name": "id", "source": "json", "path": "$.id"}}], "tags": []}}],
 "suites": [{{"name": "...", "steps": [{{"case": "nombre de un caso", "alias": "paso1", "enrich": [{{"action": "set", "target": "headers", "path": "Authorization", "source": {{"type": "template", "value": "Bearer {{{{@paso1:$.token}}}}"}}}}]}}]}}]}}
Tipos de aserción válidos: {', '.join(sorted(core.ASSERTION_TYPES))}.
Reglas: rutas JSON con sintaxis $.a.b[0].c; variables {{{{nombre}}}}; secretos solo por nombre como {{{{secret:NOMBRE}}}}, JAMÁS valores reales de credenciales; cada caso con al menos una aserción de estado y otra sobre el cuerpo cuando haya cuerpo JSON;
los nombres de casos y ambientes son únicos; los pasos de una suite solo pueden enriquecerse con pasos anteriores; no inventes endpoints que no estén en la descripción o el contrato; si usas ambientes ya existentes, repite su nombre sin definirlos de nuevo.'''


def operations_digest(module, limit=60):
    """Compact text of an imported OpenAPI module: enough for the model, small enough for a local one."""
    lines = [f'Contrato «{module["name"]}» {module.get("version", "")}']
    for operation in module.get('operations', [])[:limit]:
        params = ', '.join(f'{p.get("name")}({p.get("in")}{"*" if p.get("required") else ""})' for p in operation.get('parameters', []) if isinstance(p, dict))
        body = ''
        for media in ((operation.get('requestBody') or {}).get('content') or {}).values():
            props = ((media.get('schema') or {}).get('properties') or {}) if isinstance(media, dict) else {}
            body = ' body{' + ', '.join(f'{k}:{(v or {}).get("type", "?")}' for k, v in list(props.items())[:15]) + '}' if props else ''
        codes = ','.join(sorted(str(c) for c in (operation.get('responses') or {})))
        lines.append(f'- {operation["method"]} {operation["path"]} — {operation.get("summary", "")} [{params}]{body} → {codes}')
    if len(module.get('operations', [])) > limit:
        lines.append(f'… y {len(module["operations"]) - limit} operaciones más')
    return '\n'.join(lines)


def _extract_json(text):
    fenced = re.search(r'```(?:json)?\s*(.*?)```', text, flags=re.S)
    candidate = fenced.group(1) if fenced else text
    start, end = candidate.find('{'), candidate.rfind('}')
    if start < 0 or end <= start:
        raise ValueError('La respuesta no contiene un objeto JSON')
    return json.loads(candidate[start:end + 1])


def generate_messages(description, module=None, environment_names=()):
    parts = [f'Descripción de lo que hay que probar:\n{description.strip()}']
    if module:
        parts.append(operations_digest(module))
    if environment_names:
        parts.append('Ambientes que ya existen (úsalos por nombre): ' + ', '.join(environment_names))
    return GENERATE_SYSTEM, redact(_clip('\n\n'.join(parts)))


def generate_spec(description, module=None, environment_names=(), config=None, attempts=2):
    """{'spec', 'valid', 'errors', 'warnings', 'raw', 'attempts'}. One automatic repair round when the validator complains."""
    if not (description or '').strip():
        raise LLMError('Describe qué quieres probar.')
    system, user = generate_messages(description, module, environment_names)
    raw, errors, spec = '', [], None
    for attempt in range(1, attempts + 1):
        raw = ask(system, user, config)
        try:
            spec = _extract_json(raw)
            result = agent.validate_spec(spec, known_environments=environment_names)
        except ValueError as exc:
            spec, result = None, {'valid': False, 'errors': [{'path': '$', 'message': f'JSON no válido: {exc}'}], 'warnings': []}
        if result['valid']:
            return {'spec': spec, 'valid': True, 'errors': [], 'warnings': result['warnings'], 'raw': raw, 'attempts': attempt}
        errors = result['errors']
        user = redact(_clip(user.split('\n\nTu respuesta anterior')[0] + '\n\nTu respuesta anterior tenía estos errores de validación; devuelve el JSON completo corregido:\n' +
                            '\n'.join(f'- {e["path"]}: {e["message"]}' for e in errors[:15])))
    return {'spec': spec, 'valid': False, 'errors': errors, 'warnings': [], 'raw': raw, 'attempts': attempts}


# --------------------------------------------------------------------------- judging a chat conversation
# Not "did the request match the contract" (that's what assertions already check on a saved turn-as-case) but
# "does this conversation actually satisfy what it was meant to prove" — a chat has no assertions of its own
# until a turn gets frozen into a case, and even then they're mechanical (status code, a field exists). The
# three sources of criteria (explicit HU text, a linked Funcionalidad, or just the case's own name/notes) are
# resolved by the caller (chat_page.py knows about Funcionalidades; this module doesn't) and handed in as one
# `context_text` string — empty means "infer it from the conversation itself", which the prompt already covers.

VERDICT_SYSTEM_FINAL = (
    'Eres un QA senior. Te paso una conversación con un chatbot y, si existe, el criterio contra el que debe '
    'evaluarse (una historia de usuario, criterios de aceptación, o la descripción del caso de prueba). '
    'Responde SOLO con un objeto JSON válido, sin texto antes ni después: {"pass": true|false, "reasoning": "..."}. '
    'reasoning: 2-4 frases concretas, en español, citando turnos puntuales cuando corresponda. '
    'Si no hay criterio explícito, inferilo del nombre/notas del caso y de la propia conversación, y decilo en el razonamiento.')

VERDICT_SYSTEM_ONGOING = (
    'Eres un QA senior. Te paso una conversación con un chatbot, TODAVÍA EN CURSO (no necesariamente terminada), '
    'y si existe, el criterio contra el que debe evaluarse (una historia de usuario, criterios de aceptación, o '
    'la descripción del caso de prueba). Responde SOLO con un objeto JSON válido, sin texto antes ni después: '
    '{"pass": true|false, "reasoning": "..."}. pass: true si, hasta donde llegó, va bien encaminada hacia el '
    'criterio (no hace falta que ya lo haya cumplido del todo); false si ya se desvió o algo contradice el '
    'criterio. reasoning: 2-4 frases concretas sobre cómo va hasta ahora, no un cierre definitivo. Si no hay '
    'criterio explícito, inferilo del nombre/notas del caso y de la propia conversación.')


def _transcript(messages):
    """'Vos: ...' / 'Bot: ...' por turno, en orden — mismo texto que ya arma conversation_evidence_dialog."""
    who_labels = {'user': 'Vos', 'bot': 'Bot', 'error': 'Error'}
    return '\n'.join(f'{who_labels.get(turn.get("who"), turn.get("who"))}: {turn.get("text", "")}' for turn in messages)


def verdict_messages(messages, context_text='', mode='final'):
    """(system, user) exactly as they will be sent - the UI shows this before anything leaves the machine.
    mode: 'final' (¿pasa o no, de punta a punta?) u 'ongoing' (¿va bien encaminada hasta donde llegó? — para
    «Analizar hasta acá», sobre una conversación que puede seguir, no un cierre definitivo)."""
    system = VERDICT_SYSTEM_FINAL if mode == 'final' else VERDICT_SYSTEM_ONGOING
    parts = []
    if (context_text or '').strip():
        parts.append(f'Criterio contra el que evaluar:\n{context_text.strip()}')
    parts.append(f'Conversación:\n{_transcript(messages)}')
    return system, redact(_clip('\n\n'.join(parts)))


def judge_conversation(messages, context_text='', mode='final', config=None):
    """{'pass': bool, 'reasoning': str, 'raw': str}. `messages` son los turnos tal como vive S['messages'] en
    chat_page.py ({'who', 'text', ...}); `context_text` es la HU/criterio ya resuelto por el caller (vacío si
    hay que inferirlo); `mode` ver verdict_messages. Parsea el JSON de la respuesta con _extract_json; si no
    parsea o le faltan campos, es un LLMError claro — nunca un veredicto inventado."""
    if not messages:
        raise LLMError('No hay turnos todavía para evaluar.')
    system, user = verdict_messages(messages, context_text, mode)
    raw = ask(system, user, config)
    try:
        data = _extract_json(raw)
    except ValueError as exc:
        raise LLMError(f'La respuesta del modelo no es el JSON esperado: {exc}') from exc
    if not isinstance(data, dict) or 'pass' not in data or 'reasoning' not in data:
        raise LLMError('La respuesta del modelo no tiene el formato esperado (pass/reasoning).')
    return {'pass': bool(data['pass']), 'reasoning': str(data['reasoning']), 'raw': raw}


# --------------------------------------------------------------------------- veredicto con argumento, Fase 6: el
# mismo mecanismo de judge_conversation, aplicado a UN run de Caso API/UI en vez de a una conversación de Chat —
# «¿esta corrida cumple el objetivo, y por qué?», no solo el resultado mecánico de sus aserciones.

RUN_VERDICT_SYSTEM = (
    'Eres un QA senior. Te paso la corrida de un caso de prueba (API o UI) — la petición y la respuesta, o los '
    'pasos ejecutados, y el resultado de sus aserciones — y, si existe, el criterio contra el que debe '
    'evaluarse (una historia de usuario, criterios de aceptación, o una Funcionalidad ligada). Responde SOLO '
    'con un objeto JSON válido, sin texto antes ni después: {"pass": true|false, "reasoning": "..."}. '
    'reasoning: 2-4 frases concretas, en español, citando el paso o la aserción puntual cuando corresponda. '
    'Si no hay criterio explícito, inferilo del nombre del caso, de la petición o los pasos, y de si las '
    'aserciones ya definidas pasaron o no, y decilo en el razonamiento.')


def _run_transcript(run):
    """Texto legible de UN run de Caso API/UI (no una conversación) — nombre, qué se mandó/ejecutó, y el
    resultado de cada aserción o paso. Formateador propio: la forma de un run no se parece en nada a
    S['messages'] de Chat, así que no tiene sentido reusar _transcript acá."""
    lines = [f'Caso: {run.get("case_name") or run.get("case_id") or "(sin nombre)"} (tipo {run.get("type", "api")})']
    if run.get('type') == 'ui':
        for step in run.get('steps') or []:
            label = step.get('action', '')
            lines.append(f'Paso {step.get("index", 0) + 1}: {label} — {"OK" if step.get("passed") else "FALLÓ"}')
    else:
        req = run.get('request') or {}
        if req:
            lines.append(f'{req.get("method", "")} {req.get("url", "")}')
            if req.get('body') is not None:
                lines.append(f'Body enviado: {_clip(str(req["body"]), 1500)}')
        lines.append(f'HTTP {run.get("http_status", "—")}')
        resp = run.get('response') or {}
        if resp.get('body'):
            lines.append(f'Respuesta: {_clip(str(resp["body"]), 1500)}')
    for item in run.get('assertions') or []:
        rule = item.get('rule') or {}
        ok = item.get('passed')
        detail = f' (se esperaba {rule.get("expected")!r}, se obtuvo {item.get("actual")!r})' if not ok else ''
        lines.append(f'Aserción {rule.get("type", "?")}: {"OK" if ok else "FALLÓ" + detail}')
    if run.get('error'):
        lines.append(f'Error: {run["error"]}')
    return '\n'.join(lines)


def run_verdict_messages(run, context_text=''):
    """(system, user) exactly as they will be sent — mismo criterio que verdict_messages."""
    parts = []
    if (context_text or '').strip():
        parts.append(f'Criterio contra el que evaluar:\n{context_text.strip()}')
    parts.append(f'Corrida:\n{_run_transcript(run)}')
    return RUN_VERDICT_SYSTEM, redact(_clip('\n\n'.join(parts)))


def judge_run(run, context_text='', config=None):
    """{'pass': bool, 'reasoning': str, 'raw': str} — mismo contrato que judge_conversation, para un run de
    Caso API/UI en vez de una conversación de Chat. Mismo parseo robusto: si la respuesta no es el JSON
    esperado, LLMError claro, nunca un veredicto inventado."""
    if not run:
        raise LLMError('No hay corrida para evaluar.')
    system, user = run_verdict_messages(run, context_text)
    raw = ask(system, user, config)
    try:
        data = _extract_json(raw)
    except ValueError as exc:
        raise LLMError(f'La respuesta del modelo no es el JSON esperado: {exc}') from exc
    if not isinstance(data, dict) or 'pass' not in data or 'reasoning' not in data:
        raise LLMError('La respuesta del modelo no tiene el formato esperado (pass/reasoning).')
    return {'pass': bool(data['pass']), 'reasoning': str(data['reasoning']), 'raw': raw}


# --------------------------------------------------------------------------- conversación conducida por el modelo
# El modelo hace de PERSONA USUARIA (no del bot): a partir de una instrucción/objetivo y, si corresponde, un
# objetivo de datos a conseguir, sugiere el próximo turno — texto libre o, si el bot acaba de ofrecer opciones de
# respuesta rápida, cuál de ellas tomar. `chat_page.py` decide qué hacer con la sugerencia (mandarla de corrido o
# mostrarla editable antes de mandarla); acá no se manda nada solo.

TURN_SYSTEM = (
    'Actuás como la persona USUARIA (no el bot) en una conversación de prueba con un chatbot, siguiendo el '
    'objetivo que te paso. Si el bot ofreció opciones de respuesta rápida para elegir, se te informan aparte: '
    'elegí la que más se ajuste al objetivo y devolvé su texto EXACTO en "option" (nunca inventes una opción que '
    'el bot no ofreció); si ninguna encaja o no hay opciones, "option" va en null y escribís el mensaje libre en '
    '"text". Si la instrucción menciona una preferencia para cierto punto de la conversación, respetala al pie '
    'de la letra cuando llegues ahí. Responde SOLO con un objeto JSON válido, sin texto antes ni después: '
    '{"text": "...", "option": "..."|null, "done": true|false, "collected": {}}. "collected": de los datos que '
    'se piden conseguir (si los hay), los que ya se puedan confirmar con lo visto hasta ahora — puede ir vacío. '
    'done=true cuando el objetivo (o los datos pedidos) ya se cumplieron, o cuando ya no tiene sentido seguir '
    '(el bot quedó en un error o en un bucle, por ejemplo); ahí "text"/"option" pueden ir vacíos.')


def _offered_options(messages):
    if messages and messages[-1].get('who') == 'bot':
        return messages[-1].get('options') or []
    return []


def turn_messages(messages, instruction, data_goals=None):
    """(system, user) exactly as they will be sent - mismo criterio que verdict_messages: la UI lo puede mostrar
    antes de mandarlo. `instruction`: el objetivo/instrucción inicial que escribió la persona (puede incluir
    opciones preferidas, ver TURN_SYSTEM). `data_goals`: lista de strings con lo que se busca conseguir."""
    parts = []
    if (instruction or '').strip():
        parts.append(f'Objetivo de la conversación:\n{instruction.strip()}')
    if data_goals:
        parts.append('Datos a conseguir durante la conversación:\n' + '\n'.join(f'- {g}' for g in data_goals))
    parts.append(f'Conversación hasta ahora:\n{_transcript(messages)}' if messages else
                 'Conversación hasta ahora: todavía no empezó — este es el primer mensaje.')
    offered = _offered_options(messages)
    if offered:
        parts.append('El bot acaba de ofrecer estas opciones de respuesta rápida: ' + ' | '.join(offered))
    return TURN_SYSTEM, redact(_clip('\n\n'.join(parts)))


def suggest_next_turn(messages, instruction, data_goals=None, config=None):
    """{'text': str, 'option': str|None, 'done': bool, 'collected': dict} — el próximo turno que escribiría la
    persona usuaria, sugerido por el modelo. Mismo parseo robusto que judge_conversation: si la respuesta no es
    el JSON esperado, LLMError claro — nunca un turno inventado de este lado."""
    system, user = turn_messages(messages, instruction, data_goals)
    raw = ask(system, user, config)
    try:
        data = _extract_json(raw)
    except ValueError as exc:
        raise LLMError(f'La respuesta del modelo no es el JSON esperado: {exc}') from exc
    if not isinstance(data, dict) or 'done' not in data:
        raise LLMError('La respuesta del modelo no tiene el formato esperado (text/option/done).')
    collected = data.get('collected')
    return {'text': str(data.get('text') or ''), 'option': (str(data['option']) if data.get('option') else None),
            'done': bool(data['done']), 'collected': collected if isinstance(collected, dict) else {}}


# --------------------------------------------------------------------------- chat libre con el Asistente de IA
# («Hablale al Asistente», Fase A): a diferencia de TURN_SYSTEM (que SOLO redacta el próximo turno de «vos» para
# el bot), acá el modelo conversa CON la persona que está probando — puede simplemente responder, anotar algo
# para después, o decidir que le están pidiendo avanzar la conversación actual con el bot ahora mismo (un turno
# puntual para revisar, o varios seguidos sin pedir revisión). chat_page.py decide qué hacer con cada acción;
# acá no se manda ni se guarda nada solo.

ASSISTANT_CHAT_SYSTEM = (
    'Sos el Asistente de IA de Local Test Workspace, dentro del Chat: hablás con la persona que está probando un '
    'chatbot/API conversacional — no sos el bot que se está probando, sos quien la ayuda a probarlo. Tenés la '
    'conversación de prueba tal como va hasta ahora y el historial de esta charla con vos. Respondé en español, '
    'corto y concreto. Responde SOLO con un objeto JSON válido, sin texto antes ni después: '
    '{"reply": "...", "action": "chat"|"note"|"continue", "autopilot": true|false, "instruction": "..."}. '
    '"reply": lo que le decís a la persona — confirmá qué vas a hacer, o respondé derecho si solo preguntó algo. '
    '"action": "chat" si solo te está preguntando o charlando (nada para ejecutar); "note" si te da una '
    'instrucción, dato o restricción para tener en cuenta más adelante (antes de que arranque una corrida, o para '
    'una ya en curso) pero no te pide avanzar la conversación con el bot ahora mismo; "continue" si te pide '
    'explícitamente que sigas, avances, mandes el próximo turno, o lleves vos la conversación actual con el bot. '
    '"autopilot": solo junto con action="continue" — true si pidió que la lleves toda o varios turnos sin que '
    'revises cada uno («de corrido», «llevala vos sola/sin pausas», «seguí hasta terminar»); false si pidió un '
    'solo turno puntual o no lo aclaró (ante la duda, false: un turno a la vez, revisable, es más seguro). '
    '"instruction": el objetivo/instrucciones/restricciones a seguir, en tus palabras, juntando TODO lo relevante '
    'de este mensaje y de mensajes previos de este mismo mini-chat que sigan aplicando; vacío si action="chat".')


def _assistant_chat_transcript(assistant_messages):
    who_labels = {'user': 'Vos', 'assistant': 'Asistente'}
    return '\n'.join(f'{who_labels.get(turn.get("who"), turn.get("who"))}: {turn.get("text", "")}' for turn in assistant_messages)


def assistant_chat_messages(conversation_messages, assistant_messages, text, ai_run_active):
    """(system, user) exactly as they will be sent - the UI shows this before anything leaves the machine.
    `conversation_messages`: S['messages'] (la charla CON EL BOT). `assistant_messages`: el historial de ESTE
    mini-chat hasta ahora (sin el mensaje nuevo, que va aparte en `text`). `ai_run_active`: si ya hay una
    Conversación conducida por IA corriendo (para que el modelo no trate "continue" como redundante sin saberlo)."""
    parts = [f'Mensaje nuevo de la persona: {text.strip()}',
             '¿Hay una Conversación conducida por IA corriendo ahora mismo? ' + ('Sí.' if ai_run_active else 'No.')]
    if assistant_messages:
        parts.append(f'Charla con vos hasta ahora (este mini-chat, sin contar el mensaje nuevo):\n{_assistant_chat_transcript(assistant_messages)}')
    parts.append(f'Conversación de prueba con el bot hasta ahora:\n{_transcript(conversation_messages)}' if conversation_messages else
                 'Conversación de prueba con el bot: todavía no empezó.')
    return ASSISTANT_CHAT_SYSTEM, redact(_clip('\n\n'.join(parts)))


def assistant_reply(conversation_messages, assistant_messages, text, ai_run_active, config=None):
    """{'reply': str, 'action': 'chat'|'note'|'continue', 'autopilot': bool, 'instruction': str}. Mismo parseo
    robusto que suggest_next_turn: si la respuesta no es el JSON esperado, LLMError claro."""
    system, user = assistant_chat_messages(conversation_messages, assistant_messages, text, ai_run_active)
    raw = ask(system, user, config)
    try:
        data = _extract_json(raw)
    except ValueError as exc:
        raise LLMError(f'La respuesta del modelo no es el JSON esperado: {exc}') from exc
    if not isinstance(data, dict) or 'reply' not in data:
        raise LLMError('La respuesta del modelo no tiene el formato esperado (reply/action).')
    action = data.get('action') if data.get('action') in ('chat', 'note', 'continue') else 'chat'
    return {'reply': str(data['reply']), 'action': action, 'autopilot': bool(data.get('autopilot')),
            'instruction': str(data.get('instruction') or '')}
