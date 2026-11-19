"""Qué adaptador de memoria del Asistente está activo (archivos JSON o SQLite propio), persistido en un
archivo dentro de `core.ROOT` — mismo molde que `storage_config.py` para el backend de datos, pero
independiente de él: la memoria del Asistente puede vivir en JSON mientras los datos del workspace viven en
Azure SQL, o viceversa."""
import json
import os
from . import core

BACKENDS = ('json', 'sqlite')


def _config_path():
    return core.ROOT / 'assistant_memory_config.json'


def load():
    """{'backend': 'json'|'sqlite'} — 'json' si nunca se guardó nada."""
    path = _config_path()
    if not path.is_file():
        return {'backend': 'json'}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return {'backend': 'json'}
    if not isinstance(data, dict) or data.get('backend') not in BACKENDS:
        return {'backend': 'json'}
    return data


def save(config):
    if config.get('backend') not in BACKENDS:
        raise ValueError('Backend de memoria del Asistente inválido')
    core.ROOT.mkdir(parents=True, exist_ok=True)
    _config_path().write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')


def active_backend():
    """'json' o 'sqlite' — LTW_ASSISTANT_MEMORY_BACKEND (variable de entorno) gana siempre si está puesta; si
    no, lo decide la configuración guardada. Igual que storage_config.active_backend(), no hay cambio en
    caliente: un proceso ya arrancado sigue usando el adaptador que tenía (ver assistant_memory.get_adapter)."""
    env = os.environ.get('LTW_ASSISTANT_MEMORY_BACKEND', '').strip().lower()
    if env in BACKENDS:
        return env
    return load().get('backend', 'json')


def set_active(backend):
    if backend not in BACKENDS:
        raise ValueError('Backend de memoria del Asistente inválido')
    save({'backend': backend})
