"""Configuraciones → Base de datos: qué backend de almacenamiento está activo ahora mismo (SQLite local o
Azure SQL), establecer una conexión de Azure SQL como activa (o volver a SQLite) con confirmación, y probar
credenciales antes de comprometerse a nada. «Dual»: los datos de conexión de Azure SQL quedan guardados aunque
SQLite esté activo, listos para reactivar sin volver a escribirlos. El cambio se guarda y pide reiniciar la
aplicación — nunca se aplica en caliente (ver manual, capítulo 15.4)."""
import os
from nicegui import run, ui
from .. import azure_sql_backend, core, storage_config, storage_sync
from .common import frame, guard, confirm, confirm_with_phrase, protected_page, team_config_card

SYNC_TABLE_LABELS = {'projects': 'Proyectos', 'module_groups': 'Grupos de módulos', 'modules': 'Componentes',
                     'environments': 'Ambientes', 'cases': 'Casos', 'features': 'Funcionalidades', 'suites': 'Flujos',
                     'schedules': 'Programaciones', 'datasets': 'Conjuntos de datos', 'suite_groups': 'Suites',
                     'integrations': 'Integraciones', 'runs': 'Historial'}
SYNC_DIRECTIONS = {'sqlite_to_azure': 'SQLite → Azure SQL', 'azure_to_sqlite': 'Azure SQL → SQLite'}

ACTIVATE_PHRASE = 'CONFIRMAR'


@protected_page('/storage')
def storage_settings():
    with frame('Base de datos', '/storage'):
        env_driven = bool(os.environ.get('LTW_BACKEND', '').strip())
        active = storage_config.active_backend()

        with ui.card().classes('w-full'):
            ui.label('Backend activo').classes('text-lg font-semibold')
            if active == 'azure_sql':
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
                with ui.row().classes('gap-2'):
                    ui.button('Probar conexión activa', icon='bolt', on_click=guard(test_active)).props('outline').mark('storage-test-active')
                    if not env_driven:
                        def do_deactivate():
                            storage_config.set_active('sqlite')
                            ui.notify('Guardado. Cerrá la ventana y volvé a ejecutar scripts\\run.bat (o python run.py) para que tome efecto.',
                                     type='positive', multi_line=True)
                        ui.button('Volver a SQLite', icon='undo', on_click=lambda: confirm_with_phrase(
                            'Esto cambia el backend activo a SQLite (hace falta reiniciar para que tome efecto).',
                            ACTIVATE_PHRASE, do_deactivate, 'Guardar y pedir reinicio')).props('outline color=warning').mark('storage-deactivate')
            else:
                ui.label('SQLite (local) — el archivo vive en la carpeta de datos de la aplicación.').classes('text-sm text-gray-600')
            if env_driven:
                ui.label('Fijado por la variable de entorno LTW_BACKEND: para cambiarlo, cambiá esa variable y reiniciá — '
                          'esta pantalla no puede anularla.').classes('text-xs text-amber-700')
            else:
                ui.label('Se guarda en un archivo local (fuera de git) y pide reiniciar la aplicación para aplicarse; '
                          'nunca cambia el backend en caliente.').classes('text-xs text-gray-500')

        with ui.card().classes('w-full'):
            ui.label('Probar y establecer una conexión de Azure SQL').classes('text-lg font-semibold')
            ui.label('Probá que el servidor, la base, el usuario y la contraseña funcionan antes de comprometerte a nada; '
                      '«Establecer» la guarda (la contraseña va al llavero del sistema) y la deja lista para activarla.').classes('text-sm text-gray-500')
            server = ui.input('Servidor', placeholder='tu-servidor.database.windows.net').props('outlined dense').classes('w-full').mark('storage-probe-server')
            database = ui.input('Base de datos').props('outlined dense').classes('w-full').mark('storage-probe-database')
            with ui.row().classes('w-full gap-3'):
                user = ui.input('Usuario').props('outlined dense').classes('grow').mark('storage-probe-user')
                port = ui.number('Puerto', value=1433, min=1, max=65535).props('outlined dense').classes('w-32').mark('storage-probe-port')
            password = ui.input('Contraseña', password=True, password_toggle_button=True).props('outlined dense').classes('w-full').mark('storage-probe-password')

            def read_form():
                missing = [label for label, value in (('Servidor', server.value), ('Base de datos', database.value),
                                                       ('Usuario', user.value), ('Contraseña', password.value)) if not (value or '').strip()]
                if missing:
                    raise ValueError('Completa: ' + ', '.join(missing))
                return {'server': server.value.strip(), 'database': database.value.strip(), 'user': user.value.strip(),
                       'password': password.value, 'port': int(port.value or 1433)}

            async def probe():
                config = read_form()
                try:
                    await run.io_bound(azure_sql_backend.test_connection, config)
                    ui.notify('Conexión correcta', type='positive')
                except Exception as exc:
                    ui.notify(azure_sql_backend.describe_error(exc), type='negative', multi_line=True)

            async def establish(activate):
                config = read_form()
                try:
                    await run.io_bound(azure_sql_backend.test_connection, config)   # no guarda nada si la conexión falla
                except Exception as exc:
                    raise ValueError(azure_sql_backend.describe_error(exc)) from exc
                storage_config.set_azure_sql(config['server'], config['database'], config['user'], config['password'],
                                             port=config['port'], activate=activate)
                msg = ('Guardado y activado. ' if activate else 'Guardado (SQLite sigue activo). ') + \
                      'Cerrá la ventana y volvé a ejecutar scripts\\run.bat (o python run.py) para que tome efecto.'
                ui.notify(msg, type='positive', multi_line=True)

            def open_establish_dialog(activate):
                confirm_with_phrase(
                    'Esto guarda esta conexión de Azure SQL' + (' y la activa (hace falta reiniciar para que tome efecto).' if activate else ' (no la activa: SQLite sigue en uso hasta que la actives).'),
                    ACTIVATE_PHRASE, lambda: establish(activate), 'Guardar')

            with ui.row().classes('gap-2'):
                ui.button('Probar conexión', icon='bolt', on_click=guard(probe)).props('color=primary').mark('storage-probe-submit')
                ui.button('Establecer (sin activar)', icon='save', on_click=lambda: open_establish_dialog(False)).props('outline').mark('storage-establish')
                ui.button('Establecer y activar', icon='power_settings_new', on_click=lambda: open_establish_dialog(True)).props('outline color=positive').mark('storage-establish-activate')

        with ui.card().classes('w-full'):
            ui.label('Sincronizar bases de datos').classes('text-lg font-semibold')
            ui.label('Copia datos de un backend al otro, a demanda — no cambia cuál backend está activo ni reemplaza «Establecer/Activar» de arriba. '
                      '«Fusionar» nunca sobrescribe lo que ya existe en el destino, solo agrega lo que falta; «Reemplazar» sí sobrescribe las coincidencias.').classes('text-sm text-gray-500')
            if storage_config.azure_sql_connection_config() is None:
                ui.label('Todavía no hay una conexión de Azure SQL guardada — establecela arriba primero.').classes('text-sm text-amber-700')
            else:
                with ui.row().classes('w-full gap-3 items-end flex-wrap'):
                    direction = ui.select(SYNC_DIRECTIONS, value='sqlite_to_azure', label='Sentido').props('outlined dense').classes('w-64').mark('storage-sync-direction')
                    strategy = ui.select({'merge': 'Fusionar (omite lo que ya existe)', 'replace': 'Reemplazar coincidencias'},
                                         value='merge', label='Estrategia').props('outlined dense').classes('w-72').mark('storage-sync-strategy')
                include_runs = ui.checkbox('Incluir historial (ejecuciones)').mark('storage-sync-include-runs')
                preview_box = ui.column().classes('w-full gap-1')

                async def do_preview():
                    preview_box.clear()
                    summary = await run.io_bound(storage_sync.preview_sync, direction.value, strategy.value, include_runs.value)
                    with preview_box:
                        rows = [(table, counts) for table, counts in summary.items() if counts['total']]
                        if not rows:
                            ui.label('No hay nada para sincronizar en ese sentido.').classes('text-gray-500')
                        for table, counts in rows:
                            ui.label(f'{SYNC_TABLE_LABELS.get(table, table)}: {counts["total"]} ({counts["new"]} nuevo(s), {counts["existing"]} coincidente(s))')

                async def do_sync():
                    summary = await run.io_bound(storage_sync.sync, direction.value, strategy.value, include_runs.value)
                    written = sum(summary.values())
                    ui.notify(f'Sincronizado: {written} registro(s) escritos.' if written else 'No había nada para sincronizar.', type='positive')
                    preview_box.clear()

                def open_sync_dialog():
                    label = SYNC_DIRECTIONS[direction.value]
                    if strategy.value == 'replace':
                        confirm_with_phrase(f'Esto puede sobrescribir datos reales en el destino ({label}, reemplazando coincidencias).',
                                            ACTIVATE_PHRASE, do_sync, 'Sincronizar')
                    else:
                        confirm(f'¿Sincronizar {label}? «Fusionar» nunca sobrescribe lo que ya existe en el destino.', do_sync, 'Sincronizar')

                with ui.row().classes('gap-2'):
                    ui.button('Vista previa', icon='visibility', on_click=guard(do_preview)).props('outline').mark('storage-sync-preview')
                    ui.button('Sincronizar', icon='sync', on_click=guard(open_sync_dialog)).props('color=primary').mark('storage-sync-submit')

        with ui.card().classes('w-full'):
            ui.label('Carpeta de evidencia').classes('text-lg font-semibold')
            ui.label('Configurala una sola vez acá; después, «Guardar en mi carpeta» (en el detalle de una corrida o en '
                      '«Evidencia de la conversación» del Chat) la usa a demanda, nunca sola. También la puede usar «Hablale '
                      'al Asistente» cuando le pidas guardar algo ahí.').classes('text-sm text-gray-500')
            current = core.evidence_folder()
            if current:
                ui.label(f'Carpeta actual: {current}').classes('text-sm')
            folder_input = ui.input('Ruta de la carpeta', value=current or '').props('outlined dense').classes('w-full').mark('evidence-folder-path')

            def save_folder():
                saved = core.set_evidence_folder(folder_input.value)
                folder_input.set_value(saved)
                ui.notify('Carpeta de evidencia guardada', type='positive')
            ui.button('Guardar', icon='save', on_click=guard(save_folder)).props('outline').mark('evidence-folder-save')

        team_config_card()
