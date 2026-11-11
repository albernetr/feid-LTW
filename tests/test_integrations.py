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


# --------------------------------------------------------------------------- asignar / cambiar estado — Jira

def test_jira_update_assignment_resolves_account_id_then_puts_it(monkeypatch):
    core.secret_set('jira-token-assign', 'tok-123')
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith('/user/search'):
            return httpx.Response(200, json=[{'accountId': 'acc-1'}])
        return httpx.Response(204)

    monkeypatch.setattr(core, '_httpx_client', _client_with(handler))
    config = {'site_url': 'https://acme.atlassian.net', 'email': 'qa@acme.com', 'secret': 'jira-token-assign'}
    result = integrations.jira_update_assignment(config, 'PROJ-1', 'dev@acme.com')
    assert result == {'accountId': 'acc-1'}
    assert calls[0].url.params['query'] == 'dev@acme.com'
    assert calls[1].method == 'PUT' and calls[1].url.path.endswith('/issue/PROJ-1/assignee')
    assert json.loads(calls[1].content) == {'accountId': 'acc-1'}


def test_jira_update_assignment_raises_when_no_user_matches(monkeypatch):
    core.secret_set('jira-token-assign2', 'tok-123')
    monkeypatch.setattr(core, '_httpx_client', _client_with(lambda r: httpx.Response(200, json=[])))
    config = {'site_url': 'https://acme.atlassian.net', 'email': 'qa@acme.com', 'secret': 'jira-token-assign2'}
    with pytest.raises(ValueError, match='No se encontró ningún usuario'):
        integrations.jira_update_assignment(config, 'PROJ-1', 'nadie@acme.com')


def test_jira_update_status_posts_the_matching_transition(monkeypatch):
    core.secret_set('jira-token-status', 'tok-123')
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.path.endswith('/transitions') and request.method == 'GET':
            return httpx.Response(200, json={'transitions': [{'id': '31', 'name': 'Done', 'to': {'name': 'Hecho'}}]})
        return httpx.Response(204)

    monkeypatch.setattr(core, '_httpx_client', _client_with(handler))
    config = {'site_url': 'https://acme.atlassian.net', 'email': 'qa@acme.com', 'secret': 'jira-token-status'}
    result = integrations.jira_update_status(config, 'PROJ-1', 'hecho')
    assert result == {'transition': 'Hecho'}
    assert calls[1].method == 'POST' and json.loads(calls[1].content) == {'transition': {'id': '31'}}


def test_jira_update_status_raises_with_available_transitions_when_none_matches(monkeypatch):
    core.secret_set('jira-token-status2', 'tok-123')
    monkeypatch.setattr(core, '_httpx_client', _client_with(
        lambda r: httpx.Response(200, json={'transitions': [{'id': '1', 'name': 'Start', 'to': {'name': 'En progreso'}}]})))
    config = {'site_url': 'https://acme.atlassian.net', 'email': 'qa@acme.com', 'secret': 'jira-token-status2'}
    with pytest.raises(ValueError, match='En progreso'):
        integrations.jira_update_status(config, 'PROJ-1', 'Cerrado')


# --------------------------------------------------------------------------- asignar / cambiar estado — Azure DevOps

def test_azdo_update_assignment_patches_assigned_to(monkeypatch):
    core.secret_set('azdo-pat-assign', 'pat-123')
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'id': 42})

    monkeypatch.setattr(core, '_httpx_client', _client_with(handler))
    config = {'organization': 'acme', 'project': 'proj', 'secret': 'azdo-pat-assign'}
    result = integrations.azdo_update_assignment(config, 42, 'dev@acme.com')
    assert result == {'id': 42}
    body = json.loads(calls[0].content)
    assert body[0]['path'] == '/fields/System.AssignedTo' and body[0]['value'] == 'dev@acme.com'


def test_azdo_update_assignment_requires_assigned_to():
    with pytest.raises(ValueError, match='Indica a quién asignar'):
        integrations.azdo_update_assignment({'organization': 'acme', 'project': 'proj', 'secret': 'x'}, 42, '')


def test_azdo_update_status_validates_against_the_work_item_types_real_states(monkeypatch):
    core.secret_set('azdo-pat-status', 'pat-123')

    def handler(request):
        if request.url.path.endswith('/states'):
            return httpx.Response(200, json={'value': [{'name': 'To Do'}, {'name': 'Doing'}, {'name': 'Done'}]})
        if request.method == 'GET':   # leer el tipo del work item
            return httpx.Response(200, json={'fields': {'System.WorkItemType': 'Issue'}})
        return httpx.Response(200, json={'id': 42})

    monkeypatch.setattr(core, '_httpx_client', _client_with(handler))
    config = {'organization': 'acme', 'project': 'proj', 'secret': 'azdo-pat-status'}
    assert integrations.azdo_update_status(config, 42, 'Doing') == {'id': 42}
    with pytest.raises(ValueError, match='Estado inválido'):
        integrations.azdo_update_status(config, 42, 'Cerrado')


# --------------------------------------------------------------------------- dispatch genérico

def test_update_assignment_and_update_status_dispatch_by_platform(monkeypatch):
    calls = []
    monkeypatch.setattr(integrations, 'jira_update_assignment', lambda c, t, v: calls.append(('jira-assign', t, v)))
    monkeypatch.setattr(integrations, 'azdo_update_assignment', lambda c, t, v: calls.append(('azdo-assign', t, v)))
    monkeypatch.setattr(integrations, 'jira_update_status', lambda c, t, v: calls.append(('jira-status', t, v)))
    monkeypatch.setattr(integrations, 'azdo_update_status', lambda c, t, v: calls.append(('azdo-status', t, v)))

    integrations.update_assignment({'platform': 'jira', 'config': {}}, 'PROJ-1', 'qa@acme.com')
    integrations.update_assignment({'platform': 'azdo', 'config': {}}, 42, 'qa@acme.com')
    integrations.update_status({'platform': 'jira', 'config': {}}, 'PROJ-1', 'Hecho')
    integrations.update_status({'platform': 'azdo', 'config': {}}, 42, 'Doing')
    assert calls == [
        ('jira-assign', 'PROJ-1', 'qa@acme.com'), ('azdo-assign', 42, 'qa@acme.com'),
        ('jira-status', 'PROJ-1', 'Hecho'), ('azdo-status', 42, 'Doing'),
    ]
    with pytest.raises(ValueError, match='no soportada'):
        integrations.update_assignment({'platform': 'trello', 'config': {}}, 1, 'x')
    with pytest.raises(ValueError, match='no soportada'):
        integrations.update_status({'platform': 'trello', 'config': {}}, 1, 'x')
