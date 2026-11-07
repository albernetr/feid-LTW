"""Stand-in for a model server (OpenAI-compatible and Anthropic wire formats) so the assistant can be tested and demoed with no model and no tokens.
Run: python sample_app/fake_llm.py [port]"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


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

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length') or 0)) or b'{}')
        server = self.server
        server.requests.append({'path': self.path, 'headers': {k.lower(): v for k, v in self.headers.items()}, 'body': body})
        if server.required_key and server.required_key not in (self.headers.get('Authorization', ''), self.headers.get('api-key', ''), self.headers.get('x-api-key', '')):
            return self._send(401, {'error': {'message': 'Incorrect API key provided'}})
        if body.get('model') != server.model:
            return self._send(404, {'error': {'message': f'model "{body.get("model")}" not found'}})
        if server.status != 200:
            return self._send(server.status, {'error': {'message': 'boom'}})
        user = body['messages'][-1]['content']
        reply = server.replies.pop(0) if server.replies else server.default_reply(user)
        if self.path.endswith('/messages'):
            return self._send(200, {'content': [{'type': 'text', 'text': reply}], 'role': 'assistant'})
        if self.path.endswith('/chat/completions'):
            return self._send(200, {'choices': [{'message': {'role': 'assistant', 'content': reply}}]})
        self._send(404, {'error': {'message': 'ruta desconocida'}})


def _default_reply(user):
    if user.strip() == 'ping':
        return 'OK'
    if 'Descripción de lo que hay que probar' in user:
        return '```json\n' + json.dumps({'format': 'ltw.spec/1', 'name': 'generado', 'environments': [{'name': 'api', 'base_url': 'http://127.0.0.1:8765'}],
                                         'cases': [{'name': 'health', 'method': 'GET', 'path': '/health', 'environment': 'api', 'assertions': [{'type': 'status', 'expected': 200}]}]}) + '\n```'
    if 'Conversación:' in user:   # llm.judge_conversation (veredicto de una conversación de Chat)
        return json.dumps({'pass': True, 'reasoning': 'La conversación cumple con lo pedido en el criterio.'})
    if 'Objetivo de la conversación' in user or 'Conversación hasta ahora' in user:   # llm.suggest_next_turn
        return json.dumps({'text': '', 'option': None, 'done': True, 'collected': {}})
    return '**Qué pasó**\nLa respuesta no cumple lo esperado.\n\n**Causa más probable**\nCambio en el servicio.\n\n**Dónde corregir**\nEl handler.\n\n**Siguiente paso**\nReejecutar.'


class FakeLLM:
    def __init__(self, port=0, model='modelo-demo', required_key=None):
        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.server.requests, self.server.replies, self.server.status = [], [], 200
        self.server.model, self.server.required_key, self.server.default_reply = model, required_key, _default_reply
        self.thread = Thread(target=self.server.serve_forever, daemon=True)

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server.server_port}'

    @property
    def requests(self):
        return self.server.requests

    def queue(self, *replies):
        self.server.replies.extend(replies)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 11434
    with FakeLLM(port) as fake:
        print('Modelo simulado en', fake.url, '(Ctrl+C para salir)')
        try:
            fake.thread.join()
        except KeyboardInterrupt:
            pass
