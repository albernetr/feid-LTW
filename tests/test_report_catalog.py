"""Catálogo de la sección "Reportes" (app/report_catalog.py): que el batch de cada tipo combine en UN solo
documento el contenido íntegro de cada item elegido, con un heading propio — no un resumen ni un recorte."""
import pytest
from app import core, report_catalog


@pytest.fixture
def world():
    project = core.create_project('Reportería catálogo')
    pid = project['id']
    env = core.save('environments', {'name': 'local', 'project_id': pid, 'base_url': 'http://x', 'auth': {'type': 'none'}, 'variables': {}})
    story_a = core.create_user_story('Iniciar sesión', pid, as_a='usuario', i_want='entrar', so_that='usar la app', priority='high')
    story_b = core.create_user_story('Cerrar sesión', pid, as_a='usuario', i_want='salir', so_that='proteger mi cuenta', priority='medium')
    tc_a = core.create_test_case_spec('Login válido', pid, story_id=story_a['id'], preconditions='cuenta activa',
                                       steps=[{'action': 'enviar credenciales', 'expected': 'entra'}])
    tc_b = core.create_test_case_spec('Login inválido', pid, story_id=story_a['id'], preconditions='cuenta activa',
                                       steps=[{'action': 'enviar credenciales malas', 'expected': 'rechaza'}])
    case_a = core.save('cases', {'name': 'Consultar salud', 'method': 'GET', 'path': '/health', 'project_id': pid, 'environment_id': env['id'],
                                 'headers': {}, 'query': {}, 'body': None, 'assertions': [], 'variables': {}, 'extract': [], 'timeout': 10})
    case_b = core.save('cases', {'name': 'Listar items', 'method': 'GET', 'path': '/items', 'project_id': pid, 'environment_id': env['id'],
                                 'headers': {}, 'query': {}, 'body': None, 'assertions': [], 'variables': {}, 'extract': [], 'timeout': 10})
    group = core.save_suite_group('Regresión', pid, [{'type': 'case', 'id': case_a['id']}], environment_id=env['id'])
    run_a = core.save('runs', {'type': 'api', 'case_id': case_a['id'], 'case_name': case_a['name'], 'project_id': pid, 'status': 'passed',
                               'started_at': core.now(), 'duration_ms': 10, 'assertions': []})
    run_b = core.save('runs', {'type': 'api', 'case_id': case_b['id'], 'case_name': case_b['name'], 'project_id': pid, 'status': 'failed',
                               'started_at': core.now(), 'duration_ms': 12, 'error': 'timeout', 'assertions': []})
    return {'pid': pid, 'story_a': story_a, 'story_b': story_b, 'tc_a': tc_a, 'tc_b': tc_b,
            'case_a': case_a, 'case_b': case_b, 'group': group, 'run_a': run_a, 'run_b': run_b}


def _titles(report_type):
    return next(rt for rt in report_catalog.REPORT_TYPES if rt.key == report_type)


def test_catalog_lists_every_report_type_once():
    keys = [rt.key for rt in report_catalog.REPORT_TYPES]
    assert keys == ['user_story', 'test_case', 'case', 'suite_group', 'evidence', 'matrix']
    assert len(keys) == len(set(keys))


def test_user_story_batch_doc_combines_both_stories_under_their_own_heading(world):
    rt = _titles('user_story')
    stories = rt.list_fn(world['pid'])   # orden: lo que devuelve list_fn (rowid DESC), no el de creación
    assert {s['id'] for s in stories} == {world['story_a']['id'], world['story_b']['id']}
    doc = rt.batch_doc_fn(stories)
    headings = [b['text'] for b in doc['blocks'] if b['kind'] == 'heading' and b['level'] == 1]
    assert headings == [s['title'] for s in stories]
    expected = []
    for story in stories:
        expected.append({'kind': 'heading', 'text': story['title'], 'level': 1})
        expected += rt.single_doc_fn(story)['blocks']
    assert doc['blocks'] == expected   # el contenido de cada HU entra íntegro, no resumido


def test_test_case_batch_doc_combines_both_specs(world):
    rt = _titles('test_case')
    specs = rt.list_fn(world['pid'])
    doc = rt.batch_doc_fn(specs)
    headings = {b['text'] for b in doc['blocks'] if b['kind'] == 'heading' and b['level'] == 1}
    assert headings == {'Login válido', 'Login inválido'}


def test_case_batch_doc_combines_both_cases_with_their_own_history(world):
    rt = _titles('case')
    cases = rt.list_fn(world['pid'])
    doc = rt.batch_doc_fn(cases)
    headings = {b['text'] for b in doc['blocks'] if b['kind'] == 'heading' and b['level'] == 1}
    assert headings == {'Consultar salud', 'Listar items'}
    assert any(b['kind'] == 'badge' for b in doc['blocks'])


def test_suite_group_batch_doc_with_a_single_group_matches_the_single_doc(world):
    rt = _titles('suite_group')
    groups = rt.list_fn(world['pid'])
    assert len(groups) == 1
    batch = rt.batch_doc_fn(groups)
    single = rt.single_doc_fn(groups[0])
    assert batch['blocks'] == [{'kind': 'heading', 'text': 'Regresión', 'level': 1}] + single['blocks']


def test_evidence_list_only_offers_leaf_runs_most_recent_first(world):
    rt = _titles('evidence')
    runs = rt.list_fn(world['pid'])
    assert [r['id'] for r in runs] == [world['run_b']['id'], world['run_a']['id']]


def test_evidence_batch_doc_combines_both_runs_in_one_report(world):
    rt = _titles('evidence')
    runs = rt.list_fn(world['pid'])
    doc = rt.batch_doc_fn(runs)
    assert doc['title'] == 'Evidencias (2 corridas)'
    step_headings = {b['children'][0]['text'] for b in doc['blocks'] if b['kind'] == 'group'}
    assert step_headings == {'Consultar salud', 'Listar items'}


def test_case_single_doc_honors_a_custom_template(world):
    """Antes Caso ejecutable era un doc de estructura fija; ahora la plantilla elige qué campos entran."""
    rt = _titles('case')
    template = {'name': 'Solo estado', 'body': [{'field': 'case_status', 'label': 'Estado'}]}
    doc = rt.single_doc_fn(world['case_a'], template)
    assert [b['kind'] for b in doc['blocks']] == ['heading', 'badge']


def test_suite_group_single_doc_honors_a_custom_template(world):
    rt = _titles('suite_group')
    template = {'name': 'Solo miembros', 'body': [{'field': 'suite_members', 'label': 'Miembros'}]}
    doc = rt.single_doc_fn(world['group'], template)
    assert [b['kind'] for b in doc['blocks']] == ['heading', 'table']


def test_evidence_single_doc_honors_a_custom_template(world):
    rt = _titles('evidence')
    template = {'name': 'Solo resumen', 'body': [{'field': 'evidence_summary', 'label': 'Resumen'}]}
    doc = rt.single_doc_fn(world['run_a'], template)
    assert [b['kind'] for b in doc['blocks']] == ['heading', 'cards']


def test_matrix_project_doc_is_not_a_batch_it_is_the_whole_project(world):
    rt = _titles('matrix')
    assert rt.scope == 'project' and rt.list_fn is None
    doc = rt.project_doc_fn(world['pid'])
    assert doc['title'] == 'Matriz de trazabilidad'
