"""Importing a contract from a URL: direct link, Swagger UI page, redirect, Swagger 2 servers, limits and errors."""
import asyncio
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import pytest
from app import core

V3 = {'openapi': '3.0.0', 'info': {'title': 'Tienda', 'version': '2'}, 'servers': [{'url': '/api/v3'}],
      'paths': {'/items': {'get': {'summary': 'Listar', 'responses': {'200': {'description': 'ok'}}}}}}
V2 = {'swagger': '2.0', 'info': {'title': 'Legado', 'version': '1'}, 'host': 'legacy.example.com', 'basePath': '/v1', 'schemes': ['https', 'http'],
      'paths': {'/ping': {'get': {'responses': {'200': {'description': 'ok'}}}}}}
UI_PAGE = '<html><script src="./swagger-initializer.js"></script></html>'
INITIALIZER = 'window.onload=function(){const defaultDefinitionUrl = "https://petstore.swagger.io/v2/swagger.json";' \
              'const oss = `{HOST}=http://{HOST}/api/v3/openapi.json,otro.example.com=https://otro.example.com/x.json`;}'
REDOC = '<html><body><redoc spec-url="/specs/tienda.json"></redoc></body></html>'


EXTRA = {}   # routes a single test adds on top of the base ones


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        routes = {'/api/v3/openapi.json': (json.dumps(V3), 'application/json'), '/legacy.json': (json.dumps(V2), 'application/json'),
                  '/ui/': (UI_PAGE, 'text/html'), '/ui/swagger-initializer.js': (INITIALIZER.replace('{HOST}', self.headers['Host']), 'application/javascript'),
                  '/redoc': (REDOC, 'text/html'), '/specs/tienda.json': (json.dumps(V3), 'application/json'), '/plain': ('<html>hola</html>', 'text/html'),
                  '/big.json': ('x' * (core.MAX_SPEC_BYTES + 10), 'application/json'), **EXTRA}
        if self.path == '/moved':
            self.send_response(302)
            self.send_header('Location', '/api/v3/openapi.json')
            self.end_headers()
            return
        if self.path not in routes:
            self.send_response(404)
            self.end_headers()
            return
        body, kind = routes[self.path]
        raw = body.encode()
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


@pytest.fixture
def docs():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    Thread(target=server.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{server.server_port}'
    server.shutdown()
    server.server_close()


def test_direct_link_and_redirect(docs):
    assert core.fetch_openapi(docs + '/api/v3/openapi.json')['source_url'] == docs + '/api/v3/openapi.json'
    assert core.fetch_openapi(docs + '/moved')['raw'].startswith('{"openapi"')


def test_swagger_ui_page_finds_its_own_contract_not_the_demo(docs):
    found = core.fetch_openapi(docs + '/ui/')
    assert found['source_url'] == docs + '/api/v3/openapi.json'                       # same host wins over the petstore demo and other hosts


def test_redoc_page_by_spec_url(docs):
    assert core.fetch_openapi(docs + '/redoc')['source_url'] == docs + '/specs/tienda.json'


def test_page_without_links_falls_back_to_well_known_paths(docs, monkeypatch):
    monkeypatch.setitem(EXTRA, '/v3/api-docs', (json.dumps(V3), 'application/json'))
    assert core.fetch_openapi(docs + '/plain')['source_url'] == docs + '/v3/api-docs'


def test_github_blob_links_become_raw():
    assert core.normalize_spec_url('https://github.com/o/r/blob/main/a/b.yaml') == 'https://raw.githubusercontent.com/o/r/main/a/b.yaml'
    assert core.normalize_spec_url('https://example.com/x.json') == 'https://example.com/x.json'


def test_errors_are_clear(docs):
    with pytest.raises(ValueError, match='URL inválida'):
        core.fetch_openapi('ftp://x/y')
    with pytest.raises(ValueError, match='URL inválida'):
        core.fetch_openapi('no es url')
    with pytest.raises(ValueError, match='no es un contrato'):
        core.fetch_openapi(docs + '/plain')
    with pytest.raises(ValueError, match='No se encontró un contrato'):
        core.fetch_openapi('http://127.0.0.1:1/x.json')
    with pytest.raises(ValueError, match='10 MB'):
        core.fetch_openapi(docs + '/big.json')


def test_import_keeps_the_source_and_resolves_relative_servers(docs):
    project = core.create_project('p')
    module = core.import_openapi_url(docs + '/ui/', project['id'])
    assert module['name'] == 'Tienda' and module['source_url'] == docs + '/api/v3/openapi.json'
    assert core.get('modules', module['id'])['source_url'] == module['source_url']
    assert core.module_base_url(module) == docs + '/api/v3'                           # '/api/v3' resolved against where it came from


def test_swagger2_host_and_basepath_become_a_server():
    module = core.parse_openapi(json.dumps(V2))
    assert module['servers'] == [{'url': 'https://legacy.example.com/v1'}]
    assert core.module_base_url(module) == 'https://legacy.example.com/v1'
    assert core.module_base_url({'servers': [{'url': '{scheme}://x/y'}]}) is None
    assert core.module_base_url({'servers': [], 'source_url': 'http://h:8000/openapi.json'}) == 'http://h:8000'   # FastAPI declares no servers


async def test_modules_page_imports_from_a_swagger_ui_page_and_creates_the_environment(user, docs):
    project = core.create_project('Mod')
    core.set_active_project(project['id'])
    await user.open('/modules')
    user.find('URL del contrato, de su página de Swagger UI o un enlace de GitHub').type(docs + '/ui/')
    user.find('Importar desde URL').click()
    await asyncio.sleep(1.5)  # the download runs in a worker thread
    await user.should_see('Importado «Tienda»')
    assert core.list_project_items('modules', project['id'])[0]['source_url'] == docs + '/api/v3/openapi.json'
    await user.should_see('Ambiente «Tienda» creado')  # the environment is registered automatically on import now
    assert [e['base_url'] for e in core.list_project_items('environments', project['id'])] == [docs + '/api/v3']
    module_id = core.list_project_items('modules', project['id'])[0]['id']
    await user.open(f'/modules/edit?id={module_id}')
    await user.should_see(f'«Tienda» · {docs}/api/v3')  # already linked: shown directly, no manual button needed


FASTAPI_DOCS = ('<html><head><link type="text/css" rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css"></head><body><div id="swagger-ui"></div>'
                '<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>'
                "<script>const ui = SwaggerUIBundle({url: '/openapi.json', dom_id: '#swagger-ui', presets: [SwaggerUIBundle.presets.apis]})</script></body></html>")


def test_fastapi_style_docs_page_and_api_root(docs, monkeypatch):
    monkeypatch.setitem(EXTRA, '/docs', (FASTAPI_DOCS, 'text/html'))
    monkeypatch.setitem(EXTRA, '/openapi.json', (json.dumps({**V3, 'servers': []}), 'application/json'))
    for typed in ('/docs', '/'):                                                  # «/» answers 404 here, like an API without a root route
        found = core.fetch_openapi(docs + typed)
        assert found['source_url'] == docs + '/openapi.json'
    module = core.import_openapi_url(docs + '/docs', core.create_project('f')['id'])
    assert core.module_base_url(module) == docs


def test_recursive_models_are_accepted_and_cut_where_they_repeat():
    spec = {'openapi': '3.0.0', 'info': {'title': 'Arbol', 'version': '1'}, 'paths': {'/tree': {'get': {'responses': {'200': {'description': 'ok', 'content': {'application/json': {'schema': {'$ref': '#/components/schemas/Node'}}}}}}}},
            'components': {'schemas': {'Node': {'type': 'object', 'properties': {'name': {'type': 'string'}, 'children': {'type': 'array', 'items': {'$ref': '#/components/schemas/Node'}}}}}}}
    module = core.parse_openapi(json.dumps(spec))
    schema = core.operation_response_schema(module['operations'][0])
    assert schema['properties']['name']['type'] == 'string'
    inner = schema['properties']['children']['items']
    assert inner['x-ltw-recursive'] == '#/components/schemas/Node' and 'type' not in inner     # open at the cut: anything validates there
    import jsonschema
    jsonschema.validate({'name': 'a', 'children': [{'name': 'b', 'children': [{'x': 1}]}]}, schema)
    with pytest.raises(ValueError, match='locales'):
        core.parse_openapi(json.dumps({'openapi': '3.0.0', 'paths': {'/x': {'get': {'$ref': 'otro.yaml#/get'}}}}))
