"""Diseñador visual de reportes (Reportería, Fase 1 — contenedores tipo Dreamweaver/Webflow): core.py
(report_layouts, CRUD + limpieza del árbol) y app/pages/report_designer.py (_layout_to_blocks, la traducción
a los bloques de report_doc.py que ya existen)."""
import pytest
from app import core, report_doc as rd, report_render
from app.pages import report_designer as design


@pytest.fixture
def project():
    return core.create_project('Demo Reportería')


def test_create_report_layout_cleans_the_container_tree(project):
    header = [{'kind': 'line', 'orientation': 'horizontal', 'thickness': 2, 'color': '#2563eb'}]
    body = [{'kind': 'container', 'direction': 'row', 'background': '#f3f4f6', 'border': True, 'children': [
        {'kind': 'table', 'col_span': 6, 'headers': ['A', 'B'], 'rows': [['1', '2']]},
        {'kind': 'table', 'col_span': 6, 'headers': ['C', 'D'], 'rows': []},
    ]}]
    layout = core.create_report_layout('Mi diseño', 'report', project['id'], header, body, [])
    assert layout['header'][0]['kind'] == 'line' and layout['header'][0]['thickness'] == 2
    row_node = layout['body'][0]
    assert row_node['kind'] == 'container' and row_node['direction'] == 'row' and row_node['border'] is True
    assert [c['col_span'] for c in row_node['children']] == [6, 6]
    assert row_node['children'][0]['rows'] == [['1', '2']]


def test_create_report_layout_discards_a_node_kind_not_supported_yet(project):
    """'field'/'image'/'repeat' se suman en fases siguientes -- hoy un nodo de ese kind se descarta en
    silencio (mismo criterio que _clean_template_node con un nodo irreconocible), no rompe el guardado."""
    layout = core.create_report_layout('x', 'report', project['id'], body=[{'kind': 'field', 'field_key': 'as_a'}])
    assert layout['body'] == []


def test_create_report_layout_requires_a_project():
    with pytest.raises(ValueError):
        core.create_report_layout('x', 'report', None)


def test_create_report_layout_validates_applies_to(project):
    with pytest.raises(ValueError):
        core.create_report_layout('x', 'bogus', project['id'])


def test_update_and_delete_report_layout(project):
    layout = core.create_report_layout('Mi diseño', 'report', project['id'])
    updated = core.update_report_layout(layout['id'], 'Otro nombre', 'user_story', [], [], [])
    assert updated['name'] == 'Otro nombre' and updated['applies_to'] == 'user_story'
    core.delete_report_layout(layout['id'])
    assert core.get('report_layouts', layout['id']) is None


def _nested_tree():
    """Fila (fondo + borde) con una tabla a la izquierda y, a la derecha, una columna anidada que contiene
    una línea -- ejercita container-fila, container-columna, table y line en un solo árbol."""
    return [
        {'kind': 'container', 'direction': 'row', 'col_span': 12, 'gap': 16, 'background': '#eee', 'border': True, 'children': [
            {'kind': 'table', 'col_span': 6, 'headers': ['A', 'B'], 'rows': [['1', '2']]},
            {'kind': 'container', 'direction': 'column', 'col_span': 6, 'children': [
                {'kind': 'line', 'orientation': 'horizontal', 'thickness': 1, 'color': '#d1d5db'},
            ]},
        ]},
    ]


def test_layout_to_blocks_builds_row_group_table_and_divider():
    blocks = design._layout_to_blocks(_nested_tree())
    assert len(blocks) == 1 and blocks[0]['kind'] == 'row'
    row_block = blocks[0]
    assert row_block['background'] == '#eee' and row_block['border'] is True
    assert row_block['cells'][0]['span'] == 6 and row_block['cells'][0]['children'][0]['kind'] == 'table'
    nested_group = row_block['cells'][1]['children'][0]
    assert nested_group['kind'] == 'group' and nested_group['children'][0]['kind'] == 'divider'


def test_layout_export_html_renders_the_grid_background_and_the_divider():
    doc = rd.doc('Diseño', design._layout_to_blocks(_nested_tree()))
    html = report_render.render_html(doc)
    assert 'display:grid' in html and 'background:#eee' in html and '<hr' in html


def test_layout_export_markdown_degrades_sequentially():
    """Markdown no distingue fila/columna ni fondo/borde -- todo secuencial, la línea se degrada a `---`."""
    doc = rd.doc('Diseño', design._layout_to_blocks(_nested_tree()))
    md = report_render.render_markdown(doc)
    assert '---' in md


def test_layout_pdf_accepts_header_and_footer_and_produces_a_valid_pdf(tmp_path):
    header_blocks = [rd.text('Encabezado de prueba')]
    footer_blocks = [rd.text('Pie de página de prueba')]
    body_doc = rd.doc('Diseño largo', [rd.heading(f'Sección {i}', level=2) for i in range(40)])
    target = tmp_path / 'r.pdf'
    report_render.render_layout_pdf(header_blocks, body_doc, footer_blocks, target)
    content = target.read_bytes()
    assert content[:4] == b'%PDF' and target.stat().st_size > 5_000


def test_layout_pdf_works_without_header_or_footer(tmp_path):
    body_doc = rd.doc('Diseño corto', [rd.text('Sin encabezado ni pie')])
    target = tmp_path / 'r.pdf'
    report_render.render_layout_pdf([], body_doc, [], target)
    assert target.read_bytes()[:4] == b'%PDF'


# --------------------------------------------------------------------------- Fase 2: elementos fijos
# text/image y list/checklist (adelantados desde la fase 3 al revisar plantillas de referencia reales).

def test_create_report_layout_cleans_text_image_list_and_checklist_nodes(project):
    body = [
        {'kind': 'text', 'value': 'Titulo', 'heading': True, 'level': 1},
        {'kind': 'image', 'file': {'id': 'abc', 'filename': 'logo.png', 'content_type': 'image/png', 'size': 10}, 'label': 'Logo'},
        {'kind': 'list', 'items': ['uno', 'dos', ''], 'ordered': True},
        {'kind': 'checklist', 'items': [{'label': 'Opcion A', 'checked': True}, {'label': '', 'checked': True}]},
    ]
    layout = core.create_report_layout('Fase 2', 'report', project['id'], body=body)
    text_node, image_node, list_node, checklist_node = layout['body']
    assert text_node == {'id': text_node['id'], 'kind': 'text', 'col_span': 12, 'value': 'Titulo', 'heading': True, 'level': 1}
    assert image_node['file']['filename'] == 'logo.png' and image_node['label'] == 'Logo'
    assert list_node['items'] == ['uno', 'dos'] and list_node['ordered'] is True   # el item vacío se descarta
    assert checklist_node['items'] == [{'label': 'Opcion A', 'checked': True}]   # la opción sin etiqueta se descarta


def test_create_report_layout_discards_an_image_file_ref_missing_id_or_filename(project):
    layout = core.create_report_layout('x', 'report', project['id'], body=[{'kind': 'image', 'file': {'filename': 'sin-id.png'}}])
    assert layout['body'][0]['file'] is None


def _text_image_list_checklist_tree():
    return [
        {'kind': 'text', 'value': 'Encabezado', 'heading': True, 'level': 2},
        {'kind': 'text', 'value': 'Parrafo libre', 'heading': False},
        {'kind': 'image', 'file': None, 'label': 'Logo'},
        {'kind': 'image', 'file': {'id': 'abc123', 'filename': 'logo.png'}, 'label': 'Logo'},
        {'kind': 'list', 'items': ['uno', 'dos'], 'ordered': False},
        {'kind': 'checklist', 'items': [{'label': 'Opcion A', 'checked': True}, {'label': 'Opcion B', 'checked': False}]},
    ]


def test_layout_to_blocks_builds_heading_text_file_list_and_checks():
    blocks = design._layout_to_blocks(_text_image_list_checklist_tree())
    assert blocks[0] == {'kind': 'heading', 'text': 'Encabezado', 'level': 2}
    assert blocks[1] == {'kind': 'text', 'text': 'Parrafo libre'}
    assert blocks[2]['kind'] == 'text' and 'sin subir' in blocks[2]['text']   # placeholder: imagen sin subir
    assert blocks[3]['kind'] == 'file' and blocks[3]['image'] is True and 'abc123' in blocks[3]['url']
    assert blocks[4] == {'kind': 'list', 'items': ['uno', 'dos'], 'ordered': False}
    assert blocks[5]['kind'] == 'checks'
    assert blocks[5]['items'] == [{'label': 'Opcion A', 'ok': True}, {'label': 'Opcion B', 'ok': False}]


def test_layout_export_html_and_markdown_render_text_list_and_checks():
    doc = rd.doc('Diseño', design._layout_to_blocks(_text_image_list_checklist_tree()))
    html = report_render.render_html(doc)
    assert '<h3>Encabezado</h3>' in html and 'Parrafo libre' in html and 'Opcion A' in html
    md = report_render.render_markdown(doc)
    assert '- uno' in md and '✓ Opcion A' in md and '✗ Opcion B' in md
