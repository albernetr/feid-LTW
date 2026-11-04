"""Configuración local de almacenamiento (qué backend está activo, datos de conexión de Azure SQL) — archivo en
core.ROOT, contraseña siempre en el llavero (core.secret_set), nunca en el archivo."""
import pytest
from app import core, storage_config


def test_load_defaults_to_sqlite_when_no_file_exists():
    assert storage_config.load() == {'backend': 'sqlite'}


def test_save_rejects_a_password_field():
    with pytest.raises(ValueError, match='contraseña'):
        storage_config.save({'backend': 'sqlite', 'password': 'x'})


def test_save_rejects_an_invalid_backend():
    with pytest.raises(ValueError, match='Backend inválido'):
        storage_config.save({'backend': 'oracle'})


def test_set_azure_sql_saves_connection_data_and_the_password_goes_to_the_keyring():
    storage_config.set_azure_sql('srv.database.windows.net', 'db', 'user', 'secret-pw', port=1433, activate=False)
    cfg = storage_config.load()
    assert cfg['backend'] == 'sqlite'   # activate=False: queda configurado pero SQLite sigue activo (dual)
    assert cfg['server'] == 'srv.database.windows.net' and cfg['database'] == 'db' and cfg['user'] == 'user'
    assert 'password' not in cfg
    assert core.secret_get(storage_config.AZURE_SQL_SECRET_NAME) == 'secret-pw'


def test_set_azure_sql_with_activate_true_makes_it_the_active_backend():
    storage_config.set_azure_sql('srv.database.windows.net', 'db', 'user', 'secret-pw', activate=True)
    assert storage_config.load()['backend'] == 'azure_sql'


def test_set_active_requires_an_existing_azure_sql_configuration():
    with pytest.raises(ValueError, match='Todavía no hay'):
        storage_config.set_active('azure_sql')
    storage_config.set_azure_sql('srv.database.windows.net', 'db', 'user', 'secret-pw')
    storage_config.set_active('azure_sql')
    assert storage_config.load()['backend'] == 'azure_sql'
    storage_config.set_active('sqlite')
    assert storage_config.load()['backend'] == 'sqlite'
    assert storage_config.load()['server'] == 'srv.database.windows.net'   # dual: los datos de conexión sobreviven


def test_active_backend_prefers_the_ltw_backend_env_var_over_the_saved_file(monkeypatch):
    storage_config.set_azure_sql('srv.database.windows.net', 'db', 'user', 'secret-pw', activate=True)
    assert storage_config.active_backend() == 'azure_sql'
    monkeypatch.setenv('LTW_BACKEND', 'sqlite')
    assert storage_config.active_backend() == 'sqlite'   # la variable de entorno gana, aunque el archivo diga azure_sql
    monkeypatch.delenv('LTW_BACKEND')
    assert storage_config.active_backend() == 'azure_sql'   # sin la variable, vuelve a mandar el archivo


def test_azure_sql_connection_config_is_none_until_fully_configured():
    assert storage_config.azure_sql_connection_config() is None
    storage_config.set_azure_sql('srv.database.windows.net', 'db', 'user', 'secret-pw', port=1434)
    cfg = storage_config.azure_sql_connection_config()
    assert cfg == {'server': 'srv.database.windows.net', 'database': 'db', 'user': 'user', 'port': 1434, 'password': 'secret-pw'}


# --------------------------------------------------------------------------- export/import cifrado

def test_export_encrypted_requires_a_saved_azure_sql_configuration():
    with pytest.raises(ValueError, match='Todavía no hay'):
        storage_config.export_encrypted('frase-secreta')


def test_export_then_import_encrypted_roundtrip_with_the_right_passphrase():
    storage_config.set_azure_sql('srv.database.windows.net', 'db', 'user', 'secret-pw', port=1433)
    data = storage_config.export_encrypted('frase-del-equipo')
    assert b'secret-pw' not in data   # la contraseña nunca queda en texto plano en el archivo

    # "otra máquina": limpiar la config local y el llavero, e importar el archivo
    core.secret_delete(storage_config.AZURE_SQL_SECRET_NAME)
    storage_config.save({'backend': 'sqlite'})
    result = storage_config.import_encrypted(data, 'frase-del-equipo')
    assert result == {'server': 'srv.database.windows.net', 'database': 'db', 'user': 'user', 'port': 1433}
    assert storage_config.load()['backend'] == 'sqlite'   # importar no activa nada solo
    assert core.secret_get(storage_config.AZURE_SQL_SECRET_NAME) == 'secret-pw'


def test_import_encrypted_rejects_the_wrong_passphrase():
    storage_config.set_azure_sql('srv.database.windows.net', 'db', 'user', 'secret-pw')
    data = storage_config.export_encrypted('frase-correcta')
    with pytest.raises(ValueError, match='no coincide'):
        storage_config.import_encrypted(data, 'frase-incorrecta')


def test_import_encrypted_rejects_an_unrecognizable_file():
    with pytest.raises(ValueError, match='JSON inválido'):
        storage_config.import_encrypted(b'not json at all', 'cualquiera')
    with pytest.raises(ValueError, match='no es una configuración'):
        storage_config.import_encrypted(b'{"format": "algo-distinto"}', 'cualquiera')
