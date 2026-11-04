"""El adaptador de Azure SQL, con una conexión/cursor falsos (sin red real) — verifica el SQL exacto que arma
para cada operación y el camino de upsert (UPDATE primero, INSERT si no existía la fila)."""
import pytest
from app import azure_sql_backend as backend


class FakeCursor:
    def __init__(self, store):
        self.store = store   # dict compartido: table -> {id: payload}
        self.rowcount = 0
        self.calls = []
        self._result = None

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        normalized = ' '.join(sql.split())
        table_rows = None
        if 'sys.tables' in normalized or normalized.startswith('CREATE TABLE'):
            return
        for table in self.store:
            if f' {table} ' in f' {normalized} ' or normalized.endswith(table):
                table_rows = self.store[table]
                break
        if table_rows is None:
            # a table referenced that isn't seeded yet (e.g. a fresh upsert) — infer it from the SQL text
            import re
            m = re.search(r'(?:FROM|INTO|UPDATE)\s+(\w+)', normalized)
            table_rows = self.store.setdefault(m.group(1), {}) if m else {}
        if normalized.startswith('SELECT payload FROM'):
            identifier = params[0] if params else None
            if identifier is None:   # list_items: no WHERE clause
                self._result = [(v,) for v in table_rows.values()]
            else:
                self._result = (table_rows[identifier],) if identifier in table_rows else None
        elif normalized.startswith('UPDATE'):
            payload, identifier = params
            if identifier in table_rows:
                table_rows[identifier] = payload
                self.rowcount = 1
            else:
                self.rowcount = 0
        elif normalized.startswith('INSERT'):
            identifier, payload = params
            table_rows[identifier] = payload
            self.rowcount = 1
        elif normalized.startswith('DELETE'):
            identifier = params[0]
            table_rows.pop(identifier, None)

    def fetchone(self):
        return self._result if not isinstance(self._result, list) else (self._result[0] if self._result else None)

    def fetchall(self):
        return self._result if isinstance(self._result, list) else []


class FakeConnection:
    def __init__(self, store):
        self.store = store
        self.autocommit = True
        self.closed = False
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return FakeCursor(self.store)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def reset_backend():
    backend.close()
    yield
    backend.close()


@pytest.fixture
def store(monkeypatch):
    shared = {}
    monkeypatch.setattr(backend, '_connect', lambda: FakeConnection(shared))
    return shared


def test_enabled_reads_ltw_backend_env_var(monkeypatch):
    monkeypatch.delenv('LTW_BACKEND', raising=False)
    assert backend.enabled() is False
    monkeypatch.setenv('LTW_BACKEND', 'azure_sql')
    assert backend.enabled() is True
    monkeypatch.setenv('LTW_BACKEND', 'sqlite')
    assert backend.enabled() is False


def test_config_requires_every_variable(monkeypatch):
    for name in ('LTW_AZURE_SQL_SERVER', 'LTW_AZURE_SQL_DATABASE', 'LTW_AZURE_SQL_USER', 'LTW_AZURE_SQL_PASSWORD'):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(backend.AzureSqlConfigError, match='LTW_AZURE_SQL_SERVER'):
        backend._config()
    monkeypatch.setenv('LTW_AZURE_SQL_SERVER', 'test-ws.database.windows.net')
    monkeypatch.setenv('LTW_AZURE_SQL_DATABASE', 'ltw')
    monkeypatch.setenv('LTW_AZURE_SQL_USER', 'devsquad')
    monkeypatch.setenv('LTW_AZURE_SQL_PASSWORD', 'x')
    cfg = backend._config()
    assert cfg == {'server': 'test-ws.database.windows.net', 'database': 'ltw', 'user': 'devsquad', 'password': 'x', 'port': 1433}


def test_check_table_rejects_anything_not_a_plain_identifier():
    backend._check_table('cases')   # does not raise
    for bad in ('cases; DROP TABLE users', 'cases--', '1cases', ''):
        with pytest.raises(ValueError):
            backend._check_table(bad)


def test_save_then_get_then_list_then_delete_roundtrip(store):
    backend.save('cases', 'c1', '{"name": "a"}')
    assert backend.get('cases', 'c1') == '{"name": "a"}'
    backend.save('cases', 'c2', '{"name": "b"}')
    assert sorted(backend.list_items('cases')) == ['{"name": "a"}', '{"name": "b"}']
    backend.delete('cases', 'c1')
    assert backend.get('cases', 'c1') is None
    assert backend.list_items('cases') == ['{"name": "b"}']


def test_save_updates_in_place_when_the_row_already_exists(store):
    backend.save('cases', 'c1', '{"v": 1}')
    backend.save('cases', 'c1', '{"v": 2}')   # mismo id: UPDATE, no un segundo INSERT
    assert backend.list_items('cases') == ['{"v": 2}']


def test_initialize_creates_every_table_without_raising(store):
    backend.initialize(('projects', 'cases', 'suites'))   # no debe lanzar (CREATE TABLE IF NOT EXISTS vía sys.tables)


def test_connection_is_cached_and_reused_across_calls(store, monkeypatch):
    connects = []
    real_connect = backend._connect

    def counting_connect():
        connects.append(1)
        return real_connect()
    monkeypatch.setattr(backend, '_connect', counting_connect)
    backend.save('cases', 'c1', '{}')
    backend.get('cases', 'c1')
    backend.list_items('cases')
    assert len(connects) == 1   # una sola conexión para las tres operaciones


def test_transaction_cursor_translates_qmark_placeholders_and_upserts(store):
    con = FakeConnection(store)
    cursor = backend.TransactionCursor(con)
    cursor.upsert('cases', 'c1', '{"v": 1}')
    assert store['cases']['c1'] == '{"v": 1}'
    cursor.execute('DELETE FROM cases WHERE id=?', ('c1',))
    assert 'c1' not in store.get('cases', {})


def test_describe_error_unwraps_a_bare_timeouterror_to_find_the_real_cause():
    """pytds hace `raise TimeoutError() from ex` sin texto propio — describe_error debe bajar por __cause__
    hasta encontrar el mensaje real, en vez de mostrar un TimeoutError vacío."""
    real = ValueError('Deny Public Network Access is set to Yes')
    wrapped = TimeoutError()
    wrapped.__cause__ = real
    assert backend.describe_error(wrapped) == 'ValueError: Deny Public Network Access is set to Yes'


def test_describe_error_uses_the_outer_exception_when_it_already_has_a_message():
    assert backend.describe_error(ValueError('credenciales inválidas')) == 'ValueError: credenciales inválidas'


def test_describe_error_falls_back_to_the_type_name_when_nothing_has_a_message():
    assert backend.describe_error(TimeoutError()) == 'TimeoutError'
