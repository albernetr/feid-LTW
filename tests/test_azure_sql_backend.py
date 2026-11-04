"""El adaptador de Azure SQL, con una conexión/cursor falsos (sin red real) — verifica el SQL exacto que arma
para cada operación y el camino de upsert (UPDATE primero, INSERT si no existía la fila). FakeAzureConnection/
FakeAzureCursor y el fixture `fake_azure_sql` viven en conftest.py (también los usa storage_sync/
storage_settings)."""
import pytest
from app import azure_sql_backend as backend
from conftest import FakeAzureConnection


@pytest.fixture(autouse=True)
def reset_backend():
    backend.close()
    yield
    backend.close()


@pytest.fixture
def store(fake_azure_sql):
    return fake_azure_sql


def test_enabled_reads_ltw_backend_env_var(monkeypatch):
    monkeypatch.delenv('LTW_BACKEND', raising=False)
    assert backend.enabled() is False
    monkeypatch.setenv('LTW_BACKEND', 'azure_sql')
    assert backend.enabled() is True
    monkeypatch.setenv('LTW_BACKEND', 'sqlite')
    assert backend.enabled() is False


def test_config_falls_back_to_storage_config_when_no_env_vars_are_set(monkeypatch):
    for name in ('LTW_AZURE_SQL_SERVER', 'LTW_AZURE_SQL_DATABASE', 'LTW_AZURE_SQL_USER', 'LTW_AZURE_SQL_PASSWORD'):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(backend.AzureSqlConfigError, match='No hay una configuración'):
        backend._config()


def test_config_requires_every_env_var_once_any_one_of_them_is_set(monkeypatch):
    for name in ('LTW_AZURE_SQL_SERVER', 'LTW_AZURE_SQL_DATABASE', 'LTW_AZURE_SQL_USER', 'LTW_AZURE_SQL_PASSWORD'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('LTW_AZURE_SQL_SERVER', 'test-ws.database.windows.net')   # solo una: las otras 3 siguen faltando
    with pytest.raises(backend.AzureSqlConfigError, match='LTW_AZURE_SQL_DATABASE'):
        backend._config()
    monkeypatch.setenv('LTW_AZURE_SQL_DATABASE', 'ltw')
    monkeypatch.setenv('LTW_AZURE_SQL_USER', 'devsquad')
    monkeypatch.setenv('LTW_AZURE_SQL_PASSWORD', 'x')
    cfg = backend._config()
    assert cfg == {'server': 'test-ws.database.windows.net', 'database': 'ltw', 'user': 'devsquad', 'password': 'x', 'port': 1433}


def test_config_uses_storage_config_when_no_env_vars_are_set_at_all(monkeypatch):
    from app import storage_config
    for name in ('LTW_AZURE_SQL_SERVER', 'LTW_AZURE_SQL_DATABASE', 'LTW_AZURE_SQL_USER', 'LTW_AZURE_SQL_PASSWORD'):
        monkeypatch.delenv(name, raising=False)
    storage_config.set_azure_sql('srv.database.windows.net', 'db', 'user', 'pw', port=1434)
    assert backend._config() == {'server': 'srv.database.windows.net', 'database': 'db', 'user': 'user', 'password': 'pw', 'port': 1434}


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


def test_initialize_only_checks_the_tables_once_per_connection(store, monkeypatch):
    """core.save/get/list_items/delete llaman a core.initialize() en CADA operación — para Azure SQL cada tabla
    es un redondeo de red aparte, así que repetirlo en cada llamada (encontrado probando en vivo: ~35 idas y
    vueltas de red solo para crear una cuenta, que parecía un cuelgue) no puede pasar. Una vez confirmadas las
    tablas para la conexión actual, llamadas posteriores no deben volver a ejecutar el chequeo — ni al llamar a
    initialize() de nuevo, ni al hacer una operación normal (que lo llama por dentro)."""
    from conftest import FakeAzureCursor
    original_execute = FakeAzureCursor.execute
    ddl_calls = []

    def counting_execute(self, sql, params=()):
        if 'sys.tables' in sql:
            ddl_calls.append(sql)
        return original_execute(self, sql, params)
    monkeypatch.setattr(FakeAzureCursor, 'execute', counting_execute)

    tables = ('projects', 'cases', 'suites')
    backend.initialize(tables)
    assert len(ddl_calls) == 3   # una consulta de sys.tables por tabla, la primera vez
    backend.initialize(tables)   # segunda vez: ya confirmado, no debe repetir nada
    backend.save('cases', 'c1', '{}')   # una operación normal (llama a initialize() por dentro) tampoco
    assert len(ddl_calls) == 3   # sigue en 3: nada se repitió


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


def test_concurrent_calls_never_execute_on_the_shared_connection_at_the_same_time(store, monkeypatch):
    """Dos hilos compartiendo la MISMA conexión cacheada (p. ej. «Probar conexión» en segundo plano mientras otra
    pestaña carga una página) no deben ejecutar sobre el socket al mismo tiempo: un TDS compartido usado por dos
    hilos a la vez puede dejar el socket colgado para siempre (encontrado probando en vivo contra un servidor
    real — ver commit). El lock debe cubrir la operación ENTERA, no solo obtener la conexión."""
    import threading
    import time
    busy = {'count': 0}
    violations = []
    from conftest import FakeAzureCursor
    original_execute = FakeAzureCursor.execute

    def slow_execute(self, sql, params=()):
        busy['count'] += 1
        if busy['count'] > 1:
            violations.append(busy['count'])
        time.sleep(0.05)   # da tiempo a que el otro hilo intente entrar si el lock no lo impide
        result = original_execute(self, sql, params)
        busy['count'] -= 1
        return result
    monkeypatch.setattr(FakeAzureCursor, 'execute', slow_execute)

    backend.save('cases', 'seed', '{}')   # asegura que la conexión ya está cacheada antes de la carrera
    errors = []

    def worker(fn):
        try:
            fn()
        except Exception as exc:   # pragma: no cover - solo si algo revienta bajo la carrera
            errors.append(exc)
    threads = [threading.Thread(target=worker, args=(lambda: backend.list_items('cases'),)),
              threading.Thread(target=worker, args=(lambda: backend.save('cases', 'c2', '{}'),))]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5)
    assert not errors, errors
    assert violations == []   # nunca dos hilos ejecutando sobre el mismo socket a la vez


def test_transaction_cursor_translates_qmark_placeholders_and_upserts(store):
    con = FakeAzureConnection(store)
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
