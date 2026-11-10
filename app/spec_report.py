"""Reportes de salida de la Especificación (Historia de usuario sola, o Matriz de trazabilidad de todo el
proyecto), con el mismo espíritu que evidence_report.py: una sola normalización de datos, tres formatos
(HTML/PDF/DOCX/MD) que no se desalinean entre sí. La plantilla de salida (`spec_templates`, kind='output') decide
qué secciones entran y en qué orden — su `body` es una lista `{field, label}`; cada campo se resuelve contra el
registro real (reporte/exportación) o contra datos de ejemplo (previsualizador de la plantilla sola)."""
import html
import io
import json
from . import core, reporting, evidence_report

FORMAT = 'ltw.spec_report/1'
_TYPE_ES = {'functional': 'Funcional', 'regression': 'Regresión', 'smoke': 'Smoke', 'exploratory': 'Exploratorio'}
_SPEC_STATUS_ES = {'draft': 'Borrador', 'ready': 'Listo', 'automated': 'Automatizado'}
_STORY_STATUS_ES = {'draft': 'Borrador', 'ready': 'Lista', 'done': 'Terminada'}

DEFAULT_STORY_TEMPLATE_BODY = [{'field': 'story', 'label': 'Historia de usuario'}, {'field': 'criteria', 'label': 'Criterios de aceptación'},
                               {'field': 'test_cases', 'label': 'Casos de prueba'}, {'field': 'traceability', 'label': 'Trazabilidad'}]
DEFAULT_MATRIX_TEMPLATE_BODY = [{'field': 'matrix', 'label': 'Matriz HU → Casos de prueba → Estado'}]

PLACEHOLDER_STORY = {
    'title': 'Recuperar contraseña por email', 'as_a': 'usuario registrado',
    'i_want': 'poder recuperar el acceso a mi cuenta si olvido la contraseña', 'so_that': 'no perder el acceso a mis datos',
    'priority': 'high', 'status': 'ready',
    'criteria': [{'text': 'Email válido', 'given': 'un email registrado y válido', 'when': 'el usuario pide recuperar su contraseña', 'then': 'se envía un enlace de recuperación', 'status': 'met'},
                 {'text': 'Enlace expirado', 'given': 'un enlace de recuperación con más de 30 minutos', 'when': 'el usuario lo abre', 'then': 'se rechaza y se ofrece reenviarlo', 'status': 'pending'}],
    'definition_of_ready': [{'text': 'Diseño de la pantalla de recuperación aprobado', 'done': True}, {'text': 'Plantilla de email definida', 'done': False}],
    'definition_of_done': [{'text': 'Pruebas automatizadas pasando', 'done': False}, {'text': 'Documentación de usuario actualizada', 'done': False}],
    'business_rules': 'Un enlace de recuperación solo puede usarse una vez.', 'assumptions': 'El proveedor de email entrega en menos de 1 minuto.',
    'risks': 'Picos de solicitudes podrían saturar el envío de emails.', 'out_of_scope': 'No cubre recuperación por SMS.',
    'story_points': 5, 'depends_on': [],
}
PLACEHOLDER_CASES = [
    {'title': 'Solicitar recuperación con email válido', 'preconditions': 'El usuario tiene una cuenta activa',
     'steps': [{'action': 'Ingresar el email registrado', 'expected': 'Se muestra un mensaje de confirmación'},
               {'action': 'Abrir el enlace recibido', 'expected': 'Se permite definir una nueva contraseña'}],
     'priority': 'high', 'type': 'functional', 'status': 'draft', 'linked_case_id': None},
    {'title': 'Enlace expirado', 'preconditions': 'Pasaron más de 30 minutos desde el envío',
     'steps': [{'action': 'Abrir un enlace vencido', 'expected': 'Se informa que el enlace expiró y se ofrece reenviarlo'}],
     'priority': 'medium', 'type': 'functional', 'status': 'draft', 'linked_case_id': None},
]


# --------------------------------------------------------------------------- resolución de campos (plantilla -> dato)

def _matrix_rows(ctx):
    rows = []
    for row in ctx['rows']:
        spec, last_run = row['spec'], row.get('last_run')
        story = row.get('story') or ctx['story']
        status = evidence_report.STATUS_ES.get(last_run['status'], last_run['status']) if last_run else _SPEC_STATUS_ES.get(spec.get('status'), spec.get('status', ''))
        rows.append({'story': story['title'] if story else '', 'case': spec['title'],
                     'type': _TYPE_ES.get(spec.get('type'), spec.get('type', '')),
                     'priority': core.PRIORITY_LABELS.get(spec.get('priority'), spec.get('priority', '')), 'status': status})
    return rows


def _resolve_field(field, ctx):
    """Campos de un reporte de Historia (sola, o agregado en la Matriz de todo el proyecto)."""
    story, stories, rows = ctx['story'], ctx['stories'], ctx['rows']
    all_criteria = (story.get('criteria') or []) if story else [c for s in stories for c in (s.get('criteria') or [])]
    if field in ('as_a', 'i_want', 'so_that'):
        return story.get(field) if story else None
    if field == 'story':
        if not story:
            return None
        return {'title': story['title'], 'as_a': story.get('as_a', ''), 'i_want': story.get('i_want', ''), 'so_that': story.get('so_that', ''),
                'priority': core.PRIORITY_LABELS.get(story.get('priority'), story.get('priority', '')),
                'status': _STORY_STATUS_ES.get(story.get('status'), story.get('status', ''))}
    if field == 'criteria':
        if story:
            return story.get('criteria') or []
        return [{'text': f'{s["title"]}: {c["text"]}', 'status': c.get('status', 'pending')} for s in stories for c in (s.get('criteria') or [])]
    if field == 'test_cases':
        return [r['spec'] for r in rows]
    if field in ('traceability', 'matrix'):
        return _matrix_rows(ctx)
    if field == 'coverage':
        return {'total': len(rows), 'automated': sum(1 for r in rows if r['spec'].get('linked_case_id')),
                'passing': sum(1 for r in rows if r.get('last_run') and r['last_run']['status'] == 'passed')}
    if field == 'summary':
        automated = sum(1 for r in rows if r['spec'].get('linked_case_id'))
        passing = sum(1 for r in rows if r.get('last_run') and r['last_run']['status'] == 'passed')
        met = sum(1 for c in all_criteria if c.get('status') == 'met')
        quien = f'«{story["title"]}»' if story else f'{len(stories)} historia(s)'
        return f'{quien}: {met}/{len(all_criteria)} criterio(s) cumplido(s), {len(rows)} caso(s) de prueba ({automated} automatizado(s), {passing} pasa(n)).'
    if field == 'risks':   # riesgos CALCULADOS (criterios pendientes + casos automatizados en rojo) — no confundir con 'business_risks' (los que redactó la persona)
        risks = [f'Criterio pendiente: {c["text"] or (c.get("then") or "")}' for c in all_criteria if c.get('status') != 'met']
        for r in rows:
            spec, last_run = r['spec'], r.get('last_run')
            if spec.get('linked_case_id') and (not last_run or last_run['status'] != 'passed'):
                risks.append(f'Caso automatizado «{spec["title"]}» en estado {last_run["status"] if last_run else "nunca ejecutado"}.')
        return risks
    if field in ('business_rules', 'assumptions', 'out_of_scope'):
        return (story.get(field) or None) if story else None
    if field == 'business_risks':
        return (story.get('risks') or None) if story else None
    if field in ('definition_of_ready', 'definition_of_done'):
        if not story:
            return None
        return [{'text': item['text'], 'status': 'met' if item.get('done') else 'pending'} for item in (story.get(field) or [])]
    if field == 'story_points':
        return str(story.get('story_points')) if story and story.get('story_points') is not None else None
    if field == 'dependencies':
        if not story:
            return None
        titles = [core.get('user_stories', sid) for sid in (story.get('depends_on') or [])]
        return [t['title'] for t in titles if t] or None
    if field == 'assigned_to':
        if not story:
            return None
        user = core.get('users', story.get('assigned_to')) if story.get('assigned_to') else None
        return f'{user.get("first_name", "")} {user.get("last_name", "")}'.strip() if user else None
    if field == 'content':
        return (story.get('content') or None) if story else None
    return None   # preconditions/expected/given/when/then: no modelados a nivel de Historia


def _resolve_test_case_field(field, record):
    """Campos de la vista previa de una plantilla de ENTRADA que aplica a Caso de prueba (p. ej. ISTQB)."""
    if field == 'preconditions':
        return record.get('preconditions') or None
    if field == 'priority':
        return core.PRIORITY_LABELS.get(record.get('priority'), record.get('priority', ''))
    if field == 'type':
        return _TYPE_ES.get(record.get('type'), record.get('type', ''))
    if field == 'steps':
        return [s.get('action', '') for s in (record.get('steps') or [])]
    if field == 'expected':
        return [s.get('expected', '') for s in (record.get('steps') or [])]
    return None


def _build_section(field, label, resolve):
    return {'field': field, 'label': label, 'content': resolve(field)}


# --------------------------------------------------------------------------- construcción del reporte

def build_story_report_data(story, template=None, sample=False):
    """Reporte de UNA Historia de usuario: sus datos, criterios, casos de prueba ligados y su trazabilidad.
    `story=None` (o `sample=True`) usa una Historia de ejemplo — mismo resolvedor y renderers que un reporte
    real, para que el previsualizador de una plantilla nunca se desalinee del documento que de verdad se exporta."""
    sample = sample or story is None
    source = PLACEHOLDER_STORY if sample else story
    rows = ([{'spec': tc, 'last_run': None} for tc in PLACEHOLDER_CASES] if sample else core.story_coverage(story['id'])['rows'])
    ctx = {'story': source, 'stories': [source], 'rows': rows}
    resolve = lambda f: _resolve_field(f, ctx)   # noqa: E731
    body = (template or {}).get('body') or DEFAULT_STORY_TEMPLATE_BODY
    sections = [_build_section(f.get('field'), f.get('label') or f.get('field'), resolve) for f in body]
    return {'format': FORMAT, 'kind': 'story', 'title': source['title'], 'generated_at': core.now(), 'sample': sample,
            'template_name': (template or {}).get('name') or 'Especificación detallada (por defecto)', 'sections': sections}


def build_test_matrix_report_data(project_id, template=None):
    """Matriz de trazabilidad de TODO el proyecto: cada Historia con sus Casos de prueba y, si están ligados a
    un Caso automatizado, el estado de su última corrida."""
    stories = core.list_project_items('user_stories', project_id)
    rows = [{'story': s, 'spec': r['spec'], 'last_run': r['last_run']} for s in stories for r in core.story_coverage(s['id'])['rows']]
    ctx = {'story': None, 'stories': stories, 'rows': rows}
    resolve = lambda f: _resolve_field(f, ctx)   # noqa: E731
    body = (template or {}).get('body') or DEFAULT_MATRIX_TEMPLATE_BODY
    sections = [_build_section(f.get('field'), f.get('label') or f.get('field'), resolve) for f in body]
    return {'format': FORMAT, 'kind': 'matrix', 'title': 'Matriz de trazabilidad', 'generated_at': core.now(), 'sample': False,
            'template_name': (template or {}).get('name') or 'Matriz de trazabilidad (por defecto)', 'sections': sections}


def build_template_preview(template, story=None, spec=None):
    """Previsualizador de CUALQUIER plantilla (de entrada o de salida): la renderiza contra el registro real
    dado (`story`/`spec`) o, si no se da ninguno, contra datos de ejemplo — reusa el mismo resolvedor y los
    mismos renderers que un reporte real."""
    applies_to = template.get('applies_to', 'report')
    if applies_to == 'test_case':
        record, sample = (spec or PLACEHOLDER_CASES[0]), spec is None
        resolve = lambda f: _resolve_test_case_field(f, record)   # noqa: E731
        title = record['title']
    elif applies_to == 'user_story':
        record, sample = (story or PLACEHOLDER_STORY), story is None
        rows = [{'spec': tc, 'last_run': None} for tc in PLACEHOLDER_CASES] if sample else core.story_coverage(record['id'])['rows']
        ctx = {'story': record, 'stories': [record], 'rows': rows}
        resolve = lambda f: _resolve_field(f, ctx)   # noqa: E731
        title = record['title']
    else:
        return build_story_report_data(story, template, sample=story is None)
    sections = [_build_section(f.get('field'), f.get('label') or f.get('field'), resolve) for f in (template.get('body') or [])]
    return {'format': FORMAT, 'kind': applies_to, 'title': title, 'generated_at': core.now(), 'sample': sample,
            'template_name': template.get('name', ''), 'sections': sections}


# --------------------------------------------------------------------------- HTML / PDF

HTML_CSS = '''
:root{color-scheme:light}*{box-sizing:border-box}body{font-family:Segoe UI,Calibri,Arial,sans-serif;color:#111827;margin:0;background:#f3f4f6}
main{max-width:900px;margin:0 auto;padding:24px 20px 48px}h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:22px 0 8px;border-bottom:1px solid #e5e7eb;padding-bottom:4px}
.meta{color:#6b7280;font-size:13px;margin-bottom:12px}.muted{color:#9ca3af;font-size:13px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin:10px 0}
.card{background:#fff;border-radius:8px;padding:10px 14px;border:1px solid #e5e7eb}.card .v{font-size:22px;font-weight:700}.card .l{font-size:12px;color:#6b7280}
.story-card{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:10px 14px}
table{width:100%;border-collapse:collapse;background:#fff;font-size:13px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #e5e7eb;vertical-align:top}th{background:#f9fafb;color:#374151}
.tc{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:10px 14px;margin:8px 0}
.criteria{list-style:none;padding-left:0;margin:0}.criteria li{margin:6px 0}.criteria input{margin-right:6px;vertical-align:middle}
.sample{background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:8px 12px;font-size:13px;margin-bottom:12px}
@media print{body{background:#fff}main{padding:0}.tc,table{break-inside:avoid}}
'''


def _render_content_html(content):
    e = html.escape
    if content is None:
        return '<p class="muted">No aplica a este documento.</p>'
    if isinstance(content, str):
        return f'<p>{e(content) if content else "—"}</p>'
    if isinstance(content, dict) and 'as_a' in content:
        return (f'<div class="story-card"><p><b>{e(content["title"])}</b></p><p><b>Como</b> {e(content["as_a"])}</p>'
                f'<p><b>Quiero</b> {e(content["i_want"])}</p><p><b>Para</b> {e(content["so_that"])}</p>'
                f'<p class="meta">Prioridad: {e(content["priority"])} · Estado: {e(content["status"])}</p></div>')
    if isinstance(content, dict) and 'total' in content:
        card = lambda v, l: f'<div class="card"><div class="v">{v}</div><div class="l">{e(l)}</div></div>'   # noqa: E731
        return f'<div class="cards">{card(content["total"], "Casos de prueba")}{card(content["automated"], "Automatizados")}{card(content["passing"], "Pasan")}</div>'
    if isinstance(content, list) and not content:
        return '<p class="muted">Ninguno.</p>'
    if isinstance(content, list) and 'steps' in content[0]:
        parts = []
        for tc in content:
            parts.append(f'<div class="tc"><b>{e(tc["title"])}</b> <span class="meta">{e(_TYPE_ES.get(tc.get("type"), ""))} · '
                         f'{e(core.PRIORITY_LABELS.get(tc.get("priority"), ""))} · {e(_SPEC_STATUS_ES.get(tc.get("status"), ""))}</span>')
            if tc.get('preconditions'):
                parts.append(f'<div class="meta">Precondición: {e(tc["preconditions"])}</div>')
            steps = tc.get('steps') or []
            parts.append(('<ol>' + ''.join(f'<li>{e(s.get("action", ""))} → {e(s.get("expected", ""))}</li>' for s in steps) + '</ol>')
                        if steps else '<p class="muted">Sin pasos.</p>')
            parts.append('</div>')
        return ''.join(parts)
    if isinstance(content, list) and 'status' in content[0] and 'text' in content[0]:
        # checkbox real del navegador, no un glifo de fuente (un círculo vacío "○" puede confundirse con una "O" suelta
        # según la fuente/el renderizador — un checkbox no depende de ninguna fuente y es inequívoco). Estilo en
        # línea (no una clase CSS externa): este fragmento también se incrusta tal cual en la vista de solo
        # lectura de la propia pantalla (ver render_story_view_html), que no carga HTML_CSS. Si el criterio trae
        # Dado/Cuando/Entonces (Gherkin), se muestra debajo del resumen — si no (p. ej. Definición de Listo/Hecho,
        # o un criterio "viejo" sin estructurar), solo el resumen.
        items = []
        for c in content:
            label = e(c['text']) if c.get('text') else '<i style="color:#9ca3af">(sin resumen)</i>'
            gherkin = ''
            if c.get('given') or c.get('when') or c.get('then'):
                gherkin = (f'<div style="margin:2px 0 0 24px;font-size:13px;color:#4b5563">'
                          f'<b>Dado</b> {e(c.get("given", ""))} <b>cuando</b> {e(c.get("when", ""))} <b>entonces</b> {e(c.get("then", ""))}</div>')
            items.append(f'<li style="margin:8px 0"><label style="cursor:default"><input type="checkbox" disabled{" checked" if c.get("status") == "met" else ""} '
                        f'style="margin-right:6px;vertical-align:middle"> {label}</label>{gherkin}</li>')
        return '<ul style="list-style:none;padding-left:0;margin:0">' + ''.join(items) + '</ul>'
    if isinstance(content, list) and isinstance(content[0], str):
        return '<ul>' + ''.join(f'<li>{e(c)}</li>' for c in content) + '</ul>'
    if isinstance(content, list) and 'case' in content[0]:
        rows = ''.join(f'<tr><td>{e(r["story"])}</td><td>{e(r["case"])}</td><td>{e(r["type"])}</td><td>{e(r["priority"])}</td><td>{e(r["status"])}</td></tr>' for r in content)
        return f'<table><tr><th>Historia</th><th>Caso de prueba</th><th>Tipo</th><th>Prioridad</th><th>Estado</th></tr>{rows}</table>'
    return f'<pre>{e(json.dumps(content, ensure_ascii=False, indent=2))}</pre>'


# --------------------------------------------------------------------------- vista de lectura en la propia pantalla
# (no exportación): un fragmento HTML — sin <html>/<head>, para incrustar con ui.html() tal cual, con estilos en
# línea (no depende de HTML_CSS, que solo se carga en el documento exportado) — que muestra la Historia o el Caso
# de prueba redactado como se leería, en vez del formulario. Reusa _render_content_html para que la redacción
# nunca se desalinee del reporte que de verdad se exporta.

def _h3(label):
    return f'<h3 style="margin:18px 0 8px;font-size:15px;font-weight:600;color:#374151">{label}</h3>'


def render_story_view_html(story):
    """`story`: as_a/i_want/so_that/priority/story_points/criteria/definition_of_ready/definition_of_done/
    business_rules/assumptions/risks/out_of_scope tal como viven en la base — más `dependency_titles` (lista de
    strings, no ids: títulos ya resueltos por el caller, para no tener que ir a buscarlos acá)."""
    e = html.escape
    parts = []
    if story.get('content'):
        parts.append(f'<div style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:10px 14px;white-space:pre-wrap">{e(story["content"])}</div>')
    elif story.get('as_a') or story.get('i_want') or story.get('so_that'):
        parts.append('<div style="background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:4px 0 2px">')
        parts.append(f'<p style="margin:6px 0"><b>Como</b> {e(story.get("as_a", "")) or "—"}</p>')
        parts.append(f'<p style="margin:6px 0"><b>Quiero</b> {e(story.get("i_want", "")) or "—"}</p>')
        parts.append(f'<p style="margin:6px 0"><b>Para</b> {e(story.get("so_that", "")) or "—"}</p>')
        parts.append('</div>')
    meta = []
    if story.get('priority'):
        meta.append(f'Prioridad: {core.PRIORITY_LABELS.get(story["priority"], story["priority"])}')
    if story.get('story_points') not in (None, ''):
        meta.append(f'{story["story_points"]} story points')
    if meta:
        parts.append(f'<p style="margin:10px 0 0;font-size:13px;color:#6b7280">{e(" · ".join(meta))}</p>')

    parts.append(_h3('Criterios de aceptación'))
    parts.append(_render_content_html(story.get('criteria') or []))

    for field, label in (('definition_of_ready', 'Definición de Listo'), ('definition_of_done', 'Definición de Hecho')):
        items = story.get(field) or []
        if items:
            parts.append(_h3(label))
            parts.append(_render_content_html([{'text': i['text'], 'status': 'met' if i.get('done') else 'pending'} for i in items]))

    for field, label in (('business_rules', 'Reglas de negocio'), ('assumptions', 'Supuestos'), ('risks', 'Riesgos'), ('out_of_scope', 'Fuera de alcance')):
        if story.get(field):
            parts.append(_h3(label) + f'<p style="margin:0">{e(story[field])}</p>')

    if story.get('dependency_titles'):
        parts.append(_h3('Depende de'))
        parts.append(_render_content_html(story['dependency_titles']))
    return ''.join(parts)


def render_test_case_view_html(spec):
    e = html.escape
    parts = []
    if spec.get('preconditions'):
        parts.append(f'<p style="margin:6px 0"><b>Precondición</b><br>{e(spec["preconditions"])}</p>')
    parts.append('<h3 style="margin:18px 0 8px;font-size:15px;font-weight:600;color:#374151">Pasos de ejecución y resultado esperado</h3>')
    steps = spec.get('steps') or []
    if not steps:
        parts.append('<p style="color:#9ca3af;font-size:13px">Ninguno todavía.</p>')
    else:
        parts.append('<ol style="margin:0;padding-left:22px">' + ''.join(
            f'<li style="margin:8px 0">{e(s.get("action", "")) or "—"} <span style="color:#9ca3af">→</span> {e(s.get("expected", "")) or "—"}</li>' for s in steps) + '</ol>')
    return ''.join(parts)


def render_spec_html(data):
    e = html.escape
    parts = [f'<h1>{e(data["title"])}</h1>', f'<div class="meta">Plantilla: {e(data["template_name"])} · generado {e(data["generated_at"])}</div>']
    if data.get('sample'):
        parts.append('<div class="sample">Vista previa con datos de ejemplo — no corresponde a un registro real.</div>')
    for section in data['sections']:
        parts.append(f'<h2>{e(section["label"])}</h2>{_render_content_html(section["content"])}')
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(data["title"])}</title><style>{HTML_CSS}</style></head><body><main>{"".join(parts)}</main></body></html>')


def render_spec_pdf(html_text, destination):
    return reporting.render_pdf(html_text, destination)


# --------------------------------------------------------------------------- Markdown

def _render_content_markdown(content):
    if content is None:
        return ['_No aplica a este documento._', '']
    if isinstance(content, str):
        return [content or '—', '']
    if isinstance(content, dict) and 'as_a' in content:
        return [f'**{content["title"]}**', '', f'- Como {content["as_a"]}', f'- Quiero {content["i_want"]}', f'- Para {content["so_that"]}',
               f'- Prioridad: {content["priority"]} · Estado: {content["status"]}', '']
    if isinstance(content, dict) and 'total' in content:
        return [f'{content["total"]} caso(s) de prueba · {content["automated"]} automatizado(s) · {content["passing"]} pasa(n).', '']
    if isinstance(content, list) and not content:
        return ['_Ninguno._', '']
    if isinstance(content, list) and 'steps' in content[0]:
        lines = []
        for tc in content:
            lines.append(f'**{tc["title"]}** — {_TYPE_ES.get(tc.get("type"), "")}/{core.PRIORITY_LABELS.get(tc.get("priority"), "")}/{_SPEC_STATUS_ES.get(tc.get("status"), "")}')
            if tc.get('preconditions'):
                lines.append(f'Precondición: {tc["preconditions"]}')
            lines += [f'{i}. {s.get("action", "")} → {s.get("expected", "")}' for i, s in enumerate(tc.get('steps') or [], 1)]
            lines.append('')
        return lines
    if isinstance(content, list) and 'status' in content[0] and 'text' in content[0]:
        lines = []
        for c in content:
            lines.append(('- [x] ' if c.get('status') == 'met' else '- [ ] ') + (c.get('text') or '(sin resumen)'))
            if c.get('given') or c.get('when') or c.get('then'):
                lines.append(f'  Dado {c.get("given", "")}, cuando {c.get("when", "")}, entonces {c.get("then", "")}')
        return lines + ['']
    if isinstance(content, list) and isinstance(content[0], str):
        return [f'- {c}' for c in content] + ['']
    if isinstance(content, list) and 'case' in content[0]:
        lines = ['| Historia | Caso de prueba | Tipo | Prioridad | Estado |', '|---|---|---|---|---|']
        return lines + [f'| {r["story"]} | {r["case"]} | {r["type"]} | {r["priority"]} | {r["status"]} |' for r in content] + ['']
    return ['```json', json.dumps(content, indent=2, ensure_ascii=False), '```', '']


def render_spec_markdown(data):
    lines = [f'# {data["title"]}', '', f'Plantilla: {data["template_name"]} · Generado: {data["generated_at"]}', '']
    if data.get('sample'):
        lines += ['> Vista previa con datos de ejemplo — no corresponde a un registro real.', '']
    for section in data['sections']:
        lines += [f'## {section["label"]}', ''] + _render_content_markdown(section['content'])
    return '\n'.join(lines) + '\n'


# --------------------------------------------------------------------------- Word

def _write_content_docx(doc, content):
    if content is None:
        doc.add_paragraph('No aplica a este documento.')
        return
    if isinstance(content, str):
        doc.add_paragraph(content or '—')
        return
    if isinstance(content, dict) and 'as_a' in content:
        doc.add_paragraph(content['title'])
        doc.add_paragraph(f'Como {content["as_a"]}')
        doc.add_paragraph(f'Quiero {content["i_want"]}')
        doc.add_paragraph(f'Para {content["so_that"]}')
        doc.add_paragraph(f'Prioridad: {content["priority"]} · Estado: {content["status"]}')
        return
    if isinstance(content, dict) and 'total' in content:
        doc.add_paragraph(f'{content["total"]} caso(s) de prueba · {content["automated"]} automatizado(s) · {content["passing"]} pasa(n).')
        return
    if isinstance(content, list) and not content:
        doc.add_paragraph('Ninguno.')
        return
    if isinstance(content, list) and 'steps' in content[0]:
        for tc in content:
            doc.add_paragraph(f'{tc["title"]} — {_TYPE_ES.get(tc.get("type"), "")}/{core.PRIORITY_LABELS.get(tc.get("priority"), "")}/{_SPEC_STATUS_ES.get(tc.get("status"), "")}')
            if tc.get('preconditions'):
                doc.add_paragraph(f'Precondición: {tc["preconditions"]}')
            for i, s in enumerate(tc.get('steps') or [], 1):
                doc.add_paragraph(f'{i}. {s.get("action", "")} → {s.get("expected", "")}')
        return
    if isinstance(content, list) and 'status' in content[0] and 'text' in content[0]:
        # "[x]"/"[ ]" en vez de un glifo de círculo: inequívoco sin depender de que la fuente lo soporte.
        for c in content:
            doc.add_paragraph(('[x] ' if c.get('status') == 'met' else '[ ] ') + (c.get('text') or '(sin resumen)'))
            if c.get('given') or c.get('when') or c.get('then'):
                doc.add_paragraph(f'    Dado {c.get("given", "")}, cuando {c.get("when", "")}, entonces {c.get("then", "")}')
        return
    if isinstance(content, list) and isinstance(content[0], str):
        for c in content:
            doc.add_paragraph(f'• {c}')
        return
    if isinstance(content, list) and 'case' in content[0]:
        table = doc.add_table(rows=1, cols=5)
        for cell, text in zip(table.rows[0].cells, ('Historia', 'Caso de prueba', 'Tipo', 'Prioridad', 'Estado')):
            cell.text = text
        for r in content:
            cells = table.add_row().cells
            for cell, key in zip(cells, ('story', 'case', 'type', 'priority', 'status')):
                cell.text = str(r[key])
        return
    doc.add_paragraph(json.dumps(content, ensure_ascii=False, indent=2))


def render_spec_docx(data):
    from docx import Document
    doc = Document()
    doc.add_heading(data['title'], level=1)
    doc.add_paragraph(f'Plantilla: {data["template_name"]} · Generado: {data["generated_at"]}')
    if data.get('sample'):
        doc.add_paragraph('Vista previa con datos de ejemplo — no corresponde a un registro real.')
    for section in data['sections']:
        doc.add_heading(section['label'], level=2)
        _write_content_docx(doc, section['content'])
    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
