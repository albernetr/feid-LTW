"""Sección "Reportes": catálogo centralizado (ver app/report_catalog.py) para exportar uno, varios o todos los
registros de cualquier tipo en un solo documento — complementa (no reemplaza) los botones de exportar por fila
que ya existen en Historias/Suites/Casos API/evidencia de una corrida."""
import re
import tempfile
from pathlib import Path
from nicegui import ui, run
from .. import core, report_catalog, report_render
from .common import frame, guard, empty_state, require_project, protected_page, open_evidence_in_new_tab, CONTENT_TYPES

FORMAT_OPTIONS = {'html': 'HTML', 'pdf': 'PDF', 'docx': 'Word', 'md': 'Markdown'}


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


def _template_select(pid):
    templates = core.visible_templates('output', 'report', pid)
    return ui.select({t['id']: t['name'] for t in templates}, label='Plantilla de salida').props('outlined dense').classes('w-full')


def _resolved_template(select):
    return core.get('spec_templates', select.value) if select and select.value else None


def _generate_controls(doc_for, pid, rt):
    """`doc_for(template)` arma el documento a exportar con la plantilla resuelta — ya decidido por quien
    llama si toca single_doc_fn o batch_doc_fn (o project_doc_fn, para Matriz)."""
    template_select = _template_select(pid) if rt.uses_template else None
    format_select = ui.select(FORMAT_OPTIONS, value='html', label='Formato').props('outlined dense').classes('w-60')

    async def preview():
        _preview_catalog_doc(doc_for(_resolved_template(template_select)))

    async def generate():
        await _download_catalog_doc(doc_for(_resolved_template(template_select)), format_select.value)

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

    def doc_for(template):
        chosen = [item for item in items if selected[item['id']]]
        if not chosen:
            raise ValueError('Marca al menos un elemento')
        return rt.single_doc_fn(chosen[0], template) if len(chosen) == 1 else rt.batch_doc_fn(chosen, template)

    _generate_controls(doc_for, pid, rt)


def _project_section(rt, pid):
    def doc_for(template):
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
