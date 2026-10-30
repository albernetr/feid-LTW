"""Executive summary for product owners and managers: traffic light, trend, what fails and since when, exportable status report."""
import tempfile
from pathlib import Path
from nicegui import ui, run
from .. import core, reporting
from .common import frame, guard, require_project, show_run


@ui.page('/resumen')
def summary_page():
    with frame('Resumen ejecutivo', '/resumen'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        state = {'days': 14, 'notes': ''}

        @ui.refreshable
        def view():
            report = reporting.collect(pid, state['days'], notes=state['notes'])
            k, rag = report['kpis'], report['rag']
            with ui.card().classes('w-full text-white').style(f'background:{reporting.RAG_COLOR[rag["level"]]}').props('flat').mark('rag-banner'):
                ui.label(f'Estado general: {rag["label"]}').classes('text-2xl font-bold')
                ui.label(report['headline']).classes('text-base')
                for reason in rag['reasons']:
                    ui.label('• ' + reason).classes('text-sm')

            with ui.row().classes('gap-3 flex-wrap w-full'):
                def kpi(value, label, hint=''):
                    with ui.card().classes('w-44'):
                        ui.label(str(value)).classes('text-3xl font-bold')
                        ui.label(label).classes('text-gray-600 text-sm')
                        if hint:
                            ui.label(hint).classes('text-xs text-gray-500')
                delta = k['delta']
                kpi('—' if k['success_rate'] is None else f'{k["success_rate"]}%', 'Tasa de éxito',
                    '' if delta is None else f'{"▲" if delta > 0 else "▼" if delta < 0 else "="} {delta:+} pts vs. periodo anterior')
                kpi(f'{k["suites_healthy"]} de {k["suites_total"]}', 'Flujos sanos', f'{k["suites_never_run"]} sin ejecutar' if k['suites_never_run'] else '')
                kpi(k['cases']['failed'] + k['cases']['error'], 'Casos fallando', f'de {k["cases"]["total"]} casos')
                kpi(k['cases']['never'], 'Casos sin ejecutar')
                kpi(k['executions'], 'Ejecuciones', f'antes: {k["executions_previous"]}')
                kpi('—' if k['avg_response_ms'] is None else f'{k["avg_response_ms"]} ms', 'Respuesta media')

            with ui.card().classes('w-full'):
                ui.label('Ejecuciones por día').classes('font-semibold')
                ui.html(reporting.trend_svg(report['trend']), sanitize=False).classes('w-full')
                ui.label('Verde: pasaron · Rojo: fallaron').classes('text-xs text-gray-500')

            with ui.card().classes('w-full'):
                ui.label('Flujos (suites)').classes('font-semibold')
                if not report['suites']:
                    ui.label('Aún no hay suites. Los flujos agrupan casos y son lo primero que conviene vigilar.').classes('text-sm text-gray-500')
                for s in report['suites']:
                    with ui.row().classes('items-center gap-3 w-full'):
                        ui.badge(reporting.STATUS_ES.get(s['status'], 'Sin ejecutar'), color={'passed': 'positive', 'failed': 'negative', 'error': 'warning'}.get(s['status'], 'grey')).classes('w-20 justify-center')
                        ui.label(s['name']).classes('font-medium w-64')
                        ui.html(reporting.spark_svg(s['spark']), sanitize=False)
                        ui.label('—' if s['success_rate'] is None else f'{s["success_rate"]}% en {s["runs"]} ejecución(es)').classes('text-sm text-gray-600')
                        if s['delta'] is not None:
                            ui.label(reporting._arrow(s['delta'])).classes('text-sm ' + ('text-green-700' if s['delta'] > 0 else 'text-red-700' if s['delta'] < 0 else 'text-gray-500'))
                        ui.space()
                        ui.label(reporting._fmt(s['last_run'])).classes('text-xs text-gray-500')
                        if s['run_id']:
                            ui.button('Detalle', on_click=lambda _, r=s['run_id']: show_run(core.get('runs', r))).props('flat dense size=sm')

            with ui.card().classes('w-full'):
                ui.label('Qué está fallando y desde cuándo').classes('font-semibold')
                if not report['failing']:
                    ui.label('Nada falla en la última ejecución de cada caso.').classes('text-sm text-green-800')
                for f in report['failing']:
                    with ui.row().classes('items-start gap-3 w-full no-wrap'):
                        ui.icon('error', color='negative' if f['status'] == 'failed' else 'warning')
                        with ui.column().classes('gap-0 grow'):
                            ui.label(f'{f["name"]} · {f["target"]}').classes('font-medium')
                            ui.label(f'Desde {reporting._fmt(f["since"])} · {f["consecutive_failures"]} ejecución(es) seguidas' + (f' · responsable: {f["owner_hint"]}' if f['owner_hint'] else '')).classes('text-xs text-gray-500')
                            if f['detail']:
                                ui.label(f['detail']).classes('text-sm text-gray-700')
                        ui.button('Detalle', on_click=lambda _, r=f['run_id']: show_run(core.get('runs', r))).props('flat dense size=sm')

            with ui.row().classes('w-full gap-4 items-start'):
                with ui.card().classes('grow basis-80'):
                    ui.label('Casos inestables').classes('font-semibold')
                    ui.label('Pasan y fallan sin que nadie cambie la prueba: revísalos antes de confiar en ellos.').classes('text-xs text-gray-500')
                    if not report['unstable']:
                        ui.label('Ninguno en el periodo.').classes('text-sm text-gray-600')
                    for u in report['unstable']:
                        ui.label(f'{u["name"]} · {u["flips"]} cambio(s) de estado en {u["runs"]} ejecuciones ({u["pass_rate"]}% éxito)').classes('text-sm')
                with ui.card().classes('grow basis-80'):
                    ui.label('Más lentos').classes('font-semibold')
                    if not report['slow']:
                        ui.label('Sin datos de tiempos en el periodo.').classes('text-sm text-gray-600')
                    for s in report['slow']:
                        ui.label(f'{s["name"]} · promedio {s["avg_ms"]} ms (máx. {s["max_ms"]} ms)').classes('text-sm')
                with ui.card().classes('grow basis-80'):
                    ui.label('Interfaces observadas y programaciones').classes('font-semibold')
                    o, sc = report['observer'], report['schedules']
                    if o['changes']:
                        for c in o['changes']:
                            ui.label(f'⚠ {c["module"]}: {c["pending"]} cambio(s) sin aviso' + (f' · {c["owner"]}' if c['owner'] else '')).classes('text-sm text-amber-800')
                        ui.link('Abrir el Observador', '/observer').classes('text-sm')
                    else:
                        ui.label(f'Sin cambios pendientes en {o["modules"]} módulo(s) observados.').classes('text-sm text-gray-600')
                    ui.label(f'Programaciones: {sc["enabled"]} activa(s) de {sc["total"]}; vencidas: {sc["overdue"]}; scheduler {"en marcha" if sc["scheduler_running"] else "detenido"}.').classes('text-sm text-gray-600')
            ui.label(f'Criterio del semáforo: verde con éxito ≥ {report["thresholds"]["green_at_least"]:.0f}% y sin fallos pendientes; rojo si un flujo falla o el éxito baja de '
                     f'{report["thresholds"]["red_below"]:.0f}%; ámbar en el resto.').classes('text-xs text-gray-500')
            return report

        with ui.row().classes('items-center gap-3 w-full'):
            period = ui.toggle({d: f'{d} días' for d in reporting.RANGES}, value=state['days']).props('no-caps dense')
            period.on_value_change(lambda e: (state.__setitem__('days', e.value), view.refresh()))
            ui.space()

            def current():
                return reporting.collect(pid, state['days'], notes=state['notes'])

            async def download(kind):
                report = current()
                stem = f'estatus-{core.get("projects", pid)["name"]}-{report["generated_at"][:10]}'.replace(' ', '_')
                if kind == 'pdf':
                    with tempfile.TemporaryDirectory() as folder:
                        target = Path(folder) / 'r.pdf'
                        await run.io_bound(reporting.render_pdf, reporting.render_html(report), target)
                        ui.download(target.read_bytes(), stem + '.pdf')
                else:
                    ui.download(reporting.render(report, kind), f'{stem}.{kind}')
                ui.notify('Reporte generado', type='positive')

            def copy_summary():
                ui.clipboard.write(reporting.summary_text(current()))
                ui.notify('Resumen copiado: pégalo en un correo o chat', type='positive')
            ui.button('Copiar resumen', icon='content_copy', on_click=guard(copy_summary)).props('outline dense no-caps')
            with ui.button('Reporte de estatus', icon='download').props('color=primary dense no-caps'):
                with ui.menu():
                    for label, kind in (('Página web (.html)', 'html'), ('PDF', 'pdf'), ('Markdown (.md)', 'md'), ('Datos (.json)', 'json')):
                        ui.menu_item(label, on_click=guard(lambda k=kind: download(k)))
        notes = ui.textarea('Comentarios para el reporte (opcional)', placeholder='Contexto, decisiones, riesgos… se incluye en el reporte exportado.').props('outlined dense autogrow').classes('w-full')
        notes.on_value_change(lambda e: state.__setitem__('notes', e.value or ''))
        view()
