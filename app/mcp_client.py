"""Cliente MCP genérico (JSON-RPC sobre HTTP, transporte streamable-HTTP) — no sabe nada de Playwright ni de
Casos UI, solo habla el protocolo Model Context Protocol con cualquier servidor que lo use (hoy, el puente de
mcp_bridge.py; eventualmente podría reusarse para que app/llm.py hable MCP también). Las respuestas llegan
envueltas en SSE (`event: message\\ndata: {...}`), no como JSON plano — hay que desenvolverlas.
"""
import itertools
import json
import httpx

PROTOCOL_VERSION = '2024-11-05'


class MCPError(RuntimeError):
    """Algo detuvo la conversación con el servidor MCP: no responde, no habla el protocolo, o una herramienta devolvió un error."""


def _parse_response(response):
    """Streamable-HTTP envuelve cada respuesta en SSE (`event: message` + `data: {...}`), a veces varios
    eventos por cuerpo — se queda con el último `data` parseable. Si el cuerpo ya es JSON plano (otro
    transporte), lo usa tal cual."""
    content_type = response.headers.get('content-type', '')
    if content_type.startswith('text/event-stream'):
        payload = None
        for line in response.text.splitlines():
            if line.startswith('data:'):
                try:
                    payload = json.loads(line[len('data:'):].strip())
                except ValueError:
                    continue
        if payload is None:
            raise MCPError('El servidor MCP respondió un evento sin datos utilizables.')
        return payload
    try:
        return response.json()
    except ValueError:
        raise MCPError('La respuesta del servidor MCP no es JSON (¿la URL apunta al endpoint correcto, termina en /mcp?).')


def text_of(result):
    """El texto plano de un resultado de tools/call — la forma habitual en la que Playwright MCP devuelve
    snapshots, el estado de la página y el código que ejecutó."""
    parts = [p.get('text', '') for p in (result.get('content') or []) if p.get('type') == 'text']
    return '\n'.join(parts)


class MCPSession:
    """Una sesión contra un servidor MCP local (p. ej. `npx @playwright/mcp --extension --port N`, ver
    mcp_bridge.py). `initialize()` abre la sesión; `call_tool(...)` invoca una de sus herramientas."""

    def __init__(self, port, host='127.0.0.1', timeout=10.0):
        self.url = f'http://{host}:{port}/mcp'
        self.timeout = timeout
        self.session_id = None
        self._ids = itertools.count(1)

    def _post(self, body):
        headers = {'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'}
        if self.session_id:
            headers['Mcp-Session-Id'] = self.session_id
        try:
            response = httpx.post(self.url, headers=headers, json=body, timeout=self.timeout)
        except httpx.TimeoutException:
            raise MCPError(f'El puente MCP no respondió en {int(self.timeout)} s.')
        except httpx.TransportError as exc:
            raise MCPError(f'No se pudo conectar al puente MCP en {self.url}: ¿está abierto? ({type(exc).__name__})')
        session_id = response.headers.get('mcp-session-id')
        if session_id:
            self.session_id = session_id
        return response

    def initialize(self):
        response = self._post({'jsonrpc': '2.0', 'id': next(self._ids), 'method': 'initialize',
                                'params': {'protocolVersion': PROTOCOL_VERSION, 'capabilities': {},
                                           'clientInfo': {'name': 'local-test-workspace', 'version': '1.0'}}})
        payload = _parse_response(response)
        if payload.get('error'):
            raise MCPError(payload['error'].get('message') or 'El servidor MCP rechazó la inicialización.')
        # El protocolo exige confirmar la sesión con esta notificación antes de llamar a nada más — no tiene
        # id ni devuelve una respuesta que leer (ver notifications/initialized en la especificación de MCP).
        self._post({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        return payload.get('result')

    def call_tool(self, name, arguments=None):
        response = self._post({'jsonrpc': '2.0', 'id': next(self._ids), 'method': 'tools/call',
                                'params': {'name': name, 'arguments': arguments or {}}})
        payload = _parse_response(response)
        if payload.get('error'):
            raise MCPError(payload['error'].get('message') or f'La herramienta «{name}» falló.')
        result = payload.get('result') or {}
        if result.get('isError'):
            raise MCPError(text_of(result) or f'La herramienta «{name}» devolvió un error.')
        return result
