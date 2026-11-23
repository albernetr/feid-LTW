"""Bloque `row` (Fase 2: grilla real para el documento exportado) — report_doc.py/report_render.py."""
from app import report_doc as rd, report_render


def _doc_with_row():
    return rd.doc('Reporte', [
        rd.row([{'span': 6, 'children': [rd.heading('Columna A'), rd.text('texto A')]},
               {'span': 6, 'children': [rd.heading('Columna B'), rd.text('texto B')]}]),
    ])


def test_row_renders_as_a_real_css_grid_in_html():
    html = report_render.render_html(_doc_with_row())
    assert 'display:grid' in html and 'grid-template-columns:repeat(12,1fr)' in html
    assert html.count('grid-column:span 6') == 2
    assert 'Columna A' in html and 'Columna B' in html


def test_row_concatenates_cells_sequentially_in_markdown():
    """Markdown no tiene columnas — una fila de 2 celdas se degrada a secuencial, a propósito."""
    md = report_render.render_markdown(_doc_with_row())
    assert md.index('Columna A') < md.index('texto A') < md.index('Columna B') < md.index('texto B')


def test_row_renders_as_a_one_row_table_with_proportional_widths_in_docx():
    import io
    from docx import Document
    content = report_render.render_docx(_doc_with_row())
    assert content[:2] == b'PK'
    document = Document(io.BytesIO(content))
    assert len(document.tables) == 1
    table = document.tables[0]
    assert len(table.rows) == 1 and len(table.columns) == 2
    assert 'Columna A' in table.cell(0, 0).text and 'texto A' in table.cell(0, 0).text
    assert 'Columna B' in table.cell(0, 1).text and 'texto B' in table.cell(0, 1).text


def test_row_with_an_unequal_three_column_split():
    doc = rd.doc('Reporte', [rd.row([{'span': 4, 'children': [rd.text('un tercio')]},
                                     {'span': 4, 'children': [rd.text('otro tercio')]},
                                     {'span': 4, 'children': [rd.text('ultimo tercio')]}])])
    html = report_render.render_html(doc)
    assert html.count('grid-column:span 4') == 3


# --------------------------------------------------------------------------- divider y background/border de
# group/row (diseñador visual, Reportería) -- `background`/`border` por defecto en None/False para no afectar
# a ningún caller existente de group()/row() (resumen ejecutivo, evidencia, Suite...).

def test_group_and_row_without_background_or_border_render_unchanged():
    doc = rd.doc('Reporte', [rd.group([rd.text('a')]), rd.row([{'span': 12, 'children': [rd.text('b')]}])])
    html = report_render.render_html(doc)
    assert '<div class="group">' in html   # sin estilo inline -- el .group de HTML_CSS sigue gobernando solo
    assert 'style="background' not in html and 'border:1px solid #d1d5db"' not in html


def test_group_with_background_and_border_renders_inline_style_in_html_only():
    doc = rd.doc('Reporte', [rd.group([rd.text('a')], background='#fff7ed', border=True)])
    html = report_render.render_html(doc)
    assert 'background:#fff7ed' in html and 'border:1px solid #d1d5db' in html
    assert '#fff7ed' not in report_render.render_markdown(doc)


def test_divider_renders_as_hr_in_html_and_separator_in_markdown():
    doc = rd.doc('Reporte', [rd.divider(thickness=3, color='#2563eb')])
    html = report_render.render_html(doc)
    assert '<hr' in html and 'border-top:3px solid #2563eb' in html
    assert '---' in report_render.render_markdown(doc)


def test_vertical_divider_has_no_markdown_equivalent_and_is_omitted():
    doc = rd.doc('Reporte', [rd.divider(orientation='vertical')])
    assert '---' not in report_render.render_markdown(doc)
    assert 'border-left' in report_render.render_html(doc)


def test_divider_renders_as_a_bottom_border_paragraph_in_docx():
    import io
    from docx import Document
    doc = rd.doc('Reporte', [rd.text('antes'), rd.divider(), rd.text('despues')])
    document = Document(io.BytesIO(report_render.render_docx(doc)))
    texts = [p.text for p in document.paragraphs]
    assert 'antes' in texts and 'despues' in texts
    # el párrafo de la línea es uno vacío, entre los otros dos, con el borde inferior agregado por XML
    divider_index = texts.index('antes') + 1
    assert texts[divider_index] == ''
