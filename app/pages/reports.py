"""Sección "Reportes": catálogo centralizado (ver app/report_catalog.py) para exportar uno, varios o todos los
registros de cualquier tipo en un solo documento — complementa (no reemplaza) los botones de exportar por fila
que ya existen en Historias/Suites/Casos API/evidencia de una corrida.

Fase 4 de Reportería: además de la Plantilla de salida (spec_templates) de siempre, un tipo con registros
propios (Historia de usuario/Caso de prueba) puede generarse con un Diseño visual (report_layouts, ver
app/pages/report_designer.py) -- mismo botón Vista previa/Generar, el mismo documento de siempre, solo que
armado con layout_to_blocks en vez de spec_report/report_tree. Esto es lo que de verdad conecta el
diseñador con un reporte real (no solo con su propia vista previa interna)."""
import re
import tempfile
from pathlib import Path
from nicegui import ui, run
from .. import core, report_catalog, report_doc as rd, report_render
from .common import frame, guard, empty_state, require_project, protected_page, open_evidence_in_new_tab, CONTENT_TYPES
from .report_designer import layout_to_blocks

FORMAT_OPTIONS = {'html': 'HTML', 'pdf': 'PDF', 'docx': 'Word', 'md': 'Markdown'}
# Un Diseño visual (report_layouts) solo tiene sentido para un tipo de reporte con registros PROPIOS reales
# (Historia de usuario/Caso de prueba) -- 'report' (Suite/Caso ejecutable/Evidencia/Matriz) comparte el pool
# KNOWN_REPORT_FIELDS sin un resolvedor único por registro, así que no se ofrece ahí todavía.
LAYOUT_APPLIES_TO_BY_REPORT_KEY = {'user_story': 'user_story', 'test_case': 'test_case'}


def _stem(text_value):
    return re.sub(r'[\\/:*?"<>|]+', '_', text_value or 'reporte').replace(' ', '_')


async def _render_catalog_doc(doc, fmt):
    if fmt == 'pdf':
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'r.pdf'
            await run.io_bound(report_render.render_pdf_from_html, report_render.render_html(doc), target)
            return target.read_bytes(), CONTENT_TYPES['pdf']
    if fmt == 'docx':
        return await run.io_bound(report_render.render_docx, doc), CONTENT_TYPES['docx']
    if fmt == 'md':
        return report_render.render_markdown(doc).encode('utf-8'), CONTENT_TYPES['md']
    return report_render.render_html(doc).encode('utf-8'), CONTENT_TYPES['html']


async def _download_catalog_doc(doc, fmt):
    content, _ = await _render_catalog_doc(doc, fmt)
    ui.download(content, f'{_stem(doc["title"])}.{fmt}')
    ui.notify('Reporte generado', type='positive')


def _preview_catalog_doc(doc):
    html_text = report_render.render_html(doc)
    view_id = core.uid()
    filename = f'{view_id}-catalog-report.html'
    (core.ARTIFACTS / filename).write_text(html_text, encoding='utf-8')
    open_evidence_in_new_tab(view_id, filename)


def _source_select(pid, rt):
    """Plantilla de salida (spec_templates) o Diseño visual (report_layouts) para este tipo -- un solo
    selector con las dos familias de opciones (prefijo 'tpl:'/'layout:' en el value) en vez de un toggle
    aparte, para no duplicar el layout del formulario. None si no hay ninguna opción para ofrecer."""
    options = {}
    if rt.uses_template:
        for t in core.visible_templates('output', 'report', pid):
            options[f'tpl:{t["id"]}'] = f'Plantilla: {t["name"]}'
    layout_applies_to = LAYOUT_APPLIES_TO_BY_REPORT_KEY.get(rt.key)
    if layout_applies_to:
        for layout in core.list_project_items('report_layouts', pid):
            if layout['applies_to'] == layout_applies_to:
                options[f'layout:{layout["id"]}'] = f'Diseño visual: {layout["name"]}'
    if not options:
        return None
    return ui.select(options, label='Plantilla de salida / Diseño visual').props('outlined dense').classes('w-full')


def _resolved_source(select):
    """(template, layout) -- a lo sumo uno de los dos no-None, según el prefijo elegido en _source_select."""
    if not select or not select.value:
        return None, None
    kind, _, item_id = select.value.partition(':')
    if kind == 'layout':
        return None, core.get('report_layouts', item_id)
    return core.get('spec_templates', item_id), None


def _layout_doc_for_items(layout, items, rt, pid, header_mode='per_item'):
    """El mismo documento que ya arma report_designer.py (Encabezado+Cuerpo+Pie concatenados, sin paginado
    real -- eso solo lo tiene el botón "Exportar PDF" del propio diseñador) pero resuelto contra el/los
    registro(s) REALES elegidos acá, no contra un registro de previsualización -- esto es lo que de verdad
    conecta el diseñador con un reporte real: el mismo layout_to_blocks, el mismo árbol guardado, ahora con
    el dato de verdad del registro que se está reportando.

    Con varios ítems elegidos, `header_mode` decide cómo tratar Encabezado/Pie (solo importa si hay más de
    un ítem; con uno solo ambos modos son idénticos):
    - 'per_item' (hoy el único comportamiento, se mantiene como default): Encabezado+Cuerpo+Pie completos
      se repiten por cada ítem -- como generar un reporte separado por cada uno, pero en un solo documento.
      Un campo dinámico en el Encabezado (ej. Título) sale resuelto contra CADA registro, no se queda
      pegado al primero.
    - 'single': Encabezado se resuelve una sola vez (contra el primer ítem) y Pie una sola vez (contra el
      último), envolviendo todos los Cuerpos concatenados -- para cuando el Encabezado/Pie es contenido
      fijo (logo, título de la empresa) que no tiene sentido repetir por cada ítem."""
    def header_for(record):
        return layout_to_blocks(layout.get('header') or [], record, applies_to=layout['applies_to'], project_id=pid)
    def body_for(record):
        return layout_to_blocks(layout.get('body') or [], record, applies_to=layout['applies_to'], project_id=pid)
    def footer_for(record):
        return layout_to_blocks(layout.get('footer') or [], record, applies_to=layout['applies_to'], project_id=pid)

    if len(items) == 1:
        return rd.doc(layout['name'], header_for(items[0]) + body_for(items[0]) + footer_for(items[0]))

    if header_mode == 'single':
        blocks = header_for(items[0])
        for item in items:
            blocks.append(rd.heading(rt.label_fn(item), level=1))
            blocks += body_for(item)
        blocks += footer_for(items[-1])
        return rd.doc(layout['name'], blocks, meta=f'{len(items)} ítem(s) combinados')

    blocks = []
    for item in items:
        blocks.append(rd.heading(rt.label_fn(item), level=1))
        blocks += header_for(item) + body_for(item) + footer_for(item)
    return rd.doc(layout['name'], blocks, meta=f'{len(items)} ítem(s) combinados')


def _generate_controls(doc_for, pid, rt):
    """`doc_for(template, layout)` arma el documento a exportar -- a lo sumo uno de los dos no es None (ver
    _resolved_source); ya decidido por quien llama si toca single_doc_fn/batch_doc_fn/project_doc_fn o
    _layout_doc_for_items."""
    source_select = _source_select(pid, rt)
    format_select = ui.select(FORMAT_OPTIONS, value='html', label='Formato').props('outlined dense').classes('w-60')

    async def preview():
        template, layout = _resolved_source(source_select)
        _preview_catalog_doc(doc_for(template, layout))

    async def generate():
        template, layout = _resolved_source(source_select)
        await _download_catalog_doc(doc_for(template, layout), format_select.value)

    with ui.row().classes('items-center gap-2 mt-2'):
        ui.button('Vista previa', icon='open_in_new', on_click=guard(preview)).props('outline')
        ui.button('Generar', icon='download', on_click=guard(generate)).props('color=primary')


def _items_section(rt, pid):
    items = rt.list_fn(pid)
    if not items:
        empty_state('No hay elementos de este tipo en el proyecto activo.')
        return
    selected = {item['id']: False for item in items}
    checkbox_refs = {}
    count_label = ui.label('0 seleccionado(s)').classes('text-sm text-gray-500')
    header_mode_select = None
    if LAYOUT_APPLIES_TO_BY_REPORT_KEY.get(rt.key):
        header_mode_select = ui.select(
            {'per_item': 'Por cada elemento (como reportes separados, en un solo documento)',
             'single': 'Único para todo el documento'},
            value='per_item', label='Encabezado/pie del Diseño visual (con varios elementos)',
        ).props('outlined dense').classes('w-full')

    def refresh_count():
        count_label.set_text(f'{sum(1 for picked in selected.values() if picked)} seleccionado(s)')

    def pick(item_id, value):
        selected[item_id] = value
        refresh_count()

    def toggle_all(e):
        for item_id in selected:
            selected[item_id] = e.value
            checkbox_refs[item_id].value = e.value
        refresh_count()

    with ui.row().classes('items-center gap-2'):
        ui.checkbox('Seleccionar todos', on_change=toggle_all).props('dense')
        count_label
    with ui.column().classes('w-full gap-0').style('max-height:260px;overflow:auto'):
        for item in items:
            with ui.row().classes('items-center gap-2'):
                checkbox_refs[item['id']] = ui.checkbox(value=False, on_change=lambda e, iid=item['id']: pick(iid, e.value)).props('dense')
                ui.label(rt.label_fn(item)).classes('text-sm')

    def doc_for(template, layout):
        chosen = [item for item in items if selected[item['id']]]
        if not chosen:
            raise ValueError('Marca al menos un elemento')
        if layout:
            mode = header_mode_select.value if header_mode_select else 'per_item'
            return _layout_doc_for_items(layout, chosen, rt, pid, header_mode=mode)
        return rt.single_doc_fn(chosen[0], template) if len(chosen) == 1 else rt.batch_doc_fn(chosen, template)

    _generate_controls(doc_for, pid, rt)


def _project_section(rt, pid):
    def doc_for(template, layout):
        return rt.project_doc_fn(pid, template)
    _generate_controls(doc_for, pid, rt)


def _report_type_page(rt):
    """Una ruta propia por tipo (/reports/<slug>), cada una su propio ítem en el nav dentro de "Reportes" —
    no una sola pantalla con los 6 tipos apilados: así el usuario entra directo al que necesita, igual que
    Historias/Casos de prueba/Plantillas son rutas separadas dentro de "Especificación"."""
    route = f'/reports/{rt.slug}'

    @protected_page(route)
    def _page():
        with frame(f'Reporte · {rt.label}', route):
            if not require_project():
                return
            pid = core.get_active_project_id()
            if rt.scope == 'project':
                _project_section(rt, pid)
            else:
                _items_section(rt, pid)
    _page.__name__ = f'reports_{rt.key}_page'
    return _page


REPORT_TYPE_PAGES = [_report_type_page(rt) for rt in report_catalog.REPORT_TYPES]
