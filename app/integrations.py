"""Adjuntar un archivo de evidencia a un ticket de Jira o un work item de Azure DevOps, con credenciales
propias del usuario — nunca otro cliente HTTP ni otro almacén de secretos: reutiliza core._httpx_client (TLS
contra la raíz de confianza del sistema) y core.secret_get (mismo llavero que la autenticación de un Ambiente).

Supuesto: Jira **Cloud** (atlassian.net). Jira Server/Data Center usa rutas de API distintas — no cubierto."""
from . import core


def jira_attach_file(config, issue_key, filename, content, content_type='application/octet-stream'):
    """POST {site_url}/rest/api/3/issue/{issueKey}/attachments — multipart/form-data, auth Basic
    (email + token API), header X-Atlassian-Token: no-check (sin él, Jira lo rechaza por protección XSRF)."""
    site_url = (config.get('site_url') or '').rstrip('/')
    email = config.get('email') or ''
    token = core.secret_get(config.get('secret') or '')
    if not site_url or not email or not token:
        raise ValueError('Faltan datos de conexión a Jira (URL del sitio, email o token).')
    if not issue_key:
        raise ValueError('Indica el ticket de Jira (p. ej. PROJ-123).')
    url = f'{site_url}/rest/api/3/issue/{issue_key}/attachments'
    with core._httpx_client(timeout=30) as client:
        response = client.post(url, auth=(email, token), headers={'X-Atlassian-Token': 'no-check'},
                                files={'file': (filename, content, content_type)})
    if response.status_code >= 400:
        raise ValueError(f'Jira respondió {response.status_code}: {response.text[:300]}')
    return response.json()


def azdo_attach_file(config, work_item_id, filename, content):
    """Dos pasos: subir el archivo (devuelve una URL) y parchear el work item para que lo referencie como
    adjunto (JSON Patch). Auth Basic con usuario vacío y el PAT (Personal Access Token) como password."""
    org, project = config.get('organization') or '', config.get('project') or ''
    token = core.secret_get(config.get('secret') or '')
    if not org or not project or not token:
        raise ValueError('Faltan datos de conexión a Azure DevOps (organización, proyecto o PAT).')
    if not work_item_id:
        raise ValueError('Indica el número del work item.')
    base = f'https://dev.azure.com/{org}/{project}/_apis/wit'
    with core._httpx_client(timeout=30) as client:
        upload = client.post(f'{base}/attachments', params={'fileName': filename, 'api-version': '7.1'}, auth=('', token),
                              content=content, headers={'Content-Type': 'application/octet-stream'})
        if upload.status_code >= 400:
            raise ValueError(f'Azure DevOps (subir archivo) respondió {upload.status_code}: {upload.text[:300]}')
        attachment_url = upload.json()['url']
        patch = client.patch(f'{base}/workitems/{work_item_id}', params={'api-version': '7.1'}, auth=('', token),
                              headers={'Content-Type': 'application/json-patch+json'},
                              json=[{'op': 'add', 'path': '/relations/-',
                                     'value': {'rel': 'AttachedFile', 'url': attachment_url, 'attributes': {'comment': filename}}}])
    if patch.status_code >= 400:
        raise ValueError(f'Azure DevOps (adjuntar al work item) respondió {patch.status_code}: {patch.text[:300]}')
    return patch.json()


def attach_evidence(integration, filename, content, content_type, ticket):
    """Despacha según la plataforma de la integración — mismo punto de entrada para la UI."""
    config = integration.get('config') or {}
    if integration.get('platform') == 'jira':
        return jira_attach_file(config, ticket, filename, content, content_type)
    if integration.get('platform') == 'azdo':
        return azdo_attach_file(config, ticket, filename, content)
    raise ValueError('Plataforma de integración no soportada')


# --------------------------------------------------------------------------- probar conexión (sin adjuntar nada)

def jira_test_connection(config):
    """GET {site_url}/rest/api/3/myself — confirma credenciales sin tocar ningún ticket."""
    site_url = (config.get('site_url') or '').rstrip('/')
    email = config.get('email') or ''
    token = core.secret_get(config.get('secret') or '')
    if not site_url or not email or not token:
        raise ValueError('Faltan datos de conexión a Jira (URL del sitio, email o token).')
    with core._httpx_client(timeout=15) as client:
        response = client.get(f'{site_url}/rest/api/3/myself', auth=(email, token))
    if response.status_code >= 400:
        raise ValueError(f'Jira respondió {response.status_code}: {response.text[:300]}')
    data = response.json()
    return data.get('displayName') or data.get('emailAddress') or 'conectado'


def azdo_test_connection(config):
    """GET .../_apis/projects/{project} — confirma que el PAT ve ese proyecto."""
    org, project = config.get('organization') or '', config.get('project') or ''
    token = core.secret_get(config.get('secret') or '')
    if not org or not project or not token:
        raise ValueError('Faltan datos de conexión a Azure DevOps (organización, proyecto o PAT).')
    url = f'https://dev.azure.com/{org}/_apis/projects/{project}'
    with core._httpx_client(timeout=15) as client:
        response = client.get(url, params={'api-version': '7.1'}, auth=('', token))
    if response.status_code >= 400:
        raise ValueError(f'Azure DevOps respondió {response.status_code}: {response.text[:300]}')
    return response.json().get('name') or 'conectado'


def test_connection(integration):
    config = integration.get('config') or {}
    if integration.get('platform') == 'jira':
        return jira_test_connection(config)
    if integration.get('platform') == 'azdo':
        return azdo_test_connection(config)
    raise ValueError('Plataforma de integración no soportada')
