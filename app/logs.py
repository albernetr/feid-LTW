"""Structured JSON-lines logging and a diagnostic bundle that never contains secrets."""
import json
import logging
import logging.handlers
import platform
import re
import sys
import zipfile
from pathlib import Path
from . import core

_SENSITIVE_KEY = re.compile(r'token|password|passwd|secret|authorization|cookie|api[_-]?key', re.I)
_BEARER = re.compile(r'(Bearer\s+)[A-Za-z0-9._~+/=-]+', re.I)
_handlers = {}


def log_dir():
    path = core.ROOT / 'logs'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _clean(value):
    if isinstance(value, dict):
        return {k: ('[REDACTED]' if _SENSITIVE_KEY.search(str(k)) else _clean(v)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, str):
        return _BEARER.sub(r'\1[REDACTED]', value)[:2000]
    return value


def _logger():
    directory = log_dir()
    logger = logging.getLogger('local_test_workspace')
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if _handlers.get('dir') != str(directory):
        for handler in list(logger.handlers):
            handler.close(); logger.removeHandler(handler)
        handler = logging.handlers.RotatingFileHandler(directory / 'workspace.log', maxBytes=1_000_000, backupCount=3, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(handler)
        _handlers['dir'] = str(directory)
    return logger


def event(name, **fields):
    """Writes one JSON line; sensitive keys and bearer tokens are redacted."""
    try:
        record = {'ts': core.now(), 'event': name, **_clean(fields)}
        _logger().info(json.dumps(record, ensure_ascii=False, default=str))
    except Exception:
        pass  # logging must never break a test run


def diagnostic_package(destination):
    """ZIP with versions, record counts, sanitized environments and recent logs."""
    destination = Path(destination)
    info = {
        'created_at': core.now(), 'python': sys.version, 'platform': platform.platform(),
        'counts': {t: len(core.list_items(t)) for t in core.ALL_TABLES if t != 'settings'},
        'workspace_home': str(core.ROOT),
    }
    from importlib import metadata
    for package in ('nicegui', 'httpx', 'playwright', 'jsonschema', 'PyYAML', 'keyring'):
        try:
            info.setdefault('versions', {})[package] = metadata.version(package)
        except Exception:
            info.setdefault('versions', {})[package] = 'n/d'
    environments = [{'id': e['id'], 'name': e.get('name'), 'base_url': e.get('base_url'),
                     'auth_type': e.get('auth', {}).get('type')} for e in core.list_items('environments')]
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('info.json', json.dumps(info, indent=2, ensure_ascii=False))
        z.writestr('environments.json', json.dumps(environments, indent=2, ensure_ascii=False))
        for log_file in sorted(log_dir().glob('workspace.log*')):
            lines = log_file.read_text(encoding='utf-8', errors='replace').splitlines()[-2000:]
            z.writestr(f'logs/{log_file.name}', '\n'.join(json.dumps(_clean_line(line), ensure_ascii=False) for line in lines))
    return destination


def _clean_line(line):
    try:
        return _clean(json.loads(line))
    except ValueError:
        return {'raw': _BEARER.sub(r'\1[REDACTED]', line)[:500]}
