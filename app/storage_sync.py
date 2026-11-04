"""Sincronizar datos entre SQLite y Azure SQL a demanda — a diferencia de «Establecer/Activar» (que decide cuál
backend USA la app), esto copia filas de un backend al otro mientras los dos quedan intactos para su propio uso
(«dual»). No pasa por el despacho de core.py (core.list_items/save/get), que solo habla con el backend
**activo** global (azure_sql_backend.enabled(), que lee storage_config.active_backend()): sincronizar necesita
hablar con los DOS backends a la vez, así que usa funciones siempre-contra-un-backend-específico — igual que ya
hace core.py internamente (core._open() siempre-SQLite) o azure_sql_backend (list_items/save, que ya ignoran el
flag global). Forzar ese flag temporalmente con os.environ para sincronizar rompería cualquier otra
pestaña/sesión que esté corriendo al mismo tiempo.

Mismo límite de «qué es portable» que ya usa export_workspace/import_workspace: core.TABLES, más `runs` si se
pide include_runs. No se tocan settings/users/sequences/llm_profiles/lab_history/interfaces/taps."""
import json
from . import core, azure_sql_backend

DIRECTIONS = ('sqlite_to_azure', 'azure_to_sqlite')
STRATEGIES = ('merge', 'replace')


def _ensure_both_ready():
    """Las tablas tienen que existir en los DOS backends antes de leer/escribir — el que esté inactivo puede no
    haberlas creado nunca. Misma creación de tablas que ya hace core.initialize() para cada backend."""
    core.ROOT.mkdir(parents=True, exist_ok=True)
    with core._open() as con:
        con.execute('PRAGMA journal_mode=' + ('DELETE' if core.on_network_drive(core.DB) else 'WAL'))
        for table in core.ALL_TABLES:
            con.execute(f'CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    azure_sql_backend.initialize(core.ALL_TABLES)


def _sqlite_items(table):
    with core._open() as con:
        return {row[0]: json.loads(row[1]) for row in con.execute(f'SELECT id, payload FROM {table}')}


def _sqlite_upsert(table, item):
    with core._open() as con:
        con.execute(f'INSERT OR REPLACE INTO {table} VALUES (?,?)', (item['id'], json.dumps(item, ensure_ascii=False)))


def _azure_items(table):
    return {item['id']: item for item in (json.loads(payload) for payload in azure_sql_backend.list_items(table))}


def _azure_upsert(table, item):
    azure_sql_backend.save(table, item['id'], json.dumps(item, ensure_ascii=False))


def _tables(include_runs):
    return core.TABLES + (('runs',) if include_runs else ())


def _source_and_target(direction):
    if direction not in DIRECTIONS:
        raise ValueError('Dirección inválida')
    if direction == 'sqlite_to_azure':
        return _sqlite_items, _azure_items, _azure_upsert
    return _azure_items, _sqlite_items, _sqlite_upsert


def preview_sync(direction, strategy='merge', include_runs=False):
    """Mismo tipo de resumen que core.preview_import: {tabla: {total, new, existing}} — total/new/existing son
    del lado del ORIGEN relativos a lo que ya existe en el destino. No escribe nada."""
    if strategy not in STRATEGIES:
        raise ValueError('Estrategia inválida')
    source_items, target_items, _ = _source_and_target(direction)
    _ensure_both_ready()
    summary = {}
    for table in _tables(include_runs):
        source = source_items(table)
        target = target_items(table)
        existing = sum(1 for identifier in source if identifier in target)
        summary[table] = {'total': len(source), 'new': len(source) - existing, 'existing': existing}
    return summary


def sync(direction, strategy='merge', include_runs=False):
    """`merge` omite una fila que ya existe en el destino (gana el destino); `replace` la sobrescribe con la del
    origen. Devuelve {tabla: cantidad escrita}."""
    if strategy not in STRATEGIES:
        raise ValueError('Estrategia inválida')
    source_items, target_items, target_upsert = _source_and_target(direction)
    _ensure_both_ready()
    counts = {}
    for table in _tables(include_runs):
        source = source_items(table)
        target = target_items(table)
        written = 0
        for identifier, item in source.items():
            if strategy == 'merge' and identifier in target:
                continue
            target_upsert(table, item)
            written += 1
        counts[table] = written
    return counts
