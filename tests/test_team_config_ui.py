"""UI de la tarjeta compartida «Exportar / importar configuración del equipo» (team_config.py), visible tanto
en /storage como en /models."""
from nicegui import ui
from nicegui.elements.upload_files import SmallFileUpload
from nicegui.testing import User
from app import azure_sql_backend, core, llm, storage_config, team_config


def _register_model():
    return llm.save_profile({'name': 'GPT local', 'preset': 'ollama', 'protocol': 'openai',
                             'base_url': 'http://localhost:11434', 'model': 'llama3', 'auth': 'none',
                             'allow_cloud': False, 'timeout': 60}, api_key='sk-local')


async def test_team_config_card_appears_on_storage_and_models_pages(user: User, monkeypatch):
    monkeypatch.setattr(azure_sql_backend, 'test_connection', lambda config=None: None)
    await user.open('/storage')
    await user.should_see('Exportar / importar configuración del equipo')
    await user.open('/models')
    await user.should_see('Exportar / importar configuración del equipo')


async def test_export_button_downloads_and_notifies(user: User):
    storage_config.set_azure_sql('srv.database.windows.net', 'db', 'user', 'secret-pw', port=1433)
    _register_model()
    await user.open('/storage')
    user.find(marker='team-config-export-phrase').type('frase-equipo')
    user.find(marker='team-config-export-submit').click()
    await user.should_see('Archivo descargado')


async def test_export_without_a_phrase_is_rejected(user: User):
    storage_config.set_azure_sql('srv.database.windows.net', 'db', 'user', 'secret-pw', port=1433)
    await user.open('/storage')
    user.find(marker='team-config-export-submit').click()
    await user.should_see('Indica una frase')


async def test_import_through_the_ui_restores_db_and_model(user: User):
    storage_config.set_azure_sql('srv.database.windows.net', 'db', 'user', 'secret-pw', port=1433)
    model = _register_model()
    data = team_config.export_encrypted('frase-equipo')

    # "otra máquina": limpiar todo antes de importar
    core.secret_delete(storage_config.AZURE_SQL_SECRET_NAME)
    core.secret_delete(llm.profile_secret_name(model['id']))
    storage_config.save({'backend': 'sqlite'})
    core.delete('llm_profiles', model['id'])

    await user.open('/models')
    upload = user.find(kind=ui.upload).elements.pop()
    await upload.handle_uploads([SmallFileUpload(name='ltw-config-equipo.json', content_type='application/json', _data=data)])
    await user.should_see('Archivo cargado')
    user.find(marker='team-config-import-phrase').type('frase-equipo')
    user.find(marker='team-config-import-submit').click()
    await user.should_see('Importado')
    assert core.secret_get(storage_config.AZURE_SQL_SECRET_NAME) == 'secret-pw'
    restored = llm.get_profile(model['id'])
    assert restored and restored['name'] == 'GPT local'


async def test_import_with_the_wrong_phrase_shows_an_error_without_crashing(user: User):
    _register_model()
    data = team_config.export_encrypted('frase-correcta', include_db=False, include_models=True)
    await user.open('/models')
    upload = user.find(kind=ui.upload).elements.pop()
    await upload.handle_uploads([SmallFileUpload(name='x.json', content_type='application/json', _data=data)])
    user.find(marker='team-config-import-phrase').type('frase-incorrecta')
    user.find(marker='team-config-import-submit').click()
    await user.should_see('no coincide')
