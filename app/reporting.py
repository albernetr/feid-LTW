"""Executive view and status report: what is healthy, what changed, what is failing and since when. Pure functions over the run history,
so the screen, the exported files and the command line all say exactly the same thing."""
import datetime as dt
import html
import json
import statistics
import sys
from pathlib import Path
from . import core, observer

FORMAT = 'ltw.status/1'
RANGES = (7, 14, 30, 90)
GREEN_RATE, AMBER_RATE = 0.95, 0.80
DECISIVE = ('passed', 'failed', 'error')                      # cancelled / skipped say nothing about health
RAG = {'green': 'VERDE', 'amber': 'ÁMBAR', 'red': 'ROJO', 'grey': 'SIN DATOS'}
RAG_COLOR = {'green': '#16a34a', 'amber': '#d97706', 'red': '#dc2626', 'grey': '#6b7280'}
STATUS_ES = {'passed': 'Pasó', 'failed': 'Falló', 'error': 'Error', 'cancelled': 'Cancelada', 'skipped': 'Omitido'}
STATUS_COLOR = {'passed': '#16a34a', 'failed': '#dc2626', 'error': '#d97706', 'cancelled': '#9ca3af', 'skipped': '#9ca3af'}


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
            'avg_response_ms': round(statistics.mean(all_durations)) if all_durations else None}
    level, reasons = _traffic_light(kpis, drift, overdue, enabled, scheduler_on)
    report = {'format': FORMAT, 'title': title or 'Reporte de estatus de pruebas', 'generated_at': now.isoformat(), 'notes': notes,
              'tool': {'name': 'local-test-workspace'}, 'project': {'id': project_id, 'name': project['name'] if project else 'Todos los proyectos'},
              'period': {'days': days, 'from': start.isoformat(), 'to': now.isoformat()}, 'rag': {'level': level, 'label': RAG[level], 'reasons': reasons},
              'kpis': kpis, 'trend': trend, 'suites': suite_rows, 'failing': failing, 'unstable': unstable[:8], 'slow': slow,
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
    if rate is not None and rate < AMBER_RATE * 100:
        worsen('red', f'La tasa de éxito del periodo es {rate}% (mínimo aceptable {int(AMBER_RATE * 100)}%).')
    elif rate is not None and rate < GREEN_RATE * 100:
        worsen('amber', f'La tasa de éxito del periodo es {rate}% (objetivo {int(GREEN_RATE * 100)}%).')
    failing = cases['failed'] + cases['error']
    if failing:
        worsen('amber', f'{failing} caso(s) fallan en su última ejecución.')
    if drift:
        worsen('amber', f'{sum(m["drift"] for m in drift)} cambio(s) sin aviso detectados en {len(drift)} módulo(s) observados.')
    if overdue:
        worsen('amber', f'{len(overdue)} programación(es) vencidas sin ejecutarse' + ('' if scheduler_on else ' (el scheduler está detenido).'))
    if kpis['suites_never_run']:
        reasons.append(f'{kpis["suites_never_run"]} flujo(s) nunca se han ejecutado (informativo).')
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


def render_markdown(report):
    k = report['kpis']
    lines = [f'# {report["title"]}', '', f'**Proyecto:** {report["project"]["name"]} · **Periodo:** últimos {report["period"]["days"]} días · **Generado:** {_fmt(report["generated_at"])}', '',
             f'## Estado general: {report["rag"]["label"]}', '', report['headline'], '']
    lines += [f'- {r}' for r in report['rag']['reasons']] + ['']
    if report.get('notes'):
        lines += ['## Comentarios', '', report['notes'], '']
    lines += ['## Indicadores', '', '| Indicador | Valor |', '|---|---|',
              f'| Tasa de éxito | {k["success_rate"] if k["success_rate"] is not None else "—"}% ({_arrow(k["delta"])} vs. periodo anterior) |',
              f'| Ejecuciones en el periodo | {k["executions"]} (anterior: {k["executions_previous"]}) |',
              f'| Flujos sanos | {k["suites_healthy"]} de {k["suites_total"]} |',
              f'| Casos: pasan / fallan / error / sin ejecutar | {k["cases"]["passed"]} / {k["cases"]["failed"]} / {k["cases"]["error"]} / {k["cases"]["never"]} (de {k["cases"]["total"]}) |',
              f'| Tiempo medio de respuesta | {k["avg_response_ms"] if k["avg_response_ms"] is not None else "—"} ms |', '']
    if report['suites']:
        lines += ['## Flujos', '', '| Flujo | Último estado | Última ejecución | Ejecuciones | Éxito | Cambio |', '|---|---|---|---|---|---|']
        for s in report['suites']:
            lines.append(f'| {s["name"]} | {STATUS_ES.get(s["status"], "Sin ejecutar")} | {_fmt(s["last_run"])} | {s["runs"]} | '
                         f'{s["success_rate"] if s["success_rate"] is not None else "—"}% | {_arrow(s["delta"])} |')
        lines.append('')
    if report['failing']:
        lines += ['## Qué está fallando', '', '| Caso | Desde | Seguidas | Detalle |', '|---|---|---|---|']
        for f in report['failing']:
            lines.append(f'| {f["name"]} ({f["target"]}) | {_fmt(f["since"])} | {f["consecutive_failures"]} | {f["detail"][:140].replace("|", "/")} |')
        lines.append('')
    if report['unstable']:
        lines += ['## Casos inestables (pasan y fallan sin cambios)', '', '| Caso | Ejecuciones | Cambios de estado | Éxito |', '|---|---|---|---|']
        lines += [f'| {u["name"]} | {u["runs"]} | {u["flips"]} | {u["pass_rate"]}% |' for u in report['unstable']] + ['']
    if report['slow']:
        lines += ['## Más lentos', '', '| Caso | Promedio | Máximo | Ejecuciones |', '|---|---|---|---|']
        lines += [f'| {s["name"]} | {s["avg_ms"]} ms | {s["max_ms"]} ms | {s["runs"]} |' for s in report['slow']] + ['']
    o = report['observer']
    lines += ['## Cambios en interfaces observadas', '']
    lines += ([f'- **{c["module"]}**: {c["pending"]} cambio(s) pendiente(s)' + (f' · responsable: {c["owner"]}' if c['owner'] else '') + (f' ({c["company"]})' if c['company'] else '') for c in o['changes']]
              or [f'Sin cambios pendientes en {o["modules"]} módulo(s) observados.'])
    s = report['schedules']
    lines += ['', '## Programaciones', '', f'{s["enabled"]} activa(s) de {s["total"]}; vencidas sin ejecutar: {s["overdue"]}; scheduler {"en marcha" if s["scheduler_running"] else "detenido"}.', '',
              f'_Criterio del semáforo: verde con éxito ≥ {report["thresholds"]["green_at_least"]:.0f}% y sin fallos pendientes; rojo si algún flujo falla o el éxito baja de {report["thresholds"]["red_below"]:.0f}%; ámbar en el resto._']
    return '\n'.join(lines) + '\n'


HTML_CSS = '''
:root{color-scheme:light}*{box-sizing:border-box}body{font-family:Segoe UI,Calibri,Arial,sans-serif;color:#111827;margin:0;background:#f3f4f6}
main{max-width:980px;margin:0 auto;padding:24px 20px 48px}h1{font-size:24px;margin:0 0 2px}h2{font-size:16px;margin:26px 0 8px;border-bottom:1px solid #e5e7eb;padding-bottom:4px}
.meta{color:#6b7280;font-size:13px}.banner{border-radius:10px;padding:16px 20px;color:#fff;margin:16px 0}.banner b{font-size:22px;letter-spacing:.5px}
.banner ul{margin:8px 0 0 18px;padding:0}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}.card{background:#fff;border-radius:8px;padding:12px 14px;border:1px solid #e5e7eb}
.card .v{font-size:26px;font-weight:700}.card .l{font-size:12px;color:#6b7280}table{width:100%;border-collapse:collapse;background:#fff;font-size:13px}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #e5e7eb;vertical-align:top}th{background:#f9fafb;color:#374151}.pill{display:inline-block;padding:1px 8px;border-radius:10px;color:#fff;font-size:12px}
.up{color:#16a34a}.down{color:#dc2626}.notes{background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:10px 14px;white-space:pre-wrap}.foot{color:#6b7280;font-size:12px;margin-top:24px}
@media print{body{background:#fff}main{padding:0}.card,table{break-inside:avoid}h2{break-after:avoid}}
'''


def render_html(report):
    e = html.escape
    k = report['kpis']

    def pill(status):
        return f'<span class="pill" style="background:{STATUS_COLOR.get(status, "#6b7280")}">{e(STATUS_ES.get(status, "Sin ejecutar"))}</span>'

    def delta(value):
        return f'<span class="{"up" if value and value > 0 else "down" if value and value < 0 else ""}">{e(_arrow(value))}</span>'
    card = lambda value, label: f'<div class="card"><div class="v">{value}</div><div class="l">{e(label)}</div></div>'     # noqa: E731
    body = [f'<h1>{e(report["title"])}</h1><div class="meta">Proyecto <b>{e(report["project"]["name"])}</b> · últimos {report["period"]["days"]} días · generado {e(_fmt(report["generated_at"]))}</div>',
            f'<div class="banner" style="background:{RAG_COLOR[report["rag"]["level"]]}"><b>{e(report["rag"]["label"])}</b><div>{e(report["headline"])}</div>'
            f'<ul>{"".join(f"<li>{e(r)}</li>" for r in report["rag"]["reasons"])}</ul></div>']
    if report.get('notes'):
        body.append(f'<h2>Comentarios</h2><div class="notes">{e(report["notes"])}</div>')
    c = k['cases']
    body.append('<div class="cards">' + card(f'{k["success_rate"] if k["success_rate"] is not None else "—"}%', 'Tasa de éxito') +
                card(delta(k['delta']), 'vs. periodo anterior') + card(f'{k["suites_healthy"]}/{k["suites_total"]}', 'Flujos sanos') +
                card(c['failed'] + c['error'], 'Casos fallando') + card(c['never'], 'Casos sin ejecutar') + card(k['executions'], 'Ejecuciones') +
                card(f'{k["avg_response_ms"]} ms' if k['avg_response_ms'] is not None else '—', 'Respuesta media') + '</div>')
    body.append(f'<h2>Ejecuciones por día</h2>{trend_svg(report["trend"])}<div class="meta">Verde: pasaron · Rojo: fallaron</div>')
    if report['suites']:
        rows = ''.join(f'<tr><td>{e(s["name"])}</td><td>{pill(s["status"])}</td><td>{e(_fmt(s["last_run"]))}</td><td>{s["runs"]}</td>'
                       f'<td>{"—" if s["success_rate"] is None else str(s["success_rate"]) + "%"}</td><td>{delta(s["delta"])}</td><td>{spark_svg(s["spark"])}</td></tr>' for s in report['suites'])
        body.append(f'<h2>Flujos</h2><table><tr><th>Flujo</th><th>Último estado</th><th>Última ejecución</th><th>Ejec.</th><th>Éxito</th><th>Cambio</th><th>Recientes</th></tr>{rows}</table>')
    if report['failing']:
        rows = ''.join(f'<tr><td>{e(f["name"])}<div class="meta">{e(f["target"])}</div></td><td>{e(_fmt(f["since"]))}</td><td>{f["consecutive_failures"]}</td>'
                       f'<td>{e(f["detail"][:200])}</td></tr>' for f in report['failing'])
        body.append(f'<h2>Qué está fallando</h2><table><tr><th>Caso</th><th>Falla desde</th><th>Seguidas</th><th>Detalle</th></tr>{rows}</table>')
    if report['unstable']:
        rows = ''.join(f'<tr><td>{e(u["name"])}</td><td>{u["runs"]}</td><td>{u["flips"]}</td><td>{u["pass_rate"]}%</td></tr>' for u in report['unstable'])
        body.append(f'<h2>Casos inestables</h2><div class="meta">Pasan y fallan sin que nadie haya cambiado la prueba: candidatos a revisar.</div><table><tr><th>Caso</th><th>Ejec.</th><th>Cambios de estado</th><th>Éxito</th></tr>{rows}</table>')
    if report['slow']:
        rows = ''.join(f'<tr><td>{e(s["name"])}</td><td>{s["avg_ms"]} ms</td><td>{s["max_ms"]} ms</td><td>{s["runs"]}</td></tr>' for s in report['slow'])
        body.append(f'<h2>Más lentos</h2><table><tr><th>Caso</th><th>Promedio</th><th>Máximo</th><th>Ejec.</th></tr>{rows}</table>')
    o, s = report['observer'], report['schedules']
    changes = ''.join(f'<li><b>{e(m["module"])}</b>: {m["pending"]} cambio(s) pendiente(s)' + (f' · responsable: {e(m["owner"])}' if m['owner'] else '') +
                      (f' ({e(m["company"])})' if m['company'] else '') + '</li>' for m in o['changes'])
    body.append(f'<h2>Cambios en interfaces observadas</h2>' + (f'<ul>{changes}</ul>' if changes else f'<div>Sin cambios pendientes en {o["modules"]} módulo(s) observados.</div>'))
    body.append(f'<h2>Programaciones</h2><div>{s["enabled"]} activa(s) de {s["total"]}; vencidas sin ejecutar: {s["overdue"]}; scheduler {"en marcha" if s["scheduler_running"] else "detenido"}.</div>')
    body.append(f'<div class="foot">Criterio del semáforo: verde con éxito ≥ {report["thresholds"]["green_at_least"]:.0f}% y sin fallos pendientes; rojo si algún flujo falla o el éxito baja de '
                f'{report["thresholds"]["red_below"]:.0f}%; ámbar en el resto. Generado por Local Test Workspace · {e(FORMAT)}.</div>')
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(report["title"])}</title>'
            f'<style>{HTML_CSS}</style></head><body><main>{"".join(body)}</main></body></html>')


def render_pdf(html_text, destination):
    """Chromium (already required by the UI cases) prints the HTML report."""
    from playwright.sync_api import sync_playwright
    destination = Path(destination)
    source = destination.with_suffix('.tmp.html')
    source.write_text(html_text, encoding='utf-8')
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(source.as_uri(), wait_until='load')
            page.emulate_media(media='print')
            page.pdf(path=str(destination), format='A4', print_background=True, margin={'top': '14mm', 'bottom': '14mm', 'left': '12mm', 'right': '12mm'})
            browser.close()
    finally:
        source.unlink(missing_ok=True)
    return destination


def render(report, kind):
    if kind == 'html':
        return render_html(report).encode('utf-8')
    if kind in ('md', 'markdown'):
        return render_markdown(report).encode('utf-8')
    if kind == 'json':
        return json.dumps(report, indent=2, ensure_ascii=False).encode('utf-8')
    raise ValueError('Formato no reconocido (html, md, json o pdf)')


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
