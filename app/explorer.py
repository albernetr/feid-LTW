"""Automatic exploration of an imported OpenAPI contract: discover what is safe to call, build cases whose
assertions come from the contract itself (not guessed), run them for real, and write up what was found.

Design choice: most of this needs no model at all. Which operations exist, which are safe (GET) versus a
write, which path parameters can be filled from another endpoint's listing, and where a field such as `id`
actually sits in the response (possibly behind a wrapper key) are all things the contract already states —
reading it carefully replaces re-deriving them by hand. The only place real judgement is useful is writing a
plausible body for a POST/PUT/PATCH; that step is optional and goes through `llm` when configured, and is never
executed automatically (see `include_writes`).

The whole point is to replace the repetitive part of a session like: open the contract, find a safe GET, guess
where the id lives, call it, notice the extraction path is wrong because the response wraps the object, fix it,
move on to the next endpoint, and finally write up what passed, what failed and why.
"""
import copy
import json
import re
from . import core, agent, observer

ID_NAME_RE = re.compile(r'(^id$|^uuid$|_id$|Id$|ID$)')
GENERATED_TAG = 'auto-explorado'
MAX_LISTING_SAMPLES = 40
MAX_SELF_HEAL_ATTEMPTS = 3


class ExplorationError(ValueError):
    pass


# --------------------------------------------------------------------------- reading the contract, not guessing

def _unwrap(schema):
    """Pydantic-style optional fields show up as anyOf: [{type}, {type: null}]; look past that wrapper."""
    if isinstance(schema, dict) and isinstance(schema.get('anyOf'), list):
        for option in schema['anyOf']:
            if isinstance(option, dict) and option.get('type') != 'null':
                return option
    return schema if isinstance(schema, dict) else {}


def guess_id_paths(schema):
    """Where a scalar identifier sits in a response, shallowest and declared-first first. ['$.id', '$.process.id', ...].
    The match is on the PROPERTY NAME (id, dataset_id, ...), so this walks properties directly rather than through
    `_walk_schema`'s node-only predicate."""
    found = []

    def recurse(node, path, depth):
        if depth > 4 or not isinstance(node, dict):
            return
        node = _unwrap(node)
        for name, sub in (node.get('properties') or {}).items():
            sub_u = _unwrap(sub)
            if ID_NAME_RE.search(name) and sub_u.get('type') in ('string', 'integer'):
                found.append(f'{path}.{name}')
            if sub_u.get('type') == 'object':
                recurse(sub_u, f'{path}.{name}', depth + 1)
    recurse(schema, '$', 0)
    return found


def guess_listing_paths(schema):
    """Where a list of objects with an id lives in a response: ['$.items[0].id', '$.data.datasets[0].id', ...]."""
    found = []

    def recurse(node, path, depth):
        if depth > 4 or not isinstance(node, dict):
            return
        node = _unwrap(node)
        if node.get('type') == 'array':
            items = _unwrap(node.get('items') or {})
            ids = guess_id_paths(items) if items.get('type') == 'object' else (['$'] if items.get('type') in ('string', 'integer') else [])
            if ids:
                found.append(path + '[0]' + ids[0][1:])
            return
        for name, sub in (node.get('properties') or {}).items():
            recurse(_unwrap(sub), f'{path}.{name}', depth + 1)
    recurse(schema, '$', 0)
    return found


def success_status(operation):
    """The first 2xx the contract documents for this operation, or a sane default by method."""
    for code in sorted((operation.get('responses') or {}), key=lambda c: (not c.startswith('2'), c)):
        if code.startswith('2'):
            return int(code) if code.isdigit() else ({'POST': 201}.get(operation['method'], 200))
    return {'POST': 201, 'DELETE': 204}.get(operation['method'], 200)


def path_params(operation):
    return re.findall(r'\{(\w+)\}', operation['path'])


def required_query_params(operation):
    return [p['name'] for p in operation.get('parameters', []) if isinstance(p, dict) and p.get('in') == 'query' and p.get('required')]


# --------------------------------------------------------------------------- discovery: what can be called, and with what

def discover(module, env, extra_headers=None, max_listing_samples=MAX_LISTING_SAMPLES):
    """Classifies every GET as 'ready' (safe, parameters resolved) or 'blocked' (needs data we could not find),
    by first running the zero-parameter GETs and harvesting real ids from their responses.
    Returns {'ready': [...], 'blocked': [...], 'pool': {name: [values]}} - pure analysis, nothing besides the
    harvesting GETs is called. Writes (POST/PUT/PATCH/DELETE) are listed separately, never called here."""
    gets = [o for o in module['operations'] if o['method'] == 'GET']
    zero_param = [o for o in gets if not path_params(o) and not required_query_params(o)]
    templated = [o for o in gets if path_params(o)]
    writes = [o for o in module['operations'] if o['method'] in ('POST', 'PUT', 'PATCH', 'DELETE')]

    pool, sources = {}, {}  # param-ish name -> sample values; name -> the op that produced them (for prefix matching)
    ready, blocked = [], []
    for op in zero_param:
        schema = core.operation_response_schema(op, str(success_status(op)))
        listing_paths = guess_listing_paths(schema) if schema else []
        entry = {'operation': op, 'resolved_path': op['path'], 'status': 'ready', 'kind': 'listing' if listing_paths else 'leaf',
                 'listing_paths': listing_paths}
        ready.append(entry)
        if listing_paths:
            # a bare probe: no assertions, so LTW always calls it 'failed' (no assertion = nothing confirmed) - only the real HTTP
            # outcome and body matter here, this is not a test result and nothing from it is ever shown as one.
            try:
                probe = core.execute_api({'method': 'GET', 'path': op['path'], 'headers': extra_headers or {}, 'query': {}, 'body': None, 'timeout': 20},
                                         env, persist=False)
            except Exception:
                continue
            if probe.get('error') or not (200 <= (probe.get('http_status') or 0) < 300) or not probe.get('response'):
                continue
            try:
                body = json.loads(probe['response']['body'])
            except (ValueError, TypeError):
                continue
            for list_path in listing_paths:
                try:
                    values = core.extract_path(body, re.sub(r'\[0\]', '[*]', list_path))
                except core.PathError:
                    continue
                values = values if isinstance(values, list) else [values]
                values = [str(v) for v in values[:max_listing_samples] if v is not None]
                if values:
                    base = op['path'].rstrip('/').rsplit('/', 1)[-1]  # last path segment names the resource: /datasets -> "datasets"
                    for key in {base, base.rstrip('s'), base + '_id', base.rstrip('s') + '_id'}:
                        pool.setdefault(key, values)
                        sources.setdefault(key, op['path'])

    for op in templated:
        params = path_params(op)
        missing = []
        path = op['path']
        for param in params:
            candidates = [param, param.lower(), re.sub(r'_?[Ii]d$', '', param), re.sub(r'_?[Ii]d$', '', param).lower()]
            value = next((pool[c][0] for c in candidates if c in pool and pool[c]), None)
            if value is None:  # fall back to prefix matching against the op's own path (covers names like org_id ~ organizations)
                best = max((k for k in pool if pool[k]), key=lambda k: _common_prefix(op['path'], sources.get(k, '')), default=None)
                if best and _common_prefix(op['path'], sources.get(best, '')) >= 1:
                    value = pool[best][0]
            if value is None:
                missing.append(param)
            else:
                path = path.replace('{' + param + '}', value)
        if missing or required_query_params(op):
            blocked.append({'operation': op, 'reason': f"faltan valores para: {', '.join(missing + required_query_params(op))}"})
        else:
            ready.append({'operation': op, 'resolved_path': path, 'status': 'ready', 'kind': 'leaf', 'listing_paths': []})
    return {'ready': ready, 'blocked': blocked, 'writes': writes, 'pool': pool}


def _common_prefix(a, b):
    a_parts, b_parts = a.strip('/').split('/'), b.strip('/').split('/')
    n = 0
    for x, y in zip(a_parts, b_parts):
        if x != y:
            break
        n += 1
    return n


# --------------------------------------------------------------------------- building a case from the contract alone

def build_case(entry, module, project_id, environment_id, extra_headers=None):
    op = entry['operation']
    schema = core.operation_response_schema(op, str(success_status(op)))
    id_paths = guess_id_paths(schema) if schema else []
    assertions = [{'type': 'status', 'expected': success_status(op)}]
    if schema:
        assertions.append({'type': 'json_schema', 'schema': schema})
    extract = [{'name': 'id', 'source': 'json', 'path': id_paths[0]}] if id_paths else []
    return {'name': f'[{GENERATED_TAG}] {op["method"]} {op["path"]}', 'method': op['method'], 'path': entry['resolved_path'],
            'project_id': project_id, 'environment_id': environment_id, 'module_id': module.get('id'), 'headers': dict(extra_headers or {}),
            'query': {}, 'body': None, 'assertions': assertions, 'variables': {}, 'extract': extract, 'timeout': 20,
            'tags': [GENERATED_TAG], 'notes': op.get('summary', ''),
            'explorer': {'module_id': module.get('id'), 'operation': f'{op["method"]} {op["path"]}', 'id_paths': id_paths, 'id_path_attempt': 0}}


def _self_heal(case, run, entry):
    """If every failure is an assertion about a path the contract offered more than one candidate for, try the next
    candidate instead of giving up - this is exactly the `$.id` vs `$.process.id` mistake, fixed from the contract,
    not by poking at the live response until something sticks."""
    candidates = case.get('explorer', {}).get('id_paths') or []
    attempt = case.get('explorer', {}).get('id_path_attempt', 0) + 1
    if attempt >= len(candidates) or attempt > MAX_SELF_HEAL_ATTEMPTS:
        return None
    failing_kinds = {a['rule']['type'] for a in run.get('assertions', []) if not a['passed']}
    if not failing_kinds <= {'json_schema'} or run.get('http_status') != success_status(entry['operation']):
        return None  # a status mismatch or a body that fails json_schema for a real reason is not a path-guessing problem
    healed = copy.deepcopy(case)
    healed['extract'] = [{'name': 'id', 'source': 'json', 'path': candidates[attempt]}]
    healed['explorer']['id_path_attempt'] = attempt
    return healed


# --------------------------------------------------------------------------- running the plan and classifying what happened

def run_plan(plan, module, project_id, environment, extra_headers=None, persist=True, on_progress=None, cancel=None):
    """Executes every 'ready' GET, self-healing id-path guesses once, and classifies each result:
    'passed', 'needs_review' (contract vs. reality disagree: a real finding), or 'blocked' (never run).
    `on_progress(entry)` is called once per completed GET, like `automation.execute_suite`'s, so the same
    dialog/progress-bar pattern the UI already has for suites works here too. `cancel`: a threading.Event-like
    object (see `automation.new_cancel_token`); checked between calls, so a long sweep can be stopped early -
    anything already run stays recorded, the rest is reported as cancelled rather than blocked.
    Returns {'results': [...], 'blocked': plan['blocked'], 'cancelled': int, 'summary': {...}}."""
    results = []
    cancelled = 0
    for entry in plan['ready']:
        if cancel is not None and cancel.is_set():
            cancelled += 1
            continue
        case = build_case(entry, module, project_id, environment['id'], extra_headers)
        run = core.execute_api(case, environment, persist=persist)
        healed_case = _self_heal(case, run, entry) if run['status'] != 'passed' else None
        if healed_case is not None:
            healed_run = core.execute_api(healed_case, environment, persist=persist)
            if healed_run['status'] == 'passed':
                case, run = healed_case, healed_run
        classification = 'passed' if run['status'] == 'passed' else _classify_failure(run, entry['operation'])
        if run.get('response') is not None:
            try:
                parsed = json.loads(run['response']['body'])
                observer.record(module['name'], project_id, entry['operation']['method'], entry['operation']['path'], '', '',
                                run.get('http_status') or 0, json.dumps(parsed), run.get('duration_ms') or 0, origin=environment.get('base_url', ''))
            except (ValueError, TypeError):
                pass
        entry_result = {'case': case, 'run': run, 'classification': classification, 'operation': entry['operation']}
        results.append(entry_result)
        if on_progress:
            on_progress(entry_result)
    passed = sum(r['classification'] == 'passed' for r in results)
    review = [r for r in results if r['classification'] != 'passed']
    return {'results': results, 'blocked': plan['blocked'], 'cancelled': cancelled,
            'summary': {'total': len(results), 'passed': passed, 'needs_review': len(review), 'blocked': len(plan['blocked']), 'cancelled': cancelled}}


def _classify_failure(run, operation):
    """Mirrors agent.py's heuristic: a declared-but-different status or a schema mismatch is a contract-vs-reality
    finding worth a human's attention; it is never silently weakened or hidden."""
    kind = agent._kind(run)
    return agent._diagnose(run, kind)['category']


# --------------------------------------------------------------------------- keeping the generated cases honest after a contract changes

def diff_module(old_module, new_module):
    """{'added': [...op keys], 'removed': [...], 'changed': [(op_key, [reasons])]} comparing two imports of the same module."""
    def key(op):
        return f'{op["method"]} {op["path"]}'
    old_by_key = {key(o): o for o in old_module.get('operations', [])}
    new_by_key = {key(o): o for o in new_module.get('operations', [])}
    added = sorted(set(new_by_key) - set(old_by_key))
    removed = sorted(set(old_by_key) - set(new_by_key))
    changed = []
    for k in sorted(set(old_by_key) & set(new_by_key)):
        old_op, new_op = old_by_key[k], new_by_key[k]
        reasons = []
        old_required = {p['name'] for p in old_op.get('parameters', []) if isinstance(p, dict) and p.get('required')}
        new_required = {p['name'] for p in new_op.get('parameters', []) if isinstance(p, dict) and p.get('required')}
        if new_required - old_required:
            reasons.append(f'nuevos parámetros obligatorios: {", ".join(sorted(new_required - old_required))}')
        old_ids = guess_id_paths(core.operation_response_schema(old_op, str(success_status(old_op))) or {})
        new_ids = guess_id_paths(core.operation_response_schema(new_op, str(success_status(new_op))) or {})
        if old_ids[:1] != new_ids[:1]:
            reasons.append(f'la forma de la respuesta cambió: el identificador pasó de {old_ids[:1] or "—"} a {new_ids[:1] or "—"}')
        if reasons:
            changed.append((k, reasons))
    return {'added': added, 'removed': removed, 'changed': changed}


def save_generated_cases(plan_result, project_id):
    """Persists the cases this exploration built (passed or needs_review - both are worth keeping as regression
    cases), upserting by (module, operation) so running the same exploration twice updates in place instead of
    piling up duplicates - the exact mistake a hand-run script made during the FEID session."""
    existing = {(c['explorer']['module_id'], c['explorer']['operation']): c for c in core.list_project_items('cases', project_id) if c.get('explorer')}
    saved = []
    for r in plan_result['results']:
        case = copy.deepcopy(r['case'])
        case['project_id'] = project_id
        key = (case['explorer']['module_id'], case['explorer']['operation'])
        if key in existing:
            case['id'] = existing[key]['id']
        saved.append(core.save('cases', case))
    return saved


def stale_cases(project_id, module_id, diff):
    """Cases this explorer generated that a contract diff has just invalidated (operation removed, or changed in a
    way its assertions no longer reflect): these are the ones worth re-discovering, not every case in the project."""
    affected_keys = set(diff['removed']) | {k for k, _ in diff['changed']}
    stale = []
    for case in core.list_project_items('cases', project_id):
        info = case.get('explorer')
        if info and info.get('module_id') == module_id and info.get('operation') in affected_keys:
            stale.append(case)
    return stale


# --------------------------------------------------------------------------- the write-up

def narrate(module, plan_result, project_name, llm_config=None):
    """Markdown summary of one exploration run: coverage, what needs a human, and why - the part that otherwise
    gets typed out by hand after every session like this one. `llm_config`: pass to layer a prose paragraph on
    top (optional; the structured report below is already complete without it)."""
    s = plan_result['summary']
    lines = [f'# Exploración automática: {module["name"]}', '', f'**Proyecto:** {project_name} · **Operaciones del contrato:** {len(module["operations"])}', '',
             '## Cobertura', '', f'- {s["total"]} lectura(s) sin parámetros bloqueantes, ejecutadas', f'- {s["passed"]} coinciden con lo que declara el contrato',
             f'- {s["needs_review"]} necesitan revisión (el contrato y la respuesta real no coinciden)', f'- {s["blocked"]} no se pudieron ejecutar (sin datos para resolver sus parámetros)', '']
    review = [r for r in plan_result['results'] if r['classification'] != 'passed']
    if review:
        lines += ['## Necesitan revisión', '']
        for r in review:
            op, run = r['operation'], r['run']
            lines.append(f'- **{op["method"]} {op["path"]}** ({r["classification"]}): HTTP {run.get("http_status")}'
                         + (f' — {run.get("error")}' if run.get('error') else ''))
        lines.append('')
    if plan_result['blocked']:
        lines += ['## Sin ejecutar (faltan datos)', ''] + [f'- {b["operation"]["method"]} {b["operation"]["path"]}: {b["reason"]}' for b in plan_result['blocked']] + ['']
    if llm_config is not None:
        from . import llm
        try:
            prose = llm.ask('Resume en dos o tres frases, en español, el estado de esta exploración de API para alguien que no va a leer el detalle.',
                            '\n'.join(lines), llm_config)
            lines = [lines[0], '', prose, ''] + lines[1:]
        except llm.LLMError:
            pass
    return '\n'.join(lines)


# --------------------------------------------------------------------------- command line

def cli(argv):
    """python run.py --explore --project NOMBRE --module NOMBRE [--environment NOMBRE] [--save] [--report out.md]
    Read-only: only GETs are ever called. --save persists the generated cases into the project (upserted, not duplicated)."""
    import sys
    args = list(argv)

    def take(flag, default=None):
        if flag in args:
            index = args.index(flag)
            value = args[index + 1] if index + 1 < len(args) else default
            del args[index:index + 2]
            return value
        return default
    project_name, module_name, env_name = take('--project'), take('--module'), take('--environment')
    save, report_path = '--save' in args, take('--report')
    if '--save' in args:
        args.remove('--save')
    headers = {}
    while '--header' in args:
        raw = take('--header')
        name, _, value = raw.partition(':')
        headers[name.strip()] = value.strip()
    if not project_name or not module_name:
        print('Indica --project NOMBRE y --module NOMBRE', file=sys.stderr)
        return 2
    project = next((p for p in core.list_items('projects') if p['name'].lower() == project_name.lower()), None)
    if project is None:
        print(f'No existe el proyecto «{project_name}»', file=sys.stderr)
        return 2
    module = next((m for m in core.list_project_items('modules', project['id']) if m['name'].lower() == module_name.lower()), None)
    if module is None:
        print(f'No existe el módulo «{module_name}» en «{project_name}»', file=sys.stderr)
        return 2
    envs = core.list_project_items('environments', project['id'])
    env = next((e for e in envs if e['name'].lower() == (env_name or '').lower()), None) if env_name else (envs[0] if len(envs) == 1 else None)
    if env is None:
        print('Indica --environment NOMBRE (hay más de un ambiente, o ninguno, en el proyecto)' if envs else 'El proyecto no tiene ambientes', file=sys.stderr)
        return 2
    plan = discover(module, env, extra_headers=headers)
    result = run_plan(plan, module, project['id'], env, extra_headers=headers)
    text = narrate(module, result, project['name'])
    print(text)
    if report_path:
        from pathlib import Path
        Path(report_path).write_text(text, encoding='utf-8')
    if save:
        saved = save_generated_cases(result, project['id'])
        print(f'\n{len(saved)} caso(s) guardados en el proyecto.')
    return 1 if result['summary']['needs_review'] else 0
