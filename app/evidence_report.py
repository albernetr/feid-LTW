"""Evidencia descargable de una corrida (api/ui/suite/suite_group), paso a paso: misma estructura normalizada para
HTML, PDF (reusa reporting.render_pdf) y Word. Ninguno de los tres intenta igualar el diseño del Resumen ejecutivo
— esto es evidencia de QUÉ pasó en una corrida puntual, no un tablero de salud del proyecto."""
import json
from . import core, automation, reporting, report_doc as rd, report_render, report_tree as rt

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


# Reproduce exactamente el orden del antiguo _to_doc fijo — quien exporta sin elegir plantilla (los botones
# de evidencia en common.py/chat_page.py) no ve ningún cambio.
DEFAULT_EVIDENCE_TEMPLATE_BODY = [{'field': 'evidence_verdict', 'label': 'Veredicto del modelo'}, {'field': 'evidence_status', 'label': 'Estado'},
                                  {'field': 'evidence_summary', 'label': 'Resumen'}, {'field': 'evidence_steps', 'label': 'Pasos'}]


def _resolve_evidence_report_field(field, data):
    if field == 'evidence_verdict':
        verdict = data.get('llm_verdict')
        return {'kind': 'blocks', 'items': [_verdict_block(verdict)]} if verdict else None
    if field == 'evidence_status':
        return {'kind': 'badge', 'label': STATUS_ES.get(data['status'], data['status'] or ''), 'color': STATUS_COLOR.get(data['status'], '#6b7280')}
    if field == 'evidence_summary':
        s = data['summary']
        return {'kind': 'cards', 'items': [{'value': s['total'], 'label': 'Pasos'}, {'value': s['passed'], 'label': 'Pasaron'},
                                           {'value': s['failed'], 'label': 'Fallaron'}, {'value': s['skipped'], 'label': 'Omitidos'}]}
    if field == 'evidence_steps':
        return {'kind': 'blocks', 'items': [_step_to_block(step) for step in data['steps']]} if data['steps'] else None
    return None


def _with_evidence_sections(data, template):
    body = (template or {}).get('body') or DEFAULT_EVIDENCE_TEMPLATE_BODY
    data['template_name'] = (template or {}).get('name') or 'Evidencia (por defecto)'
    data['sections'] = rt._build_tree_sections(body, lambda f: _resolve_evidence_report_field(f, data), None)
    return data


def build_report_data(run, llm_verdict=None, template=None):
    """Normaliza un doc de `runs` (api/ui/suite/suite_group) a una estructura uniforme para los tres formatos.
    `llm_verdict` ({'pass': bool, 'reasoning': str}, ver llm.judge_conversation) es opcional y, si se da, los
    renderers lo muestran arriba de todo — nadie lo calcula acá, es responsabilidad del caller pedirlo antes."""
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
    data = {'format': FORMAT, 'title': title, 'run_id': run.get('id'), 'run_type': kind, 'status': run.get('status'),
            'started_at': run.get('started_at'), 'finished_at': run.get('finished_at'), 'generated_at': core.now(),
            'summary': {'total': len(steps), 'passed': passed, 'failed': failed, 'skipped': skipped}, 'steps': steps,
            'llm_verdict': llm_verdict}
    return _with_evidence_sections(data, template)


def build_multi_report_data(title, runs, llm_verdict=None, template=None):
    """Misma estructura que build_report_data, para una lista de corridas sueltas elegidas a mano (p. ej. los
    turnos de una conversación de Chat que el agente nunca persiste en Historial: persist=False). A diferencia de
    una Suite, acá no hay un doc de `runs` que las agrupe — cada una ya es un run_doc completo (petición,
    respuesta, aserciones) tal como lo arma core.execute_api."""
    steps = [_step_from_run(r) for r in runs]
    passed = sum(1 for s in steps if s['status'] == 'passed')
    failed = sum(1 for s in steps if s['status'] in ('failed', 'error'))
    skipped = sum(1 for s in steps if s['status'] in ('skipped', 'cancelled'))
    data = {'format': FORMAT, 'title': title, 'run_id': None, 'run_type': 'conversation',
            'status': 'passed' if failed == 0 else 'failed',
            'started_at': runs[0].get('started_at') if runs else None, 'finished_at': runs[-1].get('finished_at') if runs else None,
            'generated_at': core.now(), 'summary': {'total': len(steps), 'passed': passed, 'failed': failed, 'skipped': skipped}, 'steps': steps,
            'llm_verdict': llm_verdict}
    return _with_evidence_sections(data, template)


# --------------------------------------------------------------------------- doc (ver report_doc.py / report_render.py)

def _step_to_block(step, depth=0):
    children = [rd.heading(step.get('name') or 'Paso', level=2 + depth),
                rd.badge(STATUS_ES.get(step['status'], step['status']), STATUS_COLOR.get(step['status'], '#6b7280'))]
    if step.get('duration_ms') is not None:
        children.append(rd.text(f'{step["duration_ms"]} ms'))
    if step.get('error'):
        children.append(rd.text(f'Error: {step["error"]}'))
    if 'request' in step:
        req = step['request']
        children.append(rd.text(f'{req.get("method") or ""} {req.get("url") or ""}' + (f' · HTTP {step["http_status"]}' if step.get('http_status') else '')))
        if req.get('query'):
            children += [rd.text('Query:'), rd.code(json.dumps(req['query'], indent=2, ensure_ascii=False), 'json')]
        if req.get('body') is not None:
            body_text = req['body'] if isinstance(req['body'], str) else json.dumps(req['body'], indent=2, ensure_ascii=False)
            children += [rd.text('Body enviado:'), rd.code(body_text, 'json')]
        if step.get('response', {}).get('body'):
            children += [rd.text('Respuesta:'), rd.code(step['response']['body'][:4000], 'json')]
        if step.get('assertions'):
            children.append(rd.checks([{'label': a['label'], 'ok': a['passed'], 'detail': a.get('actual')} for a in step['assertions']]))
    if step.get('ui_steps'):
        children.append(rd.checks([{'label': u['label'], 'ok': u['passed']} for u in step['ui_steps']]))
    if step.get('screenshot'):
        children.append(rd.text(f'Captura: {step["screenshot"]}'))
    if step.get('substeps'):
        children.append(rd.group([_step_to_block(s, depth + 1) for s in step['substeps']], indent=True))
    return rd.group(children)


def _verdict_block(verdict):
    title = '✅ El modelo considera que pasa' if verdict['pass'] else '❌ El modelo considera que no pasa'
    return rd.banner('#16a34a' if verdict['pass'] else '#dc2626', title, [verdict['reasoning']])


def _to_doc(data):
    meta = f'Corrida {data.get("run_id") or ""} · generada {data["generated_at"]}' + (f' · inicio {data["started_at"]}' if data.get('started_at') else '')
    return rd.doc(data['title'], rt._sections_to_blocks(data['sections']), meta=meta)


def render_evidence_html(data):
    return report_render.render_html(_to_doc(data))


def render_evidence_pdf(html_text, destination):
    return reporting.render_pdf(html_text, destination)


def render_evidence_markdown(data):
    return report_render.render_markdown(_to_doc(data))


def render_evidence_docx(data):
    """Mismo contenido que el HTML/PDF, en formato simple (sin buscar igualar el diseño del PDF)."""
    return report_render.render_docx(_to_doc(data))
