"""Reportes de salida de la Especificación: HU sola, Matriz de trazabilidad y el previsualizador de plantillas
(spec_report.py), en los tres formatos (HTML/Markdown/Word)."""
import pytest
from app import core, spec_report


@pytest.fixture
def world():
    project = core.create_project('Especificación reportes')
    pid = project['id']
    story = core.create_user_story('Recuperar contraseña', pid, as_a='usuario', i_want='recuperar acceso', so_that='no perder mis datos',
                                   priority='high', criteria=[{'text': 'Se envía un email', 'status': 'met'}, {'text': 'El link expira', 'status': 'pending'}])
    env = core.save('environments', {'name': 'local', 'project_id': pid, 'base_url': 'http://x', 'auth': {'type': 'none'}, 'variables': {}})
    api_case = core.save('cases', {'name': 'Pedir recuperación', 'method': 'GET', 'path': '/recover', 'project_id': pid, 'environment_id': env['id'],
                                   'headers': {}, 'query': {}, 'body': None, 'assertions': [], 'variables': {}, 'extract': [], 'timeout': 10})
    manual_spec = core.create_test_case_spec('Enviar email de recuperación', pid, story_id=story['id'], preconditions='cuenta activa',
                                              steps=[{'action': 'pedir recuperación', 'expected': 'llega el email'}], priority='high', type='functional')
    automated_spec = core.create_test_case_spec('Rechazar email inválido', pid, story_id=story['id'], linked_case_id=api_case['id'])
    core.save('runs', {'type': 'api', 'case_id': api_case['id'], 'status': 'failed', 'started_at': core.now(), 'assertions': []})
    return {'pid': pid, 'story': story, 'manual_spec': manual_spec, 'automated_spec': automated_spec}


def _template(name):
    return next(t for t in core.list_items('spec_templates') if t['name'] == name)


def _flatten(sections):
    """Historia de usuario (INVEST) y Caso de prueba (ISTQB) ahora agrupan sus campos fijos en secciones
    (ver core.DEFAULT_SPEC_TEMPLATES/core.template_top_level_groups) — aplana recursivamente para poder seguir
    indexando por 'field' como antes, sin que un nodo 'group' (sin esa clave) rompa el dict comprehension."""
    flat = {}
    for s in sections:
        if s.get('kind') == 'group':
            flat.update(_flatten(s['children']))
        else:
            flat[s['field']] = s['content']
    return flat


def test_build_story_report_data_resolves_every_known_field(world):
    tpl = _template('Especificación detallada')
    data = spec_report.build_story_report_data(world['story'], tpl)
    assert data['format'] == 'ltw.spec_report/1' and data['sample'] is False
    sections = {s['field']: s['content'] for s in data['sections']}
    assert sections['story']['title'] == 'Recuperar contraseña' and sections['story']['as_a'] == 'usuario'
    assert [c['text'] for c in sections['criteria']] == ['Se envía un email', 'El link expira']
    titles = {tc['title'] for tc in sections['test_cases']}
    assert titles == {'Enviar email de recuperación', 'Rechazar email inválido'}
    rows = {r['case']: r['status'] for r in sections['traceability']}
    assert rows['Rechazar email inválido'] == 'Falló'          # última corrida real del Caso ligado
    assert rows['Enviar email de recuperación'] == 'Borrador'  # nunca automatizado: cae al estado del propio spec


def test_build_story_report_data_summary_coverage_and_risks(world):
    tpl = _template('Reporte ejecutivo')
    data = spec_report.build_story_report_data(world['story'], tpl)
    sections = {s['field']: s['content'] for s in data['sections']}
    assert '1/2 criterio(s) cumplido(s)' in sections['summary'] and '2 caso(s) de prueba' in sections['summary']
    assert sections['coverage'] == {'total': 2, 'automated': 1, 'passing': 0}
    assert any('El link expira' in r for r in sections['risks'])
    assert any('Rechazar email inválido' in r and 'failed' in r for r in sections['risks'])


def test_build_story_report_data_without_a_template_uses_the_default_body():
    data = spec_report.build_story_report_data(None)   # sample mode
    assert data['sample'] is True
    assert {s['field'] for s in data['sections']} == {'story', 'criteria', 'test_cases', 'traceability'}
    assert data['title'] == spec_report.PLACEHOLDER_STORY['title']


def test_build_test_matrix_report_data_aggregates_every_story_in_the_project(world):
    other = core.create_user_story('Otra historia', world['pid'], criteria=[{'text': 'algo', 'status': 'pending'}])
    core.create_test_case_spec('Caso de la otra', world['pid'], story_id=other['id'])
    tpl = _template('Matriz de trazabilidad')
    data = spec_report.build_test_matrix_report_data(world['pid'], tpl)
    assert data['sample'] is False
    rows = data['sections'][0]['content']
    assert {r['story'] for r in rows} == {'Recuperar contraseña', 'Otra historia'}
    assert {r['case'] for r in rows} == {'Enviar email de recuperación', 'Rechazar email inválido', 'Caso de la otra'}


def test_build_test_matrix_report_data_with_no_stories_is_not_an_error():
    project = core.create_project('Sin historias')
    data = spec_report.build_test_matrix_report_data(project['id'])
    assert data['sections'][0]['content'] == []


def test_build_template_preview_for_a_test_case_template_uses_placeholder_steps():
    tpl = _template('Caso de prueba (ISTQB)')
    data = spec_report.build_template_preview(tpl)
    assert data['sample'] is True and data['kind'] == 'test_case'
    sections = _flatten(data['sections'])
    assert sections['preconditions'] and sections['steps']


def test_build_template_preview_for_a_user_story_template(world):
    tpl = _template('Historia de usuario (INVEST)')
    sample = spec_report.build_template_preview(tpl)
    assert sample['sample'] is True
    real = spec_report.build_template_preview(tpl, story=world['story'])
    assert real['sample'] is False and real['title'] == 'Recuperar contraseña'
    sections = _flatten(real['sections'])
    assert sections['as_a'] == 'usuario' and [c['text'] for c in sections['criteria']] == ['Se envía un email', 'El link expira']


def test_build_template_preview_for_a_free_format_template_shows_not_applicable():
    tpl = _template('Formato libre')
    data = spec_report.build_template_preview(tpl)
    assert data['sections'][0]['field'] == 'content' and data['sections'][0]['content'] is None


def test_build_template_preview_for_an_output_template_delegates_to_the_story_report():
    tpl = _template('Especificación detallada')
    data = spec_report.build_template_preview(tpl)
    assert data['kind'] == 'story' and data['sample'] is True


@pytest.mark.parametrize('render', [spec_report.render_spec_html, spec_report.render_spec_markdown])
def test_renderers_cover_every_content_shape_without_crashing(world, render):
    for template_name in ('Especificación detallada', 'Reporte ejecutivo', 'Matriz de trazabilidad'):
        tpl = _template(template_name)
        data = spec_report.build_story_report_data(world['story'], tpl) if template_name != 'Matriz de trazabilidad' \
            else spec_report.build_test_matrix_report_data(world['pid'], tpl)
        output = render(data)
        assert data['title'] in output if isinstance(output, str) else data['title'].encode('utf-8') in output


def test_render_spec_html_marks_a_sample_report():
    data = spec_report.build_story_report_data(None)
    assert 'datos de ejemplo' in spec_report.render_spec_html(data)
    assert 'datos de ejemplo' in spec_report.render_spec_markdown(data)


def test_render_spec_docx_does_not_crash_on_every_section_shape(world):
    tpl = _template('Especificación detallada')
    data = spec_report.build_story_report_data(world['story'], tpl)
    content = spec_report.render_spec_docx(data)
    assert content[:2] == b'PK'   # .docx es un zip


def test_render_spec_pdf_uses_reporting_render_pdf(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(spec_report.reporting, 'render_pdf', lambda html_text, destination: calls.append((html_text, destination)))
    spec_report.render_spec_pdf('<html></html>', tmp_path / 'r.pdf')
    assert calls and calls[0][0] == '<html></html>'


# --------------------------------------------------------------------------- Rediseño de Plantillas: campos
# tipados custom, secciones/subsecciones, layout de dos columnas y as_tab (ver core.py y el nuevo
# _build_tree_sections/_render_sections_*/_write_sections_docx).

def _output_template_with_custom_fields(pid):
    return core.create_spec_template('Con campos custom', 'output', 'report', project_id=pid, body=[
        {'kind': 'field', 'label': 'Historia de usuario', 'field_key': 'story'},
        {'kind': 'group', 'label': 'Contexto adicional', 'as_tab': True, 'children': [
            {'kind': 'field', 'label': 'Presupuesto', 'field_key': 'presupuesto', 'field_type': 'text', 'width': 'half'},
            {'kind': 'field', 'label': 'Riesgo extra', 'field_key': 'riesgo_extra', 'field_type': 'textarea', 'width': 'half'},
            {'kind': 'field', 'label': 'Checklist', 'field_key': 'checklist', 'field_type': 'list'},
            {'kind': 'field', 'label': 'Matriz propia', 'field_key': 'matriz_propia', 'field_type': 'table'},
            {'kind': 'field', 'label': 'Captura', 'field_key': 'captura', 'field_type': 'image'},
            {'kind': 'field', 'label': 'Anexo', 'field_key': 'anexo', 'field_type': 'attachment'}]},
    ])


def _custom_fields_sample():
    file_ref = core.save_custom_field_file(b'fake-png-bytes', 'captura.png', content_type='image/png')
    attach_ref = core.save_custom_field_file(b'fake-pdf-bytes', 'anexo.pdf', content_type='application/pdf')
    return {'presupuesto': '5000 USD', 'riesgo_extra': 'Proveedor único de email', 'checklist': [{'text': 'Aprobado por legal', 'done': True}],
           'matriz_propia': {'headers': ['Riesgo', 'Impacto'], 'rows': [['Latencia', 'Alto']]}, 'captura': file_ref, 'anexo': attach_ref}


def test_custom_field_types_resolve_and_render_in_html_markdown_and_docx(world):
    tpl = _output_template_with_custom_fields(world['pid'])
    s0 = world['story']
    story = core.update_user_story(s0['id'], s0['title'], s0['as_a'], s0['i_want'], s0['so_that'], criteria=s0['criteria'],
                                   custom_fields=_custom_fields_sample())
    data = spec_report.build_story_report_data(story, tpl)

    group = next(s for s in data['sections'] if s['kind'] == 'group')
    assert group['label'] == 'Contexto adicional' and group['as_tab'] is True
    by_field = {c['field']: c for c in group['children']}
    assert by_field['presupuesto']['content'] == '5000 USD' and by_field['presupuesto']['width'] == 'half'
    assert by_field['checklist']['content'] == [{'text': 'Aprobado por legal', 'done': True}]
    assert by_field['matriz_propia']['content']['headers'] == ['Riesgo', 'Impacto']
    assert by_field['captura']['content']['filename'] == 'captura.png'
    assert by_field['anexo']['content']['filename'] == 'anexo.pdf'

    html_out = spec_report.render_spec_html(data)
    assert '5000 USD' in html_out and 'Proveedor único de email' in html_out and 'Aprobado por legal' in html_out
    assert '<table>' in html_out and 'Latencia' in html_out
    assert '<img src="/evidence/' in html_out and 'captura.png' in html_out
    assert 'anexo.pdf' in html_out

    md_out = spec_report.render_spec_markdown(data)
    assert '5000 USD' in md_out and '| Riesgo | Impacto |' in md_out and '![captura.png]' in md_out and '[anexo.pdf]' in md_out

    docx_bytes = spec_report.render_spec_docx(data)
    assert docx_bytes[:2] == b'PK'


def test_custom_field_value_shape_mismatch_is_treated_as_empty_not_a_crash(world):
    """Si una plantilla distinta guardó otro tipo bajo la misma field_key, el valor existente no matchea la
    forma que este field_type espera — se trata como vacío, nunca revienta (ver _validate_custom_value)."""
    tpl = _output_template_with_custom_fields(world['pid'])
    s0 = world['story']
    story = core.update_user_story(s0['id'], s0['title'], s0['as_a'], s0['i_want'], s0['so_that'], criteria=s0['criteria'],
                                   custom_fields={'presupuesto': {'headers': [], 'rows': []}, 'matriz_propia': 'no es una tabla'})
    data = spec_report.build_story_report_data(story, tpl)
    group = next(s for s in data['sections'] if s['kind'] == 'group')
    by_field = {c['field']: c for c in group['children']}
    assert by_field['presupuesto']['content'] is None   # un dict donde se esperaba un string: vacío, no error
    assert by_field['matriz_propia']['content'] is None   # un string donde se esperaba {headers, rows}: vacío
    for render in (spec_report.render_spec_html, spec_report.render_spec_markdown):
        render(data)   # no debe reventar
    assert spec_report.render_spec_docx(data)[:2] == b'PK'


def test_width_half_pairs_consecutive_siblings_into_a_two_column_row_in_html():
    rows = spec_report._pair_rows([
        {'width': 'half', 'field': 'a'}, {'width': 'half', 'field': 'b'}, {'width': 'full', 'field': 'c'}, {'width': 'half', 'field': 'd'}])
    assert [len(r) for r in rows] == [2, 1, 1]
    assert [n['field'] for n in rows[0]] == ['a', 'b'] and rows[1][0]['field'] == 'c' and rows[2][0]['field'] == 'd'


def test_as_tab_group_metadata_survives_into_the_built_report_tree(world):
    tpl = _output_template_with_custom_fields(world['pid'])
    data = spec_report.build_story_report_data(world['story'], tpl)
    group = next(s for s in data['sections'] if s['kind'] == 'group')
    assert group['as_tab'] is True
    assert {c['field'] for c in group['children']} == {'presupuesto', 'riesgo_extra', 'checklist', 'matriz_propia', 'captura', 'anexo'}


def test_build_test_case_report_data_resolves_preconditions_and_steps(world):
    data = spec_report.build_test_case_report_data(world['manual_spec'])
    sections = {s['field']: s['content'] for s in data['sections']}
    assert sections['preconditions'] == 'cuenta activa'
    [tc] = sections['steps']
    assert tc['title'] == 'Enviar email de recuperación'
    assert spec_report.render_spec_html(data) and spec_report.render_spec_markdown(data)
    assert spec_report.render_spec_docx(data)[:2] == b'PK'
