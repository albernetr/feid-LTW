"""Sincronizar datos entre SQLite y Azure SQL a demanda (Fase 3) — azure_sql_backend habla contra un dict en
memoria (fixture compartido fake_azure_sql), nunca contra la red."""
import pytest
from app import core, storage_sync


def _case(name, **extra):
    item = {'name': name, 'type': 'api', 'method': 'GET', 'path': '/health', 'assertions': []}
    item.update(extra)
    return core.save('cases', item)


def test_preview_sync_sqlite_to_azure_counts_new_and_existing_without_writing_anything(fake_azure_sql):
    a = _case('a')
    _case('b')
    storage_sync._azure_upsert('cases', dict(a))   # ya existe del lado de Azure (destino)
    summary = storage_sync.preview_sync('sqlite_to_azure')
    assert summary['cases'] == {'total': 2, 'new': 1, 'existing': 1}
    assert list(fake_azure_sql.get('cases', {})) == [a['id']]   # preview no escribió nada: sigue solo el que ya estaba


def test_sync_merge_only_adds_missing_rows_and_never_overwrites_the_target(fake_azure_sql):
    a = _case('a')
    b = _case('b')
    storage_sync._azure_upsert('cases', {**a, 'name': 'a (versión de Azure)'})   # mismo id, distinto contenido
    counts = storage_sync.sync('sqlite_to_azure', strategy='merge')
    assert counts['cases'] == 1   # solo b, que no existía
    azure_now = storage_sync._azure_items('cases')
    assert azure_now[a['id']]['name'] == 'a (versión de Azure)'   # el destino gana: no se pisó
    assert azure_now[b['id']]['name'] == 'b'


def test_sync_replace_overwrites_existing_rows_with_the_source_version(fake_azure_sql):
    a = _case('a')
    storage_sync._azure_upsert('cases', {**a, 'name': 'a (versión vieja de Azure)'})
    counts = storage_sync.sync('sqlite_to_azure', strategy='replace')
    assert counts['cases'] == 1
    assert storage_sync._azure_items('cases')[a['id']]['name'] == 'a'   # el origen gana


def test_sync_azure_to_sqlite_writes_into_the_local_database(fake_azure_sql):
    storage_sync._azure_upsert('cases', {'id': 'from-azure', 'name': 'solo en Azure', 'type': 'api',
                                         'method': 'GET', 'path': '/x', 'assertions': []})
    counts = storage_sync.sync('azure_to_sqlite', strategy='merge')
    assert counts['cases'] == 1
    assert core.get('cases', 'from-azure')['name'] == 'solo en Azure'


def test_sync_only_touches_portable_tables_unless_include_runs_is_set(fake_azure_sql):
    core.save('runs', {'id': 'r1', 'type': 'api', 'status': 'passed'})
    counts = storage_sync.sync('sqlite_to_azure')
    assert 'runs' not in counts
    counts_with_runs = storage_sync.sync('sqlite_to_azure', include_runs=True)
    assert counts_with_runs.get('runs') == 1


def test_sync_handles_an_empty_table_without_errors(fake_azure_sql):
    summary = storage_sync.preview_sync('sqlite_to_azure')
    assert summary['cases'] == {'total': 0, 'new': 0, 'existing': 0}
    counts = storage_sync.sync('sqlite_to_azure')
    assert counts['cases'] == 0


def test_sync_rejects_an_invalid_direction_or_strategy(fake_azure_sql):
    with pytest.raises(ValueError, match='Dirección inválida'):
        storage_sync.sync('sideways')
    with pytest.raises(ValueError, match='Estrategia inválida'):
        storage_sync.sync('sqlite_to_azure', strategy='overwrite-everything')
