import keyring
import keyring.backend
import pytest
from app import core


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
