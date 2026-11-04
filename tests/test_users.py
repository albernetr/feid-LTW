"""Cuentas de usuario: hashing de contraseña, alta por contraseña/Windows, y created_by en Flujos/Suites."""
import pytest
from app import core


def test_hash_password_roundtrip_and_rejects_wrong_password():
    stored = core.hash_password('correcta123')
    assert core.verify_password('correcta123', stored) is True
    assert core.verify_password('incorrecta', stored) is False
    assert core.verify_password('', stored) is False


def test_create_user_by_password_requires_name_email_and_a_real_password():
    with pytest.raises(ValueError, match='obligatorios'):
        core.create_user('', 'Apellido', 'a@b.com', 'password', password='algomuylargo')
    with pytest.raises(ValueError, match='Correo inválido'):
        core.create_user('Ana', 'Pérez', 'no-es-un-correo', 'password', password='algomuylargo')
    with pytest.raises(ValueError, match='contraseña'):
        core.create_user('Ana', 'Pérez', 'ana@acme.com', 'password', password='corta')
    user = core.create_user('Ana', 'Pérez', 'ana@acme.com', 'password', password='algomuylargo')
    assert user['first_name'] == 'Ana' and user['auth_method'] == 'password'
    assert 'password_hash' in user and user['password_hash'] != 'algomuylargo'


def test_create_user_rejects_a_duplicate_email():
    core.create_user('Ana', 'Pérez', 'ana@acme.com', 'password', password='algomuylargo')
    with pytest.raises(ValueError, match='Ya existe una cuenta'):
        core.create_user('Otra', 'Persona', 'ana@acme.com', 'password', password='algomuylargo')


def test_create_user_by_windows_requires_a_username_and_rejects_duplicates():
    with pytest.raises(ValueError, match='usuario de Windows'):
        core.create_user('Ana', 'Pérez', 'ana@acme.com', 'windows')
    user = core.create_user('Ana', 'Pérez', 'ana@acme.com', 'windows', windows_username='aperez')
    assert user['auth_method'] == 'windows' and 'password_hash' not in user
    with pytest.raises(ValueError, match='Ya existe una cuenta'):
        core.create_user('Otra', 'Persona', 'otra@acme.com', 'windows', windows_username='aperez')


def test_authenticate_password_happy_and_sad_paths():
    core.create_user('Ana', 'Pérez', 'ana@acme.com', 'password', password='algomuylargo')
    assert core.authenticate_password('ana@acme.com', 'algomuylargo')['email'] == 'ana@acme.com'
    assert core.authenticate_password('ana@acme.com', 'mal') is None
    assert core.authenticate_password('nadie@acme.com', 'algomuylargo') is None
    # un usuario de Windows no puede entrar por este camino, aunque alguien "adivine" algo
    core.create_user('Beto', 'Gómez', 'beto@acme.com', 'windows', windows_username='bgomez')
    assert core.authenticate_password('beto@acme.com', '') is None


def test_get_user_by_email_and_windows_username_are_case_insensitive():
    user = core.create_user('Ana', 'Pérez', 'Ana@Acme.com', 'password', password='algomuylargo')
    assert core.get_user_by_email('ANA@ACME.COM')['id'] == user['id']
    win = core.create_user('Beto', 'Gómez', 'beto@acme.com', 'windows', windows_username='BGomez')
    assert core.get_user_by_windows_username('bgomez')['id'] == win['id']


def test_delete_user_refuses_to_remove_the_last_account():
    only = core.create_user('Ana', 'Pérez', 'ana@acme.com', 'password', password='algomuylargo')
    with pytest.raises(ValueError, match='último usuario'):
        core.delete_user(only['id'])
    core.create_user('Beto', 'Gómez', 'beto@acme.com', 'password', password='algomuylargo')
    core.delete_user(only['id'])   # now there's a second account, so this one can go
    assert core.get('users', only['id']) is None


def test_user_display_name_resolves_sentinels_real_users_and_deleted_users():
    assert core.user_display_name(None) == '—'
    assert core.user_display_name('scheduler') == 'Programación automática'
    assert core.user_display_name('agent') == 'Agente (CLI / API)'
    user = core.create_user('Ana', 'Pérez', 'ana@acme.com', 'password', password='algomuylargo')
    assert core.user_display_name(user['id']) == 'Ana Pérez'
    assert core.user_display_name('no-existe') == '(usuario eliminado)'


def test_save_suite_and_save_suite_group_stamp_created_by_on_create_and_preserve_it_on_edit():
    project = core.create_project('P')
    env = core.save('environments', {'name': 'e', 'project_id': project['id'], 'base_url': 'http://x', 'auth': {'type': 'none'}})
    case = core.save('cases', {'name': 'c', 'type': 'api', 'project_id': project['id'], 'method': 'GET', 'path': '/h', 'assertions': []})
    creator = core.create_user('Ana', 'Pérez', 'ana@acme.com', 'password', password='algomuylargo')
    editor = core.create_user('Beto', 'Gómez', 'beto@acme.com', 'password', password='algomuylargo')

    suite = core.save_suite('s', env['id'], [case['id']], project['id'], created_by=creator['id'])
    assert suite['created_by'] == creator['id']
    edited = core.save_suite('s renombrada', env['id'], [case['id']], project['id'], id=suite['id'], created_by=creator['id'])
    assert edited['created_by'] == creator['id']   # el editor (Beto) nunca se pasa: la página lo filtra antes

    group = core.save_suite_group('g', project['id'], [{'type': 'case', 'id': case['id']}], environment_id=env['id'], created_by=creator['id'])
    assert group['created_by'] == creator['id']
    edited_group = core.save_suite_group('g renombrada', project['id'], [{'type': 'case', 'id': case['id']}],
                                         environment_id=env['id'], id=group['id'], created_by=creator['id'])
    assert edited_group['created_by'] == creator['id']
