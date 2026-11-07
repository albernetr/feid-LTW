"""Tiny local app used for end-to-end tests of the API and UI runners.

Run it manually with:  python -m sample_app.server   (http://127.0.0.1:8765)
API: GET /health, POST /api/login, GET/POST /api/items, GET /api/items/<id>   (Bearer tok-abc123)
     GET /api/users/<1-5> (public; includes a volatile requested_at)
UI : /login (form), /clientes (list), /con-iframe (an <iframe> wrapping /iframe-inner)
"""
import datetime
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

TOKEN = 'tok-abc123'
PAGE = '<!doctype html><html lang="es"><head><meta charset="utf-8"><title>{title}</title></head><body>{body}</body></html>'
LOGIN = '''<h1>Iniciar sesión</h1>
<form id="f"><label for="u">Usuario</label><input id="u" name="u">
<label for="p">Contraseña</label><input id="p" name="p" type="password">
<button type="submit">Entrar</button></form><p id="msg" data-testid="msg"></p>
<script>document.getElementById('f').addEventListener('submit',async e=>{e.preventDefault();
const r=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({user:u.value,password:p.value})});
document.getElementById('msg').textContent=r.ok?'Bienvenido '+u.value:'Credenciales inválidas';});</script>'''
IFRAME_INNER = '''<h2>Adentro</h2>
<label for="campo">Campo interno</label><input id="campo" data-testid="campo-interno">
<button data-testid="boton-interno" type="button" onclick="document.getElementById('campo').setAttribute('data-ok','1')">Confirmar</button>'''
IFRAME_OUTER = '<h1>Con iframe</h1><iframe id="caja" src="/iframe-inner" style="width:400px;height:200px"></iframe>'


class Handler(BaseHTTPRequestHandler):
    items = None

    def log_message(self, *args):
        pass

    def _send(self, status, payload, content_type='application/json'):
        raw = payload if isinstance(payload, bytes) else (json.dumps(payload).encode() if content_type == 'application/json' else payload.encode())
        self.send_response(status)
        self.send_header('Content-Type', content_type + '; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self):
        return self.headers.get('Authorization') == f'Bearer {TOKEN}'

    def _body(self):
        length = int(self.headers.get('Content-Length', 0))
        try:
            return json.loads(self.rfile.read(length) or b'{}')
        except ValueError:
            return None

    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/health':
            return self._send(200, {'status': 'ok'})
        if path == '/login':
            return self._send(200, PAGE.format(title='Login', body=LOGIN), 'text/html')
        if path == '/clientes':
            rows = ''.join(f'<li>{i["name"]}</li>' for i in self.server.items)
            return self._send(200, PAGE.format(title='Clientes', body=f'<h1>Clientes</h1><ul>{rows}</ul>'), 'text/html')
        if path == '/con-iframe':   # para probar que un locator necesita `frame` para entrar a un <iframe>
            return self._send(200, PAGE.format(title='Con iframe', body=IFRAME_OUTER), 'text/html')
        if path == '/iframe-inner':
            return self._send(200, PAGE.format(title='Adentro', body=IFRAME_INNER), 'text/html')
        if path == '/set-cookie':   # para probar que una sesión guardada (storage_state) llega al navegador antes del primer paso
            body = PAGE.format(title='Cookie', body='<p>ok</p>').encode()
            self.send_response(200)
            self.send_header('Set-Cookie', 'session=qa-token; Path=/')
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == '/whoami':
            cookie = self.headers.get('Cookie') or 'ninguna'
            return self._send(200, PAGE.format(title='Whoami', body=f'<p data-testid="cookie">{cookie}</p>'), 'text/html')
        if path.startswith('/api/users/'):  # public, deterministic except for requested_at
            ident = path.rsplit('/', 1)[1]
            if not ident.isdigit() or not 1 <= int(ident) <= 5:
                return self._send(404, {'error': 'user not found'})
            name = 'USER' if getattr(self.server, 'rename_users', False) else f'user{ident}'   # flip to simulate a code change
            stamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
            if getattr(self.server, 'drift_users', False):                                       # simulates an unannounced contract change
                return self._send(200, {'id': ident, 'name': name, 'email': f'user{ident}@example.com', 'requested_at': stamp})
            return self._send(200, {'id': int(ident), 'name': name, 'role': 'admin' if ident == '1' else 'member', 'requested_at': stamp})
        if path == '/api/items':
            if not self._authorized():
                return self._send(401, {'error': 'unauthorized'})
            return self._send(200, {'items': self.server.items, 'total': len(self.server.items)})
        if path.startswith('/api/items/'):
            if not self._authorized():
                return self._send(401, {'error': 'unauthorized'})
            for item in self.server.items:
                if str(item['id']) == path.rsplit('/', 1)[1]:
                    return self._send(200, item)
            return self._send(404, {'error': 'not found'})
        return self._send(404, {'error': 'not found'})

    def do_POST(self):
        path = self.path.split('?')[0]
        data = self._body()
        if data is None:
            return self._send(400, {'error': 'invalid json'})
        if path == '/api/login':
            if data.get('user') == 'qa' and data.get('password') == 'qa-pass':
                return self._send(200, {'token': TOKEN, 'user': {'name': 'qa'}})
            return self._send(401, {'error': 'bad credentials'})
        if path == '/api/items':
            if not self._authorized():
                return self._send(401, {'error': 'unauthorized'})
            if not isinstance(data.get('name'), str) or not data['name'].strip():
                return self._send(422, {'error': 'name is required'})
            item = {'id': len(self.server.items) + 1, 'name': data['name']}
            self.server.items.append(item)
            return self._send(201, item)
        return self._send(404, {'error': 'not found'})


class SampleApp:
    def __init__(self, port=0):
        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.server.items = [{'id': 1, 'name': 'Acme'}]
        self.server.rename_users = bool(os.environ.get('SAMPLE_RENAME_USERS'))  # simulates a code change
        self.server.drift_users = bool(os.environ.get('SAMPLE_DRIFT_USERS'))    # simulates a contract change
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


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    with SampleApp(port) as app:
        print('Sample app en', app.url, '(Ctrl+C para salir)')
        try:
            app.thread.join()
        except KeyboardInterrupt:
            pass
