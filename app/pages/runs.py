from nicegui import ui
from .. import core
from .common import frame, guard, confirm, empty_state, fmt_time, show_run, STATUS_LABEL


@ui.page('/runs')
def runs_page():
    with frame('Historial de ejecuciones', '/runs'):
        pid = core.get_active_project_id()
        all_runs = [r for r in core.list_items('runs') if not pid or r.get('project_id') in (pid, None)]

        with ui.row().classes('items-center gap-3'):
            status = ui.select({'': 'Todos los estados', **STATUS_LABEL}, value='', label='Estado').props('outlined dense').classes('w-48')
            kind = ui.select({'': 'Todos los tipos', 'api': 'API', 'ui': 'UI', 'suite': 'Suite'}, value='', label='Tipo').props('outlined dense').classes('w-44')
            text = ui.input('Buscar por nombre').props('outlined dense clearable').classes('w-60')

        columns = [
            {'name': 'started', 'label': 'Inicio', 'field': 'started', 'align': 'left', 'sortable': True},
            {'name': 'type', 'label': 'Tipo', 'field': 'type', 'align': 'left'},
            {'name': 'name', 'label': 'Nombre', 'field': 'name', 'align': 'left'},
            {'name': 'status', 'label': 'Estado', 'field': 'status', 'align': 'left'},
            {'name': 'detail', 'label': 'Detalle', 'field': 'detail', 'align': 'left'},
        ]

        def rows():
            result = []
            for run in all_runs:
                label = run.get('case_name') or run.get('suite_name') or ''
                if status.value and run['status'] != status.value or kind.value and run['type'] != kind.value or (text.value or '').lower() not in label.lower():
                    continue
                detail = (f'HTTP {run["http_status"]} · {run.get("duration_ms")} ms' if run.get('http_status') else
                          f'{len(run.get("case_runs", []))} casos' if run['type'] == 'suite' else run.get('error', '')[:80])
                result.append({'id': run['id'], 'started': fmt_time(run.get('started_at')), 'type': run['type'].upper(), 'name': label,
                               'status': STATUS_LABEL.get(run['status'], run['status']), 'detail': detail})
            return result
        if not all_runs:
            empty_state('Todavía no hay ejecuciones.')
        else:
            table = ui.table(columns=columns, rows=rows(), row_key='id', pagination=15).classes('w-full')
            table.props('flat bordered')
            table.add_slot('body-cell-status', '''<q-td :props="props"><q-badge :color="props.value==='Pasó'?'positive':(props.value==='Falló'?'negative':'grey')">{{ props.value }}</q-badge></q-td>''')

            def refresh(_=None):
                table.rows = rows()
                table.update()
            for control in (status, kind, text):
                control.on_value_change(refresh)
            table.on('rowClick', lambda e: show_run(core.get('runs', e.args[1]['id'])))
            ui.label('Haz clic en una fila para ver el detalle, capturas y trazas.').classes('text-sm text-gray-500')

        with ui.card().classes('w-full'):
            ui.label('Retención de evidencias').classes('font-semibold')
            ui.label('Elimina ejecuciones y archivos (capturas, trazas) anteriores a N días.').classes('text-sm text-gray-500')
            with ui.row().classes('items-center gap-3'):
                days = ui.number('Conservar (días)', value=30, min=0, max=3650, precision=0).props('outlined dense').classes('w-44')

                def purge():
                    result = core.purge_evidence(int(days.value or 0))
                    ui.notify(f'Eliminadas {result["runs"]} ejecuciones y {result["files"]} archivos', type='positive')
                    ui.navigate.reload()
                ui.button('Purgar ahora', icon='cleaning_services', on_click=lambda: confirm(
                    f'Se eliminarán las ejecuciones con más de {int(days.value or 0)} días. ¿Continuar?', purge, 'Purgar')).props('outline color=negative')
