import json
import pytest
import httpx
from app import core


def response(body, status=200, headers=None):
    return httpx.Response(status, json=body, headers=headers or {'X-Id': 'abc'})


def run(resp, *rules):
    return [r['passed'] for r in core.check_assertions(resp, list(rules), 5)]


def test_jsonpath_subset():
    data = {'a': {'b': [{'c': 1}, {'c': 2}]}, 'k-x': 3}
    assert core.extract_path(data, '$.a.b[1].c') == 2
    assert core.extract_path(data, 'a.b.0.c') == 1
    assert core.extract_path(data, "$['k-x']") == 3
    assert core.extract_path(data, '$.a.b[*].c') == [1, 2]
    with pytest.raises(core.PathError):
        core.extract_path(data, '$.a.b[5]')
    with pytest.raises(core.PathError):
        core.extract_path(data, '$.nope')


def test_visual_assertion_catalog_passes_and_fails():
    r = response({'id': 7, 'name': 'Ana', 'tags': ['x', 'y'], 'ok': True, 'score': 4.5})
    assert run(r,
               {'type': 'status', 'expected': 200}, {'type': 'status_in', 'expected': '200,201'},
               {'type': 'response_time_max', 'expected': 100},
               {'type': 'header_exists', 'name': 'X-Id'}, {'type': 'header_equals', 'name': 'X-Id', 'expected': 'abc'},
               {'type': 'header_contains', 'name': 'X-Id', 'expected': 'b'},
               {'type': 'json_equals', 'path': '$.name', 'expected': 'Ana'},
               {'type': 'json_not_equals', 'path': '$.name', 'expected': 'Bob'},
               {'type': 'json_type', 'path': '$.id', 'expected': 'integer'},
               {'type': 'json_type', 'path': '$.ok', 'expected': 'boolean'},
               {'type': 'json_length', 'path': '$.tags', 'expected': 2},
               {'type': 'json_regex', 'path': '$.name', 'expected': '^A'},
               {'type': 'json_contains', 'path': '$.tags', 'expected': 'x'},
               {'type': 'numeric_greater', 'path': '$.score', 'expected': 4},
               {'type': 'json_not_exists', 'path': '$.zzz'},
               {'type': 'regex', 'expected': r'"id":\s*7'}) == [True] * 16
    assert run(r,
               {'type': 'status', 'expected': 404}, {'type': 'response_time_max', 'expected': 1},
               {'type': 'header_equals', 'name': 'X-Id', 'expected': 'zzz'},
               {'type': 'json_type', 'path': '$.id', 'expected': 'string'},
               {'type': 'json_type', 'path': '$.ok', 'expected': 'integer'},
               {'type': 'json_length', 'path': '$.tags', 'expected': 3},
               {'type': 'json_exists', 'path': '$.zzz'}, {'type': 'bogus'}) == [False] * 8


def test_json_schema_assertion():
    schema = {'type': 'object', 'required': ['id', 'name'], 'properties': {'id': {'type': 'integer'}, 'name': {'type': 'string'}}}
    ok = core.check_assertions(response({'id': 1, 'name': 'a'}), [{'type': 'json_schema', 'schema': schema}])[0]
    bad = core.check_assertions(response({'id': 'x'}), [{'type': 'json_schema', 'schema': schema}])[0]
    broken = core.check_assertions(response({'id': 1}), [{'type': 'json_schema', 'schema': {'type': 'nope'}}])[0]
    assert ok['passed'] and not bad['passed'] and not broken['passed']
    assert any('id' in line for line in bad['actual'])


def test_invalid_json_body_fails_assertion_instead_of_crashing():
    resp = httpx.Response(200, text='not json')
    assert run(resp, {'type': 'json_equals', 'path': '$.a', 'expected': 1}, {'type': 'json_schema', 'schema': {}}) == [False, False]


def test_rule_validation_for_the_visual_editor():
    assert core.validate_assertion_rule({'type': 'status', 'expected': 200}) is None
    assert 'Falta' in core.validate_assertion_rule({'type': 'json_equals', 'path': '$.a'})
    assert 'numérico' in core.validate_assertion_rule({'type': 'status', 'expected': 'abc'})
    assert 'regular' in core.validate_assertion_rule({'type': 'regex', 'expected': '('})
    assert 'no soportado' in core.validate_assertion_rule({'type': 'x'})
    assert core.validate_assertion_rule({'type': 'json_schema', 'schema': []})


def test_contract_response_schema_from_openapi():
    spec = json.dumps({'openapi': '3.0.3', 'info': {'title': 'x'},
                       'paths': {'/i': {'get': {'responses': {'200': {'description': 'ok', 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/I'}}}}}}}},
                       'components': {'schemas': {'I': {'type': 'object', 'required': ['id']}}}})
    op = core.parse_openapi(spec)['operations'][0]
    assert core.operation_response_schema(op)['required'] == ['id']
    assert core.operation_response_schema(op, '404') is None


def test_extractions_for_chaining():
    r = response({'token': 'abc', 'items': [{'id': 9}]})
    values, errors = core.run_extractions(r, [
        {'name': 'tok', 'path': '$.token'}, {'name': 'first', 'path': '$.items[0].id'},
        {'name': 'h', 'source': 'header', 'path': 'X-Id'}, {'name': 'st', 'source': 'status'},
        {'name': 'nope', 'path': '$.missing'}])
    assert values == {'tok': 'abc', 'first': 9, 'h': 'abc', 'st': 200}
    assert len(errors) == 1 and 'nope' in errors[0]
