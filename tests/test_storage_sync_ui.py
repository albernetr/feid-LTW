"""UI de la tarjeta «Sincronizar bases de datos» en /storage (Fase 3)."""
from nicegui.testing import User
from app import core, storage_config, storage_sync


def _seed_case():
    project = core.create_project('P')
    return core.save('cases', {'name': 'Mi caso', 'type': 'api', 'project_id': project['id'], 'method': 'GET',
                               'path': '/health', 'assertions': []})


async def test_sync_card_shows_a_hint_without_an_azure_sql_configuration(user: User):
    await user.open('/storage')
    await user.should_see('Todavía no hay una conexión de Azure SQL guardada')


async def test_preview_shows_counts_without_writing_anything(user: User, fake_azure_sql):
    storage_config.set_azure_sql('srv.database.windows.net', 'db', 'user', 'x', activate=False)
    case = _seed_case()
    await user.open('/storage')
    user.find(marker='storage-sync-preview').click()
    await user.should_see('Casos: 1 (1 nuevo(s), 0 coincidente(s))')
    assert fake_azure_sql.get('cases', {}) == {}   # vista previa: no escribió nada


async def test_sync_merge_requires_simple_confirmation_and_writes_new_rows(user: User, fake_azure_sql):
    storage_config.set_azure_sql('srv.database.windows.net', 'db', 'user', 'x', activate=False)
    _seed_case()
    await user.open('/storage')
    user.find(marker='storage-sync-submit').click()
    await user.should_see('¿Sincronizar')
    user.find(marker='confirm-dialog-accept').click()
    await user.should_see('Sincronizado: 2 registro(s) escritos.', retries=10)   # 1 proyecto + 1 caso (_seed_case crea los dos)
    assert len(fake_azure_sql.get('cases', {})) == 1


async def test_sync_replace_requires_the_confirmation_phrase(user: User, fake_azure_sql):
    storage_config.set_azure_sql('srv.database.windows.net', 'db', 'user', 'x', activate=False)
    _seed_case()
    await user.open('/storage')
    user.find(marker='storage-sync-strategy').click()
    user.find('Reemplazar coincidencias').click()
    user.find(marker='storage-sync-submit').click()
    await user.should_see('Escribe CONFIRMAR')
    user.find(marker='confirm-phrase-input').type('CONFIRMAR')
    user.find(marker='confirm-phrase-accept').click()
    await user.should_see('Sincronizado: 2 registro(s) escritos.', retries=10)   # 1 proyecto + 1 caso


async def test_sync_azure_to_sqlite_direction_writes_into_the_local_database(user: User, fake_azure_sql):
    storage_config.set_azure_sql('srv.database.windows.net', 'db', 'user', 'x', activate=False)
    storage_sync._azure_upsert('cases', {'id': 'from-azure', 'name': 'solo en Azure', 'type': 'api',
                                         'method': 'GET', 'path': '/x', 'assertions': []})
    await user.open('/storage')
    user.find(marker='storage-sync-direction').click()
    user.find('Azure SQL → SQLite').click()
    user.find(marker='storage-sync-submit').click()
    await user.should_see('¿Sincronizar')
    user.find(marker='confirm-dialog-accept').click()
    await user.should_see('Sincronizado: 1 registro(s) escritos.', retries=10)
    assert core.get('cases', 'from-azure')['name'] == 'solo en Azure'
