"""Login (bootstrap de la primera cuenta, contraseña, usuario de Windows) y el gate protected_page — verificado
contra páginas reales con el cliente de pruebas de NiceGUI."""
import asyncio
import getpass
import pytest
from nicegui.testing import User
from app import core

pytestmark = pytest.mark.no_auto_login   # este archivo prueba el login en sí mismo, desde "nadie logueado"


async def eventually(condition, seconds=8):
    """Polls until condition() is true (navigating/redirecting takes a moment)."""
    for _ in range(int(seconds * 2)):
        await asyncio.sleep(0.1)
        try:
            if condition():
                return
        except Exception:
            pass
    assert condition()


async def test_bootstrap_creates_the_first_account_and_logs_in(user: User):
    assert core.list_items('users') == []
    await user.open('/login')
    await user.should_see('Creá la primera cuenta')
    user.find(marker='login-boot-first').type('Ana')
    user.find(marker='login-boot-last').type('Pérez')
    user.find(marker='login-boot-email').type('ana@acme.com')
    user.find(marker='login-boot-password').type('algomuylargo')
    user.find(marker='login-boot-confirm').type('algomuylargo')
    user.find(marker='login-boot-submit').click()
    await eventually(lambda: user.client.page.path == '/')
    assert len(core.list_items('users')) == 1
    assert core.list_items('users')[0]['email'] == 'ana@acme.com'


async def test_protected_page_redirects_to_login_when_nobody_is_logged_in(user: User):
    core.create_user('Ana', 'Pérez', 'ana@acme.com', 'password', password='algomuylargo')
    await user.open('/users')
    await user.should_see(marker='login-email')   # redirigido al formulario de login, no a la lista de usuarios


async def test_password_login_happy_and_sad_path(user: User):
    core.create_user('Ana', 'Pérez', 'ana@acme.com', 'password', password='algomuylargo')
    await user.open('/login')
    user.find(marker='login-email').type('ana@acme.com')
    user.find(marker='login-password').type('mal')
    user.find(marker='login-submit').click()
    await user.should_see('Correo o contraseña incorrectos', retries=10)   # do_login() ahora corre en un hilo (run.io_bound)
    user.find(marker='login-password').clear().type('algomuylargo')
    user.find(marker='login-submit').click()
    await eventually(lambda: user.client.page.path == '/')


async def test_login_page_redirects_away_once_already_logged_in(user: User):
    core.create_user('Ana', 'Pérez', 'ana@acme.com', 'password', password='algomuylargo')
    await user.open('/login')
    user.find(marker='login-email').type('ana@acme.com')
    user.find(marker='login-password').type('algomuylargo')
    user.find(marker='login-submit').click()
    await eventually(lambda: user.client.page.path == '/')
    await user.open('/login')
    await eventually(lambda: user.client.page.path == '/')   # /login se redirige de vuelta a Inicio


async def test_windows_user_login_creates_the_account_on_first_use(user: User):
    core.create_user('Ana', 'Pérez', 'ana@acme.com', 'password', password='algomuylargo')   # para que /login muestre el formulario normal, no el bootstrap
    win_user = getpass.getuser()
    await user.open('/login')
    user.find(marker='login-tab-windows').click()
    await user.should_see(f'«{win_user}»')
    user.find(marker='login-windows-first').type('Beto')
    user.find(marker='login-windows-last').type('Gómez')
    user.find(marker='login-windows-email').type('beto@acme.com')
    user.find(marker='login-windows-submit').click()
    await eventually(lambda: user.client.page.path == '/')
    assert core.get_user_by_windows_username(win_user) is not None


async def test_windows_user_login_reuses_an_existing_account_without_asking_for_data_again(user: User):
    win_user = getpass.getuser()
    core.create_user('Beto', 'Gómez', 'beto@acme.com', 'windows', windows_username=win_user)
    await user.open('/login')
    user.find(marker='login-tab-windows').click()
    user.find(marker='login-windows-submit').click()   # "Entrar como «x»": no pide nombre/apellidos/correo
    await eventually(lambda: user.client.page.path == '/')
