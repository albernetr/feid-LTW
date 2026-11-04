"""Pantalla de login: por correo/contraseña, o confiando en el usuario de Windows de esta sesión (la app corre
en loopback, en la máquina de quien la usa — sin pedir contraseña de Windows, sin pywin32/AD). Standalone: sin
frame() (menú lateral, selector de proyecto) porque nadie inició sesión todavía."""
import getpass
from nicegui import ui
from .. import core
from .common import guard, login, current_user


def _card():
    with ui.column().classes('w-full min-h-screen items-center justify-center bg-gray-50'):
        card = ui.card().classes('w-[440px] max-w-full gap-3 m-4')
    return card


def _after_login(user):
    login(user)
    ui.navigate.to('/')


def _bootstrap():
    """No existe ningún usuario todavía: crear la primera cuenta."""
    with _card():
        ui.label('Bienvenido a Local Test Workspace').classes('text-xl font-semibold')
        ui.label('Creá la primera cuenta para empezar.').classes('text-gray-600')
        first = ui.input('Nombre').props('outlined dense').classes('w-full').mark('login-boot-first')
        last = ui.input('Apellidos').props('outlined dense').classes('w-full').mark('login-boot-last')
        email = ui.input('Correo').props('outlined dense').classes('w-full').mark('login-boot-email')
        win_user = getpass.getuser()
        method = ui.radio({'password': 'Elegir una contraseña', 'windows': f'Usar mi usuario de Windows («{win_user}»)'}, value='password') \
            .props('inline').mark('login-boot-method')
        with ui.column().classes('w-full gap-2').bind_visibility_from(method, 'value', lambda v: v == 'password'):
            password = ui.input('Contraseña', password=True, password_toggle_button=True).props('outlined dense').classes('w-full').mark('login-boot-password')
            confirm = ui.input('Confirmar contraseña', password=True, password_toggle_button=True).props('outlined dense').classes('w-full').mark('login-boot-confirm')

        def create():
            if method.value == 'password' and password.value != confirm.value:
                raise ValueError('Las contraseñas no coinciden')
            user = core.create_user(first.value, last.value, email.value, method.value,
                                    password=password.value if method.value == 'password' else None,
                                    windows_username=win_user if method.value == 'windows' else None)
            _after_login(user)
        ui.button('Crear cuenta y entrar', icon='person_add', on_click=guard(create)).props('color=primary').mark('login-boot-submit')


def _login_form():
    with _card():
        ui.label('Local Test Workspace').classes('text-xl font-semibold')
        with ui.tabs().classes('w-full') as tabs:
            password_tab = ui.tab('Correo y contraseña').mark('login-tab-password')
            windows_tab = ui.tab('Usuario de Windows').mark('login-tab-windows')
        with ui.tab_panels(tabs, value=password_tab).classes('w-full'):
            with ui.tab_panel(password_tab).classes('gap-2'):
                email = ui.input('Correo').props('outlined dense').classes('w-full').mark('login-email')
                password = ui.input('Contraseña', password=True, password_toggle_button=True).props('outlined dense').classes('w-full').mark('login-password')

                def do_login():
                    user = core.authenticate_password(email.value, password.value)
                    if not user:
                        raise ValueError('Correo o contraseña incorrectos')
                    _after_login(user)
                ui.button('Entrar', icon='login', on_click=guard(do_login)).props('color=primary').mark('login-submit')
            with ui.tab_panel(windows_tab).classes('gap-2'):
                win_user = getpass.getuser()
                ui.label(f'Usuario de Windows detectado: «{win_user}»').classes('text-gray-700')
                existing = core.get_user_by_windows_username(win_user)
                if existing:
                    ui.button(f'Entrar como «{win_user}»', icon='login', on_click=guard(lambda: _after_login(existing))) \
                        .props('color=primary').mark('login-windows-submit')
                else:
                    ui.label('Primera vez con este usuario de Windows: completá tus datos.').classes('text-sm text-gray-600')
                    first = ui.input('Nombre').props('outlined dense').classes('w-full').mark('login-windows-first')
                    last = ui.input('Apellidos').props('outlined dense').classes('w-full').mark('login-windows-last')
                    win_email = ui.input('Correo').props('outlined dense').classes('w-full').mark('login-windows-email')

                    def create_and_login():
                        user = core.create_user(first.value, last.value, win_email.value, 'windows', windows_username=win_user)
                        _after_login(user)
                    ui.button('Crear cuenta y entrar', icon='person_add', on_click=guard(create_and_login)).props('color=primary').mark('login-windows-submit')
        with ui.expansion('Crear cuenta nueva', icon='person_add').classes('w-full').mark('login-register-expansion'):
            reg_first = ui.input('Nombre').props('outlined dense').classes('w-full').mark('login-register-first')
            reg_last = ui.input('Apellidos').props('outlined dense').classes('w-full').mark('login-register-last')
            reg_email = ui.input('Correo').props('outlined dense').classes('w-full').mark('login-register-email')
            reg_password = ui.input('Contraseña', password=True, password_toggle_button=True).props('outlined dense').classes('w-full').mark('login-register-password')
            reg_confirm = ui.input('Confirmar contraseña', password=True, password_toggle_button=True).props('outlined dense').classes('w-full').mark('login-register-confirm')

            def register():
                if reg_password.value != reg_confirm.value:
                    raise ValueError('Las contraseñas no coinciden')
                user = core.create_user(reg_first.value, reg_last.value, reg_email.value, 'password', password=reg_password.value)
                _after_login(user)
            ui.button('Crear cuenta', icon='person_add', on_click=guard(register)).props('outline').mark('login-register-submit')


@ui.page('/login')
def login_page():
    ui.page_title('Entrar · Local Test Workspace')
    if current_user():
        ui.navigate.to('/')
        return
    if not core.list_items('users'):
        _bootstrap()
    else:
        _login_form()
