import re
import keyring
import keyring.backend
import pytest
from nicegui import app as nicegui_app
from nicegui.testing import User
from app import core


class FakeAzureCursor:
    """Simula un cursor de pytds contra un dict compartido (table -> {id: payload}) — nunca toca la red.
    Usado tanto por tests/test_azure_sql_backend.py (SQL exacto que arma cada operación) como por cualquier
    pantalla que, en un test, deba creer que Azure SQL está activo (p. ej. storage_settings.py) sin conectarse
    de verdad a nada que se parezca a un dominio real de *.database.windows.net."""

    def __init__(self, store):
        self.store = store
        self.rowcount = 0
        self.calls = []
        self._result = None

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        normalized = ' '.join(sql.split())
        if 'sys.tables' in normalized or normalized.startswith('CREATE TABLE'):
            return
        table_rows = None
        for table in self.store:
            if f' {table} ' in f' {normalized} ' or normalized.endswith(table):
                table_rows = self.store[table]
                break
        if table_rows is None:
            m = re.search(r'(?:FROM|INTO|UPDATE)\s+(\w+)', normalized)
            table_rows = self.store.setdefault(m.group(1), {}) if m else {}
        if normalized.startswith('SELECT payload FROM'):
            identifier = params[0] if params else None
            if identifier is None:
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


class FakeAzureConnection:
    def __init__(self, store):
        self.store = store
        self.autocommit = True
        self.closed = False
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return FakeAzureCursor(self.store)

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


@pytest.fixture
def fake_azure_sql(monkeypatch):
    """Hace que azure_sql_backend hable contra un dict en memoria en vez de la red — para cualquier test que
    necesite que el backend Azure SQL "funcione" (incluida la sola carga de una página protegida, que ya hace
    core.initialize()) sin arriesgarse a tocar un servidor real."""
    from app import azure_sql_backend
    store = {}
    azure_sql_backend.close()   # descarta cualquier conexión (falsa o real) cacheada por un test anterior
    monkeypatch.setattr(azure_sql_backend, '_connect', lambda config=None: FakeAzureConnection(store))
    yield store
    azure_sql_backend.close()


class MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        self.store = {}

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def get_password(self, service, username):
        return self.store.get((service, username))

    def delete_password(self, service, username):
        self.store.pop((service, username), None)


@pytest.fixture(autouse=True)
def isolated_workspace(tmp_path, monkeypatch):
    """Every test gets its own workspace directory and an in-memory credential store."""
    monkeypatch.setattr(core, 'ROOT', tmp_path / 'home')
    monkeypatch.setattr(core, 'DB', tmp_path / 'home' / 'workspace.sqlite3')
    monkeypatch.setattr(core, 'ARTIFACTS', tmp_path / 'home' / 'evidence')
    previous = keyring.get_keyring()
    keyring.set_keyring(MemoryKeyring())
    core.initialize()
    yield
    keyring.set_keyring(previous)


@pytest.fixture
def sample_app():
    from sample_app.server import SampleApp
    with SampleApp() as app:
        yield app


pytest_plugins = ['nicegui.testing.user_plugin']


def pytest_configure(config):
    config.addinivalue_line('markers', 'no_auto_login: skip the automatic test-account login (used by '
                             'tests/test_auth_pages.py, which tests the login flow itself from a logged-out state)')


@pytest.fixture
async def user(user: User, request: pytest.FixtureRequest) -> User:
    """Toda pantalla requiere sesión (common.protected_page) — para que las pruebas existentes (que abren una
    ruta directamente) no tengan que loguearse una por una, este fixture sobreescribe el `user` de NiceGUI
    (mismo nombre: pytest resuelve el parámetro `user` al fixture original del plugin) y loguea una cuenta de
    prueba apenas se abre la primera página. @pytest.mark.no_auto_login lo salta (tests/test_auth_pages.py)."""
    if request.node.get_closest_marker('no_auto_login'):
        return user
    test_account = core.create_user('Test', 'User', 'test@ltw.local', 'password', password='test-password-123')
    await user.open('/login')
    with user:
        nicegui_app.storage.user['user_id'] = test_account['id']
    return user


@pytest.fixture
def second_app():
    """A second, independent module (different host:port) to test flows that cross modules."""
    from sample_app.server import SampleApp
    with SampleApp() as app:
        yield app


@pytest.fixture
def chat_app():
    """A fictitious multi-turn WhatsApp-style bot, for the Workspace Chat tab."""
    from sample_app.chat_server import ChatApp
    with ChatApp() as app:
        yield app
