"""Contrato de MemoryAdapter, verificado contra los 3 adaptadores a la vez (InMemoryAdapter de referencia +
los 2 reales en app/assistant_memory.py) — así un cambio de contrato se nota en los tres juntos."""
import pytest
from app import assistant_memory, assistant_memory_config, core
from app.assistant import InMemoryAdapter

ADAPTERS = [InMemoryAdapter, assistant_memory.JsonFileMemoryAdapter, assistant_memory.SqliteMemoryAdapter]


@pytest.fixture(params=ADAPTERS)
def adapter(request, monkeypatch, tmp_path):
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    return request.param()


def test_load_on_unknown_thread_is_empty(adapter):
    assert adapter.load('nope') == []


def test_append_then_load_roundtrips(adapter):
    adapter.append('t1', {'who': 'user', 'text': 'hola'})
    adapter.append('t1', {'who': 'assistant', 'text': 'hola de vuelta'})
    assert adapter.load('t1') == [{'who': 'user', 'text': 'hola'}, {'who': 'assistant', 'text': 'hola de vuelta'}]


def test_save_replaces_the_whole_thread(adapter):
    adapter.append('t1', {'who': 'user', 'text': 'uno'})
    adapter.save('t1', [{'who': 'user', 'text': 'reemplazado'}])
    assert adapter.load('t1') == [{'who': 'user', 'text': 'reemplazado'}]


def test_threads_are_independent(adapter):
    adapter.append('t1', {'who': 'user', 'text': 'a'})
    adapter.append('t2', {'who': 'user', 'text': 'b'})
    assert adapter.load('t1') == [{'who': 'user', 'text': 'a'}]
    assert adapter.load('t2') == [{'who': 'user', 'text': 'b'}]


def test_delete_removes_the_thread(adapter):
    adapter.append('t1', {'who': 'user', 'text': 'a'})
    adapter.delete('t1')
    assert adapter.load('t1') == []


def test_clear_is_an_alias_for_delete(adapter):
    adapter.append('t1', {'who': 'user', 'text': 'a'})
    adapter.clear('t1')
    assert adapter.load('t1') == []


def test_compact_keeps_only_the_last_n_turns(adapter):
    for i in range(5):
        adapter.append('t1', {'who': 'user', 'text': str(i)})
    adapter.compact('t1', keep_last=2)
    assert adapter.load('t1') == [{'who': 'user', 'text': '3'}, {'who': 'user', 'text': '4'}]


def test_compact_is_a_noop_when_under_the_limit(adapter):
    adapter.append('t1', {'who': 'user', 'text': 'a'})
    adapter.compact('t1', keep_last=20)
    assert adapter.load('t1') == [{'who': 'user', 'text': 'a'}]


def test_unknown_thread_is_enabled_by_default_unless_told_otherwise(adapter):
    assert adapter.is_enabled('nope') is True
    assert adapter.is_enabled('nope', default=False) is False


def test_set_enabled_persists_across_loads(adapter):
    adapter.append('t1', {'who': 'user', 'text': 'a'})
    adapter.set_enabled('t1', False)
    assert adapter.is_enabled('t1') is False
    adapter.set_enabled('t1', True)
    assert adapter.is_enabled('t1') is True


def test_list_threads_reports_every_known_thread(adapter):
    adapter.append('t1', {'who': 'user', 'text': 'a'})
    adapter.append('t2', {'who': 'user', 'text': 'b'})
    adapter.append('t2', {'who': 'assistant', 'text': 'c'})
    by_id = {row['id']: row for row in adapter.list_threads()}
    assert by_id['t1']['turn_count'] == 1
    assert by_id['t2']['turn_count'] == 2


def test_clear_all_empties_every_thread(adapter):
    adapter.append('t1', {'who': 'user', 'text': 'a'})
    adapter.append('t2', {'who': 'user', 'text': 'b'})
    adapter.clear_all()
    assert adapter.load('t1') == []
    assert adapter.load('t2') == []
    assert adapter.list_threads() == []


# --------------------------------------------------------------------------- selección de backend/adaptador

def test_active_backend_defaults_to_json(monkeypatch, tmp_path):
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    monkeypatch.delenv('LTW_ASSISTANT_MEMORY_BACKEND', raising=False)
    assert assistant_memory_config.active_backend() == 'json'


def test_active_backend_follows_saved_config(monkeypatch, tmp_path):
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    monkeypatch.delenv('LTW_ASSISTANT_MEMORY_BACKEND', raising=False)
    assistant_memory_config.set_active('sqlite')
    assert assistant_memory_config.active_backend() == 'sqlite'


def test_env_var_wins_over_saved_config(monkeypatch, tmp_path):
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    assistant_memory_config.set_active('sqlite')
    monkeypatch.setenv('LTW_ASSISTANT_MEMORY_BACKEND', 'json')
    assert assistant_memory_config.active_backend() == 'json'


def test_get_adapter_returns_the_matching_class(monkeypatch, tmp_path):
    monkeypatch.setattr(core, 'ROOT', tmp_path)
    assistant_memory._cached.clear()
    monkeypatch.setenv('LTW_ASSISTANT_MEMORY_BACKEND', 'sqlite')
    assert isinstance(assistant_memory.get_adapter(), assistant_memory.SqliteMemoryAdapter)
    monkeypatch.setenv('LTW_ASSISTANT_MEMORY_BACKEND', 'json')
    assistant_memory._cached.clear()
    assert isinstance(assistant_memory.get_adapter(), assistant_memory.JsonFileMemoryAdapter)
