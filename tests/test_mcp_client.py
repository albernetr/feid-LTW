"""Cliente MCP genérico (JSON-RPC sobre HTTP, transporte streamable-HTTP) — ver app/mcp_client.py. Las
respuestas de este test usan la forma real que devuelve `npx @playwright/mcp@latest` (capturadas a mano contra
el paquete real durante el diseño de esta función), no una aproximación."""
import httpx
import pytest
from app import mcp_client

INITIALIZE_SSE = (
    'event: message\r\n'
    'data: {"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{"listChanged":true}},'
    '"serverInfo":{"name":"Playwright","version":"1.65.0-alpha-2026-10-30"}},"jsonrpc":"2.0","id":1}\r\n\r\n'
)
TOOLS_CALL_SSE = (
    'event: message\r\n'
    'data: {"result":{"content":[{"type":"text","text":"### Ran Playwright code\\n```js\\nawait '
    'page.goto(\'http://127.0.0.1:8080/\');\\n```\\n### Page\\n- Page URL: http://127.0.0.1:8080/login"}]},'
    '"jsonrpc":"2.0","id":2}\r\n\r\n'
)
ERROR_RESULT_SSE = (
    'event: message\r\n'
    'data: {"result":{"content":[{"type":"text","text":"### Error\\nError: Browser is already in use"}],'
    '"isError":true},"jsonrpc":"2.0","id":3}\r\n\r\n'
)
RPC_ERROR_SSE = (
    'event: message\r\n'
    'data: {"error":{"code":-32602,"message":"Unknown tool: no_existe"},"jsonrpc":"2.0","id":4}\r\n\r\n'
)


def _fake_transport(responses):
    """`responses`: lista de (texto_sse, headers_extra) — una por POST, en orden."""
    calls = []

    def handler(request):
        text, extra_headers = responses[len(calls)]
        calls.append(request)
        headers = {'content-type': 'text/event-stream', **extra_headers}
        return httpx.Response(200, headers=headers, text=text)
    return httpx.MockTransport(handler), calls


def _patch_httpx_post(monkeypatch, responses):
    transport, calls = _fake_transport(responses)
    client = httpx.Client(transport=transport)

    def fake_post(url, headers=None, json=None, timeout=None):
        return client.post(url, headers=headers, json=json)
    monkeypatch.setattr(mcp_client.httpx, 'post', fake_post)
    return calls


def test_initialize_captures_the_session_id_and_sends_the_initialized_notification(monkeypatch):
    calls = _patch_httpx_post(monkeypatch, [
        (INITIALIZE_SSE, {'mcp-session-id': 'abc-123'}),
        ('', {}),  # respuesta a notifications/initialized (202 Accepted sin cuerpo, en la práctica)
    ])
    session = mcp_client.MCPSession(8931)
    result = session.initialize()
    assert result['serverInfo']['name'] == 'Playwright'
    assert session.session_id == 'abc-123'
    assert len(calls) == 2
    assert calls[1].headers['mcp-session-id'] == 'abc-123'  # la notificación ya va con el header de sesión
    import json as _json
    assert _json.loads(calls[1].content)['method'] == 'notifications/initialized'


def test_call_tool_returns_the_result_and_reuses_the_session_id(monkeypatch):
    calls = _patch_httpx_post(monkeypatch, [
        (INITIALIZE_SSE, {'mcp-session-id': 'abc-123'}),
        ('', {}),
        (TOOLS_CALL_SSE, {}),
    ])
    session = mcp_client.MCPSession(8931)
    session.initialize()
    result = session.call_tool('browser_navigate', {'url': 'http://127.0.0.1:8080/'})
    assert 'Page URL: http://127.0.0.1:8080/login' in mcp_client.text_of(result)
    assert calls[2].headers['mcp-session-id'] == 'abc-123'


def test_call_tool_raises_on_a_tool_level_error(monkeypatch):
    _patch_httpx_post(monkeypatch, [(ERROR_RESULT_SSE, {})])
    session = mcp_client.MCPSession(8931)
    with pytest.raises(mcp_client.MCPError, match='Browser is already in use'):
        session.call_tool('browser_navigate', {'url': 'http://x/'})


def test_call_tool_raises_on_a_json_rpc_error(monkeypatch):
    _patch_httpx_post(monkeypatch, [(RPC_ERROR_SSE, {})])
    session = mcp_client.MCPSession(8931)
    with pytest.raises(mcp_client.MCPError, match='Unknown tool'):
        session.call_tool('no_existe', {})


def test_initialize_raises_a_clear_error_on_timeout(monkeypatch):
    def timeout(*a, **k):
        raise httpx.TimeoutException('boom')
    monkeypatch.setattr(mcp_client.httpx, 'post', timeout)
    session = mcp_client.MCPSession(8931, timeout=1)
    with pytest.raises(mcp_client.MCPError, match='no respondió'):
        session.initialize()


def test_initialize_raises_a_clear_error_when_nothing_is_listening(monkeypatch):
    def refused(*a, **k):
        raise httpx.ConnectError('refused')
    monkeypatch.setattr(mcp_client.httpx, 'post', refused)
    session = mcp_client.MCPSession(8931)
    with pytest.raises(mcp_client.MCPError, match='No se pudo conectar'):
        session.initialize()


def test_text_of_joins_every_text_part():
    result = {'content': [{'type': 'text', 'text': 'uno'}, {'type': 'image', 'data': 'xyz'}, {'type': 'text', 'text': 'dos'}]}
    assert mcp_client.text_of(result) == 'uno\ndos'
