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


def ask(system, user, config=None, max_tokens=MAX_OUTPUT_TOKENS, check=True):
    """One round trip to the configured model. check=False skips the cloud gate (only for the harmless connection test)."""
    config = config or get_config()
    state = status(config)
    if check and not state['ready']:
        raise LLMError(state['problem'])
    if not check and state['problem'] and 'clave' in state['problem']:
        raise LLMError(state['problem'])
    key = core.secret_get(KEY_SECRET) if config['auth'] != 'none' else None
    try:
        response = httpx.post(_endpoint(config), headers=_headers(config, key), json=_payload(config, system, user, max_tokens), timeout=config['timeout'])
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


def test_connection(config=None):
    """Sends a one-word prompt; carries no workspace data, so it is allowed even when cloud use is not."""
    config = config or get_config()
    text = ask('Responde únicamente con la palabra OK.', 'ping', config, max_tokens=16, check=False)
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
