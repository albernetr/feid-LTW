"""Evidencia descargable de una corrida (api/ui/suite/suite_group), paso a paso: misma estructura normalizada para
HTML, PDF (reusa reporting.render_pdf) y Word. Ninguno de los tres intenta igualar el diseño del Resumen ejecutivo
— esto es evidencia de QUÉ pasó en una corrida puntual, no un tablero de salud del proyecto."""
import html
import io
import json
from . import core, automation, reporting

FORMAT = 'ltw.evidence/1'
STATUS_ES = {'passed': 'Pasó', 'failed': 'Falló', 'error': 'Error', 'cancelled': 'Cancelada', 'skipped': 'Omitido'}
STATUS_COLOR = {'passed': '#16a34a', 'failed': '#dc2626', 'error': '#d97706', 'cancelled': '#9ca3af', 'skipped': '#9ca3af'}


def _assertion_label(rule):
    spec = core.ASSERTION_TYPES.get(rule.get('type'), {})
    detail = ' '.join(str(rule[k]) for k in ('path', 'name', 'expected') if rule.get(k) not in (None, ''))
    return f'{spec.get("label", rule.get("type"))} {detail}'.strip()


def _step_from_run(run, name=None):
    """Un paso 'de hoja': una corrida real tipo api o ui, con toda su petición/respuesta/aserciones."""
    step = {'name': name or run.get('case_name') or '', 'type': run.get('type'), 'status': run.get('status'),
            'duration_ms': run.get('duration_ms'), 'error': run.get('error')}
    if run.get('type') == 'api':
        req, resp = run.get('request') or {}, run.get('response') or {}
        step['request'] = {'method': req.get('method'), 'url': req.get('url'), 'headers': req.get('headers') or {},
                            'query': req.get('query') or {}, 'body': req.get('body')}
        step['http_status'] = run.get('http_status')
        step['response'] = {'body': resp.get('body', '')}
        step['assertions'] = [{'label': _assertion_label(a.get('rule', {})), 'passed': a.get('passed', False), 'actual': a.get('actual')}
                               for a in run.get('assertions', [])]
    elif run.get('type') == 'ui':
        step['ui_steps'] = [{'label': automation.STEP_ACTIONS.get(s['action'], {}).get('label', s['action']), 'passed': s.get('passed', False)}
                             for s in run.get('steps', [])]
        step['screenshot'] = run.get('screenshot')
    return step


def _step_from_case_entry(entry):
    """Un paso de un Flujo (`case_runs`): resuelve la corrida real si existe (no la hay para 'skipped'/'cancelled')."""
    sub = core.get('runs', entry['run_id']) if entry.get('run_id') else None
    step = _step_from_run(sub, name=entry.get('case_name') or entry.get('alias')) if sub else \
        {'name': entry.get('case_name') or entry.get('alias') or (entry.get('case_id') or '')[:8], 'type': 'api', 'error': entry.get('error')}
    step['status'] = entry['status']   # el estado del paso manda (p. ej. 'skipped' aunque hubiera una corrida vieja)
    return step


def _step_from_item_entry(entry):
    """Un miembro de una Suite (`item_runs`): un Caso suelto es una hoja; un Flujo trae sus propios sub-pasos."""
    sub = core.get('runs', entry['run_id']) if entry.get('run_id') else None
    if sub is None:
        return {'name': entry.get('name') or (entry.get('id') or '')[:8], 'type': entry.get('type'), 'status': entry['status'], 'error': entry.get('error')}
    if entry['type'] == 'flow':
        nested = build_report_data(sub)
        return {'name': entry.get('name') or sub.get('suite_name'), 'type': 'flow', 'status': entry['status'], 'substeps': nested['steps']}
    step = _step_from_run(sub, name=entry.get('name'))
    step['status'] = entry['status']
    return step


def build_report_data(run):
    """Normaliza un doc de `runs` (api/ui/suite/suite_group) a una estructura uniforme para los tres formatos."""
    kind = run.get('type')
    if kind == 'suite':
        steps = [_step_from_case_entry(e) for e in run.get('case_runs', [])]
    elif kind == 'suite_group':
        steps = [_step_from_item_entry(e) for e in run.get('item_runs', [])]
    else:
        steps = [_step_from_run(run)]
    passed = sum(1 for s in steps if s['status'] == 'passed')
    failed = sum(1 for s in steps if s['status'] in ('failed', 'error'))
    skipped = sum(1 for s in steps if s['status'] in ('skipped', 'cancelled'))
    title = run.get('case_name') or run.get('suite_name') or run.get('group_name') or 'Ejecución'
    return {'format': FORMAT, 'title': title, 'run_id': run.get('id'), 'run_type': kind, 'status': run.get('status'),
            'started_at': run.get('started_at'), 'finished_at': run.get('finished_at'), 'generated_at': core.now(),
            'summary': {'total': len(steps), 'passed': passed, 'failed': failed, 'skipped': skipped}, 'steps': steps}


def build_multi_report_data(title, runs):
    """Misma estructura que build_report_data, para una lista de corridas sueltas elegidas a mano (p. ej. los
    turnos de una conversación de Chat que el agente nunca persiste en Historial: persist=False). A diferencia de
    una Suite, acá no hay un doc de `runs` que las agrupe — cada una ya es un run_doc completo (petición,
    respuesta, aserciones) tal como lo arma core.execute_api."""
    steps = [_step_from_run(r) for r in runs]
    passed = sum(1 for s in steps if s['status'] == 'passed')
    failed = sum(1 for s in steps if s['status'] in ('failed', 'error'))
    skipped = sum(1 for s in steps if s['status'] in ('skipped', 'cancelled'))
    return {'format': FORMAT, 'title': title, 'run_id': None, 'run_type': 'conversation',
            'status': 'passed' if failed == 0 else 'failed',
            'started_at': runs[0].get('started_at') if runs else None, 'finished_at': runs[-1].get('finished_at') if runs else None,
            'generated_at': core.now(), 'summary': {'total': len(steps), 'passed': passed, 'failed': failed, 'skipped': skipped}, 'steps': steps}


# --------------------------------------------------------------------------- HTML / PDF

HTML_CSS = '''
:root{color-scheme:light}*{box-sizing:border-box}body{font-family:Segoe UI,Calibri,Arial,sans-serif;color:#111827;margin:0;background:#f3f4f6}
main{max-width:900px;margin:0 auto;padding:24px 20px 48px}h1{font-size:22px;margin:0 0 4px}.meta{color:#6b7280;font-size:13px;margin-bottom:12px}
.pill{display:inline-block;padding:2px 10px;border-radius:10px;color:#fff;font-size:12px;font-weight:600}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin:14px 0}
.card{background:#fff;border-radius:8px;padding:10px 14px;border:1px solid #e5e7eb}.card .v{font-size:22px;font-weight:700}.card .l{font-size:12px;color:#6b7280}
.step{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:12px 14px;margin:10px 0}
.step .head{display:flex;align-items:center;gap:8px;font-weight:600}.sub{margin-left:18px;border-left:2px solid #e5e7eb;padding-left:14px}
pre{background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:8px 10px;font-size:12px;overflow:auto;white-space:pre-wrap;word-break:break-word}
.assert{display:flex;gap:6px;align-items:flex-start;font-size:13px;margin:2px 0}.ok{color:#16a34a}.bad{color:#dc2626}
.err{color:#991b1b;background:#fef2f2;border:1px solid #fecaca;border-radius:6px;padding:6px 10px;font-size:13px;white-space:pre-wrap}
@media print{body{background:#fff}main{padding:0}.step{break-inside:avoid}}
'''


def _render_step_html(step, depth=0):
    e = html.escape
    pill = f'<span class="pill" style="background:{STATUS_COLOR.get(step["status"], "#6b7280")}">{e(STATUS_ES.get(step["status"], step["status"]))}</span>'
    extra = f' · {step["duration_ms"]} ms' if step.get('duration_ms') is not None else ''
    parts = [f'<div class="head">{pill}<span>{e(step.get("name", ""))}</span><span class="meta">{extra}</span></div>']
    if step.get('error'):
        parts.append(f'<div class="err">{e(step["error"])}</div>')
    if 'request' in step:
        req = step['request']
        parts.append(f'<div class="meta">{e(req.get("method") or "")} {e(req.get("url") or "")}' + (f' · HTTP {step["http_status"]}' if step.get('http_status') else '') + '</div>')
        if req.get('query'):
            parts.append(f'<div class="meta">Query:</div><pre>{e(json.dumps(req["query"], indent=2, ensure_ascii=False))}</pre>')
        if req.get('body') is not None:
            body_text = req['body'] if isinstance(req['body'], str) else json.dumps(req['body'], indent=2, ensure_ascii=False)
            parts.append(f'<div class="meta">Body enviado:</div><pre>{e(body_text)}</pre>')
        if step.get('response', {}).get('body'):
            parts.append(f'<div class="meta">Respuesta:</div><pre>{e(step["response"]["body"][:4000])}</pre>')
        for a in step.get('assertions', []):
            icon = '✓' if a['passed'] else '✗'
            parts.append(f'<div class="assert {"ok" if a["passed"] else "bad"}">{icon} {e(a["label"])}' + ('' if a['passed'] else f' → {e(str(a.get("actual"))[:300])}') + '</div>')
    if step.get('ui_steps'):
        for u in step['ui_steps']:
            parts.append(f'<div class="assert {"ok" if u["passed"] else "bad"}">{"✓" if u["passed"] else "✗"} {e(u["label"])}</div>')
    if step.get('screenshot'):
        parts.append(f'<div class="meta">Captura: {e(step["screenshot"])}</div>')
    body = f'<div class="step">{"".join(parts)}</div>'
    if step.get('substeps'):
        body += '<div class="sub">' + ''.join(_render_step_html(s, depth + 1) for s in step['substeps']) + '</div>'
    return body


def render_evidence_html(data):
    e = html.escape
    s = data['summary']
    card = lambda value, label: f'<div class="card"><div class="v">{value}</div><div class="l">{e(label)}</div></div>'   # noqa: E731
    body = [f'<h1>{e(data["title"])}</h1>',
            f'<div class="meta">Corrida {e(data.get("run_id") or "")} · generada {e(data["generated_at"])}'
            + (f' · inicio {e(data["started_at"])}' if data.get('started_at') else '') + '</div>',
            f'<span class="pill" style="background:{STATUS_COLOR.get(data["status"], "#6b7280")}">{e(STATUS_ES.get(data["status"], data["status"] or ""))}</span>',
            f'<div class="cards">{card(s["total"], "Pasos")}{card(s["passed"], "Pasaron")}{card(s["failed"], "Fallaron")}{card(s["skipped"], "Omitidos")}</div>']
    body += [_render_step_html(step) for step in data['steps']]
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(data["title"])}</title><style>{HTML_CSS}</style></head><body><main>{"".join(body)}</main></body></html>')


def render_evidence_pdf(html_text, destination):
    return reporting.render_pdf(html_text, destination)


# --------------------------------------------------------------------------- Markdown

def _step_markdown(step, level=2):
    status = STATUS_ES.get(step['status'], step['status'] or '')
    lines = [f'{"#" * min(level, 6)} {step.get("name", "")} — {status}', '']
    if step.get('duration_ms') is not None:
        lines.append(f'*{step["duration_ms"]} ms*')
    if step.get('error'):
        lines.append(f'> Error: {step["error"]}')
    if 'request' in step:
        req = step['request']
        line = f'`{req.get("method") or ""} {req.get("url") or ""}`' + (f' · HTTP {step["http_status"]}' if step.get('http_status') else '')
        lines.append(line)
        if req.get('body') is not None:
            body_text = req['body'] if isinstance(req['body'], str) else json.dumps(req['body'], indent=2, ensure_ascii=False)
            lines += ['', 'Body enviado:', '```json', body_text, '```']
        if step.get('response', {}).get('body'):
            lines += ['', 'Respuesta:', '```json', step['response']['body'][:4000], '```']
        lines.append('')
        for a in step.get('assertions', []):
            lines.append(('- ✓ ' if a['passed'] else '- ✗ ') + a['label'] + ('' if a['passed'] else f' → {str(a.get("actual"))[:300]}'))
    for u in step.get('ui_steps', []):
        lines.append(('- ✓ ' if u['passed'] else '- ✗ ') + u['label'])
    lines.append('')
    for sub in step.get('substeps', []):
        lines += _step_markdown(sub, level + 1)
    return lines


def render_evidence_markdown(data):
    status = STATUS_ES.get(data['status'], data['status'] or '')
    s = data['summary']
    lines = [f'# {data["title"]}', '', f'Estado: **{status}** · Generado: {data["generated_at"]}', '',
             f'{s["passed"]} de {s["total"]} pasos pasaron ({s["failed"]} fallaron, {s["skipped"]} omitidos)', '']
    for step in data['steps']:
        lines += _step_markdown(step)
    return '\n'.join(lines) + '\n'


# --------------------------------------------------------------------------- Word

def _write_step_docx(doc, step, level=2):
    from docx.shared import Pt
    doc.add_heading(f'{step.get("name", "")} — {STATUS_ES.get(step["status"], step["status"])}', level=min(level, 4))
    if step.get('duration_ms') is not None:
        doc.add_paragraph(f'{step["duration_ms"]} ms')
    if step.get('error'):
        doc.add_paragraph(f'Error: {step["error"]}')
    if 'request' in step:
        req = step['request']
        line = f'{req.get("method") or ""} {req.get("url") or ""}' + (f' · HTTP {step["http_status"]}' if step.get('http_status') else '')
        doc.add_paragraph(line)
        if req.get('body') is not None:
            body_text = req['body'] if isinstance(req['body'], str) else json.dumps(req['body'], indent=2, ensure_ascii=False)
            p = doc.add_paragraph(body_text)
            for run_ in p.runs:
                run_.font.name = 'Consolas'
                run_.font.size = Pt(9)
        if step.get('response', {}).get('body'):
            p = doc.add_paragraph(step['response']['body'][:4000])
            for run_ in p.runs:
                run_.font.name = 'Consolas'
                run_.font.size = Pt(9)
        for a in step.get('assertions', []):
            doc.add_paragraph(('✓ ' if a['passed'] else '✗ ') + a['label'])
    for u in step.get('ui_steps', []):
        doc.add_paragraph(('✓ ' if u['passed'] else '✗ ') + u['label'])
    for sub in step.get('substeps', []):
        _write_step_docx(doc, sub, level=level + 1)


def render_evidence_docx(data):
    """Mismo contenido que el HTML/PDF, en formato simple (sin buscar igualar el diseño del PDF)."""
    from docx import Document
    doc = Document()
    doc.add_heading(data['title'], level=1)
    doc.add_paragraph(f'Estado: {STATUS_ES.get(data["status"], data["status"] or "")} · Generado: {data["generated_at"]}')
    s = data['summary']
    doc.add_paragraph(f'{s["passed"]} de {s["total"]} pasos pasaron ({s["failed"]} fallaron, {s["skipped"]} omitidos)')
    for step in data['steps']:
        _write_step_docx(doc, step)
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
