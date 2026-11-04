"""Adjuntar evidencia a Jira/Azure DevOps: mockea core._httpx_client (sin red real) para verificar la forma
exacta de las requests — no se puede probar contra Jira/AzDO reales desde CI."""
import json
import httpx
import pytest
from app import core, integrations


def _client_with(handler):
    def factory(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(handler))
    return factory


# --------------------------------------------------------------------------- Jira

def test_jira_attach_file_posts_multipart_with_basic_auth_and_xsrf_header(monkeypatch):
    core.secret_set('jira-token-test', 'tok-123')
    captured = {}

    def handler(request):
        captured['method'] = request.method
        captured['url'] = str(request.url)
        captured['headers'] = {k.lower(): v for k, v in request.headers.items()}
        return httpx.Response(200, json={'id': '1'})

    monkeypatch.setattr(core, '_httpx_client', _client_with(handler))
    config = {'site_url': 'https://acme.atlassian.net', 'email': 'qa@acme.com', 'secret': 'jira-token-test'}
    result = integrations.jira_attach_file(config, 'PROJ-1', 'evidencia.html', b'<html></html>', 'text/html')
    assert captured['method'] == 'POST'
    assert captured['url'] == 'https://acme.atlassian.net/rest/api/3/issue/PROJ-1/attachments'
    assert captured['headers']['x-atlassian-token'] == 'no-check'
    assert captured['headers']['authorization'].startswith('Basic ')
    assert result == {'id': '1'}


def test_jira_attach_file_raises_a_readable_error_on_http_failure(monkeypatch):
    core.secret_set('jira-token-test2', 'tok-123')
    monkeypatch.setattr(core, '_httpx_client', _client_with(lambda r: httpx.Response(403, text='Forbidden')))
    config = {'site_url': 'https://acme.atlassian.net', 'email': 'qa@acme.com', 'secret': 'jira-token-test2'}
    with pytest.raises(ValueError, match='403'):
        integrations.jira_attach_file(config, 'PROJ-1', 'f.html', b'x', 'text/html')


def test_jira_attach_file_requires_connection_data():
    with pytest.raises(ValueError, match='Faltan datos'):
        integrations.jira_attach_file({}, 'PROJ-1', 'f.html', b'x', 'text/html')


# --------------------------------------------------------------------------- Azure DevOps

def test_azdo_attach_file_uploads_then_patches_the_work_item(monkeypatch):
    core.secret_set('azdo-pat-test', 'pat-123')
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith('/attachments'):
            return httpx.Response(200, json={'url': 'https://dev.azure.com/acme/proj/_apis/wit/attachments/abc'})
        return httpx.Response(200, json={'id': 42, 'relations': [{'rel': 'AttachedFile'}]})

    monkeypatch.setattr(core, '_httpx_client', _client_with(handler))
    config = {'organization': 'acme', 'project': 'proj', 'secret': 'azdo-pat-test'}
    result = integrations.azdo_attach_file(config, 42, 'evidencia.pdf', b'%PDF-1.4 ...')
    assert len(calls) == 2
    assert calls[0].method == 'POST' and calls[0].url.path.endswith('/attachments')
    assert calls[1].method == 'PATCH' and calls[1].url.path.endswith('/workitems/42')
    body = json.loads(calls[1].content)
    assert body[0]['op'] == 'add' and body[0]['value']['rel'] == 'AttachedFile'
    assert result['id'] == 42


def test_azdo_attach_file_raises_a_readable_error_when_upload_fails(monkeypatch):
    core.secret_set('azdo-pat-test2', 'pat-123')
    monkeypatch.setattr(core, '_httpx_client', _client_with(lambda r: httpx.Response(401, text='Unauthorized')))
    config = {'organization': 'acme', 'project': 'proj', 'secret': 'azdo-pat-test2'}
    with pytest.raises(ValueError, match='401'):
        integrations.azdo_attach_file(config, 42, 'f.pdf', b'x')


def test_azdo_attach_file_requires_connection_data():
    with pytest.raises(ValueError, match='Faltan datos'):
        integrations.azdo_attach_file({}, 42, 'f.pdf', b'x')


# --------------------------------------------------------------------------- core.save_integration

def test_save_integration_validates_platform_and_required_fields():
    project = core.create_project('Integraciones')
    with pytest.raises(ValueError, match='Plataforma'):
        core.save_integration('mal', project['id'], 'trello', {})
    with pytest.raises(ValueError, match='site_url'):
        core.save_integration('jira sin datos', project['id'], 'jira', {})
    saved = core.save_integration('jira ok', project['id'], 'jira',
                                  {'site_url': 'https://acme.atlassian.net', 'email': 'qa@acme.com', 'secret': 'jira-token-test'})
    assert saved['platform'] == 'jira' and saved['config']['site_url'] == 'https://acme.atlassian.net'


def test_save_integration_cascades_on_project_delete():
    project = core.create_project('A borrar')
    core.save_integration('azdo', project['id'], 'azdo', {'organization': 'acme', 'project': 'proj', 'secret': 'azdo-pat-test'})
    assert len(core.list_project_items('integrations', project['id'])) == 1
    core.delete_project_cascade(project['id'])
    assert core.list_project_items('integrations', project['id']) == []


def test_jira_test_connection_returns_the_identified_user(monkeypatch):
    core.secret_set('jira-token-test3', 'tok-123')
    monkeypatch.setattr(core, '_httpx_client', _client_with(lambda r: httpx.Response(200, json={'displayName': 'QA Bot'})))
    config = {'site_url': 'https://acme.atlassian.net', 'email': 'qa@acme.com', 'secret': 'jira-token-test3'}
    assert integrations.jira_test_connection(config) == 'QA Bot'


def test_azdo_test_connection_returns_the_project_name(monkeypatch):
    core.secret_set('azdo-pat-test3', 'pat-123')
    monkeypatch.setattr(core, '_httpx_client', _client_with(lambda r: httpx.Response(200, json={'name': 'proj'})))
    config = {'organization': 'acme', 'project': 'proj', 'secret': 'azdo-pat-test3'}
    assert integrations.azdo_test_connection(config) == 'proj'


def test_test_connection_dispatches_by_platform(monkeypatch):
    calls = []
    monkeypatch.setattr(integrations, 'jira_test_connection', lambda c: calls.append('jira'))
    monkeypatch.setattr(integrations, 'azdo_test_connection', lambda c: calls.append('azdo'))
    integrations.test_connection({'platform': 'jira', 'config': {}})
    integrations.test_connection({'platform': 'azdo', 'config': {}})
    assert calls == ['jira', 'azdo']


def test_attach_evidence_dispatches_by_platform(monkeypatch):
    calls = []
    monkeypatch.setattr(integrations, 'jira_attach_file', lambda *a, **k: calls.append('jira'))
    monkeypatch.setattr(integrations, 'azdo_attach_file', lambda *a, **k: calls.append('azdo'))
    integrations.attach_evidence({'platform': 'jira', 'config': {}}, 'f.html', b'x', 'text/html', 'PROJ-1')
    integrations.attach_evidence({'platform': 'azdo', 'config': {}}, 'f.pdf', b'x', 'application/pdf', 42)
    assert calls == ['jira', 'azdo']
    with pytest.raises(ValueError, match='no soportada'):
        integrations.attach_evidence({'platform': 'trello', 'config': {}}, 'f', b'x', 'text/plain', 1)
