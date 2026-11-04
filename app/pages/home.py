from nicegui import ui
from .. import core, automation, maturity
from .common import frame, status_badge, fmt_time, show_run


@ui.page('/')
def home():
    with frame('Inicio', '/'):
        pid = core.get_active_project_id()
        project = core.get('projects', pid) if pid else None
        counts = {t: len(core.list_project_items(t, pid)) for t in ('modules', 'environments', 'cases', 'suites', 'schedules')}
        ui.label(f'Proyecto activo: {project["name"]}' if project else 'Aún no hay un proyecto activo').classes('text-gray-600')

        with ui.expansion('Qué tan maduro está cada parte (léelo antes de confiar)', icon='info', value=True).classes('w-full border rounded bg-amber-50'):
            ui.label(maturity.DISCLAIMER).classes('text-sm font-medium')
            for level in maturity.LEVELS:
                with ui.row().classes('items-start gap-2 w-full mt-2'):
                    ui.icon(level['icon'], color=level['color']).classes('mt-1')
                    with ui.column().classes('gap-0'):
                        ui.label(level['label']).classes('font-semibold')
                        ui.label(level['summary']).classes('text-xs text-gray-600')
                        ui.label(' · '.join(level['items'])).classes('text-xs text-gray-500')
            ui.label('Detalle completo en KNOWN_LIMITATIONS.md y en el README.').classes('text-xs text-gray-400 mt-2')

        steps = [
            ('Crear un proyecto', bool(project), '/projects'),
            ('Registrar un componente (opcional: con contrato, manual, o se omite y se crean casos directamente)', counts['modules'] > 0, '/modules'),
            ('Registrar un ambiente', counts['environments'] > 0, '/environments'),
            ('Crear un caso de prueba', counts['cases'] > 0, '/cases'),
            ('Agrupar casos en una suite', counts['suites'] > 0, '/suites'),
        ]
        if not all(done for _, done, _ in steps):
            with ui.card().classes('w-full'):
                ui.label('Primeros pasos').classes('text-lg font-semibold')
                for text, done, route in steps:
                    with ui.row().classes('items-center gap-2'):
                        ui.icon('check_circle' if done else 'radio_button_unchecked', color='positive' if done else 'grey')
                        ui.link(text, route).classes('text-gray-400 line-through' if done else '')

        ui.button('Ver el resumen ejecutivo (semáforo, tendencia y qué falla)', icon='monitor_heart', on_click=lambda: ui.navigate.to('/resumen')).props('outline color=primary')
        ui.button('Abrir el Espacio de trabajo (probar peticiones, lotes, conectividad y navegador)', icon='space_dashboard', on_click=lambda: ui.navigate.to('/workspace')).props('outline color=primary')
        with ui.row().classes('gap-3 flex-wrap'):
            for label, key, route in (('Componentes', 'modules', '/modules'), ('Ambientes', 'environments', '/environments'),
                                      ('Casos', 'cases', '/cases'), ('Flujos', 'suites', '/suites'), ('Programaciones', 'schedules', '/schedules')):
                with ui.card().classes('w-40 cursor-pointer').on('click', lambda _, r=route: ui.navigate.to(r)):
                    ui.label(str(counts[key])).classes('text-3xl font-bold text-primary')
                    ui.label(label).classes('text-gray-600')
        with ui.row().classes('items-center gap-2'):
            active = automation.scheduler_active()
            ui.icon('schedule', color='positive' if active else 'grey')
            ui.label('Scheduler activo' if active else 'Scheduler detenido: las programaciones solo corren con «scripts\\scheduler.bat» (o «python run.py --scheduler») abierto')

        ui.label('Últimas ejecuciones').classes('text-lg font-semibold')
        runs = [r for r in core.list_items('runs') if not pid or r.get('project_id') in (pid, None)][:8]
        if not runs:
            ui.label('Todavía no hay ejecuciones.').classes('text-gray-500')
        for run in runs:
            with ui.row().classes('items-center gap-3'):
                status_badge(run['status'])
                ui.label(run.get('case_name') or run.get('suite_name') or run.get('group_name') or '')
                ui.label(fmt_time(run.get('started_at'))).classes('text-gray-500 text-sm')
                ui.button('Detalle', on_click=lambda _, r=run: show_run(r)).props('flat dense')
        ui.label('Carpeta del workspace: ' + str(core.ROOT)).classes('text-xs text-gray-500')
