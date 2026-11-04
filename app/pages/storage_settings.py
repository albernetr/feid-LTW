"""Configuraciones → Base de datos: qué backend de almacenamiento está activo ahora mismo (SQLite local o
Azure SQL) y, si querés probar Azure SQL antes de activarlo de verdad, un formulario para validar
servidor/base/usuario/contraseña. El backend real se elige con la variable de entorno LTW_BACKEND antes de
arrancar la aplicación (ver manual, capítulo 15.4) — esta pantalla no lo cambia en caliente, solo prueba."""
from nicegui import run, ui
from .. import azure_sql_backend
from .common import frame, guard, protected_page


@protected_page('/storage')
def storage_settings():
    with frame('Base de datos', '/storage'):
        with ui.card().classes('w-full'):
            ui.label('Backend activo').classes('text-lg font-semibold')
            if azure_sql_backend.enabled():
                try:
                    cfg = azure_sql_backend._config()
                    ui.label(f'Azure SQL — servidor «{cfg["server"]}», base «{cfg["database"]}», usuario «{cfg["user"]}»').classes('text-sm')
                except azure_sql_backend.AzureSqlConfigError as exc:
                    ui.label(f'Azure SQL, pero falta configuración: {exc}').classes('text-sm text-red-700')

                async def test_active():
                    try:
                        await run.io_bound(azure_sql_backend.test_connection)
                        ui.notify('Conexión correcta', type='positive')
                    except Exception as exc:
                        ui.notify(azure_sql_backend.describe_error(exc), type='negative', multi_line=True)
                ui.button('Probar conexión activa', icon='bolt', on_click=guard(test_active)).props('outline').mark('storage-test-active')
            else:
                ui.label('SQLite (local) — el archivo vive en la carpeta de datos de la aplicación.').classes('text-sm text-gray-600')
            ui.label('El backend se elige con la variable de entorno LTW_BACKEND antes de arrancar la aplicación; '
                      'esta pantalla no lo cambia en caliente.').classes('text-xs text-gray-500')

        with ui.card().classes('w-full'):
            ui.label('Probar credenciales de Azure SQL').classes('text-lg font-semibold')
            ui.label('Antes de activar Azure SQL de verdad, probá que el servidor, la base, el usuario y la contraseña '
                      'funcionan — no guarda nada ni cambia el backend activo.').classes('text-sm text-gray-500')
            server = ui.input('Servidor', placeholder='tu-servidor.database.windows.net').props('outlined dense').classes('w-full').mark('storage-probe-server')
            database = ui.input('Base de datos').props('outlined dense').classes('w-full').mark('storage-probe-database')
            with ui.row().classes('w-full gap-3'):
                user = ui.input('Usuario').props('outlined dense').classes('grow').mark('storage-probe-user')
                port = ui.number('Puerto', value=1433, min=1, max=65535).props('outlined dense').classes('w-32').mark('storage-probe-port')
            password = ui.input('Contraseña', password=True, password_toggle_button=True).props('outlined dense').classes('w-full').mark('storage-probe-password')

            async def probe():
                missing = [label for label, value in (('Servidor', server.value), ('Base de datos', database.value),
                                                       ('Usuario', user.value), ('Contraseña', password.value)) if not (value or '').strip()]
                if missing:
                    raise ValueError('Completa: ' + ', '.join(missing))
                config = {'server': server.value.strip(), 'database': database.value.strip(), 'user': user.value.strip(),
                         'password': password.value, 'port': int(port.value or 1433)}
                try:
                    await run.io_bound(azure_sql_backend.test_connection, config)
                    ui.notify('Conexión correcta', type='positive')
                except Exception as exc:
                    ui.notify(azure_sql_backend.describe_error(exc), type='negative', multi_line=True)
            ui.button('Probar conexión', icon='bolt', on_click=guard(probe)).props('color=primary').mark('storage-probe-submit')

            ui.separator().classes('my-2')
            ui.label('Para activarlo de verdad, definí estas variables de entorno antes de arrancar y reiniciá la aplicación:').classes('text-sm text-gray-600')
            ui.code('set LTW_BACKEND=azure_sql\n'
                   'set LTW_AZURE_SQL_SERVER=tu-servidor.database.windows.net\n'
                   'set LTW_AZURE_SQL_DATABASE=tu_base\n'
                   'set LTW_AZURE_SQL_USER=tu_usuario\n'
                   'set LTW_AZURE_SQL_PASSWORD=tu_contraseña', language='bat').classes('w-full')
