"""Chatbot WhatsApp-style ficticio (seguros), para probar flujos conversacionales de varios turnos con LTW.

POST /api/chat/messages  - formato de petición y respuesta inspirados en un bot real de calificación de leads.
Guarda estado por conversation_id/thread_id: el mismo hilo avanza de pregunta en pregunta; uno nuevo arranca de cero.

Run it manually with:  python -m sample_app.chat_server   (http://127.0.0.1:8766)
"""
import json
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

TURNS = [
    {'text': '¡Gracias por aceptar! ¿A quién te gustaría proteger y qué tipo de seguro estás buscando?', 'field': 'BUSINESSLINE'},
    {'text': '¿Cuál es el nombre completo de la persona a asegurar?', 'field': 'INSURED_NAME'},
    {'text': 'Perfecto, en breve un asesor te contactará para cotizar. ¡Gracias!', 'field': None},
]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _body(self):
        length = int(self.headers.get('Content-Length', 0))
        try:
            return json.loads(self.rfile.read(length) or b'{}')
        except ValueError:
            return None

    def do_POST(self):
        if self.path.split('?')[0] != '/api/chat/messages':
            return self._send(404, {'error': 'not found'})
        data = self._body()
        if data is None:
            return self._send(400, {'error': 'invalid json'})
        if not (data.get('message') or '').strip():
            return self._send(422, {'error': 'message is required'})
        attrs = data.get('attributes') or {}
        if not attrs.get('consent'):
            return self._send(422, {'error': 'attributes.consent is required'})

        conversation_id = (data.get('conversation_id') or '').strip()
        threads = self.server.threads
        if not conversation_id or conversation_id not in threads:
            conversation_id = conversation_id or str(uuid.uuid4())
            threads[conversation_id] = {'turn': 0, 'answered': []}
        state = threads[conversation_id]
        turn = TURNS[min(state['turn'], len(TURNS) - 1)]
        if state['turn'] > 0:
            previous_field = TURNS[state['turn'] - 1]['field']
            if previous_field:
                state['answered'].append({'field': previous_field, 'value': data['message'][:120], 'confidence': 'high', 'source': 'provided'})
        state['turn'] += 1
        closing = state['turn'] >= len(TURNS)

        self._send(200, {
            'thread_id': conversation_id, 'mensaje': data['message'], 'respuesta': turn['text'], 'tool_calls': [],
            'lead_status': 'CLOSED' if closing else 'CAPTURED', 'action': 'handoff_to_agent' if closing else None,
            'close_reason': 'QUALIFIED' if closing else None, 'lead_id': self.server.lead_id,
            'channel': 'WhatsApp', 'role': 'Person', 'scope': 'Unique',
            'conversation': {
                'conversationId': conversation_id,
                'replies': [{'text': turn['text'], 'purpose': 'closing' if closing else 'question', 'options': [], 'citations': []}],
                'status': 'closed' if closing else 'active', 'askedField': turn['field'], 'rfcLookup': None,
                'businessLine': data.get('campaign') or 'IP', 'businessLineReason': 'PROVIDED_AT_START',
                'answeredFields': state['answered'], 'discardFields': [],
                'events': ['LOB_IDENTIFIED'] if state['turn'] == 1 else (['LEAD_QUALIFIED'] if closing else []),
                'closeReason': 'QUALIFIED' if closing else None, 'summary': None, 'flags': '',
                'promptVersion': '0.10.8-ficticio', 'corpusVersion': None, 'debug': None,
            },
        })


class ChatApp:
    def __init__(self, port=0):
        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.server.threads = {}
        self.server.lead_id = 'LEAD001'
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
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
    with ChatApp(port) as app:
        print('Chatbot ficticio en', app.url, '· POST /api/chat/messages (Ctrl+C para salir)')
        try:
            app.thread.join()
        except KeyboardInterrupt:
            pass
