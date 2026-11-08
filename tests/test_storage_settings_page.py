"""Configuraciones → Base de datos: establecer/activar/desactivar Azure SQL desde la pantalla, con confirmación
(«Escribe CONFIRMAR»), y el aviso cuando LTW_BACKEND (variable de entorno) manda por encima de todo."""
import pytest
from nicegui.testing import User
from app import azure_sql_backend, storage_config


def _fill_probe_form(user):
    user.find(marker='storage-probe-server').type('srv.database.windows.net')
    user.find(marker='storage-probe-database').type('lwt')
    user.find(marker='storage-probe-user').type('devsquad')
    user.find(marker='storage-probe-password').type('x')


async def test_establish_without_activating_keeps_sqlite_as_the_active_backend(user: User, monkeypatch):
    monkeypatch.setattr(azure_sql_backend, 'test_connection', lambda config=None: None)
    await user.open('/storage')
    await user.should_see('SQLite (local)')
    _fill_probe_form(user)
    user.find(marker='storage-establish').click()
    await user.should_see('Escribe CONFIRMAR')
    user.find(marker='confirm-phrase-input').type('CONFIRMAR')
    user.find(marker='confirm-phrase-accept').click()
    await user.should_see('Guardado (SQLite sigue activo)')
    cfg = storage_config.load()
    assert cfg['backend'] == 'sqlite' and cfg['server'] == 'srv.database.windows.net'


async def test_establish_and_activate_switches_the_saved_active_backend(user: User, monkeypatch):
    monkeypatch.setattr(azure_sql_backend, 'test_connection', lambda config=None: None)
    await user.open('/storage')
    _fill_probe_form(user)
    user.find(marker='storage-establish-activate').click()
    await user.should_see('Escribe CONFIRMAR')
    user.find(marker='confirm-phrase-input').type('CONFIRMAR')
    user.find(marker='confirm-phrase-accept').click()
    await user.should_see('Guardado y activado')
    assert storage_config.load()['backend'] == 'azure_sql'


async def test_establish_does_not_save_anything_when_the_connection_test_fails(user: User, monkeypatch):
    def fail(config=None):
        raise ConnectionError('no se pudo')
    monkeypatch.setattr(azure_sql_backend, 'test_connection', fail)
    await user.open('/storage')
    _fill_probe_form(user)
    user.find(marker='storage-establish-activate').click()
    user.find(marker='confirm-phrase-input').type('CONFIRMAR')
    user.find(marker='confirm-phrase-accept').click()
    await user.should_see('no se pudo')
    assert storage_config.load() == {'backend': 'sqlite'}   # la conexión falló: no se guardó nada


async def test_wrong_confirmation_phrase_does_not_establish_anything(user: User, monkeypatch):
    monkeypatch.setattr(azure_sql_backend, 'test_connection', lambda config=None: None)
    await user.open('/storage')
    _fill_probe_form(user)
    user.find(marker='storage-establish').click()
    user.find(marker='confirm-phrase-input').type('no')
    user.find(marker='confirm-phrase-accept').click()
    await user.should_see('Escribe exactamente CONFIRMAR')
    assert storage_config.load() == {'backend': 'sqlite'}


@pytest.mark.no_auto_login   # activar Azure SQL debe pasar *antes* de crear/loguear la cuenta (si no, queda en SQLite)
async def test_deactivate_button_returns_to_sqlite_with_confirmation(user: User, fake_azure_sql):
    from nicegui import app as nicegui_app
    from app import core
    storage_config.set_azure_sql('srv.database.windows.net', 'lwt', 'devsquad', 'x', activate=True)
    test_account = core.create_user('Test', 'User', 'test@ltw.local', 'password', password='test-password-123')
    await user.open('/login')
    with user:
        nicegui_app.storage.user['user_id'] = test_account['id']
    await user.open('/storage')
    await user.should_see('Azure SQL')
    user.find(marker='storage-deactivate').click()
    user.find(marker='confirm-phrase-input').type('CONFIRMAR')
    user.find(marker='confirm-phrase-accept').click()
    await user.should_see('Cerrá la ventana')
    assert storage_config.load()['backend'] == 'sqlite'
    assert storage_config.load()['server'] == 'srv.database.windows.net'   # dual: los datos de conexión sobreviven


async def test_evidence_folder_can_be_configured_once_and_is_restored_on_reopen(user: User, tmp_path):
    from app import core
    await user.open('/storage')
    folder = tmp_path / 'evidencia'
    folder.mkdir()
    user.find(marker='evidence-folder-path').type(str(folder))
    user.find(marker='evidence-folder-save').click()
    await user.should_see('Carpeta de evidencia guardada')
    assert core.evidence_folder() == str(folder)
    await user.open('/storage')
    await user.should_see(f'Carpeta actual: {folder}')


async def test_evidence_folder_rejects_a_path_that_is_not_an_existing_writable_folder(user: User):
    await user.open('/storage')
    user.find(marker='evidence-folder-path').type('esto-no-existe')
    user.find(marker='evidence-folder-save').click()
    await user.should_see('no es una carpeta existente')


@pytest.mark.no_auto_login   # las variables de entorno deben estar puestas *antes* de crear/loguear la cuenta
async def test_env_var_driven_backend_shows_a_note_and_hides_the_deactivate_button(user: User, monkeypatch, fake_azure_sql):
    from nicegui import app as nicegui_app
    from app import core
    monkeypatch.setenv('LTW_BACKEND', 'azure_sql')
    monkeypatch.setenv('LTW_AZURE_SQL_SERVER', 'srv.database.windows.net')
    monkeypatch.setenv('LTW_AZURE_SQL_DATABASE', 'lwt')
    monkeypatch.setenv('LTW_AZURE_SQL_USER', 'devsquad')
    monkeypatch.setenv('LTW_AZURE_SQL_PASSWORD', 'x')
    test_account = core.create_user('Test', 'User', 'test@ltw.local', 'password', password='test-password-123')
    await user.open('/login')
    with user:
        nicegui_app.storage.user['user_id'] = test_account['id']
    await user.open('/storage')
    await user.should_see('Fijado por la variable de entorno LTW_BACKEND')
    with pytest.raises(AssertionError):
        user.find(marker='storage-deactivate')


