"""Agent protocol: a predefined way to hand test cases IN and failures OUT, so another agent can go straight to the code.

  ltw.spec/1     agent  -> tool   cases, environments and suites (references by NAME, never by id, no secret values)
  ltw.report/1   tool   -> agent  summary + one `ltw.failure/1` per failing case
  ltw.failure/1  tool   -> agent  what was sent, what was expected, what came back, a heuristic diagnosis,
                                  where to look (contract, observed drift, the agent's own `code_hints`) and how to reproduce

Three doors, same data: the CLI (`python run.py --run spec.json`), a token-protected local HTTP API (`/agent/v1/...`)
and the Workspace UI. Everything here is plain JSON and works without a browser.
"""
import copy
import hashlib
import hmac
import json
import re
import secrets as _secrets
import shutil
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit
from . import core, automation

FORMAT_SPEC, FORMAT_REPORT, FORMAT_FAILURE = 'ltw.spec/1', 'ltw.report/1', 'ltw.failure/1'
METHODS = ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS']
BODY_EXCERPT = 4000
AGENT_PROJECT = 'Agente'


class SpecError(ValueError):
    def __init__(self, errors):
        super().__init__('; '.join(f'{e["path"]}: {e["message"]}' for e in errors[:5]))
        self.errors = errors


# --------------------------------------------------------------------------- the spec schema

_ASSERTION = {'type': 'object', 'required': ['type'], 'additionalProperties': False, 'properties': {
    'type': {'enum': sorted(core.ASSERTION_TYPES)}, 'path': {'type': 'string'}, 'name': {'type': 'string'}, 'expected': {},
    'schema': {'type': 'object'}, 'ignore': {'type': 'array', 'items': {'type': 'string'}}}}
_SOURCE = {'type': 'object', 'required': ['type'], 'additionalProperties': False, 'properties': {
    'type': {'enum': sorted(core.SOURCE_TYPES)}, 'value': {}, 'step': {'type': 'string'}, 'path': {'type': 'string'}, 'name': {'type': 'string'}}}
_ENRICH = {'type': 'object', 'required': ['action', 'target'], 'additionalProperties': False, 'properties': {
    'action': {'enum': sorted(core.ENRICH_ACTIONS)}, 'target': {'enum': sorted(core.ENRICH_TARGETS)}, 'path': {'type': 'string'}, 'source': _SOURCE}}
_STRING_MAP = {'type': 'object', 'additionalProperties': {'type': 'string'}}
_CASE = {'type': 'object', 'required': ['name', 'method', 'path'], 'additionalProperties': False, 'properties': {
    'name': {'type': 'string', 'minLength': 1, 'maxLength': 120}, 'method': {'enum': METHODS}, 'path': {'type': 'string', 'minLength': 1},
    'headers': _STRING_MAP, 'query': _STRING_MAP, 'body': {}, 'variables': {'type': 'object'}, 'environment': {'type': 'string'},
    'timeout': {'type': 'number', 'minimum': 1, 'maximum': 300}, 'assertions': {'type': 'array', 'items': _ASSERTION},
    'extract': {'type': 'array', 'items': {'type': 'object', 'required': ['name'], 'additionalProperties': False, 'properties': {
        'name': {'type': 'string'}, 'source': {'enum': ['json', 'header', 'status', 'regex']}, 'path': {'type': 'string'}}}},
    'tags': {'type': 'array', 'items': {'type': 'string'}}, 'notes': {'type': 'string'},
    'code_hints': {'type': 'object', 'description': 'Where the code behind this case lives (files, symbol, repo, owner...). Echoed in failures.',
                   'properties': {'files': {'type': 'array', 'items': {'type': 'string'}}, 'symbol': {'type': 'string'}, 'repo': {'type': 'string'},
                                  'owner': {'type': 'string'}, 'notes': {'type': 'string'}}}}}
_ENV = {'type': 'object', 'required': ['name', 'base_url'], 'additionalProperties': False, 'properties': {
    'name': {'type': 'string', 'minLength': 1}, 'base_url': {'type': 'string', 'pattern': '^https?://'}, 'variables': {'type': 'object'},
    'auth': {'type': 'object', 'additionalProperties': False, 'properties': {
        'type': {'enum': ['none', 'bearer', 'api_key']}, 'secret': {'type': 'string', 'description': 'NAME of a stored secret / environment variable, never its value'},
        'env_var': {'type': 'string'}, 'header': {'type': 'string'}}}}}
_STEP = {'type': 'object', 'required': ['case'], 'additionalProperties': False, 'properties': {
    'case': {'type': 'string'}, 'alias': {'type': 'string', 'pattern': core.ALIAS_RE.pattern}, 'environment': {'type': 'string'},
    'enrich': {'type': 'array', 'items': _ENRICH}}}
_SUITE = {'type': 'object', 'required': ['name', 'steps'], 'additionalProperties': False, 'properties': {
    'name': {'type': 'string', 'minLength': 1}, 'environment': {'type': 'string'}, 'on_failure': {'enum': ['continue', 'stop']},
    'retries': {'type': 'integer', 'minimum': 0, 'maximum': 5}, 'retry_delay_s': {'type': 'number', 'minimum': 0, 'maximum': 300},
    'variables': {'type': 'object'}, 'steps': {'type': 'array', 'minItems': 1, 'items': _STEP}}}
SPEC_SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema', '$id': 'https://local-test-workspace/ltw.spec.1.schema.json',
    'title': 'ltw.spec/1', 'type': 'object', 'required': ['format', 'cases'], 'additionalProperties': False,
    'properties': {'format': {'const': FORMAT_SPEC}, 'name': {'type': 'string'}, 'description': {'type': 'string'},
                   'project': {'type': 'string', 'description': 'Project to upsert into (default "Agente")'},
                   'default_environment': {'type': 'string'}, 'environments': {'type': 'array', 'items': _ENV},
                   'cases': {'type': 'array', 'minItems': 1, 'items': _CASE}, 'suites': {'type': 'array', 'items': _SUITE}}}


def _path(error):
    text = '$'
    for part in error.absolute_path:
        text += f'[{part}]' if isinstance(part, int) else f'.{part}'
    return text


def validate_spec(spec, known_environments=()):
    """{'valid': bool, 'errors': [{'path','message'}], 'warnings': [...]} - precise enough for an agent to fix the spec itself."""
    import jsonschema
    errors, warnings = [], []
    if not isinstance(spec, dict):
        return {'valid': False, 'errors': [{'path': '$', 'message': 'La especificación debe ser un objeto JSON'}], 'warnings': []}
    for error in sorted(jsonschema.Draft202012Validator(SPEC_SCHEMA).iter_errors(spec), key=lambda e: list(map(str, e.absolute_path))):
        errors.append({'path': _path(error), 'message': error.message[:300]})
    if errors:
        return {'valid': False, 'errors': errors, 'warnings': warnings}
    env_names = [e['name'] for e in spec.get('environments', [])]
    known = set(env_names) | set(known_environments)
    case_names = [c['name'] for c in spec['cases']]
    for label, names in (('environments', env_names), ('cases', case_names), ('suites', [s['name'] for s in spec.get('suites', [])])):
        for name in {n for n in names if names.count(n) > 1}:
            errors.append({'path': f'$.{label}', 'message': f'El nombre «{name}» está repetido'})
    if spec.get('default_environment') and spec['default_environment'] not in known:
        errors.append({'path': '$.default_environment', 'message': f'El ambiente «{spec["default_environment"]}» no existe'})
    for index, case in enumerate(spec['cases']):
        where = f'$.cases[{index}]'
        if case.get('environment') and case['environment'] not in known:
            errors.append({'path': f'{where}.environment', 'message': f'El ambiente «{case["environment"]}» no está definido en environments'})
        if not case['path'].startswith(('/', '{{')):
            errors.append({'path': f'{where}.path', 'message': 'La ruta debe empezar con «/» (o con una {{variable}})'})
        for number, rule in enumerate(case.get('assertions', [])):
            problem = core.validate_assertion_rule(rule)
            if problem:
                errors.append({'path': f'{where}.assertions[{number}]', 'message': problem})
        if not case.get('assertions'):
            warnings.append({'path': f'{where}.assertions', 'message': 'Sin aserciones el caso nunca pasa; agrega al menos una (p. ej. status)'})
        for header, value in (case.get('headers') or {}).items():
            if header.lower() in core.SENSITIVE_HEADERS and '{{' not in value:
                warnings.append({'path': f'{where}.headers.{header}', 'message': 'Valor literal en un header sensible: usa {{secret:NOMBRE}} para no escribir credenciales en la especificación'})
    for index, suite in enumerate(spec.get('suites', [])):
        where = f'$.suites[{index}]'
        if suite.get('environment') and suite['environment'] not in known:
            errors.append({'path': f'{where}.environment', 'message': f'El ambiente «{suite["environment"]}» no existe'})
        if not (suite.get('environment') or spec.get('default_environment') or env_names or known_environments):
            errors.append({'path': where, 'message': 'La suite necesita un ambiente (defínelo en environments)'})
        aliases = []
        for number, step in enumerate(suite['steps']):
            at = f'{where}.steps[{number}]'
            if step['case'] not in case_names:
                errors.append({'path': f'{at}.case', 'message': f'El caso «{step["case"]}» no existe en cases'})
            if step.get('environment') and step['environment'] not in known:
                errors.append({'path': f'{at}.environment', 'message': f'El ambiente «{step["environment"]}» no existe'})
            alias = step.get('alias') or core.slugify_alias(step['case'], aliases)
            if alias in aliases:
                errors.append({'path': f'{at}.alias', 'message': f'El alias «{alias}» está repetido en la suite'})
            for problem in core.validate_enrichment(step.get('enrich') or [], aliases):
                errors.append({'path': f'{at}.enrich', 'message': problem})
            aliases.append(alias)
    return {'valid': not errors, 'errors': errors, 'warnings': warnings}


def spec_digest(spec):
    return hashlib.sha256(json.dumps(spec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- spec -> workspace

def _default_env_name(spec):
    return spec.get('default_environment') or (spec['environments'][0]['name'] if spec.get('environments') else None)


def _find_by_name(table, project_id, name):
    return next((i for i in core.list_project_items(table, project_id) if i.get('name') == name), None)


def import_spec(spec, project_id, overrides=None):
    """Upserts (by name) environments, cases and suites into the project. Idempotent: sending an updated spec updates in place."""
    overrides = overrides or {}
    known = [e['name'] for e in core.list_project_items('environments', project_id)]
    report = validate_spec(spec, known)
    if not report['valid']:
        raise SpecError(report['errors'])
    envs, cases, suites = {}, {}, {}
    for env in core.list_project_items('environments', project_id):
        envs[env['name']] = env
    for item in spec.get('environments', []):
        url = overrides.get('env_urls', {}).get(item['name']) or overrides.get('base_url') or item['base_url']
        existing = _find_by_name('environments', project_id, item['name'])
        auth = {'type': 'none', 'secret': '', 'env_var': '', 'header': 'X-API-Key', **(item.get('auth') or {})}
        doc = {**(existing or {}), 'name': item['name'], 'project_id': project_id, 'base_url': url.rstrip('/'), 'auth': auth,
               'variables': item.get('variables') or {}}
        envs[item['name']] = core.save('environments', doc)
    default_env = _default_env_name(spec)
    for item in spec['cases']:
        existing = _find_by_name('cases', project_id, item['name'])
        doc = {**(existing or {}), 'name': item['name'], 'type': 'api', 'project_id': project_id, 'method': item['method'], 'path': item['path'],
               'headers': item.get('headers') or {}, 'query': item.get('query') or {}, 'body': item.get('body'), 'variables': item.get('variables') or {},
               'timeout': item.get('timeout', 20), 'assertions': item.get('assertions') or [], 'extract': item.get('extract') or [],
               'tags': item.get('tags') or [], 'notes': item.get('notes', ''), 'code_hints': item.get('code_hints') or {}, 'source': 'agent'}
        doc['environment_id'] = (envs.get(item.get('environment') or default_env) or {}).get('id')
        cases[item['name']] = core.save('cases', doc)
    for item in spec.get('suites', []):
        env = envs[item.get('environment') or default_env or next(iter(envs))]
        steps = [{'case_id': cases[s['case']]['id'], 'alias': s.get('alias') or '', 'environment_id': envs[s['environment']]['id'] if s.get('environment') else None,
                  'enrich': s.get('enrich') or []} for s in item['steps']]
        existing = _find_by_name('suites', project_id, item['name'])
        suites[item['name']] = core.save_suite(item['name'], env['id'], [], project_id, id=(existing or {}).get('id'), steps=steps,
                                              on_failure=item.get('on_failure', 'continue'), retries=item.get('retries', 0),
                                              retry_delay_s=item.get('retry_delay_s', 0), variables=item.get('variables'))
    return {'environments': envs, 'cases': cases, 'suites': suites, 'warnings': report['warnings']}


def ensure_project(name):
    name = (name or AGENT_PROJECT).strip()
    found = next((p for p in core.list_items('projects') if p['name'] == name), None)
    if found:
        return found
    project = core.save('projects', {'name': name, 'description': 'Creado por el protocolo de agentes', 'version': 1})
    if core.get_active_project_id() is None:
        core.set_active_project(project['id'])
    return project


# --------------------------------------------------------------------------- failures

def curl_command(method, url, headers=None, body=None, query=None):
    """Reproduction command. Redacted header values become environment variables to fill in."""
    parts = ['curl', '-sS', '-i', '-X', method]
    for key, value in (headers or {}).items():
        shown = f'${{{re.sub(r"[^A-Z0-9]", "_", key.upper())}}}' if value == '[REDACTED]' else value
        parts += ['-H', f'{key}: {shown}']
    target = url
    if query:
        from urllib.parse import urlencode
        target += ('&' if '?' in url else '?') + urlencode(query)
    if body is not None:
        parts += ['-H', 'Content-Type: application/json', '--data-raw', json.dumps(body, ensure_ascii=False)]
    parts.append(target)
    return ' '.join(part if re.fullmatch(r"[\w@%+=:,./${}-]+", part) else "'" + part.replace("'", "'\\''") + "'" for part in parts)


def describe_rule(rule):
    spec = core.ASSERTION_TYPES.get(rule.get('type'), {})
    detail = ' '.join(str(json.dumps(rule[k], ensure_ascii=False))[:80] for k in ('path', 'name', 'expected') if rule.get(k) not in (None, ''))
    if rule.get('type') == 'json_schema':
        detail = 'el schema esperado'
    if rule.get('type') == 'json_matches':
        detail = f'(ignorando {", ".join(rule.get("ignore") or []) or "nada"})'
    return f'{spec.get("label", rule.get("type"))} {detail}'.strip()


def _kind(run):
    if run['status'] == 'error':
        text = (run.get('error') or '').lower()
        if 'variables sin resolver' in text:
            return 'unresolved_variable'
        if 'enriquecimiento' in text:
            return 'enrichment'
        if run.get('network_error') or any(w in text for w in ('connect', 'timed out', 'timeout', 'refused', 'getaddrinfo', 'ssl')):
            return 'connection'
        return 'error'
    if any(not a['passed'] for a in run.get('assertions', [])):
        return 'assertion'
    return 'extraction' if run.get('error') else 'assertion'


def _diagnose(run, kind):
    status = run.get('http_status')
    body = (run.get('response') or {}).get('body', '')
    hints, category = [], 'unknown'
    if kind == 'connection':
        category, hints = 'network', ['El servicio no respondió: ¿está levantado y escuchando en esa URL/puerto?', 'Revisa base_url del ambiente y que el servicio arranque sin errores.']
    elif kind == 'unresolved_variable':
        category, hints = 'test_setup', ['Falta un dato de la prueba (variable). No es un fallo del servicio: define la variable en el caso, el ambiente o la suite.']
    elif kind == 'enrichment':
        category, hints = 'flow', ['Un paso anterior no devolvió lo que este paso necesita: el servicio previo cambió su respuesta o falló antes.']
    elif status in (401, 403):
        category, hints = 'auth', ['El servicio rechazó las credenciales: revisa que el secreto/token del ambiente sea válido y que el endpoint requiera ese esquema.']
    elif status == 404:
        category, hints = 'not_found', ['La ruta o el recurso no existe: ¿cambió la ruta, falta registrar el endpoint o el dato de prueba?']
    elif status in (400, 422):
        category, hints = 'validation', ['El servicio rechazó la entrada: compara el body enviado con lo que valida el endpoint (campos obligatorios, tipos).']
    elif status and status >= 500:
        category, hints = 'server_error', ['Error interno del servicio: busca la excepción en sus logs en el momento de la ejecución.']
        if re.search(r'traceback|exception|stack|at .+\(.+:\d+\)', body, re.I):
            hints.append('La respuesta incluye una traza: úsala para ubicar el archivo y la línea.')
    elif kind == 'assertion':
        kinds = {a['rule']['type'] for a in run.get('assertions', []) if not a['passed']}
        if kinds & {'json_schema', 'json_type', 'json_exists', 'json_matches'}:
            category, hints = 'contract_mismatch', ['La respuesta cambió de forma respecto a lo esperado (campos/tipos): ¿cambio intencional del contrato o regresión?']
        else:
            category, hints = 'data_mismatch', ['La respuesta es válida pero con valores distintos a los esperados.']
    return {'category': category, 'hints': hints, 'heuristic': True}


def _contract_hint(run):
    request = run.get('request') or {}
    if not request:
        return None
    path = urlsplit(request.get('url', '')).path
    for module in core.list_project_items('modules', run.get('project_id')):
        for operation in module.get('operations', []):
            from .observer import _template_regex
            if operation['method'] == request.get('method') and _template_regex(operation['path']).match(path):
                status = str(run.get('http_status') or '')
                codes = [c for c in operation.get('responses', {}) if str(c).startswith('2')]
                schema = core.operation_response_schema(operation, status if status in {str(c) for c in operation.get('responses', {})} else (codes[0] if codes else '200'))
                return {'module': module.get('name'), 'operation': f'{operation["method"]} {operation["path"]}', 'summary': operation.get('summary', ''),
                        'declared_status_codes': sorted(str(c) for c in operation.get('responses', {})), 'expected_response_schema': schema}
    return None


def _observed_drift(run):
    from . import observer
    request = run.get('request') or {}
    env = core.get('environments', run.get('environment_id')) or {}
    if not request or not env:
        return []
    template = observer.normalize_path(urlsplit(request.get('url', '')).path)
    doc = core.get('interfaces', observer.interface_id(run.get('project_id'), env.get('name', ''), request.get('method', ''), template))
    return [{'kind': d['kind'], 'where': d['where'], 'detail': d['detail'], 'times': d['count']} for d in (doc or {}).get('drift', [])[:5]]


def _body_excerpt(text):
    try:
        parsed = json.loads(text)
        shown = json.dumps(parsed, ensure_ascii=False)
        return parsed if len(shown) <= BODY_EXCERPT else shown[:BODY_EXCERPT] + '…[truncado]'
    except (TypeError, ValueError):
        return (text or '')[:BODY_EXCERPT] + ('…[truncado]' if len(text or '') > BODY_EXCERPT else '')


def failure_from_run(run, suite_run=None, rerun_command=None):
    """One self-contained, agent-ready description of why a run failed. `ltw.failure/1`."""
    snapshot = run.get('case_snapshot') or {}
    request, response = run.get('request') or {}, run.get('response') or {}
    kind = _kind(run)
    env = core.get('environments', run.get('environment_id')) or {}
    failing = [{'assertion': describe_rule(a['rule']), 'rule': a['rule'], 'actual': a['actual']} for a in run.get('assertions', []) if not a['passed']]
    passing = sum(1 for a in run.get('assertions', []) if a['passed'])
    status = run.get('http_status')
    label = f'{snapshot.get("method", request.get("method", "?"))} {snapshot.get("path", request.get("url", ""))}'
    name = run.get('case_name') or snapshot.get('name') or ''
    title = (label if (not name or name.startswith(label)) else f'{name}: {label}') + ' → ' + (str(status) if status else 'sin respuesta')
    goal_rules = [describe_rule(r) for r in snapshot.get('assertions', [])]
    previous, step = [], None
    if suite_run:
        for index, entry in enumerate(suite_run.get('case_runs', [])):
            if entry.get('run_id') == run['id']:
                step = {'suite': suite_run.get('suite_name'), 'index': index + 1, 'alias': entry.get('alias')}
                break
            previous.append({'alias': entry.get('alias'), 'case': entry.get('case_name'), 'status': entry.get('status'), 'environment': entry.get('environment')})
    failure = {
        'format': FORMAT_FAILURE, 'id': run['id'], 'at': run.get('finished_at') or run.get('started_at'), 'kind': kind, 'title': title,
        'case': {'name': run.get('case_name') or snapshot.get('name'), 'method': snapshot.get('method'), 'path': snapshot.get('path'),
                 'tags': snapshot.get('tags') or [], 'notes': snapshot.get('notes') or ''},
        'suite_step': step, 'previous_steps': previous,
        'environment': {'name': env.get('name'), 'base_url': env.get('base_url')},
        'request': {'method': request.get('method'), 'url': request.get('url'), 'headers': request.get('headers') or {},
                    'query': request.get('query') or {}, 'body': request.get('body')} if request else None,
        'enrichment_applied': run.get('enriched') or [],
        'expected': {'rules': goal_rules, 'failed': failing, 'passed_count': passing},
        'response': {'status': status, 'duration_ms': run.get('duration_ms'), 'headers': response.get('headers') or {},
                     'body': _body_excerpt(response.get('body', ''))} if response else None,
        'error': run.get('error'),
        'diagnosis': _diagnose(run, kind),
        'where_to_look': {'code_hints': snapshot.get('code_hints') or {}, 'contract': _contract_hint(run), 'observed_drift': _observed_drift(run)},
        'repro': {'curl': curl_command(request['method'], request['url'], request.get('headers'), request.get('body'), request.get('query')) if request else None,
                  'ltw': rerun_command},
        'fix_goal': 'Hacer que la prueba pase sin debilitar sus aserciones: ' + ('; '.join(goal_rules) if goal_rules else 'la petición debe responder correctamente') + '.',
    }
    failure['brief_markdown'] = brief_markdown(failure)
    return failure


def brief_markdown(f):
    """The same failure as a ready-to-paste brief for an agent (or a person)."""
    lines = [f'# Fallo de prueba: {f["title"]}', '', f'`{f["format"]}` · run `{f["id"]}` · tipo **{f["kind"]}** · diagnóstico (heurístico): **{f["diagnosis"]["category"]}**', '',
             '## Objetivo', f['fix_goal'], '']
    if f.get('suite_step'):
        lines += [f'Paso {f["suite_step"]["index"]} («{f["suite_step"]["alias"]}») de la suite «{f["suite_step"]["suite"]}». Pasos previos: ' +
                  (', '.join(f'{p["alias"]}={p["status"]}' for p in f['previous_steps']) or 'ninguno') + '.', '']
    if f.get('request'):
        lines += ['## Qué se envió', '```http', f'{f["request"]["method"]} {f["request"]["url"]}']
        lines += [f'{k}: {v}' for k, v in (f['request']['headers'] or {}).items()]
        if f['request'].get('body') is not None:
            lines += ['', json.dumps(f['request']['body'], indent=2, ensure_ascii=False)]
        lines += ['```', '']
        if f['enrichment_applied']:
            lines += ['Enriquecimiento aplicado: ' + '; '.join(f['enrichment_applied']), '']
    lines += ['## Esperado vs obtenido']
    for item in f['expected']['failed']:
        lines.append(f'- ✗ {item["assertion"]} → obtenido: `{json.dumps(item["actual"], ensure_ascii=False)[:300]}`')
    if not f['expected']['failed'] and f.get('error'):
        lines.append(f'- ✗ {f["error"]}')
    lines += [f'- ({f["expected"]["passed_count"]} aserción(es) sí pasaron)', '']
    if f.get('response'):
        body = f['response']['body']
        lines += [f'## Respuesta recibida (HTTP {f["response"]["status"]}, {f["response"]["duration_ms"]} ms)', '```json',
                  body if isinstance(body, str) else json.dumps(body, indent=2, ensure_ascii=False), '```', '']
    lines += ['## Diagnóstico (heurístico, no definitivo)'] + [f'- {h}' for h in f['diagnosis']['hints']] + ['']
    where = f['where_to_look']
    lines += ['## Dónde mirar']
    hints = where.get('code_hints') or {}
    if hints:
        lines += [f'- Pista del autor de la prueba: {json.dumps(hints, ensure_ascii=False)}']
    if where.get('contract'):
        c = where['contract']
        lines += [f'- Contrato: módulo «{c["module"]}», operación `{c["operation"]}` ({c["summary"]}); códigos declarados: {", ".join(c["declared_status_codes"])}']
    for drift in where.get('observed_drift') or []:
        lines += [f'- Cambio observado en el tráfico: {drift["kind"]} — {drift["detail"]} ({drift["times"]} veces)']
    if not hints and not where.get('contract') and not where.get('observed_drift'):
        lines += [f'- Sin pistas de código en la especificación: busca el handler de `{f["case"]["method"]} {f["case"]["path"]}` en el servicio «{f["environment"]["name"]}».']
    lines += ['', '## Cómo reproducir']
    if f['repro'].get('curl'):
        lines += ['```bash', f['repro']['curl'], '```']
    if f['repro'].get('ltw'):
        lines += ['```bash', f['repro']['ltw'], '```']
    lines += ['', '## Reglas', '- Corrige el **servicio**; no debilites ni borres las aserciones para que pase, salvo que el contrato haya cambiado a propósito (en ese caso dilo explícitamente).',
              '- Después de corregir, vuelve a ejecutar el comando de arriba y confirma que el caso pasa.']
    return '\n'.join(lines)


# --------------------------------------------------------------------------- running a spec

def run_spec(spec, project_name=None, overrides=None, only=None, ltw_command=None):
    """Imports the spec and runs it (suites, then cases that belong to no suite). Returns an `ltw.report/1` dict."""
    started = time.perf_counter()
    project = ensure_project(project_name or spec.get('project'))
    imported = import_spec(spec, project['id'], overrides)
    cases, suites = imported['cases'], imported['suites']
    only = set(only or [])
    in_suite = {s['case'] for item in spec.get('suites', []) for s in item['steps']}
    results, failures = [], []

    def collect(run_id, suite_run=None, alias=None):
        run = core.get('runs', run_id)
        if run is None:
            return
        results.append({'case': run.get('case_name'), 'alias': alias, 'status': run['status'], 'http_status': run.get('http_status'),
                        'duration_ms': run.get('duration_ms'), 'environment': (core.get('environments', run.get('environment_id')) or {}).get('name'),
                        'suite': suite_run.get('suite_name') if suite_run else None, 'run_id': run_id})
        if run['status'] != 'passed':
            failures.append(failure_from_run(run, suite_run, ltw_command))

    for item in spec.get('suites', []):
        if only and not {s['case'] for s in item['steps']} & only:
            continue
        suite_run = automation.execute_suite(suites[item['name']])
        for entry in suite_run['case_runs']:
            if entry.get('run_id'):
                collect(entry['run_id'], suite_run, entry.get('alias'))
            else:
                results.append({'case': entry.get('case_name') or entry.get('alias'), 'alias': entry.get('alias'), 'status': entry['status'], 'suite': suite_run['suite_name'],
                                'http_status': None, 'duration_ms': None, 'environment': None, 'run_id': None})
    default_env = _default_env_name(spec)
    for item in spec['cases']:
        if item['name'] in in_suite or (only and item['name'] not in only):
            continue
        env = imported['environments'].get(item.get('environment') or default_env)
        if env is None:
            raise SpecError([{'path': '$.cases', 'message': f'El caso «{item["name"]}» no tiene ambiente: define environment o default_environment'}])
        run = core.execute_api(cases[item['name']], env)
        collect(run['id'])
    counts = {s: sum(1 for r in results if r['status'] == s) for s in ('passed', 'failed', 'error')}
    report = {'format': FORMAT_REPORT, 'generated_at': core.now(), 'tool': {'name': 'local-test-workspace', 'version': core.VERSION},
              'spec': {'name': spec.get('name'), 'digest': spec_digest(spec)}, 'project': project['name'],
              'summary': {'status': 'passed' if results and not failures else 'failed', 'total': len(results), **counts,
                          'duration_ms': round((time.perf_counter() - started) * 1000, 1)},
              'results': results, 'failures': failures, 'warnings': imported['warnings']}
    return report


def report_junit(report):
    """JUnit XML for CI dashboards."""
    summary = report['summary']
    suite = ET.Element('testsuite', name=report['spec'].get('name') or 'ltw', tests=str(summary['total']), failures=str(summary['failed']),
                       errors=str(summary['error']), time=str(round(summary['duration_ms'] / 1000, 3)))
    failed = {f['id']: f for f in report['failures']}
    for result in report['results']:
        case = ET.SubElement(suite, 'testcase', name=result['case'] or '?', classname=result.get('suite') or 'cases', time=str(round((result.get('duration_ms') or 0) / 1000, 3)))
        failure = failed.get(result.get('run_id'))
        if result['status'] == 'passed':
            continue
        node = ET.SubElement(case, 'error' if result['status'] == 'error' else 'failure', message=(failure or {}).get('title', result['status']))
        node.text = (failure or {}).get('brief_markdown', result['status'])
    return ET.tostring(suite, encoding='unicode', xml_declaration=True)


# --------------------------------------------------------------------------- failures of stored runs (UI / API)

def failure_for_run_id(run_id):
    run = core.get('runs', run_id)
    if run is None or run.get('type') not in ('api', 'ui'):
        raise ValueError('Ejecución inexistente o sin detalle de petición')
    suite_run = None
    if run.get('suite_id'):
        suite_run = next((r for r in core.list_items('runs') if r.get('type') == 'suite' and any(e.get('run_id') == run_id for e in r.get('case_runs', []))), None)
    return failure_from_run(run, suite_run)


# --------------------------------------------------------------------------- API token

def agent_token():
    """Token for the local HTTP API: LTW_AGENT_TOKEN, or one generated once and kept in the workspace."""
    import os
    token = os.environ.get('LTW_AGENT_TOKEN') or core.get_setting('agent_token')
    if not token:
        token = _secrets.token_urlsafe(24)
        core.set_setting('agent_token', token)
    return token


def rotate_agent_token():
    token = _secrets.token_urlsafe(24)
    core.set_setting('agent_token', token)
    return token


def check_token(header_value):
    expected = agent_token()
    supplied = (header_value or '').removeprefix('Bearer ').strip()
    return bool(supplied) and hmac.compare_digest(supplied.encode(), expected.encode())


def register_api(app):
    """Mounts /agent/v1/* on the NiceGUI (FastAPI) app. Loopback only + bearer token: a web page cannot call it."""
    from fastapi import Header, HTTPException, Request
    from fastapi.responses import JSONResponse, PlainTextResponse

    def guard(request: Request, authorization):
        host = (request.headers.get('host') or '').split(':')[0]
        if host not in ('127.0.0.1', 'localhost', '[::1]'):
            raise HTTPException(403, 'Solo se acepta acceso local')
        if not check_token(authorization):
            raise HTTPException(401, 'Falta el token: cabecera Authorization: Bearer <token> (mostrado en el espacio de trabajo → Agente)')

    @app.get('/agent/v1/schema')
    def schema():
        return JSONResponse(SPEC_SCHEMA)

    @app.post('/agent/v1/validate')
    async def validate(request: Request, authorization: str = Header(None)):
        guard(request, authorization)
        return JSONResponse(validate_spec(await request.json()))

    @app.post('/agent/v1/run')
    async def run(request: Request, authorization: str = Header(None)):
        guard(request, authorization)
        spec = await request.json()
        overrides = {'base_url': request.query_params.get('base_url')} if request.query_params.get('base_url') else None
        try:
            return JSONResponse(run_spec(spec, overrides=overrides, ltw_command=None))
        except SpecError as exc:
            return JSONResponse({'format': FORMAT_REPORT, 'summary': {'status': 'invalid_spec'}, 'errors': exc.errors}, status_code=422)

    @app.get('/agent/v1/failures/{run_id}')
    def failure(run_id: str, request: Request, format: str = 'json', authorization: str = Header(None)):
        guard(request, authorization)
        try:
            item = failure_for_run_id(run_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))
        return PlainTextResponse(item['brief_markdown']) if format == 'md' else JSONResponse(item)


# --------------------------------------------------------------------------- command line

HELP = """Uso:
  python run.py --validate spec.json                 valida (sale 0 si es válida, 2 si no)
  python run.py --run spec.json [opciones]           importa y ejecuta; sale 0 si todo pasa, 1 si hay fallos, 2 si la spec es inválida
  python run.py --schema                             imprime el JSON Schema de ltw.spec/1
Opciones de --run:
  --report out.json     informe ltw.report/1 (con un ltw.failure/1 por fallo)     --md out.md      briefs de fallos en Markdown
  --junit out.xml       JUnit XML para CI                                          --base-url URL   reemplaza la URL de todos los ambientes
  --only-failed r.json  re-ejecuta solo lo que falló en un informe anterior        --persist        guarda en el workspace compartido (si no, base temporal)
  --project NOMBRE      proyecto destino con --persist (por defecto «Agente»)
"""


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except OSError as exc:
        raise SystemExit(f'No se pudo leer {path}: {exc}')
    except ValueError as exc:
        raise SystemExit(f'{path} no es JSON válido: {exc}')


def cli(argv):
    """Entry point used by `python run.py --run ...`. Returns the process exit code."""
    args = list(argv)

    def take(flag, default=None):
        if flag in args:
            index = args.index(flag)
            value = args[index + 1] if index + 1 < len(args) else default
            del args[index:index + 2]
            return value
        return default
    if '--schema' in args:
        print(json.dumps(SPEC_SCHEMA, indent=2, ensure_ascii=False))
        return 0
    validate_path, run_path = take('--validate'), take('--run')
    report_path, md_path, junit_path = take('--report'), take('--md'), take('--junit')
    base_url, previous, project = take('--base-url'), take('--only-failed'), take('--project')
    persist = '--persist' in args
    if not (validate_path or run_path):
        print(HELP)
        return 2
    spec = _read_json(validate_path or run_path)
    if validate_path:
        result = validate_spec(spec)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result['valid'] else 2
    temp = None
    if not persist:
        temp = Path(tempfile.mkdtemp(prefix='ltw-'))
        core.ROOT, core.DB, core.ARTIFACTS = temp, temp / 'workspace.sqlite3', temp / 'evidence'
    try:
        only = [f['case']['name'] for f in _read_json(previous).get('failures', [])] if previous else None
        command = f'python run.py --run {run_path}' + (f' --base-url {base_url}' if base_url else '')
        try:
            report = run_spec(spec, project_name=project, overrides={'base_url': base_url} if base_url else None, only=only, ltw_command=command)
        except SpecError as exc:
            print(json.dumps({'valid': False, 'errors': exc.errors}, indent=2, ensure_ascii=False), file=sys.stderr)
            return 2
        if report_path:
            Path(report_path).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        if md_path:
            Path(md_path).write_text('\n\n---\n\n'.join(f['brief_markdown'] for f in report['failures']) or '# Sin fallos\n', encoding='utf-8')
        if junit_path:
            Path(junit_path).write_text(report_junit(report), encoding='utf-8')
        s = report['summary']
        print(f'{s["status"].upper()}: {s["passed"]} pasaron, {s["failed"]} fallaron, {s["error"]} con error ({s["total"]} en total, {s["duration_ms"]} ms)')
        for failure in report['failures']:
            print(f'  ✗ {failure["title"]}  [{failure["diagnosis"]["category"]}]')
        return 0 if s['status'] == 'passed' else 1
    finally:
        if temp is not None:
            shutil.rmtree(temp, ignore_errors=True)
