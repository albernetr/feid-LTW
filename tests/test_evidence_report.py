"""Evidencia descargable (HTML/PDF/Word) de una corrida real contra el sample_app."""
import pytest
from app import core, automation, evidence_report


@pytest.fixture
def world(sample_app):
    project = core.create_project('Evidencia')
    pid = project['id']
    env = core.save('environments', {'name': 'local', 'project_id': pid, 'base_url': sample_app.url, 'auth': {'type': 'none'}, 'variables': {}})

    def api_case(name, method, path, assertions, **extra):
        return core.save('cases', {'name': name, 'type': 'api', 'project_id': pid, 'method': method, 'path': path,
                                   'assertions': assertions, **extra})
    return {'app': sample_app, 'pid': pid, 'env': env, 'api_case': api_case}


def test_build_report_data_for_a_single_api_run(world):
    case = world['api_case']('health', 'GET', '/health', [{'type': 'status', 'expected': 200}])
    run = core.execute_api(case, world['env'])
    data = evidence_report.build_report_data(run)
    assert data['format'] == 'ltw.evidence/1'
    assert data['status'] == 'passed'
    assert data['summary'] == {'total': 1, 'passed': 1, 'failed': 0, 'skipped': 0}
    step = data['steps'][0]
    assert step['name'] == 'health' and step['type'] == 'api' and step['status'] == 'passed'
    assert step['request']['method'] == 'GET' and '/health' in step['request']['url']
    assert step['assertions'][0]['passed'] is True


def test_build_report_data_for_a_flow_marks_skipped_steps_without_hiding_them(world):
    """Un paso omitido en un retest parcial no debe ocultarse del reporte ni contarse como fallo."""
    login = world['api_case']('login', 'POST', '/api/login', [{'type': 'status', 'expected': 200}],
                              body={'user': 'qa', 'password': 'qa-pass'})
    create = world['api_case']('crear', 'POST', '/api/items', [{'type': 'status', 'expected': 201}],
                               headers={'Authorization': 'Bearer {{@login:$.token}}'}, body={'name': 'x'})
    suite = core.save_suite('con reintento', world['env']['id'], [login['id'], create['id']], world['pid'],
                            steps=[{'case_id': login['id'], 'alias': 'login', 'environment_id': None, 'enrich': []},
                                   {'case_id': create['id'], 'alias': 'crear', 'environment_id': None,
                                    'enrich': [{'action': 'set', 'target': 'headers', 'path': 'Authorization',
                                                'source': {'type': 'template', 'value': 'Bearer {{@login:$.token}}'}}]}])
    automation.execute_suite(suite)
    retest = automation.execute_suite(suite, only_aliases={'crear'})
    data = evidence_report.build_report_data(retest)
    statuses = {s['name']: s['status'] for s in data['steps']}
    assert statuses == {'login': 'skipped', 'crear': 'passed'}
    assert data['summary'] == {'total': 2, 'passed': 1, 'failed': 0, 'skipped': 1}


def test_build_report_data_for_a_suite_group_nests_flow_substeps(world):
    flow_case = world['api_case']('paso del flujo', 'GET', '/health', [{'type': 'status', 'expected': 200}])
    flow = core.save_suite('mini flujo', world['env']['id'], [flow_case['id']], world['pid'])
    loose_case = world['api_case']('caso suelto', 'GET', '/health', [{'type': 'status', 'expected': 200}])
    group = core.save_suite_group('mi suite', world['pid'], [{'type': 'flow', 'id': flow['id']}, {'type': 'case', 'id': loose_case['id']}],
                                  environment_id=world['env']['id'])
    result = automation.execute_suite_group(group)
    data = evidence_report.build_report_data(result)
    assert [s['name'] for s in data['steps']] == ['mini flujo', 'caso suelto']
    flow_step, case_step = data['steps']
    assert flow_step['type'] == 'flow' and flow_step['status'] == 'passed'
    assert flow_step['substeps'][0]['name'] == flow_case['name'] and flow_step['substeps'][0]['type'] == 'api'
    assert case_step['type'] == 'api' and 'request' in case_step


def test_render_evidence_html_contains_steps_and_status(world):
    case = world['api_case']('crear', 'POST', '/api/items', [{'type': 'status', 'expected': 201}],
                             headers={'Authorization': 'Bearer tok-abc123'}, body={'name': 'x'})
    run = core.execute_api(case, world['env'])
    data = evidence_report.build_report_data(run)
    html_out = evidence_report.render_evidence_html(data)
    assert 'crear' in html_out and 'Pasó' in html_out and '<!doctype html>' in html_out


def test_render_evidence_docx_is_a_valid_document(world):
    case = world['api_case']('crear', 'POST', '/api/items', [{'type': 'status', 'expected': 201}],
                             headers={'Authorization': 'Bearer tok-abc123'}, body={'name': 'x'})
    run = core.execute_api(case, world['env'])
    data = evidence_report.build_report_data(run)
    content = evidence_report.render_evidence_docx(data)
    from docx import Document
    import io
    doc = Document(io.BytesIO(content))
    headings = [p.text for p in doc.paragraphs if p.style.name.startswith('Heading')]
    assert any('crear' in h for h in headings)   # título del reporte
    assert any('Pasó' in h for h in headings)    # encabezado del paso, con su estado


def test_render_evidence_pdf_when_chromium_is_available(world, tmp_path):
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            p.chromium.launch(headless=True).close()
    except Exception:
        pytest.skip('Chromium no disponible en este entorno')
    case = world['api_case']('crear', 'POST', '/api/items', [{'type': 'status', 'expected': 201}],
                             headers={'Authorization': 'Bearer tok-abc123'}, body={'name': 'x'})
    run = core.execute_api(case, world['env'])
    data = evidence_report.build_report_data(run)
    target = tmp_path / 'evidencia.pdf'
    evidence_report.render_evidence_pdf(evidence_report.render_evidence_html(data), target)
    assert target.is_file() and target.stat().st_size > 500
