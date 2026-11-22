"""Motor genérico que convierte el `body` (árbol de nodos) de una plantilla de salida, más un resolvedor de
campos propio de cada tipo de reporte, en el árbol de BLOQUES de report_doc.py — no sabe qué es una Historia,
un Caso de prueba, una Suite o una Evidencia: cada constructor de datos (spec_report.py/reporting.py/
evidence_report.py) le da su propio `resolve_known(field) -> content` y sus propios `custom_fields`.

Vive en un módulo aparte de spec_report.py (donde nació, migrado tal cual en Fase 3) para que reporting.py y
evidence_report.py puedan reusarlo sin crear un import circular: spec_report.py ya importa reporting.py y
evidence_report.py (para reusar su render_pdf), así que si esos dos importaran spec_report.py para este
motor, se cerraría el ciclo — este módulo es más bajo en la jerarquía que los tres."""
import json
from . import core, report_doc as rd

_TYPE_ES = {'functional': 'Funcional', 'regression': 'Regresión', 'smoke': 'Smoke', 'exploratory': 'Exploratorio'}
_SPEC_STATUS_ES = {'draft': 'Borrador', 'ready': 'Listo', 'automated': 'Automatizado'}


def _file_url(value):
    return f'/evidence/{value["id"]}/{value["id"]}-{value["filename"]}'


def _validate_custom_value(value, field_type):
    """Un campo custom (field_type declarado por la plantilla) se resuelve desde `custom_fields[field_key]` —
    el tipo con el que se guardó viaja implícito en la FORMA del valor, nunca se re-infiere de ninguna
    plantilla: si el valor no matchea la forma que este field_type espera (p. ej. quedó guardado por una
    plantilla distinta que declaraba otro tipo para la misma clave), se trata como vacío — nunca revienta."""
    if field_type in ('text', 'textarea'):
        return value if isinstance(value, str) and value else None
    if field_type == 'list':
        return value if isinstance(value, list) and value else None
    if field_type == 'table':
        return value if isinstance(value, dict) and isinstance(value.get('headers'), list) and value['headers'] else None
    if field_type in ('image', 'attachment'):
        return value if isinstance(value, dict) and value.get('id') and value.get('filename') else None
    return None


def _is_empty_content(content):
    """Sin nada que mostrar: None, texto vacío o lista vacía — un dict (story-card, coverage, o cualquiera de
    las formas {'kind': ...} de abajo) nunca cuenta como vacío, trae sus claves siempre (hasta en 0, sigue
    siendo un dato real, no un placeholder) — cada resolvedor decide él mismo cuándo devolver None."""
    return content is None or content == '' or content == []


def _build_tree_sections(body, resolve_known, custom_fields):
    """Construye, recursivamente, el árbol de SECCIONES de un reporte a partir del árbol `body` de una
    plantilla (ver core.py) — un nodo 'field' con field_type=None resuelve contra un campo FIJO conocido
    (resolve_known, el mismo resolvedor de siempre); con field_type declarado, resuelve contra `custom_fields`
    (el dict guardado en el registro). Un nodo 'group' solo agrupa: label + as_tab + sus children recursivos.
    Una sección sin nada que mostrar (ver _is_empty_content) se omite por defecto — "Ninguno."/"No aplica a
    este documento." repetido en cada campo vacío de un registro real no aporta, solo ocupa espacio; un grupo
    que se queda sin ningún hijo visible se omite entero (no deja un título sin nada debajo)."""
    sections = []
    for node in (body or []):
        if not isinstance(node, dict):
            continue
        if node.get('kind') == 'group':
            children = _build_tree_sections(node.get('children') or [], resolve_known, custom_fields)
            if not children:
                continue
            sections.append({'kind': 'group', 'label': node.get('label') or '', 'width': node.get('width', 'full'),
                             'col_span': node.get('col_span'), 'as_tab': bool(node.get('as_tab')), 'children': children})
            continue
        # `node` puede venir del editor EN VIVO (vista previa mientras se edita una plantilla, ver
        # spec_templates.py::live_preview), todavía sin pasar por core._clean_template_body — un campo recién
        # agregado y sin nombrar aún puede tener field_key/label vacíos; `or ''` evita que lleguen a None.
        field_key = node.get('field_key') or node.get('field') or ''
        field_type = node.get('field_type')
        content = resolve_known(field_key) if field_type is None else _validate_custom_value((custom_fields or {}).get(field_key), field_type)
        if _is_empty_content(content):
            continue
        sections.append({'kind': 'field', 'field': field_key, 'label': node.get('label') or field_key or '',
                         'width': node.get('width', 'full'), 'col_span': node.get('col_span'),
                         'field_type': field_type, 'content': content})
    return sections


def _content_to_blocks(content, field_type=None):
    if content is None:
        return [rd.text('No aplica a este documento.')]
    if field_type in ('text', 'textarea'):
        return [rd.text(content if content else '—')]
    if field_type == 'list':
        return [rd.checks([{'label': (it.get('text') or '(vacío)') if isinstance(it, dict) else str(it),
                            'ok': bool(it.get('done')) if isinstance(it, dict) else False} for it in content])]
    if field_type == 'table':
        return [rd.table(content.get('headers') or [], content.get('rows') or [])]
    if field_type == 'image':
        return [rd.file(_file_url(content), content.get('filename', ''), image=True,
                        path=str(core.ARTIFACTS / f'{content["id"]}-{content["filename"]}'))]
    if field_type == 'attachment':
        return [rd.file(_file_url(content), content.get('filename', ''), note=f'({content.get("size", 0)} bytes)')]
    if field_type:
        return [rd.text('(sin datos)')]
    # campos FIJOS conocidos (field_type=None): formas genéricas discriminadas por 'kind' (Suite/Caso/Evidencia,
    # ver reporting.py/evidence_report.py), antes de las formas heurísticas de HU/TC/Matriz de abajo.
    if isinstance(content, dict) and 'kind' in content:
        if content['kind'] == 'badge':
            return [rd.badge(content['label'], content['color'])]
        if content['kind'] == 'cards':
            return [rd.cards(content['items'])]
        if content['kind'] == 'trend_svg':
            blocks = [rd.svg(content['markup'])]
            if content.get('caption'):
                blocks.append(rd.text(content['caption']))
            return blocks
        if content['kind'] == 'table':
            return [rd.table(content['columns'], content['rows'])]
        if content['kind'] == 'blocks':
            return list(content['items'])
    # 8 formas heurísticas ya existentes (HU/TC/Matriz) — por FORMA del valor, no por una clave discriminadora.
    if isinstance(content, str):
        return [rd.text(content or '—')]
    if isinstance(content, dict) and 'as_a' in content:
        return [rd.text(content['title']),
                rd.kv([('Como', content['as_a']), ('Quiero', content['i_want']), ('Para', content['so_that']),
                      ('Prioridad', content['priority']), ('Estado', content['status'])])]
    if isinstance(content, dict) and 'total' in content:
        return [rd.cards([{'value': content['total'], 'label': 'Casos de prueba'}, {'value': content['automated'], 'label': 'Automatizados'},
                          {'value': content['passing'], 'label': 'Pasan'}])]
    if isinstance(content, list) and not content:
        return [rd.text('Ninguno.')]
    if isinstance(content, list) and 'steps' in content[0]:
        blocks = []
        for tc in content:
            blocks.append(rd.text(f'{tc["title"]} — {_TYPE_ES.get(tc.get("type"), "")}/{core.PRIORITY_LABELS.get(tc.get("priority"), "")}/{_SPEC_STATUS_ES.get(tc.get("status"), "")}'))
            if tc.get('preconditions'):
                blocks.append(rd.text(f'Precondición: {tc["preconditions"]}'))
            steps = tc.get('steps') or []
            blocks.append(rd.bullet_list([f'{s.get("action", "")} → {s.get("expected", "")}' for s in steps], ordered=True) if steps
                          else rd.text('Sin pasos.'))
        return blocks
    if isinstance(content, list) and 'status' in content[0] and 'text' in content[0]:
        note = lambda c: f'Dado {c.get("given", "")}, cuando {c.get("when", "")}, entonces {c.get("then", "")}' if (c.get('given') or c.get('when') or c.get('then')) else None   # noqa: E731
        return [rd.checks([{'label': c.get('text') or '(sin resumen)', 'ok': c.get('status') == 'met', 'note': note(c)} for c in content])]
    if isinstance(content, list) and isinstance(content[0], str):
        return [rd.bullet_list(content)]
    if isinstance(content, list) and 'case' in content[0]:
        return [rd.table(['Historia', 'Caso de prueba', 'Tipo', 'Prioridad', 'Estado'],
                         [[r['story'], r['case'], r['type'], r['priority'], r['status']] for r in content])]
    return [rd.code(json.dumps(content, ensure_ascii=False, indent=2), 'json')]


def _section_to_blocks(section, level):
    if section['kind'] == 'group':
        blocks = []
        if section['label']:
            blocks.append(rd.heading(section['label'], level=level))
        blocks += _sections_to_blocks(section['children'], level + 1)
        return blocks
    return [rd.heading(section['label'], level=level)] + _content_to_blocks(section['content'], section['field_type'])


def _sections_to_blocks(sections, level=2):
    """Empaqueta secciones HERMANAS en una grilla real de 12 columnas (core.pack_grid_rows, por `col_span`/
    `width`) -- una fila con una sola sección se exporta igual que siempre; una fila con 2+ se envuelve en
    `rd.row(...)` (Fase 2: HTML/PDF/Word honran las columnas reales; Markdown se degrada a secuencial)."""
    blocks = []
    for row in core.pack_grid_rows(sections):
        if len(row) == 1:
            blocks += _section_to_blocks(row[0], level)
        else:
            blocks.append(rd.row([{'span': core.node_col_span(s), 'children': _section_to_blocks(s, level)} for s in row]))
    return blocks
