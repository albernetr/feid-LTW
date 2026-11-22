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
