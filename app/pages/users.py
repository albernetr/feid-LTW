"""Usuarios: lista de cuentas (nombre, correo, método, alta) — la base para que la app sea multiusuario. Sin
roles/permisos: cualquier cuenta logueada tiene el mismo acceso completo que hoy; esto es solo atribución."""
from nicegui import ui
from .. import core
from .common import protected_page, frame, guard, confirm, empty_state, current_user_id

AUTH_METHOD_LABEL = {'password': 'Correo y contraseña', 'windows': 'Usuario de Windows'}


@protected_page('/users')
def users_list():
    with frame('Usuarios', '/users'):
        items = sorted(core.list_items('users'), key=lambda u: (u.get('first_name', ''), u.get('last_name', '')))
        if not items:
            empty_state('No hay usuarios.')
        for item in items:
            with ui.card().classes('w-full'):
                with ui.row().classes('items-center gap-3 w-full no-wrap'):
                    ui.icon('account_circle').classes('text-2xl')
                    with ui.column().classes('gap-0 grow'):
                        name = f'{item.get("first_name", "")} {item.get("last_name", "")}'.strip()
                        ui.label(name + (' (vos)' if item.get('id') == current_user_id() else '')).classes('font-semibold')
                        detail = f'{item.get("email", "")} · {AUTH_METHOD_LABEL.get(item.get("auth_method"), item.get("auth_method"))}'
                        if item.get('auth_method') == 'windows' and item.get('windows_username'):
                            detail += f' («{item["windows_username"]}»)'
                        ui.label(detail).classes('text-sm text-gray-500')

                    def remove(i=item):
                        core.delete_user(i['id'])
                        ui.navigate.reload()
                    ui.button(icon='delete', on_click=lambda _, i=item, r=remove: confirm(f'¿Eliminar la cuenta de «{name}»?', r)) \
                        .props('flat round color=negative').tooltip('Eliminar')
