import tempfile
import time
from pathlib import Path
from nicegui import ui
from .. import core, logs
from .common import frame, guard, read_upload, protected_page

MAX_ZIP = 50_000_000


@protected_page('/portable')
def portable():
    with frame('Importar y exportar', '/portable'):
        pid = core.get_active_project_id()
        export_dir = Path(tempfile.gettempdir()) / 'ltw-exports'
        export_dir.mkdir(exist_ok=True)

        with ui.card().classes('w-full'):
            ui.label('Exportar').classes('text-lg font-semibold')
            ui.label('Los secretos, variables sensibles y headers de autorización nunca se exportan. Las programaciones viajan desactivadas.').classes('text-sm text-gray-500')
            scope = ui.select({'workspace': 'Todo el workspace', 'project': 'Solo el proyecto activo', 'suites': 'Flujos seleccionados', 'cases': 'Casos seleccionados'},
                              value='project' if pid else 'workspace', label='Qué exportar').props('outlined dense').classes('w-72')
            suites = {s['id']: s['name'] for s in core.list_project_items('suites', pid)}
            cases = {c['id']: c['name'] for c in core.list_project_items('cases', pid)}
            pick_suites = ui.select(suites, multiple=True, label='Flujos', value=[]).props('outlined dense use-chips').classes('w-full')
            pick_suites.bind_visibility_from(scope, 'value', lambda v: v == 'suites')
            pick_cases = ui.select(cases, multiple=True, label='Casos', value=[]).props('outlined dense use-chips').classes('w-full')
            pick_cases.bind_visibility_from(scope, 'value', lambda v: v == 'cases')
            with_runs = ui.checkbox('Incluir historial (sin cuerpos de petición/respuesta)')
            with_runs.bind_visibility_from(scope, 'value', lambda v: v == 'workspace')

            def export():
                target = export_dir / f'workspace-{time.strftime("%Y%m%d-%H%M%S")}.zip'
                if scope.value == 'project':
                    if not pid:
                        raise ValueError('No hay proyecto activo')
                    core.export_workspace(target, project_id=pid)
                elif scope.value == 'suites':
                    if not pick_suites.value:
                        raise ValueError('Elige al menos un flujo')
                    core.export_workspace(target, suite_ids=pick_suites.value)
                elif scope.value == 'cases':
                    if not pick_cases.value:
                        raise ValueError('Elige al menos un caso')
                    core.export_workspace(target, case_ids=pick_cases.value)
                else:
                    core.export_workspace(target, include_runs=bool(with_runs.value))
                ui.download(target)
            ui.button('Exportar (.zip)', icon='download', on_click=guard(export)).props('color=primary')

        with ui.card().classes('w-full'):
            ui.label('Importar').classes('text-lg font-semibold')
            ui.label('Primero se muestra una vista previa; nada se escribe hasta que confirmes. La importación es todo-o-nada.').classes('text-sm text-gray-500')
            strategy = ui.select({'merge': 'Fusionar (omite lo que ya existe)', 'replace': 'Reemplazar coincidencias', 'new': 'Importar como copia nueva'},
                                 value='merge', label='Estrategia').props('outlined dense').classes('w-80')
            preview_box = ui.column().classes('w-full gap-2')
            pending = {}

            async def on_upload(event):
                try:
                    data = await read_upload(event)
                    target = Path(tempfile.gettempdir()) / 'ltw-incoming.zip'
                    target.write_bytes(data)
                    pending['path'] = target
                    show_preview()
                except Exception as exc:
                    preview_box.clear()
                    ui.notify(str(exc), type='negative', multi_line=True)

            def show_preview():
                preview = core.preview_import(pending['path'], strategy.value)
                preview_box.clear()
                with preview_box:
                    ui.label(f'Vista previa ({preview["scope"]}) — estrategia: {strategy.value}').classes('font-semibold')
                    labels = {'projects': 'Proyectos', 'modules': 'Componentes', 'environments': 'Ambientes', 'cases': 'Casos', 'suites': 'Flujos', 'schedules': 'Programaciones'}
                    for table, counts in preview['summary'].items():
                        if counts['total']:
                            ui.label(f'{labels[table]}: {counts["total"]} ({counts["new"]} nuevos, {counts["existing"]} existentes)')
                    for warning in preview['warnings']:
                        with ui.row().classes('items-center gap-2'):
                            ui.icon('warning', color='warning')
                            ui.label(warning).classes('text-sm')

                    def apply():
                        counts = core.import_workspace(pending['path'], strategy.value)
                        ui.notify('Importación completada: ' + ', '.join(f'{k} {v}' for k, v in counts.items() if v), type='positive')
                        preview_box.clear()
                        ui.navigate.reload()
                    ui.button('Confirmar importación', icon='check', on_click=guard(apply)).props('color=primary')
            strategy.on_value_change(lambda _: show_preview() if pending.get('path') else None)
            ui.upload(label='Elige o arrastra un .zip', on_upload=on_upload, auto_upload=True, max_file_size=MAX_ZIP).props('accept=.zip flat bordered').classes('w-full')

        with ui.card().classes('w-full'):
            ui.label('Diagnóstico').classes('text-lg font-semibold')
            ui.label('Paquete con versiones, conteos y logs recientes sin secretos, para reportar problemas.').classes('text-sm text-gray-500')

            def diagnostics():
                target = export_dir / f'diagnostico-{time.strftime("%Y%m%d-%H%M%S")}.zip'
                logs.diagnostic_package(target)
                ui.download(target)
            ui.button('Descargar diagnóstico', icon='bug_report', on_click=guard(diagnostics)).props('outline')

        with ui.card().classes('w-full border-2 border-red-300'):
            ui.label('Zona de peligro').classes('text-lg font-semibold text-red-700')
            ui.label('Borra permanentemente TODO el workspace: proyectos, componentes, ambientes, casos, flujos, '
                      'programaciones e historial. No se puede deshacer; exporta antes si quieres conservar algo. '
                      'Los secretos guardados en el Administrador de credenciales no se tocan.').classes('text-sm text-gray-600')
            keep_evidence = ui.checkbox('Conservar evidencias (capturas y trazas)', value=False)

            def do_reset():
                core.reset_workspace(remove_evidence=not keep_evidence.value)
                ui.notify('Workspace reiniciado: empiezas de cero.', type='positive')
                ui.navigate.to('/')

            def open_reset_dialog():
                with ui.dialog() as dialog, ui.card():
                    ui.label('Esto borra TODO el workspace y no se puede deshacer.').classes('font-semibold text-red-700')
                    ui.label('Escribe REINICIAR para confirmar.').classes('text-sm text-gray-600')
                    phrase = ui.input(label='Confirmación').props('outlined dense')
                    with ui.row().classes('justify-end w-full gap-2'):
                        ui.button('Cancelar', on_click=dialog.close).props('flat')

                        async def accept():
                            if phrase.value != 'REINICIAR':
                                ui.notify('Escribe exactamente REINICIAR para confirmar.', type='warning')
                                return
                            dialog.close()
                            await guard(do_reset)()
                        ui.button('Borrar todo y reiniciar', on_click=accept, color='negative')
                dialog.open()
            ui.button('Reiniciar workspace (borra todo)', icon='delete_forever', on_click=open_reset_dialog).props('outline color=negative')
