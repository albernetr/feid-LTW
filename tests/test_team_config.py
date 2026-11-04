"""Exportar/importar en un solo archivo cifrado la configuración de equipo: modelos de IA (con su clave) +
conexión a base de datos (con su contraseña). Cada sección es opcional."""
import pytest
from app import core, llm, storage_config, team_config


def _register_model():
    return llm.save_profile({'name': 'GPT local', 'preset': 'ollama', 'protocol': 'openai',
                             'base_url': 'http://localhost:11434', 'model': 'llama3', 'auth': 'none',
                             'allow_cloud': False, 'timeout': 60}, api_key='sk-local')


def test_export_requires_at_least_one_section():
    with pytest.raises(ValueError, match='Elige al menos una sección'):
        team_config.export_encrypted('frase', include_db=False, include_models=False)


def test_export_db_fails_without_a_saved_azure_sql_configuration():
    with pytest.raises(ValueError, match='Todavía no hay una configuración de Azure SQL'):
        team_config.export_encrypted('frase', include_db=True, include_models=False)


def test_export_models_fails_without_any_registered_model():
    with pytest.raises(ValueError, match='Todavía no hay modelos de IA registrados'):
        team_config.export_encrypted('frase', include_db=False, include_models=True)


def test_export_then_import_roundtrip_with_both_sections():
    storage_config.set_azure_sql('srv.database.windows.net', 'db', 'user', 'secret-pw', port=1433)
    model = _register_model()
    data = team_config.export_encrypted('frase-del-equipo')
    assert b'secret-pw' not in data and b'sk-local' not in data   # ningún secreto en texto plano

    # "otra máquina": limpiar todo e importar
    core.secret_delete(storage_config.AZURE_SQL_SECRET_NAME)
    core.secret_delete(llm.profile_secret_name(model['id']))
    storage_config.save({'backend': 'sqlite'})
    core.delete('llm_profiles', model['id'])

    summary = team_config.import_encrypted(data, 'frase-del-equipo')
    assert summary == {'db': True, 'models_imported': 1, 'models_skipped': []}
    assert storage_config.load()['backend'] == 'sqlite'   # importar no activa nada
    assert core.secret_get(storage_config.AZURE_SQL_SECRET_NAME) == 'secret-pw'
    restored = llm.get_profile(model['id'])
    assert restored['name'] == 'GPT local'
    assert core.secret_get(llm.profile_secret_name(model['id'])) == 'sk-local'


def test_export_only_models_omits_the_db_section():
    model = _register_model()
    data = team_config.export_encrypted('frase', include_db=False, include_models=True)
    core.delete('llm_profiles', model['id'])
    summary = team_config.import_encrypted(data, 'frase')
    assert summary == {'db': False, 'models_imported': 1, 'models_skipped': []}


def test_import_rejects_the_wrong_passphrase():
    _register_model()
    data = team_config.export_encrypted('frase-correcta', include_db=False, include_models=True)
    with pytest.raises(ValueError, match='no coincide'):
        team_config.import_encrypted(data, 'frase-incorrecta')


def test_import_rejects_an_unrecognizable_file():
    with pytest.raises(ValueError, match='JSON inválido'):
        team_config.import_encrypted(b'not json at all', 'cualquiera')
    with pytest.raises(ValueError, match='no es una configuración de equipo'):
        team_config.import_encrypted(b'{"format": "algo-distinto"}', 'cualquiera')


def test_import_skips_a_model_whose_name_collides_with_a_different_local_model():
    model = _register_model()
    data = team_config.export_encrypted('frase', include_db=False, include_models=True)
    core.delete('llm_profiles', model['id'])
    llm.save_profile({'name': 'GPT local', 'preset': 'custom', 'protocol': 'openai', 'base_url': 'http://otro',
                      'model': 'otro-modelo', 'auth': 'none', 'allow_cloud': False, 'timeout': 60})
    summary = team_config.import_encrypted(data, 'frase')
    assert summary['models_imported'] == 0
    assert summary['models_skipped'][0]['name'] == 'GPT local'
