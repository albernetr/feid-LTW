"""Interface observer: what really enters and leaves each module (JSON only, pre-production, local).

Two light sources feed one catalog:
  * a *tap*: a tiny reverse proxy on 127.0.0.1 that forwards to a module and records the JSON traffic;
  * the run history (API runs already store the request and response).

The catalog learns each interface's shape (fields, types, optionality, examples), lets you freeze a *baseline*,
reports drift (new fields, type changes, missing required fields, new status codes) and compares the observation
with the OpenAPI contract. Sensitive values are masked before anything is stored.
"""
import copy
import hashlib
import json
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qsl
import httpx
from . import core, logs

SENSITIVE_KEY = re.compile(r'pass(word|wd)?|secret|token|authorization|api[_-]?key|cookie|credential|session', re.I)
MAX_BODY = 5_000_000
MAX_ITEMS = 50          # array elements inspected per observation
MAX_SAMPLES = 5
MAX_EXAMPLES = 3
HOP_BY_HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailers', 'transfer-encoding',
              'upgrade', 'host', 'content-length', 'content-encoding'}
_LOCK = threading.RLock()
_UUID = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')


# --------------------------------------------------------------------------- shape helpers

def mask(value, key=''):
    """Deep copy with the values of sensitive keys replaced by '***'."""
    if SENSITIVE_KEY.search(key or '') and value not in (None, ''):
        return '***'
    if isinstance(value, dict):
        return {k: mask(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v, key) for v in value]
    return value


def type_name(value):
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, int):
        return 'integer'
    if isinstance(value, float):
        return 'number'
    if isinstance(value, str):
        return 'string'
    if value is None:
        return 'null'
    return 'object' if isinstance(value, dict) else 'array'


def _segment(key):
    return f'.{key}' if re.fullmatch(r'[A-Za-z_][\w-]*', str(key)) else f"['{key}']"


def parent_path(path):
    if path == '$':
        return None
    return re.sub(r"(\[\*\]|\['[^']*'\]|\.[^.\[\]]+)$", '', path) or '$'


def flatten(value):
    """{path: {'types': {type: n}, 'n': occurrences, 'examples': [...]}} for one JSON document."""
    out = {}

    def add(path, kind, example=None):
        node = out.setdefault(path, {'types': {}, 'n': 0, 'examples': []})
        node['n'] += 1
        node['types'][kind] = node['types'].get(kind, 0) + 1
        if example is not None and len(node['examples']) < MAX_EXAMPLES and example not in node['examples']:
            node['examples'].append(example)

    def walk(v, path, key):
        kind = type_name(v)
        if isinstance(v, dict):
            add(path, 'object')
            for child_key, child in v.items():
                walk(child, path + _segment(child_key), str(child_key))
        elif isinstance(v, list):
            add(path, 'array')
            for item in v[:MAX_ITEMS]:
                walk(item, path + '[*]', key)
        else:
            example = None if v is None else ('***' if SENSITIVE_KEY.search(key or '') and v != '' else (v[:60] if isinstance(v, str) else v))
            add(path, kind, example)
    walk(value, '$', '')
    return out


def merge_section(section, flat):
    """Adds one observation's flattened shape to a {'total', 'fields'} section."""
    section['total'] += 1
    for path, info in flat.items():
        node = section['fields'].setdefault(path, {'types': {}, 'count': 0, 'examples': []})
        node['count'] += info['n']
        for kind, n in info['types'].items():
            node['types'][kind] = node['types'].get(kind, 0) + n
        for example in info['examples']:
            if len(node['examples']) < MAX_EXAMPLES and example not in node['examples']:
                node['examples'].append(example)


def new_section():
    return {'total': 0, 'fields': {}}


def required_paths(section):
    """Paths present in every parent occurrence seen. Needs 2+ observations to mean anything."""
    fields, found = section['fields'], []
    if section['total'] < 2:
        return found
    for path, info in fields.items():
        parent = parent_path(path)
        if parent is not None and parent in fields and info['count'] == fields[parent]['count']:
            found.append(path)
    return sorted(found)


def signature(section):
    return sorted([path, kind] for path, info in section['fields'].items() for kind in info['types'])


def _child_key(path, parent):
    rest = path[len(parent):]
    if rest.startswith('.'):
        return rest[1:]
    if rest.startswith("['"):
        return rest[2:-2]
    return None


def observed_schema(section):
    """JSON Schema describing the observed shape (required = present in every occurrence, with 2+ observations)."""
    fields = section['fields']
    if '$' not in fields:
        return {}
    children = {}
    for path in fields:
        parent = parent_path(path)
        if parent is not None:
            children.setdefault(parent, []).append(path)
    enough = section['total'] >= 2

    def build(path):
        types = sorted(fields[path]['types'])
        if set(types) == {'integer', 'number'}:
            types = ['number']
        schema = {'type': types[0] if len(types) == 1 else types}
        kids = children.get(path, [])
        props, required = {}, []
        for child in kids:
            key = _child_key(child, path)
            if key is not None:
                props[key] = build(child)
                if enough and fields[child]['count'] == fields[path]['count']:
                    required.append(key)
        if props:
            schema['properties'] = props
            if required:
                schema['required'] = sorted(required)
        if path + '[*]' in fields:
            schema['items'] = build(path + '[*]')
        return schema
    return build('$')


# --------------------------------------------------------------------------- paths

def _template_regex(template):
    parts = []
    for segment in template.strip('/').split('/'):
        parts.append('[^/]+' if re.fullmatch(r'\{[^/]+\}', segment) else re.escape(segment))
    return re.compile('^/' + '/'.join(parts) + '/?$')


def normalize_path(path, templates=()):
    """'/api/users/42' -> '/api/users/{id}' (uses the contract's templates when known)."""
    path = urlsplit(path).path or '/'
    for template in sorted(templates, key=lambda t: t.count('{')):
        if _template_regex(template).match(path):
            return template
    out = []
    for segment in path.split('/'):
        if re.fullmatch(r'\d+', segment):
            out.append('{id}')
        elif _UUID.match(segment):
            out.append('{uuid}')
        elif re.fullmatch(r'[0-9a-fA-F]{16,}', segment):
            out.append('{hash}')
        else:
            out.append(segment)
    return '/'.join(out) or '/'


def _parse_json(text):
    if text is None or not str(text).strip():
        return 'empty', None
    try:
        return 'json', json.loads(text)
    except (TypeError, ValueError):
        return 'other', None


def _bounded(value, limit=20000):
    text = json.dumps(value, ensure_ascii=False, default=str)
    return value if len(text) <= limit else text[:limit] + '…[truncado]'


# --------------------------------------------------------------------------- catalog

def interface_id(project_id, module, method, template):
    return hashlib.sha1(f'{project_id}|{module.strip().lower()}|{method.upper()}|{template}'.encode()).hexdigest()


def _new_interface(project_id, module, method, template, origin):
    return {'id': interface_id(project_id, module, method, template), 'project_id': project_id, 'module': module.strip(), 'method': method.upper(),
            'path_template': template, 'origin': origin, 'count': 0, 'first_seen': core.now(), 'last_seen': core.now(), 'statuses': {},
            'non_json': 0, 'query_params': {}, 'request': new_section(), 'responses': {}, 'samples': [], 'avg_ms': 0.0,
            'baseline': None, 'drift': []}


def record(module, project_id, method, path, query, request_text, status, response_text, duration_ms, templates=(), origin=None):
    """Learns from one request/response pair. Returns the interface document (and any new drift events)."""
    template = normalize_path(path, templates)
    request_kind, request_json = _parse_json(request_text)
    response_kind, response_json = _parse_json(response_text)
    with _LOCK:
        key = interface_id(project_id, module, method, template)
        doc = core.get('interfaces', key) or _new_interface(project_id, module, method, template, origin)
        if origin and not doc.get('origin'):
            doc['origin'] = origin
        doc['count'] += 1
        doc['last_seen'] = core.now()
        doc['avg_ms'] = round(doc['avg_ms'] + (duration_ms - doc['avg_ms']) / doc['count'], 2)
        doc['statuses'][str(status)] = doc['statuses'].get(str(status), 0) + 1
        for name, _ in parse_qsl(query or '', keep_blank_values=True):
            doc['query_params'][name] = doc['query_params'].get(name, 0) + 1
        if 'other' in (request_kind, response_kind):
            doc['non_json'] += 1
        request_flat = flatten(request_json) if request_kind == 'json' else None
        response_flat = flatten(response_json) if response_kind == 'json' else None
        events = _detect_drift(doc, request_flat, response_flat, str(status)) if doc.get('baseline') else []
        if request_flat is not None:
            merge_section(doc['request'], request_flat)
        if response_flat is not None:
            merge_section(doc['responses'].setdefault(str(status), new_section()), response_flat)
        doc['samples'] = (doc['samples'] + [{'at': core.now(), 'path': path, 'query': query or '', 'status': status,
                                             'request': _bounded(mask(request_json)) if request_kind == 'json' else None,
                                             'response': _bounded(mask(response_json)) if response_kind == 'json' else None}])[-MAX_SAMPLES:]
        for event in events:
            _register_drift(doc, event)
        saved = core.save('interfaces', doc)
    return saved


def _baseline_snapshot(doc):
    return {'at': core.now(), 'count': doc['count'], 'statuses': sorted(doc['statuses']),
            'signature': {'request': signature(doc['request']), **{f'response {s}': signature(sec) for s, sec in doc['responses'].items()}},
            'required': {'request': required_paths(doc['request']), **{f'response {s}': required_paths(sec) for s, sec in doc['responses'].items()}}}


def _detect_drift(doc, request_flat, response_flat, status):
    base = doc['baseline']
    events = []
    if status not in base['statuses']:
        events.append({'kind': 'código HTTP nuevo', 'where': 'respuesta', 'path': '', 'detail': f'apareció el código {status}'})
    for where, flat in (('request', request_flat), (f'response {status}', response_flat)):
        if flat is None or where not in base['signature']:
            continue
        known = {tuple(item) for item in base['signature'][where]}
        known_paths = {path for path, _ in known}
        label = 'solicitud' if where == 'request' else f'respuesta {status}'
        for path, info in flat.items():
            for kind in info['types']:
                if (path, kind) not in known:
                    if path not in known_paths:
                        events.append({'kind': 'campo nuevo', 'where': label, 'path': path, 'detail': f'{path} ({kind}) no estaba en la línea base'})
                    else:
                        was = sorted({k for p, k in known if p == path})
                        events.append({'kind': 'tipo distinto', 'where': label, 'path': path, 'detail': f'{path}: ahora {kind}, antes {"/".join(was)}'})
        for path in base['required'].get(where, []):
            parent = parent_path(path)
            if parent in flat and flat[parent]['n'] > flat.get(path, {'n': 0})['n']:
                events.append({'kind': 'campo requerido ausente', 'where': label, 'path': path, 'detail': f'{path} ya no viene siempre (era obligatorio en la línea base)'})
    return events


def _register_drift(doc, event):
    for known in doc['drift']:
        if (known['kind'], known['where'], known['path'], known['detail']) == (event['kind'], event['where'], event['path'], event['detail']):
            known['count'] += 1
            known['last_seen'] = core.now()
            return
    doc['drift'].append({**event, 'count': 1, 'first_seen': core.now(), 'last_seen': core.now()})


def set_baseline(interface_id_):
    """Freezes the current shape as 'known and accepted'. Pending drift is cleared (kept as a count in the history)."""
    with _LOCK:
        doc = core.get('interfaces', interface_id_)
        if doc is None:
            raise ValueError('Interfaz inexistente')
        accepted = len(doc.get('drift', []))
        doc['baseline'] = _baseline_snapshot(doc)
        doc.setdefault('baseline_history', []).append({'at': doc['baseline']['at'], 'accepted_changes': accepted})
        doc['drift'] = []
        return core.save('interfaces', doc)


def interface_state(doc):
    if not doc.get('baseline'):
        return 'sin línea base'
    return f'{len(doc["drift"])} cambio(s)' if doc['drift'] else 'sin cambios'


def list_interfaces(project_id=None, module=None):
    items = [i for i in core.list_items('interfaces') if (project_id is None or i.get('project_id') == project_id)]
    if module:
        items = [i for i in items if i['module'].lower() == module.lower()]
    return sorted(items, key=lambda i: (i['module'].lower(), i['path_template'], i['method']))


def module_summaries(project_id=None):
    """One row per observed module: interfaces, calls, pending drift, last activity, owner/company from its tap."""
    taps = {t['name'].lower(): t for t in core.list_items('taps') if project_id is None or t.get('project_id') == project_id}
    rows = {}
    for doc in list_interfaces(project_id):
        row = rows.setdefault(doc['module'].lower(), {'module': doc['module'], 'interfaces': 0, 'calls': 0, 'drift': 0, 'unbaselined': 0, 'last_seen': ''})
        row['interfaces'] += 1
        row['calls'] += doc['count']
        row['drift'] += len(doc['drift'])
        row['unbaselined'] += 0 if doc.get('baseline') else 1
        row['last_seen'] = max(row['last_seen'], doc['last_seen'])
    for name, tap in taps.items():
        row = rows.setdefault(name, {'module': tap['name'], 'interfaces': 0, 'calls': 0, 'drift': 0, 'unbaselined': 0, 'last_seen': ''})
        row['company'], row['owner'] = tap.get('company', ''), tap.get('owner', '')
    return sorted(rows.values(), key=lambda r: r['module'].lower())


# --------------------------------------------------------------------------- history source

def observe_runs(project_id=None):
    """Feeds the catalog with API runs already in the history (each run is used once). Returns how many were learned."""
    done = set(core.get_setting('observed_run_ids', []) or [])
    learned = 0
    for run in sorted(core.list_items('runs'), key=lambda r: r.get('started_at', '')):
        request, response = run.get('request'), run.get('response')
        if run.get('type') != 'api' or not request or response is None or run['id'] in done:
            continue
        if project_id is not None and run.get('project_id') != project_id:
            continue
        env = core.get('environments', run.get('environment_id')) or {}
        parsed = urlsplit(request['url'])
        body = request.get('body')
        record(env.get('name') or parsed.netloc, run.get('project_id'), request['method'], parsed.path, parsed.query,
               json.dumps(body) if body is not None else '', run.get('http_status', 0), response.get('body', ''),
               run.get('duration_ms') or 0, origin=f'{parsed.scheme}://{parsed.netloc}')
        done.add(run['id'])
        learned += 1
    core.set_setting('observed_run_ids', sorted(done)[-5000:])
    return learned


# --------------------------------------------------------------------------- contract comparison

def _schema_types(schema):
    kind = schema.get('type')
    kinds = set(kind if isinstance(kind, list) else [kind] if kind else [])
    if schema.get('nullable'):
        kinds.add('null')
    if 'number' in kinds:
        kinds.add('integer')
    return kinds


def _merged(schema):
    """Properties/required of a schema, folding allOf."""
    props, required = dict(schema.get('properties') or {}), set(schema.get('required') or [])
    for part in schema.get('allOf') or []:
        sub_props, sub_required = _merged(part)
        props.update(sub_props)
        required |= sub_required
    return props, required


def _compare_section(section, schema, label, limit=40):
    fields, issues = section['fields'], []

    def child(path, key):
        return path + _segment(key)

    def check(node, path):
        if len(issues) >= limit or path not in fields:
            return
        if node.get('oneOf') or node.get('anyOf'):
            return                                     # cannot be judged structurally: left alone, not guessed
        allowed = _schema_types(node)
        observed = set(fields[path]['types'])
        if allowed and not observed <= allowed:
            issues.append(f'{label}: {path} llega como {"/".join(sorted(observed - allowed))} y el contrato dice {"/".join(sorted(allowed))}')
        props, required = _merged(node)
        for key, sub in props.items():
            sub_path = child(path, key)
            if sub_path not in fields:
                if key in required and fields[path]['count'] > 0:
                    issues.append(f'{label}: {sub_path} es requerido por el contrato y nunca se observó')
                continue
            if key in required and fields[sub_path]['count'] < fields[path]['count']:
                issues.append(f'{label}: {sub_path} es requerido por el contrato pero no siempre viene')
            check(sub, sub_path)
        if props or node.get('type') == 'object':
            declared = {child(path, k) for k in props}
            if node.get('additionalProperties') in (None, False):
                for other in fields:
                    if parent_path(other) == path and not other.endswith('[*]') and other not in declared:
                        issues.append(f'{label}: {other} se observa pero el contrato no lo declara')
        if 'items' in node and path + '[*]' in fields:
            check(node['items'], path + '[*]')
    if '$' in fields:
        check(schema, '$')
    return issues[:limit]


def compare_with_contract(doc, module):
    """Observed shape versus the OpenAPI operation of the same method and path template."""
    operation = next((o for o in module.get('operations', []) if o['method'] == doc['method'] and o['path'] == doc['path_template']), None)
    if operation is None:
        return {'matched': False, 'issues': [f'El contrato «{module.get("name")}» no declara {doc["method"]} {doc["path_template"]}']}
    issues = []
    for status, section in doc['responses'].items():
        if status not in {str(k) for k in operation.get('responses', {})}:
            issues.append(f'respuesta {status}: el contrato no declara ese código')
            continue
        schema = core.operation_response_schema(operation, status)
        if schema is None:
            issues.append(f'respuesta {status}: el contrato no declara un schema')
        else:
            issues += _compare_section(section, schema, f'respuesta {status}')
    body = None
    for media in ((operation.get('requestBody') or {}).get('content') or {}).values():
        if isinstance(media, dict) and isinstance(media.get('schema'), dict):
            body = media['schema']
            break
    if doc['request']['total'] and body is None:
        issues.append('solicitud: se observa un body pero el contrato no declara schema de petición')
    elif doc['request']['total']:
        issues += _compare_section(doc['request'], body, 'solicitud')
    return {'matched': True, 'issues': issues}


# --------------------------------------------------------------------------- from catalog to a test

def _placeholderize(value):
    if isinstance(value, dict):
        return {k: ('{{' + re.sub(r'\W+', '_', k) + '}}' if v == '***' else _placeholderize(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_placeholderize(v) for v in value]
    return value


def create_case_from_sample(doc, project_id, sample_index=-1, mode='structure'):
    """A regression case from the latest sample: same request, assertions from the observed response."""
    if not doc['samples']:
        raise ValueError('La interfaz no tiene muestras')
    if not doc.get('origin'):
        raise ValueError('No se conoce el servidor de origen de esta interfaz')
    sample = doc['samples'][sample_index]
    env, _ = core.ensure_environment_for_url(project_id, doc['origin'])
    rules = core.snapshot_assertions(sample['status'], json.dumps(sample['response']) if sample['response'] is not None else '', mode if sample['response'] is not None else 'status')
    path = sample['path'] + (f'?{sample["query"]}' if sample.get('query') else '')
    base, _, qs = path.partition('?')
    case = {'name': f'{doc["method"]} {doc["path_template"]} (observado)', 'type': 'api', 'project_id': project_id, 'method': doc['method'], 'path': base,
            'query': dict(parse_qsl(qs, keep_blank_values=True)), 'headers': {}, 'assertions': rules,
            'body': _placeholderize(sample['request']) if sample['request'] is not None else None}
    return core.save('cases', case), env


# --------------------------------------------------------------------------- tap (reverse proxy)

_TAPS = {}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.0'

    def log_message(self, *args):
        pass

    def _send(self, status, body, headers=()):
        self.send_response(status)
        for name, value in headers:
            self.send_header(name, value)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _forward(self):
        tap = self.server.tap
        if 'chunked' in (self.headers.get('Transfer-Encoding') or '').lower():
            return self._send(411, b'{"error": "tap: chunked requests are not supported"}', [('Content-Type', 'application/json')])
        length = int(self.headers.get('Content-Length') or 0)
        if length > MAX_BODY:
            return self._send(413, b'{"error": "tap: body too large"}', [('Content-Type', 'application/json')])
        body = self.rfile.read(length) if length else b''
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        started = time.perf_counter()
        try:
            response = self.server.client.request(self.command, tap['target'].rstrip('/') + self.path, content=body, headers=headers)
        except httpx.HTTPError as exc:
            logs.event('tap.upstream_error', tap=tap['name'], error=str(exc)[:200])
            return self._send(502, json.dumps({'error': f'tap: el módulo destino no respondió ({type(exc).__name__})'}).encode(), [('Content-Type', 'application/json')])
        duration = (time.perf_counter() - started) * 1000
        out = [(k, v) for k, v in response.headers.multi_items() if k.lower() not in HOP_BY_HOP]
        try:                                              # recorded BEFORE answering, so the catalog never lags behind what was forwarded
            parts = urlsplit(self.path)
            record(tap['name'], tap.get('project_id'), self.command, parts.path, parts.query, body.decode('utf-8', 'replace'), response.status_code,
                   response.text, duration, templates=_templates_for(tap), origin=tap['target'].rstrip('/'))
            self.server.calls += 1
        except Exception as exc:                          # observing must never break the traffic being observed
            logs.event('tap.record_error', tap=tap['name'], error=str(exc)[:200])
        self._send(response.status_code, response.content, out)

    do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = do_HEAD = do_OPTIONS = _forward


def _templates_for(tap):
    module = core.get('modules', tap['module_id']) if tap.get('module_id') else None
    return [o['path'] for o in (module or {}).get('operations', [])]


def validate_tap(tap):
    if not (tap.get('name') or '').strip():
        raise ValueError('El nombre del módulo es obligatorio')
    try:
        port = int(tap.get('listen_port'))
    except (TypeError, ValueError):
        raise ValueError('El puerto debe ser un número')
    if not 1024 <= port <= 65535:
        raise ValueError('El puerto debe estar entre 1024 y 65535')
    core.split_url(tap.get('target') or '')
    for other in core.list_items('taps'):
        if other['id'] != tap.get('id') and int(other['listen_port']) == port:
            raise ValueError(f'El puerto {port} ya lo usa el tap «{other["name"]}»')


def start_tap(tap_id):
    tap = core.get('taps', tap_id)
    if tap is None:
        raise ValueError('Tap inexistente')
    if tap_id in _TAPS:
        return _TAPS[tap_id]
    try:
        server = ThreadingHTTPServer(('127.0.0.1', int(tap['listen_port'])), _Handler)
    except OSError as exc:
        raise ValueError(f'No se pudo abrir el puerto {tap["listen_port"]}: {exc}')
    server.tap, server.calls = tap, 0
    server.client = httpx.Client(timeout=30, follow_redirects=False, trust_env=False)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _TAPS[tap_id] = server
    logs.event('tap.started', tap=tap['name'], port=tap['listen_port'], target=tap['target'])
    return server


def stop_tap(tap_id):
    server = _TAPS.pop(tap_id, None)
    if server is not None:
        server.shutdown()
        server.server_close()
        server.client.close()
        logs.event('tap.stopped', tap=server.tap['name'])


def tap_running(tap_id):
    return tap_id in _TAPS


def tap_calls(tap_id):
    return _TAPS[tap_id].calls if tap_id in _TAPS else 0


def stop_all_taps():
    for tap_id in list(_TAPS):
        stop_tap(tap_id)
