from nicegui import ui, run
from .. import core, automation
from .common import frame, guard, confirm, empty_state, require_project, fmt_time, show_run


@ui.page('/schedules')
def schedules():
    with frame('Programaciones', '/schedules'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        active = automation.scheduler_active()
        with ui.card().classes('w-full ' + ('bg-green-50' if active else 'bg-amber-50')):
            ui.label('Scheduler activo' if active else 'Scheduler detenido').classes('font-semibold')
            ui.label('Las programaciones solo se ejecutan mientras «scripts\\scheduler.bat» (o «python run.py --scheduler») esté abierto y el equipo encendido. '
                     'Solo puede haber un scheduler por workspace.' if not active else 'Hay un proceso scheduler atendiendo este workspace.').classes('text-sm')

        suites = core.list_project_items('suites', pid)
        if not suites:
            ui.label('Crea una suite primero.').classes('text-amber-700')
        else:
            with ui.card().classes('w-full'):
                ui.label('Nueva programación').classes('text-lg font-semibold')
                suite = ui.select({s['id']: s['name'] for s in suites}, value=suites[0]['id'], label='Suite').props('outlined dense').classes('w-72')
                frequency = ui.select(automation.FREQUENCIES, value='daily', label='Frecuencia').props('outlined dense').classes('w-60')
                with ui.row().classes('gap-3 items-center'):
                    at = ui.input('Hora (HH:MM)', value='02:00').props('outlined dense').classes('w-36')
                    at.bind_visibility_from(frequency, 'value', lambda v: v in ('daily', 'weekdays', 'weekly'))
                    weekday = ui.select({0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}, value=0, label='Día').props('outlined dense').classes('w-40')
                    weekday.bind_visibility_from(frequency, 'value', lambda v: v == 'weekly')
                    run_at = ui.input('Fecha y hora (AAAA-MM-DDTHH:MM)', placeholder='2026-12-01T09:30').props('outlined dense').classes('w-72')
                    run_at.bind_visibility_from(frequency, 'value', lambda v: v == 'once')
                    interval = ui.number('Cada (minutos)', value=60, min=1, max=10080, precision=0).props('outlined dense').classes('w-44')
                    interval.bind_visibility_from(frequency, 'value', lambda v: v == 'interval')
                    timezone = ui.input('Zona horaria IANA', value='America/Mexico_City').props('outlined dense').classes('w-60')
                    timezone.bind_visibility_from(frequency, 'value', lambda v: v != 'interval')
                missed = ui.select(automation.MISSED_POLICIES, value='run_once', label='Si el equipo estuvo apagado').props('outlined dense').classes('w-80')

                def store():
                    automation.create_schedule(suite.value, frequency.value, (at.value or '').strip(), (timezone.value or 'UTC').strip(), int(weekday.value or 0),
                                               run_at=(run_at.value or '').strip() or None, interval_minutes=interval.value if frequency.value == 'interval' else None,
                                               missed_policy=missed.value)
                    ui.notify('Programación guardada', type='positive')
                    ui.navigate.reload()
                ui.button('Programar', icon='schedule', on_click=guard(store)).props('color=primary')

        items = core.list_project_items('schedules', pid)
        if not items:
            empty_state('No hay programaciones.')
        for item in items:
            suite_item = core.get('suites', item.get('suite_id'))
            with ui.card().classes('w-full'):
                with ui.row().classes('items-center gap-3 w-full no-wrap'):
                    with ui.column().classes('gap-0 grow'):
                        ui.label(f'{suite_item["name"] if suite_item else "suite eliminada"} · {automation.describe_schedule(item)}').classes('font-semibold')
                        ui.label(f'Próxima: {fmt_time(item.get("next_run_at")) if item.get("enabled") else "—"} · Última: {fmt_time(item.get("last_trigger_at"))}'
                                 f'{" · " + item["last_outcome"] if item.get("last_outcome") else ""}').classes('text-sm text-gray-500')
                    ui.badge('Activa' if item.get('enabled') else 'Pausada', color='positive' if item.get('enabled') else 'grey')

                    def toggle(s=item):
                        s['enabled'] = not s.get('enabled', False)
                        if s['enabled']:
                            s['next_run_at'] = automation.next_due(s)
                        core.save('schedules', s)
                        ui.navigate.reload()
                    ui.button('Pausar' if item.get('enabled') else 'Activar', on_click=guard(toggle)).props('outline dense')

                    async def now(s=item):
                        target = core.get('suites', s['suite_id'])
                        if target is None:
                            raise ValueError('La suite ya no existe')
                        show_run(await run.io_bound(automation.execute_suite, target))
                    ui.button(icon='play_arrow', on_click=guard(now)).props('flat round dense color=positive').tooltip('Ejecutar ahora')

                    def remove(s=item):
                        core.delete('schedules', s['id'])
                        ui.navigate.reload()
                    ui.button(icon='delete', on_click=lambda _, s=item, r=remove: confirm('¿Eliminar esta programación?', r)).props('flat round dense color=negative')
