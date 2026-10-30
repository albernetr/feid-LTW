"""A small FEID-shaped API for testing app/explorer.py: a listing endpoint, a wrapped-object GET (the exact
`{"process": {...}}` shape that broke a hand-written extraction path during the FEID session), a resource with
no id anywhere, and a v2 contract with an added required field, for the "contract changed" tests."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

ITEMS = [{'id': 'DST-0001', 'name': 'ventas'}, {'id': 'DST-0002', 'name': 'clientes'}, {'id': 'DST-0003', 'name': 'inventario'}]

SPEC_V1 = {
    'openapi': '3.0.0', 'info': {'title': 'Fixture', 'version': '1'}, 'servers': [{'url': '/'}],
    'paths': {
        '/datasets': {'get': {'summary': 'Listar datasets', 'responses': {'200': {'description': 'ok', 'content': {'application/json': {
            'schema': {'type': 'object', 'properties': {'datasets': {'type': 'array', 'items': {'type': 'object', 'properties': {
                'id': {'type': 'string'}, 'name': {'type': 'string'}}}}, 'total': {'type': 'integer'}}}}}}}}},
        '/datasets/{dataset_id}': {'get': {'summary': 'Obtener dataset', 'parameters': [{'name': 'dataset_id', 'in': 'path', 'required': True, 'schema': {'type': 'string'}}],
            'responses': {'200': {'description': 'ok', 'content': {'application/json': {'schema': {'type': 'object', 'properties': {
                'dataset': {'type': 'object', 'properties': {'id': {'type': 'string'}, 'name': {'type': 'string'}, 'rows': {'type': 'integer'}}}}}}}}}}},
        '/ping': {'get': {'summary': 'Sin datos de interés', 'responses': {'200': {'description': 'ok', 'content': {'application/json': {
            'schema': {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}}}}}}}},
        '/broken': {'get': {'summary': 'Declara un campo que nunca llega (contrato vs. realidad)', 'parameters': [],
            'responses': {'200': {'description': 'ok', 'content': {'application/json': {'schema': {'type': 'object', 'required': ['missing_field'],
                'properties': {'missing_field': {'type': 'string'}}}}}}}}},
    },
}

# Kept out of SPEC_V1 (every test using `world` counts on its 4 operations): declared separately by the one test
# that needs an authenticated endpoint, built against the same running server (the /secure route always exists).
SECURE_OPERATION = {'/secure': {'get': {'summary': 'Requiere Authorization: Bearer secret-123', 'parameters': [],
    'responses': {'200': {'description': 'ok', 'content': {'application/json': {'schema': {'type': 'object', 'properties': {'secret': {'type': 'boolean'}}}}}}}}}}

SPEC_V2 = json.loads(json.dumps(SPEC_V1))
SPEC_V2['paths']['/datasets/{dataset_id}']['get']['parameters'].append({'name': 'tenant_id', 'in': 'query', 'required': True, 'schema': {'type': 'string'}})
SPEC_V2['paths']['/datasets/{dataset_id}']['get']['responses']['200']['content']['application/json']['schema'] = {
    'type': 'object', 'properties': {'data': {'type': 'object', 'properties': {'uuid': {'type': 'string'}, 'name': {'type': 'string'}}}}}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, payload):
        raw = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/openapi.json':
            return self._send(200, self.server.spec)
        if path == '/datasets':
            return self._send(200, {'datasets': ITEMS, 'total': len(ITEMS)})
        if path.startswith('/datasets/'):
            ident = path.rsplit('/', 1)[1]
            item = next((i for i in ITEMS if i['id'] == ident), None)
            if item is None:
                return self._send(404, {'error': 'not found'})
            return self._send(200, {'dataset': {**item, 'rows': 120}})
        if path == '/ping':
            return self._send(200, {'ok': True})
        if path == '/secure':
            if self.headers.get('Authorization') != 'Bearer secret-123':
                return self._send(401, {'error': 'unauthorized'})
            return self._send(200, {'secret': True})
        if path == '/broken':
            return self._send(200, {'unexpected_field': 'x'})  # the contract promised `missing_field`; a real finding
        return self._send(404, {'error': 'not found'})


class FixtureAPI:
    def __init__(self, port=0, spec=None):
        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.server.spec = spec or SPEC_V1
        self.thread = Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server.server_port}'

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
