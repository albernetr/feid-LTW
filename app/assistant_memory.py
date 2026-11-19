"""Adaptadores reales de memoria del Asistente — implementan el contrato `app.assistant.MemoryAdapter`
(portable, sin saber nada de LTW) contra este proyecto: uno guarda un archivo JSON por hilo, el otro una
tabla SQLite propia (`assistant_memory.sqlite3`, deliberadamente separada de `core.DB`, para que limpiar o
mover la memoria del Asistente nunca toque los datos del workspace).

Un turno es `{'who': 'user'|'assistant', 'text': str}`; el registro guardado por hilo es
`{'enabled': bool, 'turns': [...], 'updated_at': str}`."""
import json
import re
import sqlite3
import threading

from . import core
from .assistant import MemoryAdapter
from .assistant_memory_config import active_backend

_SANITIZE_RE = re.compile(r'[^A-Za-z0-9_.:-]+')


def _sanitize(thread_key):
    return _SANITIZE_RE.sub('_', thread_key)


class JsonFileMemoryAdapter(MemoryAdapter):
    """Un archivo por hilo en `core.ROOT/'assistant_memory'/<hilo-saneado>.json`."""

    def __init__(self):
        self._dir = core.ROOT / 'assistant_memory'

    def _path(self, thread_key):
        return self._dir / f'{_sanitize(thread_key)}.json'

    def _read(self, thread_key):
        path = self._path(thread_key)
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (ValueError, OSError):
            return None
        return data if isinstance(data, dict) else None

    def _write(self, thread_key, record):
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path(thread_key).write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')

    def load(self, thread_key):
        record = self._read(thread_key)
        return list(record['turns']) if record else []

    def save(self, thread_key, turns):
        record = self._read(thread_key) or {'enabled': True}
        record['turns'] = list(turns)
        record['updated_at'] = core.now()
        self._write(thread_key, record)

    def delete(self, thread_key):
        path = self._path(thread_key)
        if path.is_file():
            path.unlink()

    def is_enabled(self, thread_key, default=True):
        record = self._read(thread_key)
        return record.get('enabled', default) if record else default

    def set_enabled(self, thread_key, value):
        record = self._read(thread_key) or {'turns': []}
        record['enabled'] = value
        self._write(thread_key, record)

    def list_threads(self):
        if not self._dir.is_dir():
            return []
        rows = []
        for path in self._dir.glob('*.json'):
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
            except (ValueError, OSError):
                continue
            if not isinstance(record, dict):
                continue
            rows.append({'id': path.stem, 'enabled': record.get('enabled', True),
                         'turn_count': len(record.get('turns', [])), 'updated_at': record.get('updated_at')})
        return rows

    def clear_all(self):
        if self._dir.is_dir():
            for path in self._dir.glob('*.json'):
                path.unlink()


class SqliteMemoryAdapter(MemoryAdapter):
    """Tabla propia `threads(id TEXT PRIMARY KEY, payload TEXT NOT NULL)` en un archivo SQLite propio —
    mismo molde `id`/`payload` JSON que `core.py`, pero deliberadamente otra base."""

    def __init__(self):
        self._db = core.ROOT / 'assistant_memory.sqlite3'
        self._lock = threading.Lock()
        self._initialized = False

    def _connect(self):
        if not self._initialized:
            with self._lock:
                if not self._initialized:
                    core.ROOT.mkdir(parents=True, exist_ok=True)
                    with sqlite3.connect(self._db) as con:
                        con.execute('CREATE TABLE IF NOT EXISTS threads (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
                    self._initialized = True
        return sqlite3.connect(self._db, timeout=30)

    def _read(self, thread_key):
        with self._connect() as con:
            row = con.execute('SELECT payload FROM threads WHERE id=?', (thread_key,)).fetchone()
        return json.loads(row[0]) if row else None

    def _write(self, thread_key, record):
        with self._connect() as con:
            con.execute('INSERT OR REPLACE INTO threads VALUES (?,?)', (thread_key, json.dumps(record, ensure_ascii=False)))

    def load(self, thread_key):
        record = self._read(thread_key)
        return list(record['turns']) if record else []

    def save(self, thread_key, turns):
        record = self._read(thread_key) or {'enabled': True}
        record['turns'] = list(turns)
        record['updated_at'] = core.now()
        self._write(thread_key, record)

    def delete(self, thread_key):
        with self._connect() as con:
            con.execute('DELETE FROM threads WHERE id=?', (thread_key,))

    def is_enabled(self, thread_key, default=True):
        record = self._read(thread_key)
        return record.get('enabled', default) if record else default

    def set_enabled(self, thread_key, value):
        record = self._read(thread_key) or {'turns': []}
        record['enabled'] = value
        self._write(thread_key, record)

    def list_threads(self):
        with self._connect() as con:
            rows = con.execute('SELECT id, payload FROM threads').fetchall()
        result = []
        for thread_id, payload in rows:
            record = json.loads(payload)
            result.append({'id': thread_id, 'enabled': record.get('enabled', True),
                           'turn_count': len(record.get('turns', [])), 'updated_at': record.get('updated_at')})
        return result

    def clear_all(self):
        with self._connect() as con:
            con.execute('DELETE FROM threads')


_ADAPTERS_BY_BACKEND = {'json': JsonFileMemoryAdapter, 'sqlite': SqliteMemoryAdapter}
_cached = {}


def get_adapter():
    """El adaptador activo para este proceso — cacheado (una sola instancia por backend), sin cambio en
    caliente: igual que el backend de datos, cambiar de adaptador requiere reiniciar la app."""
    backend = active_backend()
    if backend not in _cached:
        _cached[backend] = _ADAPTERS_BY_BACKEND[backend]()
    return _cached[backend]
