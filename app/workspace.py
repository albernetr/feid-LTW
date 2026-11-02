"""Workspace logic without UI: the request being edited (draft), its persistent history, and conversions to cases."""
import copy
import getpass
import json
import re
from urllib.parse import parse_qsl, urlsplit
from . import core

HISTORY = 'lab_history'
MAX_HISTORY = 300          # per author, starred entries are kept
MAX_BODY_STORED = 100_000


def author():
    try:
        return getpass.getuser()
    except Exception:
        return 'local'


# --------------------------------------------------------------------------- draft

def row(key='', value='', on=True):
    return {'on': on, 'key': key, 'value': value}


def new_draft():
    return {'name': '', 'method': 'GET', 'scheme': 'https', 'env_id': '', 'url': '', 'body': '', 'timeout': 20,
            'headers': [], 'query': [], 'variables': [], 'assertions': [], 'extract': [], 'source': None, 'chat': None}


def rows_to_dict(rows):
    return {r['key'].strip(): str(r['value']) for r in rows if r.get('on', True) and (r.get('key') or '').strip()}


def dict_to_rows(data):
    return [row(str(k), v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)) for k, v in (data or {}).items()]


def parse_bulk(text):
    """'Key: value' / 'key=value' lines -> rows; a leading '#' keeps the row but disables it."""
    rows = []
    for line in (text or '').splitlines():
        line = line.strip()
        if not line:
            continue
        on = not line.startswith('#')
        line = line.lstrip('#').strip()
        match = re.match(r'^([^:=]+?)\s*[:=]\s*(.*)$', line)
        rows.append(row(match.group(1).strip(), match.group(2).strip(), on) if match else row(line, '', on))
    return rows


def format_bulk(rows):
    return '\n'.join(('' if r.get('on', True) else '# ') + f'{r["key"]}: {r["value"]}' for r in rows if (r.get('key') or '').strip())


def current_url(draft):
    """What the user typed, with the chosen protocol added when it is a bare host and no environment is selected."""
    raw = (draft.get('url') or '').strip()
    if not raw or raw.startswith(('http://', 'https://', '/')) or draft.get('env_id'):   # a path is never a host
        return raw
    return core.normalize_url(raw, draft.get('scheme', 'https'))


def resolve_target(draft):
    """(environment, path) for a send. Without an environment a transient one is derived from the URL (nothing is saved)."""
    raw = current_url(draft)
    if not raw:
        raise ValueError('Escribe la URL o una ruta')
    env = core.get('environments', draft['env_id']) if draft.get('env_id') else None
    if raw.startswith(('http://', 'https://')):
        origin, path = core.split_url(raw)
        if env is not None and env['base_url'].rstrip('/') != origin:
            raise ValueError(f'La URL no pertenece al ambiente «{env["name"]}» ({env["base_url"]})')
        if env is None:
            env = {'id': 'espacio-de-trabajo', 'name': urlsplit(origin).netloc, 'base_url': origin, 'auth': {'type': 'none'}, 'variables': {}}
        return env, path
    if env is None:
        raise ValueError('Con «URL completa» escribe una URL http(s) completa, o elige un ambiente y usa una ruta')
    return env, raw if raw.startswith('/') else '/' + raw


def build_case(draft, name=None, assertions=None):
    """The draft as a case dict. Raises ValueError with a message meant for the user."""
    env, path = resolve_target(draft)
    path, _, qs = path.partition('?')
    query = rows_to_dict(draft['query'])
    query.update(dict(parse_qsl(qs, keep_blank_values=True)))
    body_text = (draft.get('body') or '').strip()
    try:
        body = json.loads(body_text) if body_text else None
    except ValueError as exc:
        raise ValueError(f'El body no es JSON válido: {exc}')
    case = {'name': name or draft.get('name') or f'{draft["method"]} {path}', 'type': 'api', 'method': draft['method'], 'path': path, 'query': query,
            'body': body, 'headers': rows_to_dict(draft['headers']), 'variables': rows_to_dict(draft['variables']),
            'assertions': copy.deepcopy(draft['assertions'] if assertions is None else assertions), 'extract': copy.deepcopy(draft['extract']),
            'timeout': draft.get('timeout') or 20, 'chat': copy.deepcopy(draft.get('chat'))}
    return case, env


def placeholders(draft):
    """{{variables}} used by the draft that are neither defined in it nor in its environment."""
    try:
        case, env = build_case(draft)
    except ValueError:
        return [], []
    names = core.find_unresolved(case['path'], case['headers'], case['query'], case['body'])
    names = [n for n in names if not n.startswith('secret:') and not n.startswith('@')]
    defined = {**(env.get('variables') or {}), **case['variables']}
    return [n for n in names if n in defined], [n for n in names if n not in defined]


def draft_from_case(case, env_id=''):
    d = new_draft()
    d.update({'name': case['name'], 'method': case.get('method', 'GET'), 'env_id': env_id, 'url': case.get('path', ''), 'timeout': case.get('timeout', 20),
              'body': json.dumps(case['body'], indent=2, ensure_ascii=False) if case.get('body') is not None else '',
              'headers': dict_to_rows(case.get('headers')), 'query': dict_to_rows(case.get('query')), 'variables': dict_to_rows(case.get('variables')),
              'assertions': copy.deepcopy(case.get('assertions') or []), 'extract': copy.deepcopy(case.get('extract') or []),
              'chat': copy.deepcopy(case.get('chat')), 'source': {'type': 'case', 'id': case['id'], 'updated_at': case.get('updated_at')}})
    return d


def draft_to_spec(draft, environment=None):
    """The draft as an `ltw.spec/1` (what an agent would send): shows the format by example."""
    case, env = build_case(draft)
    item = {'name': case['name'], 'method': case['method'], 'path': case['path'], 'assertions': case['assertions'] or [{'type': 'status', 'expected': 200}]}
    for key in ('headers', 'query', 'variables'):
        if case[key]:
            item[key] = case[key]
    if case['body'] is not None:
        item['body'] = case['body']
    if case['extract']:
        item['extract'] = case['extract']
    spec = {'format': 'ltw.spec/1', 'name': case['name'], 'environments': [{'name': env.get('name') or 'destino', 'base_url': env['base_url']}], 'cases': [item]}
    if (env.get('auth') or {}).get('type', 'none') != 'none':
        spec['environments'][0]['auth'] = {k: v for k, v in env['auth'].items() if v}
    return spec


def draft_from_spec_case(item, environment=None):
    """First case of a spec as a draft (environment: the spec's environment dict, used to build the full URL)."""
    d = new_draft()
    d.update({'name': item['name'], 'method': item['method'], 'timeout': item.get('timeout', 20),
              'url': (environment['base_url'].rstrip('/') if environment else '') + item['path'],
              'body': json.dumps(item['body'], indent=2, ensure_ascii=False) if item.get('body') is not None else '',
              'headers': dict_to_rows(item.get('headers')), 'query': dict_to_rows(item.get('query')), 'variables': dict_to_rows(item.get('variables')),
              'assertions': copy.deepcopy(item.get('assertions') or []), 'extract': copy.deepcopy(item.get('extract') or [])})
    if d['url'].startswith('http://'):
        d['scheme'] = 'http'
    return d


# --------------------------------------------------------------------------- history

def request_key(draft):
    try:
        env, path = resolve_target(draft)
    except ValueError:
        return None
    return f'{draft["method"]} {env["base_url"].rstrip("/")}{path.partition("?")[0]}'


def _result_of(run):
    response = run.get('response') or {}
    body = response.get('body', '')
    return {'status': run.get('status'), 'http_status': run.get('http_status'), 'duration_ms': run.get('duration_ms'), 'error': run.get('error'),
            'headers': response.get('headers') or {}, 'body': body[:MAX_BODY_STORED], 'size': len(body),
            'assertions': [{'passed': a['passed'], 'actual': a['actual'], 'rule': a['rule']} for a in run.get('assertions', [])]}


def record_history(draft, run):
    """Stores one send. Secrets already used in the run were scrubbed by execute_api; headers are kept as the user typed them
    ({{secret:...}} references stay references)."""
    key = request_key(draft)
    snapshot = copy.deepcopy({k: v for k, v in draft.items() if k != 'source'})
    entry = {'id': core.uid(), 'author': author(), 'at': core.now(), 'starred': False, 'key': key, 'name': draft.get('name') or '',
             'draft': snapshot, 'result': _result_of(run), 'resolved_url': (run.get('request') or {}).get('url')}
    core.save(HISTORY, entry)
    _trim(entry['author'])
    return entry


def _trim(who):
    mine = [e for e in core.list_items(HISTORY) if e.get('author') == who and not e.get('starred')]
    for old in sorted(mine, key=lambda e: e['at'], reverse=True)[MAX_HISTORY:]:
        core.delete(HISTORY, old['id'])


def list_history(mine_only=True, query='', limit=200):
    who = author()
    items = [e for e in core.list_items(HISTORY) if (not mine_only or e.get('author') == who)]
    query = (query or '').strip().lower()
    if query:
        items = [e for e in items if query in (e.get('key') or '').lower() or query in (e.get('name') or '').lower()]
    return sorted(items, key=lambda e: e['at'], reverse=True)[:limit]


def toggle_star(entry_id):
    entry = core.get(HISTORY, entry_id)
    if entry:
        entry['starred'] = not entry.get('starred')
        core.save(HISTORY, entry)
    return entry


def delete_entry(entry_id):
    core.delete(HISTORY, entry_id)


def clear_history(mine_only=True):
    who = author()
    removed = 0
    for entry in core.list_items(HISTORY):
        if not entry.get('starred') and (not mine_only or entry.get('author') == who):
            core.delete(HISTORY, entry['id'])
            removed += 1
    return removed


def previous_result(draft, exclude_id=None):
    """The latest earlier response to the same method + URL (for the Diff tab)."""
    key = request_key(draft)
    if not key:
        return None
    for entry in sorted(core.list_items(HISTORY), key=lambda e: e['at'], reverse=True):
        if entry.get('key') == key and entry['id'] != exclude_id and entry['result'].get('body'):
            return entry
    return None


def diff_bodies(previous_text, current_text, limit=30):
    """Differences between two response bodies (JSON structurally, otherwise a plain 'changed' notice)."""
    try:
        before, after = json.loads(previous_text), json.loads(current_text)
    except (TypeError, ValueError):
        return [] if previous_text == current_text else ['El cuerpo cambió (no es JSON: no se detalla)']
    return core.json_diff(before, after, limit=limit)


def draft_from_history(entry):
    d = new_draft()
    d.update(copy.deepcopy(entry['draft']))
    d['source'] = {'type': 'history', 'id': entry['id']}
    return d
