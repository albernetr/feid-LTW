"""Seeds a workspace with a demo project that targets sample_app (python -m sample_app.server).

Usage: set TEST_WORKSPACE_HOME to an empty folder and run  python scripts/seed_demo.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import core, automation  # noqa: E402

SPEC = '''openapi: 3.0.3
info: {title: Sample API, version: "1.0"}
paths:
  /health:
    get: {summary: Estado del servicio, responses: {"200": {description: ok, content: {application/json: {schema: {type: object, required: [status], properties: {status: {type: string}}}}}}}}
  /api/items:
    get: {summary: Listar items, responses: {"200": {description: ok}}}
    post: {summary: Crear item, responses: {"201": {description: creado}}}
'''


def seed(base_url='http://127.0.0.1:8765'):
    project = core.create_project('Demo Sample App', 'Proyecto de ejemplo contra sample_app')
    pid = project['id']
    core.import_openapi(SPEC, pid)
    env = core.save('environments', {'name': 'Local', 'project_id': pid, 'base_url': base_url, 'auth': {'type': 'none'}, 'variables': {}})

    def case(name, method, path, assertions, **extra):
        return core.save('cases', {'name': name, 'type': 'api', 'project_id': pid, 'method': method, 'path': path, 'assertions': assertions, **extra})
    health = case('Health OK', 'GET', '/health', [{'type': 'status', 'expected': 200}, {'type': 'json_equals', 'path': '$.status', 'expected': 'ok'}])
    login = case('Login', 'POST', '/api/login', [{'type': 'status', 'expected': 200}], body={'user': 'qa', 'password': 'qa-pass'},
                 extract=[{'name': 'token', 'source': 'json', 'path': '$.token'}])
    create = case('Crear item', 'POST', '/api/items', [{'type': 'status', 'expected': 201}, {'type': 'json_type', 'path': '$.id', 'expected': 'integer'}],
                  headers={'Authorization': 'Bearer {{token}}'}, body={'name': 'demo'})
    case('Sin token (401)', 'GET', '/api/items', [{'type': 'status', 'expected': 401}])
    ui_case = core.save('cases', {'name': 'Login UI', 'type': 'ui', 'project_id': pid, 'steps': [
        {'action': 'navigate', 'url': '/login'},
        {'action': 'fill', 'locator': {'by': 'label', 'value': 'Usuario'}, 'value': 'qa'},
        {'action': 'fill', 'locator': {'by': 'label', 'value': 'Contraseña'}, 'value': 'qa-pass'},
        {'action': 'click', 'locator': {'by': 'role', 'role': 'button', 'name': 'Entrar'}},
        {'action': 'assert_text', 'locator': {'by': 'testid', 'value': 'msg'}, 'expected': 'Bienvenido qa'}]})
    suite = core.save_suite('Smoke encadenado', env['id'], [health['id'], login['id'], create['id'], ui_case['id']], pid, on_failure='stop', retries=1)
    automation.create_schedule(suite['id'], 'weekdays', '07:30', 'America/Mexico_City')
    return project


if __name__ == '__main__':
    seed()
    print('Demo creada en', core.ROOT)
