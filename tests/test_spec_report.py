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
    sections = {s['field']: s['content'] for s in data['sections']}
    assert sections['preconditions'] and sections['steps'] and sections['expected']


def test_build_template_preview_for_a_user_story_template(world):
    tpl = _template('Historia de usuario (INVEST)')
    sample = spec_report.build_template_preview(tpl)
    assert sample['sample'] is True
    real = spec_report.build_template_preview(tpl, story=world['story'])
    assert real['sample'] is False and real['title'] == 'Recuperar contraseña'
    sections = {s['field']: s['content'] for s in real['sections']}
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
