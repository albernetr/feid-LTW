"""Adaptador por plataforma (Jira / Azure DevOps) para adjuntar evidencia, probar conexión, asignar y cambiar
el estado de un ticket/work item, con credenciales propias del usuario — nunca otro cliente HTTP ni otro
almacén de secretos: reutiliza core._httpx_client (TLS contra la raíz de confianza del sistema) y
core.secret_get (mismo llavero que la autenticación de un Ambiente).

Cada plataforma expone las mismas cuatro operaciones (test_connection, attach_evidence, update_assignment,
update_status) bajo el prefijo `<plataforma>_...`; los dispatchers al final del archivo (`test_connection`,
`attach_evidence`, `update_assignment`, `update_status`) son el único punto de entrada que conoce la UI — para
agregar una plataforma nueva basta con escribir sus cuatro funciones y sumar una rama en cada dispatcher,
sin tocar nada más (de la UI ni de otras plataformas). Este módulo no depende de nada específico de este
proyecto salvo `core._httpx_client`/`core.secret_get`, así que se puede llevar tal cual a otro.

Supuesto: Jira **Cloud** (atlassian.net). Jira Server/Data Center usa rutas de API distintas — no cubierto."""
from . import core


def _jira_auth(config):
    site_url = (config.get('site_url') or '').rstrip('/')
    email = config.get('email') or ''
    token = core.secret_get(config.get('secret') or '')
    if not site_url or not email or not token:
        raise ValueError('Faltan datos de conexión a Jira (URL del sitio, email o token).')
    return site_url, email, token


def _azdo_auth(config):
    org, project = config.get('organization') or '', config.get('project') or ''
    token = core.secret_get(config.get('secret') or '')
    if not org or not project or not token:
        raise ValueError('Faltan datos de conexión a Azure DevOps (organización, proyecto o PAT).')
    return org, project, token


# --------------------------------------------------------------------------- Jira (Cloud)

def jira_test_connection(config):
    """GET {site_url}/rest/api/3/myself — confirma credenciales sin tocar ningún ticket."""
    site_url, email, token = _jira_auth(config)
    with core._httpx_client(timeout=15) as client:
        response = client.get(f'{site_url}/rest/api/3/myself', auth=(email, token))
    if response.status_code >= 400:
        raise ValueError(f'Jira respondió {response.status_code}: {response.text[:300]}')
    data = response.json()
    return data.get('displayName') or data.get('emailAddress') or 'conectado'


def jira_attach_file(config, issue_key, filename, content, content_type='application/octet-stream'):
    """POST {site_url}/rest/api/3/issue/{issueKey}/attachments — multipart/form-data, auth Basic
    (email + token API), header X-Atlassian-Token: no-check (sin él, Jira lo rechaza por protección XSRF)."""
    site_url, email, token = _jira_auth(config)
    if not issue_key:
        raise ValueError('Indica el ticket de Jira (p. ej. PROJ-123).')
    url = f'{site_url}/rest/api/3/issue/{issue_key}/attachments'
    with core._httpx_client(timeout=30) as client:
        response = client.post(url, auth=(email, token), headers={'X-Atlassian-Token': 'no-check'},
                                files={'file': (filename, content, content_type)})
    if response.status_code >= 400:
        raise ValueError(f'Jira respondió {response.status_code}: {response.text[:300]}')
    return response.json()


def jira_find_account_id(config, query):
    """Solo lectura: busca el accountId de Jira Cloud a partir de un email o nombre — la API de asignación ya
    no acepta el email directamente, exige accountId."""
    site_url, email, token = _jira_auth(config)
    with core._httpx_client(timeout=20) as client:
        response = client.get(f'{site_url}/rest/api/3/user/search', params={'query': query}, auth=(email, token))
    if response.status_code >= 400:
        raise ValueError(f'Jira (buscar usuario) respondió {response.status_code}: {response.text[:300]}')
    users = response.json()
    if not users:
        raise ValueError(f'No se encontró ningún usuario de Jira que coincida con «{query}».')
    return users[0]['accountId']


def jira_update_assignment(config, issue_key, assigned_to):
    """PUT {site_url}/rest/api/3/issue/{issueKey}/assignee — `assigned_to` es un email o nombre; se resuelve
    primero a accountId vía jira_find_account_id (una llamada de más, pero evita pedirle al usuario ese id)."""
    site_url, email, token = _jira_auth(config)
    if not issue_key:
        raise ValueError('Indica el ticket de Jira (p. ej. PROJ-123).')
    if not (assigned_to or '').strip():
        raise ValueError('Indica a quién asignar el ticket (email o nombre).')
    account_id = jira_find_account_id(config, assigned_to.strip())
    with core._httpx_client(timeout=30) as client:
        response = client.put(f'{site_url}/rest/api/3/issue/{issue_key}/assignee', auth=(email, token), json={'accountId': account_id})
    if response.status_code >= 400:
        raise ValueError(f'Jira (asignar) respondió {response.status_code}: {response.text[:300]}')
    return {'accountId': account_id}


def jira_available_transitions(config, issue_key):
    """Solo lectura: transiciones de flujo disponibles AHORA para este ticket — Jira nunca escribe el estado
    directo, todo cambio de estado pasa por una transición válida desde el estado actual."""
    site_url, email, token = _jira_auth(config)
    with core._httpx_client(timeout=20) as client:
        response = client.get(f'{site_url}/rest/api/3/issue/{issue_key}/transitions', auth=(email, token))
    if response.status_code >= 400:
        raise ValueError(f'Jira (leer transiciones) respondió {response.status_code}: {response.text[:300]}')
    return response.json().get('transitions', [])


def jira_update_status(config, issue_key, status):
    """POST {site_url}/rest/api/3/issue/{issueKey}/transitions — busca, entre las transiciones disponibles
    ahora mismo, la que lleva al estado pedido (por nombre, sin distinguir mayúsculas) y la ejecuta."""
    if not issue_key:
        raise ValueError('Indica el ticket de Jira (p. ej. PROJ-123).')
    status = (status or '').strip()
    if not status:
        raise ValueError('Indica el nuevo estado.')
    site_url, email, token = _jira_auth(config)
    transitions = jira_available_transitions(config, issue_key)
    match = next((t for t in transitions if t['to']['name'].lower() == status.lower() or t['name'].lower() == status.lower()), None)
    if not match:
        available = ', '.join(sorted({t['to']['name'] for t in transitions})) or 'ninguna'
        raise ValueError(f'No hay una transición disponible hacia «{status}» desde el estado actual de {issue_key}. Disponibles: {available}')
    with core._httpx_client(timeout=30) as client:
        response = client.post(f'{site_url}/rest/api/3/issue/{issue_key}/transitions', auth=(email, token),
                                json={'transition': {'id': match['id']}})
    if response.status_code >= 400:
        raise ValueError(f'Jira (cambiar estado) respondió {response.status_code}: {response.text[:300]}')
    return {'transition': match['to']['name']}


# --------------------------------------------------------------------------- Azure DevOps

def azdo_test_connection(config):
    """GET .../_apis/projects/{project} — confirma que el PAT ve ese proyecto."""
    org, project, token = _azdo_auth(config)
    url = f'https://dev.azure.com/{org}/_apis/projects/{project}'
    with core._httpx_client(timeout=15) as client:
        response = client.get(url, params={'api-version': '7.1'}, auth=('', token))
    if response.status_code >= 400:
        raise ValueError(f'Azure DevOps respondió {response.status_code}: {response.text[:300]}')
    return response.json().get('name') or 'conectado'


def azdo_attach_file(config, work_item_id, filename, content):
    """Dos pasos: subir el archivo (devuelve una URL) y parchear el work item para que lo referencie como
    adjunto (JSON Patch). Auth Basic con usuario vacío y el PAT (Personal Access Token) como password."""
    org, project, token = _azdo_auth(config)
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


def _azdo_patch_field(config, work_item_id, field, value):
    org, project, token = _azdo_auth(config)
    url = f'https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{work_item_id}'
    with core._httpx_client(timeout=30) as client:
        response = client.patch(url, params={'api-version': '7.1'}, auth=('', token),
                                 headers={'Content-Type': 'application/json-patch+json'},
                                 json=[{'op': 'add', 'path': f'/fields/{field}', 'value': value}])
    return response


def azdo_update_assignment(config, work_item_id, assigned_to):
    """PATCH System.AssignedTo — `assigned_to` es el email (o nombre único) de alguien de la organización;
    Azure DevOps resuelve la identidad a partir de ese texto, no hace falta un id aparte (a diferencia de Jira)."""
    if not work_item_id:
        raise ValueError('Indica el número del work item.')
    if not (assigned_to or '').strip():
        raise ValueError('Indica a quién asignar el work item (email).')
    response = _azdo_patch_field(config, work_item_id, 'System.AssignedTo', assigned_to.strip())
    if response.status_code >= 400:
        raise ValueError(f'Azure DevOps (asignar) respondió {response.status_code}: {response.text[:300]}')
    return response.json()


def azdo_work_item_type(config, work_item_id):
    """Solo lectura: tipo real del work item (Issue/Epic/Task/...) — hace falta para validar el estado nuevo
    contra los estados propios de SU tipo, no de uno asumido."""
    org, project, token = _azdo_auth(config)
    with core._httpx_client(timeout=20) as client:
        response = client.get(f'https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{work_item_id}',
                               params={'fields': 'System.WorkItemType', 'api-version': '7.1'}, auth=('', token))
    if response.status_code >= 400:
        raise ValueError(f'Azure DevOps (leer work item) respondió {response.status_code}: {response.text[:300]}')
    return response.json()['fields']['System.WorkItemType']


def azdo_valid_states(config, work_item_type):
    """Solo lectura: estados válidos de ese tipo de work item, para poder avisar con un mensaje claro en vez de
    que Azure DevOps lo rechace con un 400 críptico."""
    org, project, token = _azdo_auth(config)
    with core._httpx_client(timeout=20) as client:
        response = client.get(f'https://dev.azure.com/{org}/{project}/_apis/wit/workitemtypes/{work_item_type}/states',
                               params={'api-version': '7.1'}, auth=('', token))
    if response.status_code >= 400:
        return []
    return [s['name'] for s in response.json().get('value', [])]


def azdo_update_status(config, work_item_id, status):
    """PATCH System.State, validado antes contra los estados reales del tipo de ESE work item."""
    if not work_item_id:
        raise ValueError('Indica el número del work item.')
    status = (status or '').strip()
    if not status:
        raise ValueError('Indica el nuevo estado.')
    work_item_type = azdo_work_item_type(config, work_item_id)
    valid = azdo_valid_states(config, work_item_type)
    if valid and status not in valid:
        raise ValueError(f'Estado inválido para {work_item_type}: «{status}». Válidos: {", ".join(valid)}')
    response = _azdo_patch_field(config, work_item_id, 'System.State', status)
    if response.status_code >= 400:
        raise ValueError(f'Azure DevOps (cambiar estado) respondió {response.status_code}: {response.text[:300]}')
    return response.json()


# --------------------------------------------------------------------------- dispatch (único punto que conoce la UI)

def test_connection(integration):
    config = integration.get('config') or {}
    if integration.get('platform') == 'jira':
        return jira_test_connection(config)
    if integration.get('platform') == 'azdo':
        return azdo_test_connection(config)
    raise ValueError('Plataforma de integración no soportada')


def attach_evidence(integration, filename, content, content_type, ticket):
    config = integration.get('config') or {}
    if integration.get('platform') == 'jira':
        return jira_attach_file(config, ticket, filename, content, content_type)
    if integration.get('platform') == 'azdo':
        return azdo_attach_file(config, ticket, filename, content)
    raise ValueError('Plataforma de integración no soportada')


def update_assignment(integration, ticket, assigned_to):
    """Asigna el ticket/work item a una persona (email o, en Jira, también nombre) — mismo punto de entrada
    para la UI, sin que le importe la plataforma."""
    config = integration.get('config') or {}
    if integration.get('platform') == 'jira':
        return jira_update_assignment(config, ticket, assigned_to)
    if integration.get('platform') == 'azdo':
        return azdo_update_assignment(config, ticket, assigned_to)
    raise ValueError('Plataforma de integración no soportada')


def update_status(integration, ticket, status):
    """Cambia el estado del ticket/work item al nombre de estado pedido — mismo punto de entrada para la UI,
    sin que le importe la plataforma (cada una resuelve `status` contra su propio modelo de flujo)."""
    config = integration.get('config') or {}
    if integration.get('platform') == 'jira':
        return jira_update_status(config, ticket, status)
    if integration.get('platform') == 'azdo':
        return azdo_update_status(config, ticket, status)
    raise ValueError('Plataforma de integración no soportada')
