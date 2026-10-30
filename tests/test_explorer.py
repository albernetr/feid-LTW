"""Automatic exploration of a contract: discovery, id harvesting, schema-derived assertions, self-healing the
`$.id` vs `$.wrapper.id` mistake from the contract (not from poking the live response), and contract-change diffing."""
import asyncio
import json
import pytest
from app import core, explorer
from sample_app.fixture_api import FixtureAPI, SPEC_V1, SPEC_V2


@pytest.fixture
def world():
    with FixtureAPI() as api:
        project = core.create_project('Exploración')
        module = core.import_openapi(json.dumps(api.server.spec), project['id'])
        env = core.save('environments', {'name': 'fixture', 'project_id': project['id'], 'base_url': api.url, 'variables': {}, 'auth': {'type': 'none'}})
        yield project, module, env, api


def test_guess_id_paths_finds_the_wrapped_field_first_match_in_declared_order():
    schema = core.operation_response_schema({'responses': {'200': {'content': {'application/json': {'schema': {
        'type': 'object', 'properties': {'process': {'type': 'object', 'properties': {'id': {'type': 'string'}, 'name': {'type': 'string'}}}}}}}}}})
    assert explorer.guess_id_paths(schema) == ['$.process.id']
    assert explorer.guess_id_paths({'type': 'object', 'properties': {'ok': {'type': 'boolean'}}}) == []


def test_guess_id_paths_sees_through_optional_anyof_wrapping():
    schema = {'type': 'object', 'properties': {'item': {'anyOf': [{'type': 'object', 'properties': {'id': {'type': 'string'}}}, {'type': 'null'}]}}}
    assert explorer.guess_id_paths(schema) == ['$.item.id']


def test_guess_listing_paths_finds_the_array_of_objects():
    schema = {'type': 'object', 'properties': {'datasets': {'type': 'array', 'items': {'type': 'object', 'properties': {'id': {'type': 'string'}}}}, 'total': {'type': 'integer'}}}
    assert explorer.guess_listing_paths(schema) == ['$.datasets[0].id']


def test_discover_harvests_ids_from_the_listing_and_resolves_the_templated_get(world):
    _, module, env, _ = world
    plan = explorer.discover(module, env)
    ready_paths = {e['resolved_path'] for e in plan['ready']}
    assert '/datasets' in ready_paths and '/ping' in ready_paths and '/broken' in ready_paths
    resolved_item = next(e for e in plan['ready'] if e['operation']['path'] == '/datasets/{dataset_id}')
    assert resolved_item['resolved_path'] in (f'/datasets/{i["id"]}' for i in __import__('sample_app.fixture_api', fromlist=['ITEMS']).ITEMS)
    assert plan['blocked'] == [] and 'datasets' in plan['pool']


def test_build_case_asserts_against_the_declared_status_and_schema_not_a_guess(world):
    _, module, env, _ = world
    plan = explorer.discover(module, env)
    entry = next(e for e in plan['ready'] if e['resolved_path'] == '/datasets')
    case = explorer.build_case(entry, module, module['project_id'], env['id'])
    kinds = {a['type'] for a in case['assertions']}
    assert kinds == {'status', 'json_schema'} and case['extract'] == []  # /datasets has no scalar id at the root, only a list
    assert case['tags'] == [explorer.GENERATED_TAG] and case['explorer']['operation'] == 'GET /datasets'


def test_run_plan_passes_on_the_well_behaved_endpoints_and_flags_the_broken_one(world):
    _, module, env, _ = world
    plan = explorer.discover(module, env)
    result = explorer.run_plan(plan, module, module['project_id'], env, persist=False)
    by_path = {r['operation']['path']: r for r in result['results']}
    assert by_path['/ping']['classification'] == 'passed'
    assert by_path['/datasets']['classification'] == 'passed'
    assert by_path['/datasets/{dataset_id}']['classification'] == 'passed'        # the extraction self-heals to $.dataset.id, see below
    assert by_path['/broken']['classification'] == 'contract_mismatch'           # a real finding: the contract promised a field that never arrives
    assert result['summary'] == {'total': 4, 'passed': 3, 'needs_review': 1, 'blocked': 0, 'cancelled': 0}


def test_self_heal_fixes_the_exact_mistake_made_by_hand_in_the_feid_session(world):
    """A case built guessing `$.id` (the wrong, flatter candidate) should self-heal to `$.dataset.id` once run,
    exactly like `crear proceso` needed `$.process.id` instead of `$.id` against the real FEID API."""
    _, module, env, _ = world
    plan = explorer.discover(module, env)
    entry = next(e for e in plan['ready'] if e['operation']['path'] == '/datasets/{dataset_id}')
    case = explorer.build_case(entry, module, module['project_id'], env['id'])
    assert case['extract'][0]['path'] == '$.dataset.id'                         # the only candidate here: already correct on the first try
    bad_case = {**case, 'extract': [{'name': 'id', 'source': 'json', 'path': '$.id'}],
                'explorer': {**case['explorer'], 'id_paths': ['$.id', '$.dataset.id'], 'id_path_attempt': 0}}
    run = core.execute_api(bad_case, env, persist=False)
    assert run['status'] != 'passed' and run['extracted'] == {}
    healed = explorer._self_heal(bad_case, run, entry)
    assert healed['extract'][0]['path'] == '$.dataset.id'
    healed_run = core.execute_api(healed, env, persist=False)
    assert healed_run['status'] == 'passed' and healed_run['extracted']['id']


def test_self_heal_never_touches_a_genuine_status_mismatch(world):
    _, module, env, _ = world
    case = {'name': 'x', 'method': 'GET', 'path': '/nope', 'assertions': [{'type': 'status', 'expected': 200}], 'headers': {}, 'query': {}, 'body': None,
            'variables': {}, 'extract': [], 'timeout': 10, 'explorer': {'id_paths': ['$.a', '$.b'], 'id_path_attempt': 0}}
    run = core.execute_api(case, env, persist=False)
    entry = {'operation': {'method': 'GET', 'path': '/nope', 'responses': {'200': {}}}}
    assert explorer._self_heal(case, run, entry) is None                        # a 404 is a finding, not something to paper over


def test_blocked_operations_are_never_called(world, monkeypatch):
    project, module, env, api = world
    calls = []
    original = core.execute_api

    def spy(case, *a, **kw):
        calls.append(case['path'])
        return original(case, *a, **kw)
    monkeypatch.setattr(core, 'execute_api', spy)
    module2 = core.import_openapi(json.dumps({**api.server.spec, 'paths': {**api.server.spec['paths'],
        '/unreachable/{secret_id}': {'get': {'summary': 'no listing anywhere gives this id', 'parameters': [
            {'name': 'secret_id', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}], 'responses': {'200': {'description': 'ok'}}}}}}), project['id'])
    plan = explorer.discover(module2, env)
    assert any(b['operation']['path'] == '/unreachable/{secret_id}' for b in plan['blocked'])
    result = explorer.run_plan(plan, module2, project['id'], env, persist=False)
    assert not any('unreachable' in c for c in calls) and result['summary']['blocked'] == 1


def test_narrate_produces_a_readable_report_without_a_model(world):
    _, module, env, _ = world
    plan = explorer.discover(module, env)
    result = explorer.run_plan(plan, module, module['project_id'], env, persist=False)
    text = explorer.narrate(module, result, 'Exploración')
    assert '# Exploración automática: Fixture' in text and '/broken' in text and 'Cobertura' in text
    assert '3 coinciden' in text or 'passed' not in text  # written in Spanish, not a dump of internal field names


def test_diff_module_flags_new_required_params_and_a_changed_response_shape():
    v1 = core.parse_openapi(json.dumps(SPEC_V1))
    v2 = core.parse_openapi(json.dumps(SPEC_V2))
    diff = explorer.diff_module(v1, v2)
    assert diff['added'] == [] and diff['removed'] == []
    changed = dict(diff['changed'])
    assert 'GET /datasets/{dataset_id}' in changed
    reasons = ' '.join(changed['GET /datasets/{dataset_id}'])
    assert 'tenant_id' in reasons and 'la forma de la respuesta cambió' in reasons


def test_diff_module_detects_added_and_removed_operations():
    v1 = core.parse_openapi(json.dumps(SPEC_V1))
    trimmed = json.loads(json.dumps(SPEC_V1))
    del trimmed['paths']['/ping']
    trimmed['paths']['/new-thing'] = {'get': {'summary': 'nuevo', 'responses': {'200': {'description': 'ok'}}}}
    v3 = core.parse_openapi(json.dumps(trimmed))
    diff = explorer.diff_module(v1, v3)
    assert diff['added'] == ['GET /new-thing'] and diff['removed'] == ['GET /ping']


def test_stale_cases_finds_only_what_a_diff_actually_affects(world):
    project, module, env, _ = world
    plan = explorer.discover(module, env)
    for entry in plan['ready']:
        core.save('cases', explorer.build_case(entry, module, project['id'], env['id']))
    core.save('cases', {'name': 'manual, not auto-explored', 'method': 'GET', 'path': '/ping', 'project_id': project['id'], 'headers': {}, 'query': {},
                        'body': None, 'assertions': [], 'variables': {}, 'extract': [], 'timeout': 10})
    v2 = core.parse_openapi(json.dumps(SPEC_V2))
    diff = explorer.diff_module(module, v2)
    stale = explorer.stale_cases(project['id'], module['id'], diff)
    assert len(stale) == 1 and stale[0]['explorer']['operation'] == 'GET /datasets/{dataset_id}'


async def test_modules_page_can_trigger_exploration_from_the_ui(user, world):
    project, module, env, _ = world
    core.set_active_project(project['id'])
    await user.open(f'/modules/edit?id={module["id"]}')
    await user.should_see('Explorar automáticamente')
    user.find('Explorar automáticamente').click()
    await asyncio.sleep(8)  # discovery + run_plan make real HTTP calls in a worker thread
    await user.should_see('Guardar como casos')
    user.find('Guardar como casos').click()
    await asyncio.sleep(0.5)
    await user.should_see('guardados/actualizados')
    saved = [c for c in core.list_project_items('cases', project['id']) if c.get('explorer')]
    assert len(saved) == 4 and {c['explorer']['operation'] for c in saved} == {'GET /datasets', 'GET /datasets/{dataset_id}', 'GET /ping', 'GET /broken'}


def test_run_plan_can_be_cancelled_mid_sweep(world):
    from app import automation
    _, module, env, _ = world
    plan = explorer.discover(module, env)
    token = automation.new_cancel_token()
    seen = []

    def on_progress(entry):
        seen.append(entry)
        if len(seen) == 2:
            token.set()
    result = explorer.run_plan(plan, module, module['project_id'], env, persist=False, on_progress=on_progress, cancel=token)
    assert len(result['results']) == 2 and result['cancelled'] == len(plan['ready']) - 2 and result['summary']['cancelled'] == result['cancelled']


def test_extra_header_authenticates_and_a_secret_template_is_redacted_from_the_saved_run(world):
    from sample_app.fixture_api import SECURE_OPERATION
    project, module, env, api = world
    core.secret_set('FIXTURE_TOKEN', 'secret-123')
    secure_module = core.import_openapi(json.dumps({**api.server.spec, 'paths': {**api.server.spec['paths'], **SECURE_OPERATION}}), project['id'])
    headers = {'Authorization': 'Bearer {{secret:FIXTURE_TOKEN}}'}
    plan = explorer.discover(secure_module, env, extra_headers=headers)
    entry = next(e for e in plan['ready'] if e['operation']['path'] == '/secure')
    result = explorer.run_plan(plan, secure_module, project['id'], env, extra_headers=headers, persist=True)
    secure_result = next(r for r in result['results'] if r['operation']['path'] == '/secure')
    assert secure_result['classification'] == 'passed' and secure_result['run']['http_status'] == 200
    assert 'secret-123' not in json.dumps(core.get('runs', secure_result['run']['id']))     # redacted like any other secret-backed header


def test_wrong_or_missing_token_is_reported_not_silently_skipped(world):
    from sample_app.fixture_api import SECURE_OPERATION
    project, module, env, api = world
    secure_module = core.import_openapi(json.dumps({**api.server.spec, 'paths': {**api.server.spec['paths'], **SECURE_OPERATION}}), project['id'])
    plan = explorer.discover(secure_module, env)                                            # no header at all
    result = explorer.run_plan(plan, secure_module, project['id'], env, persist=False)
    secure_result = next(r for r in result['results'] if r['operation']['path'] == '/secure')
    assert secure_result['classification'] == 'auth' and secure_result['run']['http_status'] == 401


async def test_modules_page_header_field_authenticates_a_live_exploration(user, world):
    from sample_app.fixture_api import SECURE_OPERATION
    project, module, env, api = world
    core.secret_set('FIXTURE_TOKEN', 'secret-123')
    secure_module = core.import_openapi(json.dumps({**api.server.spec, 'paths': {**api.server.spec['paths'], **SECURE_OPERATION}}), project['id'])
    core.set_active_project(project['id'])
    await user.open(f'/modules/edit?id={secure_module["id"]}')
    user.find('Valor').type('Bearer {{secret:FIXTURE_TOKEN}}')
    user.find('Explorar automáticamente').click()
    await asyncio.sleep(8)
    await user.should_see('Guardar como casos')
    user.find('Guardar como casos').click()
    await asyncio.sleep(0.5)
    saved = [c for c in core.list_project_items('cases', project['id']) if c.get('explorer', {}).get('module_id') == secure_module['id']]
    secure_case = next(c for c in saved if c['explorer']['operation'] == 'GET /secure')
    assert secure_case['headers'] == {'Authorization': 'Bearer {{secret:FIXTURE_TOKEN}}'}   # the template, never the resolved value, is what gets saved
