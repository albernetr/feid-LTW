"""Diseñador visual de reportes (Reportería, Fase 1 — contenedores tipo Dreamweaver/Webflow): core.py
(report_layouts, CRUD + limpieza del árbol) y app/pages/report_designer.py (layout_to_blocks, la traducción
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


def test_create_report_layout_discards_an_unrecognized_node_kind(project):
    """Un kind que core.LAYOUT_NODE_KINDS no reconoce se descarta en silencio (mismo criterio que
    _clean_template_node con un nodo irreconocible), no rompe el guardado."""
    layout = core.create_report_layout('x', 'report', project['id'], body=[{'kind': 'bogus', 'children': []}])
    assert layout['body'] == []


def test_create_report_layout_discards_a_repeat_node_without_field_key(project):
    layout = core.create_report_layout('x', 'report', project['id'], body=[{'kind': 'repeat', 'children': []}])
    assert layout['body'] == []


def test_create_report_layout_keeps_a_repeat_node_and_cleans_its_children(project):
    body = [{'kind': 'repeat', 'field_key': 'pasos', 'children': [
        {'kind': 'field', 'source': 'row', 'column_index': 1},
        {'kind': 'field'},  # sin field_key y sin column_index -- se descarta
    ]}]
    layout = core.create_report_layout('x', 'report', project['id'], body=body)
    node = layout['body'][0]
    assert node['kind'] == 'repeat' and node['field_key'] == 'pasos'
    assert len(node['children']) == 1
    assert node['children'][0] == {'id': node['children'][0]['id'], 'kind': 'field', 'col_span': 12,
                                   'source': 'row', 'column_index': 1, 'label': 'Columna 2'}


def test_create_report_layout_discards_a_row_field_with_a_negative_column_index(project):
    body = [{'kind': 'field', 'source': 'row', 'column_index': -1}]
    layout = core.create_report_layout('x', 'report', project['id'], body=body)
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


def testlayout_to_blocks_builds_row_group_table_and_divider():
    blocks = design.layout_to_blocks(_nested_tree())
    assert len(blocks) == 1 and blocks[0]['kind'] == 'row'
    row_block = blocks[0]
    assert row_block['background'] == '#eee' and row_block['border'] is True
    assert row_block['cells'][0]['span'] == 6 and row_block['cells'][0]['children'][0]['kind'] == 'table'
    nested_group = row_block['cells'][1]['children'][0]
    assert nested_group['kind'] == 'group' and nested_group['children'][0]['kind'] == 'divider'


def test_layout_export_html_renders_the_grid_background_and_the_divider():
    doc = rd.doc('Diseño', design.layout_to_blocks(_nested_tree()))
    html = report_render.render_html(doc)
    assert 'display:grid' in html and 'background:#eee' in html and '<hr' in html


def test_layout_export_markdown_degrades_sequentially():
    """Markdown no distingue fila/columna ni fondo/borde -- todo secuencial, la línea se degrada a `---`."""
    doc = rd.doc('Diseño', design.layout_to_blocks(_nested_tree()))
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


def testlayout_to_blocks_builds_heading_text_file_list_and_checks():
    blocks = design.layout_to_blocks(_text_image_list_checklist_tree())
    assert blocks[0] == {'kind': 'heading', 'text': 'Encabezado', 'level': 2}
    assert blocks[1] == {'kind': 'text', 'text': 'Parrafo libre'}
    assert blocks[2]['kind'] == 'text' and 'sin subir' in blocks[2]['text']   # placeholder: imagen sin subir
    assert blocks[3]['kind'] == 'file' and blocks[3]['image'] is True and 'abc123' in blocks[3]['url']
    assert blocks[4] == {'kind': 'list', 'items': ['uno', 'dos'], 'ordered': False}
    assert blocks[5]['kind'] == 'checks'
    assert blocks[5]['items'] == [{'label': 'Opcion A', 'ok': True}, {'label': 'Opcion B', 'ok': False}]


def test_layout_export_html_and_markdown_render_text_list_and_checks():
    doc = rd.doc('Diseño', design.layout_to_blocks(_text_image_list_checklist_tree()))
    html = report_render.render_html(doc)
    assert '<h3>Encabezado</h3>' in html and 'Parrafo libre' in html and 'Opcion A' in html
    md = report_render.render_markdown(doc)
    assert '- uno' in md and '✓ Opcion A' in md and '✗ Opcion B' in md


# --------------------------------------------------------------------------- Fase 3: 'field' dinámico
# (catálogo fijo + campos propios de la Plantilla de entrada asociada al diseño) y `table` en modo 'field'.

@pytest.fixture
def input_template(project):
    return core.create_spec_template('HU con presupuesto', 'input', 'user_story', project_id=project['id'], body=[
        {'kind': 'field', 'label': 'Presupuesto', 'field_key': 'presupuesto', 'field_type': 'text'},
        {'kind': 'field', 'label': 'Matriz de riesgos', 'field_key': 'matriz_riesgos', 'field_type': 'table'},
    ])


@pytest.fixture
def story(project):
    return core.create_user_story('Mi historia', project['id'], 'Como tester', 'quiero probar', 'para validar',
                                  custom_fields={'presupuesto': '5000 USD',
                                                 'matriz_riesgos': {'headers': ['Riesgo', 'Impacto'], 'rows': [['Caida del server', 'Alto']]}})


def test_create_report_layout_cleans_a_field_node_and_discards_one_without_field_key(project):
    layout = core.create_report_layout('x', 'user_story', project['id'], body=[
        {'kind': 'field', 'source': 'fixed', 'field_key': 'as_a', 'label': 'Como (rol)'},
        {'kind': 'field', 'source': 'template', 'field_key': ''},
    ])
    assert len(layout['body']) == 1
    node = layout['body'][0]
    assert node == {'id': node['id'], 'kind': 'field', 'col_span': 12, 'source': 'fixed', 'field_key': 'as_a', 'label': 'Como (rol)'}


def test_create_report_layout_cleans_a_table_in_field_mode_and_discards_one_without_field_key(project):
    layout = core.create_report_layout('x', 'user_story', project['id'], body=[
        {'kind': 'table', 'mode': 'field', 'field_key': 'matriz_riesgos', 'label': 'Matriz de riesgos'},
        {'kind': 'table', 'mode': 'field', 'field_key': ''},
    ])
    assert len(layout['body']) == 1
    assert layout['body'][0] == {'id': layout['body'][0]['id'], 'kind': 'table', 'col_span': 12, 'mode': 'field',
                                'field_key': 'matriz_riesgos', 'label': 'Matriz de riesgos'}


def test_create_report_layout_keeps_a_literal_table_mode(project):
    layout = core.create_report_layout('x', 'report', project['id'], body=[
        {'kind': 'table', 'headers': ['A', 'B'], 'rows': [['1', '2']]},
    ])
    assert layout['body'][0]['mode'] == 'literal' and layout['body'][0]['headers'] == ['A', 'B']


def test_input_template_id_is_cleaned_when_invalid_or_mismatched(project, input_template):
    other_project = core.create_project('Otro proyecto')
    # applies_to no coincide con el de la plantilla (user_story) -- se descarta
    layout = core.create_report_layout('x', 'test_case', project['id'], input_template_id=input_template['id'])
    assert layout['input_template_id'] is None
    # la plantilla no es de este proyecto -- se descarta
    layout2 = core.create_report_layout('y', 'user_story', other_project['id'], input_template_id=input_template['id'])
    assert layout2['input_template_id'] is None
    # coincide applies_to y proyecto -- se conserva
    layout3 = core.create_report_layout('z', 'user_story', project['id'], input_template_id=input_template['id'])
    assert layout3['input_template_id'] == input_template['id']


def test_field_catalog_adds_the_associated_template_custom_fields(input_template):
    catalog = design._field_catalog('user_story', input_template)
    assert 'as_a' in catalog and catalog['presupuesto'] == 'Presupuesto'
    # sin plantilla asociada, solo quedan los fijos
    assert 'presupuesto' not in design._field_catalog('user_story', None)


def test_table_field_catalog_only_lists_table_type_custom_fields(input_template):
    assert design._table_field_catalog(input_template) == {'matriz_riesgos': 'Matriz de riesgos'}
    assert design._table_field_catalog(None) == {}


def testlayout_to_blocks_field_uses_lorem_ipsum_without_a_preview_record():
    body = [{'kind': 'field', 'source': 'fixed', 'field_key': 'as_a', 'label': 'Como (rol)'}]
    blocks = design.layout_to_blocks(body, record=None)
    assert blocks == [{'kind': 'text', 'text': design._LOREM}]


def testlayout_to_blocks_field_uses_the_real_value_when_a_record_is_selected(story):
    fixed = [{'kind': 'field', 'source': 'fixed', 'field_key': 'as_a', 'label': 'Como (rol)'}]
    assert design.layout_to_blocks(fixed, record=story) == [{'kind': 'text', 'text': 'Como tester'}]
    template_field = [{'kind': 'field', 'source': 'template', 'field_key': 'presupuesto', 'label': 'Presupuesto'}]
    assert design.layout_to_blocks(template_field, record=story) == [{'kind': 'text', 'text': '5000 USD'}]


def testlayout_to_blocks_table_field_mode_falls_back_to_a_labeled_placeholder(story):
    body = [{'kind': 'table', 'mode': 'field', 'field_key': 'matriz_riesgos', 'label': 'Matriz de riesgos'}]
    assert design.layout_to_blocks(body, record=None) == [{'kind': 'table', 'columns': ['Matriz de riesgos', 'Matriz de riesgos'], 'rows': []}]
    assert design.layout_to_blocks(body, record=story) == [{'kind': 'table', 'columns': ['Riesgo', 'Impacto'], 'rows': [['Caida del server', 'Alto']]}]


def _repeat_body():
    return [{'kind': 'repeat', 'field_key': 'matriz_riesgos', 'children': [
        {'kind': 'field', 'source': 'row', 'column_index': 0, 'label': 'Columna 1'},
        {'kind': 'field', 'source': 'row', 'column_index': 1, 'label': 'Columna 2'},
    ]}]


def test_layout_to_blocks_repeat_clones_children_once_per_real_row(story):
    blocks = design.layout_to_blocks(_repeat_body(), record=story)
    assert blocks == [{'kind': 'group', 'children': [
        {'kind': 'text', 'text': 'Caida del server'},
        {'kind': 'text', 'text': 'Alto'},
    ], 'indent': False, 'background': None, 'border': False}]


def test_layout_to_blocks_repeat_renders_one_placeholder_pass_without_real_rows():
    """Sin registro (o sin filas reales todavía) nunca queda vacío: una sola pasada de los hijos, cada
    'field' source='row' cae a su lorem ipsum, igual que cualquier otro 'field' sin dato."""
    blocks = design.layout_to_blocks(_repeat_body(), record=None)
    assert blocks == [{'kind': 'group', 'children': [
        {'kind': 'text', 'text': design._LOREM},
        {'kind': 'text', 'text': design._LOREM},
    ], 'indent': False, 'background': None, 'border': False}]


def test_layout_to_blocks_repeat_with_several_rows_separates_them_with_a_divider(project):
    story_with_two_rows = core.create_user_story('Otra', project['id'], 'Como x', 'quiero y', 'para z', custom_fields={
        'matriz_riesgos': {'headers': ['Riesgo', 'Impacto'], 'rows': [['A', 'B'], ['C', 'D']]}})
    blocks = design.layout_to_blocks(_repeat_body(), record=story_with_two_rows)
    assert len(blocks) == 1 and blocks[0]['kind'] == 'group'
    children = blocks[0]['children']
    assert children[0] == {'kind': 'text', 'text': 'A'}
    assert children[1] == {'kind': 'text', 'text': 'B'}
    assert children[2]['kind'] == 'divider'
    assert children[3] == {'kind': 'text', 'text': 'C'}
    assert children[4] == {'kind': 'text', 'text': 'D'}


def test_layout_to_blocks_row_field_falls_back_to_lorem_outside_a_repeat():
    """Un 'field' source='row' fuera de cualquier 'repeat' (row=None siempre) también degrada a lorem ipsum,
    nunca revienta -- el mismo criterio de respaldo del resto de 'field'."""
    body = [{'kind': 'field', 'source': 'row', 'column_index': 0, 'label': 'Columna 1'}]
    assert design.layout_to_blocks(body, record=None) == [{'kind': 'text', 'text': design._LOREM}]


# --------------------------------------------------------------------------- Fase 4: DOCX con encabezado/pie
# nativo de sección (se repite en cada página impresa de verdad, igual que ya hace render_layout_pdf).

def test_layout_docx_produces_a_valid_document_with_header_and_footer():
    header_blocks = [rd.text('Encabezado de prueba')]
    footer_blocks = [rd.text('Pie de página de prueba')]
    body_doc = rd.doc('Diseño', [rd.heading('Cuerpo', level=2), rd.text('Contenido del cuerpo')])
    content = report_render.render_layout_docx(header_blocks, body_doc, footer_blocks)
    assert content[:2] == b'PK'   # un .docx es un zip (python-docx no firma con %PDF)

    from docx import Document
    document = Document(__import__('io').BytesIO(content))
    section = document.sections[0]
    assert 'Encabezado de prueba' in section.header.paragraphs[0].text
    assert 'Pie de página de prueba' in section.footer.paragraphs[0].text
    assert any('Contenido del cuerpo' in p.text for p in document.paragraphs)


def test_layout_docx_works_without_header_or_footer():
    body_doc = rd.doc('Diseño corto', [rd.text('Sin encabezado ni pie')])
    content = report_render.render_layout_docx([], body_doc, [])
    assert content[:2] == b'PK'


# --------------------------------------------------------------------------- Fase 4: `table` en modo
# 'listing' (una fila por cada registro REAL del proyecto -- reporte simple tipo "listado de HUs").

def test_create_report_layout_cleans_a_listing_table_and_discards_one_without_columns(project):
    layout = core.create_report_layout('x', 'user_story', project['id'], body=[
        {'kind': 'table', 'mode': 'listing', 'columns': [
            {'field_key': 'title', 'source': 'fixed', 'label': 'Título'},
            {'field_key': ''},  # sin field_key -- se descarta esta columna puntual
        ]},
        {'kind': 'table', 'mode': 'listing', 'columns': []},  # sin ninguna columna -- se descarta el nodo
    ])
    assert len(layout['body']) == 1
    node = layout['body'][0]
    assert node['mode'] == 'listing'
    assert node['columns'] == [{'field_key': 'title', 'source': 'fixed', 'label': 'Título'}]


def test_layout_to_blocks_listing_table_lists_every_real_project_record(project):
    core.create_user_story('Primera', project['id'], 'Como a', 'quiero b', 'para c')
    core.create_user_story('Segunda', project['id'], 'Como x', 'quiero y', 'para z')
    body = [{'kind': 'table', 'mode': 'listing', 'columns': [{'field_key': 'title', 'source': 'fixed', 'label': 'Título'}]}]
    blocks = design.layout_to_blocks(body, applies_to='user_story', project_id=project['id'])
    assert len(blocks) == 1 and blocks[0]['kind'] == 'table' and blocks[0]['columns'] == ['Título']
    assert sorted(blocks[0]['rows']) == [['Primera'], ['Segunda']]


def test_layout_to_blocks_listing_table_is_empty_without_a_project_id():
    body = [{'kind': 'table', 'mode': 'listing', 'columns': [{'field_key': 'title', 'source': 'fixed', 'label': 'Título'}]}]
    assert design.layout_to_blocks(body, applies_to='user_story', project_id=None) == [{'kind': 'table', 'columns': ['Título'], 'rows': []}]


# --------------------------------------------------------------------------- Fase 5: `related` (clona por
# cada Caso de prueba REAL asociado a la Historia de usuario del registro, vía core.story_coverage).

def test_create_report_layout_cleans_a_related_node_and_a_field_with_source_related(project):
    layout = core.create_report_layout('x', 'user_story', project['id'], body=[
        {'kind': 'related', 'children': [
            {'kind': 'field', 'source': 'related', 'field_key': 'steps'},
            {'kind': 'field', 'source': 'related'},  # sin field_key -- se descarta
        ]},
    ])
    node = layout['body'][0]
    assert node['kind'] == 'related'
    assert len(node['children']) == 1
    assert node['children'][0] == {'id': node['children'][0]['id'], 'kind': 'field', 'col_span': 12,
                                   'source': 'related', 'field_key': 'steps', 'label': 'steps'}


@pytest.fixture
def story_with_cases(story):
    core.create_test_case_spec('Caso válido', story['project_id'], story_id=story['id'], priority='high',
                               steps=[{'action': 'Ingresar usuario y clave', 'expected': 'Se redirige al panel'}])
    core.create_test_case_spec('Caso sin corridas', story['project_id'], story_id=story['id'])
    return story


def test_layout_to_blocks_related_clones_once_per_real_linked_test_case(story_with_cases):
    body = [{'kind': 'related', 'children': [
        {'kind': 'field', 'source': 'related', 'field_key': 'title', 'label': 'Título'},
        {'kind': 'field', 'source': 'related', 'field_key': '_last_run_status', 'label': 'Estado'},
    ]}]
    blocks = design.layout_to_blocks(body, record=story_with_cases, applies_to='user_story')
    assert len(blocks) == 1 and blocks[0]['kind'] == 'group'
    children = blocks[0]['children']
    titles = [b['text'] for b in children if b['kind'] == 'text' and b['text'] in ('Caso válido', 'Caso sin corridas')]
    assert sorted(titles) == ['Caso sin corridas', 'Caso válido']
    assert any(b.get('text') == 'Sin corridas' for b in children)   # ninguno de los dos casos tiene una corrida real


def test_layout_to_blocks_related_steps_render_as_a_bullet_list(story_with_cases):
    body = [{'kind': 'related', 'children': [{'kind': 'field', 'source': 'related', 'field_key': 'steps', 'label': 'Pasos'}]}]
    blocks = design.layout_to_blocks(body, record=story_with_cases, applies_to='user_story')
    lists = [b for b in blocks[0]['children'] if b['kind'] == 'list']
    assert any(item == 'Ingresar usuario y clave → Se redirige al panel' for b in lists for item in b['items'])
    assert any(b['kind'] == 'text' and b['text'] == design._LOREM for b in blocks[0]['children'])  # el caso sin pasos


def test_layout_to_blocks_related_is_a_single_placeholder_pass_without_a_record():
    body = [{'kind': 'related', 'children': [{'kind': 'field', 'source': 'related', 'field_key': 'title', 'label': 'Título'}]}]
    blocks = design.layout_to_blocks(body, record=None, applies_to='user_story')
    assert blocks == [{'kind': 'group', 'children': [{'kind': 'text', 'text': design._LOREM}], 'indent': False, 'background': None, 'border': False}]


def test_layout_to_blocks_related_is_a_single_placeholder_pass_for_test_case_applies_to(story_with_cases):
    """'related' solo tiene sentido con applies_to=='user_story' -- con cualquier otro valor, una sola
    pasada placeholder, igual que sin registro."""
    body = [{'kind': 'related', 'children': [{'kind': 'field', 'source': 'related', 'field_key': 'title', 'label': 'Título'}]}]
    blocks = design.layout_to_blocks(body, record=story_with_cases, applies_to='test_case')
    assert blocks == [{'kind': 'group', 'children': [{'kind': 'text', 'text': design._LOREM}], 'indent': False, 'background': None, 'border': False}]
