"""Executive view and status report: what is healthy, what changed, what is failing and since when. Pure functions over the run history,
so the screen, the exported files and the command line all say exactly the same thing."""
import datetime as dt
import html
import json
import statistics
import sys
from pathlib import Path
from . import core, observer, report_doc as rd, report_render, report_tree as rt

FORMAT = 'ltw.status/1'
RANGES = (7, 14, 30, 90)
GREEN_RATE, AMBER_RATE = 0.95, 0.80
DECISIVE = ('passed', 'failed', 'error')                      # cancelled / skipped say nothing about health
RAG = {'green': 'VERDE', 'amber': 'ÁMBAR', 'red': 'ROJO', 'grey': 'SIN DATOS'}
RAG_COLOR = {'green': '#16a34a', 'amber': '#d97706', 'red': '#dc2626', 'grey': '#6b7280'}
STATUS_ES = {'passed': 'Pasó', 'failed': 'Falló', 'error': 'Error', 'cancelled': 'Cancelada', 'skipped': 'Omitido'}
STATUS_COLOR = {'passed': '#16a34a', 'failed': '#dc2626', 'error': '#d97706', 'cancelled': '#9ca3af', 'skipped': '#9ca3af'}


def component_maturity(component_id):
    """Nivel de madurez de un Componente, derivado de la estabilidad real de sus Casos (el mismo semáforo
    verde/ámbar/rojo del Resumen ejecutivo) — no una etiqueta manual. El último run decisivo de cada caso
    decide si ese caso cuenta como pasando hoy; el color sale de qué fracción de los casos *con datos* pasa."""
    cases = [c for c in core.list_items('cases') if c.get('module_id') == component_id]
    if not cases:
        return {'rag': 'grey', 'passed': 0, 'with_data': 0, 'total': 0}
    case_ids = {c['id'] for c in cases}
    runs = sorted((r for r in core.list_items('runs') if r.get('type') in ('api', 'ui') and r.get('case_id') in case_ids and r.get('status') in DECISIVE),
                  key=lambda r: r.get('started_at', ''))
    latest = {}
    for run in runs:
        latest[run['case_id']] = run
    passed = sum(1 for r in latest.values() if r['status'] == 'passed')
    with_data = len(latest)
    rate = _rate(passed, with_data)
    rag = 'grey' if rate is None else ('green' if rate >= GREEN_RATE else ('amber' if rate >= AMBER_RATE else 'red'))
    return {'rag': rag, 'passed': passed, 'with_data': with_data, 'total': len(cases)}


def _when(iso):
    try:
        value = dt.datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def _local_day(moment):
    return moment.astimezone().date()


def _pct(value):
    return None if value is None else round(value * 100, 1)


def _rate(passed, total):
    return None if not total else passed / total


def _failure_text(run):
    for item in run.get('assertions') or []:
        if not item.get('passed'):
            rule = item.get('rule') or {}
            return f'{rule.get("type", "aserción")} {rule.get("path", "")} → obtenido {json.dumps(item.get("actual"), ensure_ascii=False)[:120]}'.replace('  ', ' ')
    return (run.get('error') or '')[:200]


# --------------------------------------------------------------------------- collecting

def collect(project_id=None, days=14, now=None, notes='', title=''):
    """Builds the `ltw.status/1` document for the project over the last `days` days."""
    now = now or dt.datetime.now(dt.timezone.utc)
    start, previous_start = now - dt.timedelta(days=days), now - dt.timedelta(days=2 * days)
    project = core.get('projects', project_id) if project_id else None
    runs = [r for r in core.list_items('runs') if project_id is None or r.get('project_id') == project_id]
    for run in runs:
        run['_t'] = _when(run.get('started_at'))
    runs = sorted((r for r in runs if r['_t']), key=lambda r: r['_t'])
    cases = {c['id']: c for c in core.list_project_items('cases', project_id)}
    suites = core.list_project_items('suites', project_id)
    case_runs = [r for r in runs if r.get('type') in ('api', 'ui')]
    suite_runs = [r for r in runs if r.get('type') == 'suite']
    in_period = lambda r: start <= r['_t'] <= now                                     # noqa: E731
    in_previous = lambda r: previous_start <= r['_t'] < start                         # noqa: E731

    decisive = [r for r in case_runs if in_period(r) and r['status'] in DECISIVE]
    decisive_prev = [r for r in case_runs if in_previous(r) and r['status'] in DECISIVE]
    passed = sum(r['status'] == 'passed' for r in decisive)
    passed_prev = sum(r['status'] == 'passed' for r in decisive_prev)
    rate, rate_prev = _rate(passed, len(decisive)), _rate(passed_prev, len(decisive_prev))

    # current health: the latest decisive run of every case
    latest = {}
    history = {}
    for run in case_runs:
        if run.get('case_id') in cases and run['status'] in DECISIVE:
            latest[run['case_id']] = run
            history.setdefault(run['case_id'], []).append(run)
    counts = {'total': len(cases), 'passed': 0, 'failed': 0, 'error': 0, 'never': 0}
    failing = []
    for case_id, case in cases.items():
        last = latest.get(case_id)
        if last is None:
            counts['never'] += 1
        elif last['status'] == 'passed':
            counts['passed'] += 1
        else:
            counts[last['status']] += 1
            streak = 0
            since = last
            for run in reversed(history[case_id]):
                if run['status'] == 'passed':
                    break
                streak += 1
                since = run
            failing.append({'case_id': case_id, 'name': case.get('name', ''), 'target': f'{case.get("method", "")} {case.get("path", "")}'.strip(), 'status': last['status'],
                            'since': since['started_at'], 'last_run': last['started_at'], 'consecutive_failures': streak, 'detail': _failure_text(last), 'run_id': last['id'],
                            'owner_hint': (case.get('code_hints') or {}).get('owner', '')})
    failing.sort(key=lambda f: (-f['consecutive_failures'], f['name'].lower()))

    suite_rows = []
    for suite in suites:
        mine = [r for r in suite_runs if r.get('suite_id') == suite['id'] and r['status'] in DECISIVE]
        period, prev = [r for r in mine if in_period(r)], [r for r in mine if in_previous(r)]
        last = mine[-1] if mine else None
        rate_s, rate_p = _rate(sum(r['status'] == 'passed' for r in period), len(period)), _rate(sum(r['status'] == 'passed' for r in prev), len(prev))
        duration = None
        if last and _when(last.get('finished_at')):
            duration = round((_when(last['finished_at']) - last['_t']).total_seconds() * 1000)
        suite_rows.append({'suite_id': suite['id'], 'name': suite.get('name', ''), 'steps': len(core.suite_steps(suite)), 'status': last['status'] if last else 'never',
                           'last_run': last['started_at'] if last else None, 'runs': len(period), 'success_rate': _pct(rate_s),
                           'delta': None if rate_s is None or rate_p is None else round((rate_s - rate_p) * 100, 1),
                           'spark': [r['status'] for r in mine[-12:]], 'last_duration_ms': duration, 'run_id': last['id'] if last else None})
    suite_rows.sort(key=lambda s: ({'failed': 0, 'error': 0, 'never': 1, 'passed': 2}.get(s['status'], 2), s['name'].lower()))

    # Suites (suite_groups): un grupo de Flujos y/o Casos sueltos, un nivel arriba de un Flujo (ver
    # core.save_suite_group) — mismo cálculo que suite_rows, pero antes el resumen ejecutivo nunca las
    # contaba ni las listaba (el filtro de abajo solo tomaba type == 'suite').
    groups = core.list_project_items('suite_groups', project_id)
    group_runs = [r for r in runs if r.get('type') == 'suite_group']
    group_rows = []
    for group in groups:
        mine = [r for r in group_runs if r.get('group_id') == group['id'] and r['status'] in DECISIVE]
        period, prev = [r for r in mine if in_period(r)], [r for r in mine if in_previous(r)]
        last = mine[-1] if mine else None
        rate_s, rate_p = _rate(sum(r['status'] == 'passed' for r in period), len(period)), _rate(sum(r['status'] == 'passed' for r in prev), len(prev))
        group_rows.append({'group_id': group['id'], 'name': group.get('name', ''), 'members': len(group.get('members') or []),
                           'status': last['status'] if last else 'never', 'last_run': last['started_at'] if last else None,
                           'runs': len(period), 'success_rate': _pct(rate_s),
                           'delta': None if rate_s is None or rate_p is None else round((rate_s - rate_p) * 100, 1),
                           'spark': [r['status'] for r in mine[-12:]], 'run_id': last['id'] if last else None})
    group_rows.sort(key=lambda s: ({'failed': 0, 'error': 0, 'never': 1, 'passed': 2}.get(s['status'], 2), s['name'].lower()))

    unstable = []
    for case_id, items in history.items():
        window = [r['status'] == 'passed' for r in items if in_period(r)]
        flips = sum(1 for a, b in zip(window, window[1:]) if a != b)
        if flips >= 2:                                                                  # one pass→fail is a regression (see «failing»); back and forth is instability
            unstable.append({'case_id': case_id, 'name': cases[case_id].get('name', ''), 'runs': len(window), 'flips': flips,
                             'pass_rate': _pct(_rate(sum(window), len(window)))})
    unstable.sort(key=lambda u: (-u['flips'], u['name'].lower()))

    durations = {}
    for run in case_runs:
        if in_period(run) and run.get('duration_ms') and run.get('case_id') in cases:
            durations.setdefault(run['case_id'], []).append(run['duration_ms'])
    slow = sorted(({'case_id': cid, 'name': cases[cid].get('name', ''), 'runs': len(v), 'avg_ms': round(statistics.mean(v)), 'max_ms': round(max(v))}
                   for cid, v in durations.items()), key=lambda s: -s['avg_ms'])[:5]
    all_durations = [d for v in durations.values() for d in v]

    trend = []
    for offset in range(days - 1, -1, -1):
        day = _local_day(now) - dt.timedelta(days=offset)
        todays = [r for r in decisive if _local_day(r['_t']) == day]
        ok = sum(r['status'] == 'passed' for r in todays)
        trend.append({'day': day.isoformat(), 'runs': len(todays), 'passed': ok, 'failed': len(todays) - ok, 'success_rate': _pct(_rate(ok, len(todays)))})

    modules = observer.module_summaries(project_id)
    drift = [m for m in modules if m['drift']]
    schedules = core.list_project_items('schedules', project_id)
    enabled = [s for s in schedules if s.get('enabled')]
    from . import automation
    overdue = [s for s in enabled if _when(s.get('next_run_at')) and _when(s['next_run_at']) < now - dt.timedelta(minutes=10)]
    scheduler_on = automation.scheduler_active()

    kpis = {'success_rate': _pct(rate), 'success_rate_previous': _pct(rate_prev), 'delta': None if rate is None or rate_prev is None else round((rate - rate_prev) * 100, 1),
            'executions': len(decisive), 'executions_previous': len(decisive_prev), 'cases': counts,
            'suites_total': len(suite_rows), 'suites_healthy': sum(s['status'] == 'passed' for s in suite_rows),
            'suites_failing': sum(s['status'] in ('failed', 'error') for s in suite_rows), 'suites_never_run': sum(s['status'] == 'never' for s in suite_rows),
            'suite_groups_total': len(group_rows), 'suite_groups_healthy': sum(s['status'] == 'passed' for s in group_rows),
            'suite_groups_failing': sum(s['status'] in ('failed', 'error') for s in group_rows), 'suite_groups_never_run': sum(s['status'] == 'never' for s in group_rows),
            'avg_response_ms': round(statistics.mean(all_durations)) if all_durations else None}
    level, reasons = _traffic_light(kpis, drift, overdue, enabled, scheduler_on)
    report = {'format': FORMAT, 'title': title or 'Reporte de estatus de pruebas', 'generated_at': now.isoformat(), 'notes': notes,
              'tool': {'name': 'local-test-workspace'}, 'project': {'id': project_id, 'name': project['name'] if project else 'Todos los proyectos'},
              'period': {'days': days, 'from': start.isoformat(), 'to': now.isoformat()}, 'rag': {'level': level, 'label': RAG[level], 'reasons': reasons},
              'kpis': kpis, 'trend': trend, 'suites': suite_rows, 'suite_groups': group_rows, 'failing': failing, 'unstable': unstable[:8], 'slow': slow,
              'observer': {'modules': len(modules), 'with_changes': len(drift), 'unbaselined': sum(m['unbaselined'] for m in modules),
                           'changes': [{'module': m['module'], 'pending': m['drift'], 'company': m.get('company', ''), 'owner': m.get('owner', '')} for m in drift]},
              'schedules': {'total': len(schedules), 'enabled': len(enabled), 'overdue': len(overdue), 'scheduler_running': scheduler_on},
              'thresholds': {'green_at_least': GREEN_RATE * 100, 'red_below': AMBER_RATE * 100}}
    report['headline'] = headline(report)
    return report


def _traffic_light(kpis, drift, overdue, enabled, scheduler_on):
    reasons = []
    cases = kpis['cases']
    if kpis['executions'] == 0 and cases['passed'] + cases['failed'] + cases['error'] == 0:
        return 'grey', ['Todavía no hay ejecuciones en el periodo: no se puede opinar sobre la salud.']
    level = 'green'

    def worsen(to, reason):
        nonlocal level
        order = ['green', 'amber', 'red']
        level = order[max(order.index(level), order.index(to))]
        reasons.append(reason)
    rate = kpis['success_rate']
    if kpis['suites_failing']:
        worsen('red', f'{kpis["suites_failing"]} flujo(s) fallan en su última ejecución.')
    if kpis['suite_groups_failing']:
        worsen('red', f'{kpis["suite_groups_failing"]} suite(s) fallan en su última ejecución.')
    if rate is not None and rate < AMBER_RATE * 100:
        worsen('red', f'La tasa de éxito del periodo es {rate}% (mínimo aceptable {int(AMBER_RATE * 100)}%).')
    elif rate is not None and rate < GREEN_RATE * 100:
        worsen('amber', f'La tasa de éxito del periodo es {rate}% (objetivo {int(GREEN_RATE * 100)}%).')
    failing = cases['failed'] + cases['error']
    if failing:
        worsen('amber', f'{failing} caso(s) fallan en su última ejecución.')
    if drift:
        worsen('amber', f'{sum(m["drift"] for m in drift)} cambio(s) sin aviso detectados en {len(drift)} componente(s) observados.')
    if overdue:
        worsen('amber', f'{len(overdue)} programación(es) vencidas sin ejecutarse' + ('' if scheduler_on else ' (el scheduler está detenido).'))
    if kpis['suites_never_run']:
        reasons.append(f'{kpis["suites_never_run"]} flujo(s) nunca se han ejecutado (informativo).')
    if kpis['suite_groups_never_run']:
        reasons.append(f'{kpis["suite_groups_never_run"]} suite(s) nunca se han ejecutado (informativo).')
    if level == 'green' and not reasons:
        reasons.append('Todo lo ejecutado pasa y no hay cambios pendientes.')
    return level, reasons


def headline(report):
    k, rag = report['kpis'], report['rag']['level']
    days = report['period']['days']
    if rag == 'grey':
        return 'Aún no hay ejecuciones para valorar el estado.'
    trend = ''
    if k['delta'] is not None:
        trend = f' ({"+" if k["delta"] >= 0 else ""}{k["delta"]} puntos frente a los {days} días anteriores)'
    text = f'{k["suites_healthy"]} de {k["suites_total"]} flujos sanos' if k['suites_total'] else 'Sin flujos definidos'
    if k['suite_groups_total']:
        text += f'; {k["suite_groups_healthy"]} de {k["suite_groups_total"]} suites sanas'
    failing = k['cases']['failed'] + k['cases']['error']
    return (f'{text}; tasa de éxito {k["success_rate"]}%{trend}; '
            f'{failing} caso(s) fallando de {k["cases"]["total"]}.')


# --------------------------------------------------------------------------- small graphics (shared by the screen and the HTML report)

def trend_svg(trend, width=720, height=150):
    """Daily bars: height = executions, green part = passed, red part = failed."""
    biggest = max([d['runs'] for d in trend] + [1])
    gap = 3
    bar = max(2, (width - gap * len(trend)) / max(len(trend), 1))
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height + 22}" width="100%" role="img" aria-label="Ejecuciones por día">']
    for i, day in enumerate(trend):
        x = i * (bar + gap)
        h_ok, h_bad = height * day['passed'] / biggest, height * day['failed'] / biggest
        label = f'{day["day"]}: {day["runs"]} ejecuciones, {day["passed"]} pasaron, {day["failed"]} fallaron'
        parts.append(f'<g><title>{html.escape(label)}</title><rect x="{x:.1f}" y="{height - h_ok - h_bad:.1f}" width="{bar:.1f}" height="{h_bad:.1f}" fill="#dc2626"/>'
                     f'<rect x="{x:.1f}" y="{height - h_ok:.1f}" width="{bar:.1f}" height="{h_ok:.1f}" fill="#16a34a"/>'
                     + ('<rect x="{:.1f}" y="{}" width="{:.1f}" height="2" fill="#d1d5db"/>'.format(x, height - 2, bar) if not day['runs'] else '') + '</g>')
    step = max(1, len(trend) // 7)
    for i in range(0, len(trend), step):
        parts.append(f'<text x="{i * (bar + gap):.1f}" y="{height + 15}" font-size="10" fill="#6b7280">{html.escape(trend[i]["day"][5:])}</text>')
    parts.append('</svg>')
    return ''.join(parts)


def spark_svg(statuses, size=10):
    if not statuses:
        return '<span style="color:#9ca3af">—</span>'
    cells = ''.join(f'<rect x="{i * (size + 2)}" y="0" width="{size}" height="{size + 4}" rx="2" fill="{STATUS_COLOR.get(s, "#9ca3af")}"><title>{STATUS_ES.get(s, s)}</title></rect>'
                    for i, s in enumerate(statuses))
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{len(statuses) * (size + 2)}" height="{size + 4}" role="img" aria-label="Últimas ejecuciones">{cells}</svg>'


# --------------------------------------------------------------------------- rendering

def _fmt(iso):
    moment = _when(iso)
    return moment.astimezone().strftime('%Y-%m-%d %H:%M') if moment else '—'


def _arrow(delta):
    return '—' if delta is None else (f'▲ +{delta}' if delta > 0 else (f'▼ {delta}' if delta < 0 else '= 0'))


def summary_text(report):
    """Short plain text for an email or chat message."""
    lines = [f'{report["title"]} — {report["project"]["name"]} (últimos {report["period"]["days"]} días)', f'Estado {report["rag"]["label"]}: {report["headline"]}']
    lines += [f'- {r}' for r in report['rag']['reasons']]
    for f in report['failing'][:5]:
        lines.append(f'• Falla: {f["name"]} desde {_fmt(f["since"])} ({f["consecutive_failures"]} ejecución(es) seguidas) — {f["detail"][:100]}')
    return '\n'.join(lines)


def _spark_text(statuses):
    """Mismo espíritu que spark_svg (últimas corridas) pero en texto — para Markdown, que no tiene SVG."""
    return ', '.join(STATUS_ES.get(s, s) for s in statuses) if statuses else '—'


def _status_doc(report):
    """Arma el árbol de bloques genérico (ver report_doc.py) de este reporte — un solo lugar de verdad que
    luego HTML/Markdown/PDF renderizan igual (ver report_render.py). DOCX queda explícitamente sin soportar
    acá (ver render/cli más abajo), como ya era el caso antes de esta migración."""
    k = report['kpis']
    blocks = [rd.banner(RAG_COLOR[report['rag']['level']], f'Estado general: {report["rag"]["label"]}',
                        [report['headline']] + report['rag']['reasons'])]
    if report.get('notes'):
        blocks += [rd.heading('Comentarios'), rd.text(report['notes'])]
    c = k['cases']
    blocks.append(rd.cards([
        {'value': f'{k["success_rate"]}%' if k['success_rate'] is not None else '—', 'label': 'Tasa de éxito'},
        {'value': _arrow(k['delta']), 'label': 'vs. periodo anterior'},
        {'value': f'{k["suites_healthy"]}/{k["suites_total"]}', 'label': 'Flujos sanos'},
        {'value': c['failed'] + c['error'], 'label': 'Casos fallando'},
        {'value': c['never'], 'label': 'Casos sin ejecutar'},
        {'value': k['executions'], 'label': 'Ejecuciones'},
        {'value': f'{k["avg_response_ms"]} ms' if k['avg_response_ms'] is not None else '—', 'label': 'Respuesta media'}]))
    blocks += [rd.heading('Ejecuciones por día'), rd.svg(trend_svg(report['trend'])), rd.text('Verde: pasaron · Rojo: fallaron')]
    if report['suites']:
        blocks.append(rd.heading('Flujos'))
        blocks.append(rd.table(['Flujo', 'Último estado', 'Última ejecución', 'Ejec.', 'Éxito', 'Cambio', 'Recientes'],
            [[s['name'], STATUS_ES.get(s['status'], 'Sin ejecutar'), _fmt(s['last_run']), s['runs'],
              f'{s["success_rate"]}%' if s['success_rate'] is not None else '—', _arrow(s['delta']), _spark_text(s['spark'])]
             for s in report['suites']]))
    if report['suite_groups']:
        blocks.append(rd.heading('Suites'))
        blocks.append(rd.table(['Suite', 'Último estado', 'Última ejecución', 'Ejec.', 'Éxito', 'Cambio', 'Miembros', 'Recientes'],
            [[g['name'], STATUS_ES.get(g['status'], 'Sin ejecutar'), _fmt(g['last_run']), g['runs'],
              f'{g["success_rate"]}%' if g['success_rate'] is not None else '—', _arrow(g['delta']), g['members'], _spark_text(g['spark'])]
             for g in report['suite_groups']]))
    if report['failing']:
        blocks.append(rd.heading('Qué está fallando'))
        blocks.append(rd.table(['Caso', 'Falla desde', 'Seguidas', 'Detalle'],
            [[f'{f["name"]} ({f["target"]})', _fmt(f['since']), f['consecutive_failures'], f['detail'][:200]] for f in report['failing']]))
    if report['unstable']:
        blocks.append(rd.heading('Casos inestables'))
        blocks.append(rd.text('Pasan y fallan sin que nadie haya cambiado la prueba: candidatos a revisar.'))
        blocks.append(rd.table(['Caso', 'Ejec.', 'Cambios de estado', 'Éxito'],
            [[u['name'], u['runs'], u['flips'], f'{u["pass_rate"]}%'] for u in report['unstable']]))
    if report['slow']:
        blocks.append(rd.heading('Más lentos'))
        blocks.append(rd.table(['Caso', 'Promedio', 'Máximo', 'Ejec.'],
            [[s['name'], f'{s["avg_ms"]} ms', f'{s["max_ms"]} ms', s['runs']] for s in report['slow']]))
    o, s = report['observer'], report['schedules']
    blocks.append(rd.heading('Cambios en interfaces observadas'))
    if o['changes']:
        blocks.append(rd.bullet_list([f'{c["module"]}: {c["pending"]} cambio(s) pendiente(s)' +
                                      (f' · responsable: {c["owner"]}' if c['owner'] else '') + (f' ({c["company"]})' if c['company'] else '')
                                      for c in o['changes']]))
    else:
        blocks.append(rd.text(f'Sin cambios pendientes en {o["modules"]} componente(s) observados.'))
    blocks.append(rd.heading('Programaciones'))
    blocks.append(rd.text(f'{s["enabled"]} activa(s) de {s["total"]}; vencidas sin ejecutar: {s["overdue"]}; '
                          f'scheduler {"en marcha" if s["scheduler_running"] else "detenido"}.'))
    blocks.append(rd.text(f'Criterio del semáforo: verde con éxito ≥ {report["thresholds"]["green_at_least"]:.0f}% y sin fallos pendientes; '
                          f'rojo si algún flujo falla o el éxito baja de {report["thresholds"]["red_below"]:.0f}%; ámbar en el resto. '
                          f'Generado por Local Test Workspace · {FORMAT}.'))
    meta = f'Proyecto {report["project"]["name"]} · últimos {report["period"]["days"]} días · generado {_fmt(report["generated_at"])}'
    return rd.doc(report['title'], blocks, meta=meta)


def render_markdown(report):
    return report_render.render_markdown(_status_doc(report))


def render_html(report):
    return report_render.render_html(_status_doc(report))


def render_pdf(html_text, destination):
    """Alias de compatibilidad: la implementación real vive en report_render.render_pdf_from_html (motor de
    render único de toda la reportería), para que nadie que ya llame `reporting.render_pdf` deba cambiar."""
    from . import report_render
    return report_render.render_pdf_from_html(html_text, destination)


def render(report, kind):
    if kind == 'html':
        return render_html(report).encode('utf-8')
    if kind in ('md', 'markdown'):
        return render_markdown(report).encode('utf-8')
    if kind == 'json':
        return json.dumps(report, indent=2, ensure_ascii=False).encode('utf-8')
    raise ValueError('Formato no reconocido (html, md, json o pdf)')


# --------------------------------------------------------------------------- reporte de UNA Suite (suite_group)

FORMAT_SUITE_GROUP = 'ltw.suite_group_report/1'

# Reproduce exactamente el orden/contenido del antiguo _suite_group_doc fijo — quien exporta sin elegir
# plantilla (los botones por fila de suite_groups.py) no ve ningún cambio.
DEFAULT_SUITE_GROUP_TEMPLATE_BODY = [{'field': 'suite_status', 'label': 'Estado'}, {'field': 'suite_kpis', 'label': 'Indicadores'},
                                     {'field': 'suite_trend', 'label': 'Ejecuciones por día'}, {'field': 'suite_members', 'label': 'Miembros'}]


def _resolve_suite_group_report_field(field, data):
    if field == 'suite_status':
        return {'kind': 'badge', 'label': STATUS_ES.get(data['status'], 'Sin ejecutar'), 'color': STATUS_COLOR.get(data['status'], '#6b7280')}
    if field == 'suite_kpis':
        return {'kind': 'cards', 'items': [{'value': f'{data["success_rate"]}%' if data['success_rate'] is not None else '—', 'label': 'Tasa de éxito'},
                                           {'value': _arrow(data['delta']), 'label': 'vs. periodo anterior'},
                                           {'value': data['runs'], 'label': 'Ejecuciones'}]}
    if field == 'suite_trend':
        return {'kind': 'trend_svg', 'markup': trend_svg(data['trend']), 'caption': 'Verde: pasaron · Rojo: fallaron'}
    if field == 'suite_members':
        if not data['members']:
            return None
        return {'kind': 'table', 'columns': ['Miembro', 'Tipo', 'Estado'],
                'rows': [[m['name'], 'Flujo' if m['type'] == 'flow' else 'Caso', STATUS_ES.get(m['status'], 'Sin ejecutar')] for m in data['members']]}
    return None


def build_suite_group_report_data(group_id, days=14, now=None, template=None):
    """Agregado histórico de UNA Suite (suite_groups) — mismo espíritu que collect(), acotado a un grupo en
    vez de todo el proyecto. El estado de cada miembro es el de la ÚLTIMA corrida de ESTA Suite (sus propios
    item_runs), no el último run suelto de ese Flujo/Caso en cualquier otro lado — responde "¿qué pasó la
    última vez que se corrió ESTA Suite?", no el estado global del miembro."""
    group = core.get('suite_groups', group_id)
    if group is None:
        raise ValueError('Suite inexistente')
    now = now or dt.datetime.now(dt.timezone.utc)
    start, previous_start = now - dt.timedelta(days=days), now - dt.timedelta(days=2 * days)
    runs = [r for r in core.list_items('runs') if r.get('type') == 'suite_group' and r.get('group_id') == group_id]
    for r in runs:
        r['_t'] = _when(r.get('started_at'))
    runs = sorted((r for r in runs if r['_t']), key=lambda r: r['_t'])
    decisive = [r for r in runs if r['status'] in DECISIVE]
    period = [r for r in decisive if start <= r['_t'] <= now]
    previous = [r for r in decisive if previous_start <= r['_t'] < start]
    rate = _rate(sum(r['status'] == 'passed' for r in period), len(period))
    rate_prev = _rate(sum(r['status'] == 'passed' for r in previous), len(previous))
    last = decisive[-1] if decisive else None

    last_item_runs = {(it.get('type'), it.get('id')): it for it in (last or {}).get('item_runs', [])}
    members = []
    for m in group.get('members') or []:
        item = last_item_runs.get((m['type'], m['id']))
        record = core.get('suites' if m['type'] == 'flow' else 'cases', m['id']) or {}
        members.append({'type': m['type'], 'id': m['id'], 'name': (item or {}).get('name') or record.get('name', ''),
                        'status': item['status'] if item else 'never'})

    trend = []
    for offset in range(days - 1, -1, -1):
        day = _local_day(now) - dt.timedelta(days=offset)
        todays = [r for r in decisive if _local_day(r['_t']) == day]
        ok = sum(r['status'] == 'passed' for r in todays)
        trend.append({'day': day.isoformat(), 'runs': len(todays), 'passed': ok, 'failed': len(todays) - ok, 'success_rate': _pct(_rate(ok, len(todays)))})

    data = {'format': FORMAT_SUITE_GROUP, 'title': group.get('name', ''), 'group_id': group_id, 'generated_at': now.isoformat(),
            'period': {'days': days}, 'status': last['status'] if last else 'never', 'last_run': last['started_at'] if last else None,
            'runs': len(period), 'success_rate': _pct(rate), 'success_rate_previous': _pct(rate_prev),
            'delta': None if rate is None or rate_prev is None else round((rate - rate_prev) * 100, 1),
            'members': members, 'trend': trend}
    body = (template or {}).get('body') or DEFAULT_SUITE_GROUP_TEMPLATE_BODY
    data['template_name'] = (template or {}).get('name') or 'Suite (por defecto)'
    data['sections'] = rt._build_tree_sections(body, lambda f: _resolve_suite_group_report_field(f, data), None)
    return data


def _suite_group_doc(data):
    meta = f'Últimos {data["period"]["days"]} días · generado {_fmt(data["generated_at"])}'
    return rd.doc(data['title'], rt._sections_to_blocks(data['sections']), meta=meta)


def render_suite_group_html(data):
    return report_render.render_html(_suite_group_doc(data))


def render_suite_group_markdown(data):
    return report_render.render_markdown(_suite_group_doc(data))


def render_suite_group_docx(data):
    return report_render.render_docx(_suite_group_doc(data))


# --------------------------------------------------------------------------- reporte de UN Caso (Pruebas: API/UI)

FORMAT_CASE = 'ltw.case_report/1'

# Reproduce exactamente el orden/contenido del antiguo _case_doc fijo — quien exporta sin elegir plantilla
# (los botones por fila de cases.py) no ve ningún cambio.
DEFAULT_CASE_TEMPLATE_BODY = [{'field': 'case_status', 'label': 'Estado'}, {'field': 'case_target', 'label': 'Método y ruta'},
                              {'field': 'case_kpis', 'label': 'Indicadores'}, {'field': 'case_trend', 'label': 'Ejecuciones por día'},
                              {'field': 'case_recent_runs', 'label': 'Corridas recientes'}]


def _resolve_case_report_field(field, data):
    if field == 'case_status':
        return {'kind': 'badge', 'label': STATUS_ES.get(data['status'], 'Sin ejecutar'), 'color': STATUS_COLOR.get(data['status'], '#6b7280')}
    if field == 'case_target':
        return data['target'] or None
    if field == 'case_kpis':
        return {'kind': 'cards', 'items': [{'value': f'{data["success_rate"]}%' if data['success_rate'] is not None else '—', 'label': 'Tasa de éxito'},
                                           {'value': _arrow(data['delta']), 'label': 'vs. periodo anterior'},
                                           {'value': data['runs'], 'label': 'Ejecuciones'},
                                           {'value': f'{data["avg_duration_ms"]} ms' if data['avg_duration_ms'] is not None else '—', 'label': 'Respuesta media'}]}
    if field == 'case_trend':
        return {'kind': 'trend_svg', 'markup': trend_svg(data['trend']), 'caption': 'Verde: pasaron · Rojo: fallaron'}
    if field == 'case_recent_runs':
        if not data['recent']:
            return None
        return {'kind': 'table', 'columns': ['Inicio', 'Estado', 'Duración', 'Detalle'],
                'rows': [[_fmt(r['started_at']), STATUS_ES.get(r['status'], r['status']), f'{r["duration_ms"]} ms' if r['duration_ms'] is not None else '—', r['detail'][:160]]
                         for r in data['recent']]}
    return None


def build_case_report_data(case_id, days=14, now=None, template=None):
    """Agregado histórico de UN Caso (API o UI) — su historial de corridas propio, no una ejecución puntual
    (eso ya lo cubre evidence_report.py). Responde "¿cómo le ha ido a este Caso en el tiempo?"."""
    case = core.get('cases', case_id)
    if case is None:
        raise ValueError('Caso inexistente')
    now = now or dt.datetime.now(dt.timezone.utc)
    start, previous_start = now - dt.timedelta(days=days), now - dt.timedelta(days=2 * days)
    runs = [r for r in core.list_items('runs') if r.get('type') in ('api', 'ui') and r.get('case_id') == case_id]
    for r in runs:
        r['_t'] = _when(r.get('started_at'))
    runs = sorted((r for r in runs if r['_t']), key=lambda r: r['_t'])
    decisive = [r for r in runs if r['status'] in DECISIVE]
    period = [r for r in decisive if start <= r['_t'] <= now]
    previous = [r for r in decisive if previous_start <= r['_t'] < start]
    rate = _rate(sum(r['status'] == 'passed' for r in period), len(period))
    rate_prev = _rate(sum(r['status'] == 'passed' for r in previous), len(previous))
    last = decisive[-1] if decisive else None
    durations = [r['duration_ms'] for r in period if r.get('duration_ms')]

    recent = [{'started_at': r['started_at'], 'status': r['status'], 'duration_ms': r.get('duration_ms'),
              'detail': _failure_text(r) if r['status'] != 'passed' else ''} for r in decisive[-20:]]

    trend = []
    for offset in range(days - 1, -1, -1):
        day = _local_day(now) - dt.timedelta(days=offset)
        todays = [r for r in decisive if _local_day(r['_t']) == day]
        ok = sum(r['status'] == 'passed' for r in todays)
        trend.append({'day': day.isoformat(), 'runs': len(todays), 'passed': ok, 'failed': len(todays) - ok, 'success_rate': _pct(_rate(ok, len(todays)))})

    data = {'format': FORMAT_CASE, 'title': case.get('name', ''), 'case_id': case_id, 'case_type': case.get('type', 'api'),
            'target': f'{case.get("method", "")} {case.get("path", "")}'.strip() if case.get('type', 'api') == 'api' else '',
            'generated_at': now.isoformat(), 'period': {'days': days}, 'status': last['status'] if last else 'never',
            'last_run': last['started_at'] if last else None, 'runs': len(period),
            'success_rate': _pct(rate), 'success_rate_previous': _pct(rate_prev),
            'delta': None if rate is None or rate_prev is None else round((rate - rate_prev) * 100, 1),
            'avg_duration_ms': round(statistics.mean(durations)) if durations else None, 'recent': recent[::-1], 'trend': trend}
    body = (template or {}).get('body') or DEFAULT_CASE_TEMPLATE_BODY
    data['template_name'] = (template or {}).get('name') or 'Caso ejecutable (por defecto)'
    data['sections'] = rt._build_tree_sections(body, lambda f: _resolve_case_report_field(f, data), None)
    return data


def _case_doc(data):
    meta = f'Últimos {data["period"]["days"]} días · generado {_fmt(data["generated_at"])}'
    return rd.doc(data['title'], rt._sections_to_blocks(data['sections']), meta=meta)


def render_case_html(data):
    return report_render.render_html(_case_doc(data))


def render_case_markdown(data):
    return report_render.render_markdown(_case_doc(data))


def render_case_docx(data):
    return report_render.render_docx(_case_doc(data))


# --------------------------------------------------------------------------- command line

def cli(argv):
    """python run.py --status-report salida.html [--project NOMBRE] [--days N] [--notes TEXTO]   (extension decides: .html .md .json .pdf)"""
    args = list(argv)

    def take(flag, default=None):
        if flag in args:
            index = args.index(flag)
            value = args[index + 1] if index + 1 < len(args) else default
            del args[index:index + 2]
            return value
        return default
    destination, project_name, days, notes = take('--status-report'), take('--project'), take('--days', '14'), take('--notes', '')
    if not destination:
        print('Indica el archivo de salida: --status-report reporte.html', file=sys.stderr)
        return 2
    try:
        days = int(days)
        if not 1 <= days <= 365:
            raise ValueError
    except ValueError:
        print('--days debe ser un entero entre 1 y 365', file=sys.stderr)
        return 2
    project_id = None
    if project_name:
        match = next((p for p in core.list_items('projects') if p['name'].lower() == project_name.lower()), None)
        if match is None:
            print(f'No existe el proyecto «{project_name}». Disponibles: ' + ', '.join(p['name'] for p in core.list_items('projects')), file=sys.stderr)
            return 2
        project_id = match['id']
    report = collect(project_id, days, notes=notes or '')
    kind = Path(destination).suffix.lower().lstrip('.')
    if kind == 'pdf':
        render_pdf(render_html(report), destination)
    else:
        try:
            Path(destination).write_bytes(render(report, kind))
        except ValueError as exc:
            print(exc, file=sys.stderr)
            return 2
    print(f'{report["rag"]["label"]}: {report["headline"]}\nReporte: {destination}')
    return {'green': 0, 'grey': 0, 'amber': 1, 'red': 1}[report['rag']['level']]
