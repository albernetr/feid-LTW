"""Portable workspace storage, import, assertions and HTTP execution."""
import contextlib
import copy
import datetime as dt
import json
import os
import re
import shutil
import socket
import sqlite3
import ssl
import sys
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import urlparse, urljoin
import httpx
import yaml

VERSION = '1.0.0'
LEGACY_ROOT = Path.home() / '.local_test_workspace'


def app_dir():
    """Folder of the package: next to the .exe when frozen, otherwise the project root."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def default_root():
    """Portable mode: data lives in <package>/data. TEST_WORKSPACE_HOME overrides; a read-only package falls back to the user profile."""
    override = os.environ.get('TEST_WORKSPACE_HOME')
    if override:
        return Path(override)
    package = app_dir()
    return package / 'data' if os.access(package, os.W_OK) else LEGACY_ROOT


ROOT = default_root()
DB = ROOT / 'workspace.sqlite3'
ARTIFACTS = ROOT / 'evidence'

SECRET_SERVICE = 'local-test-workspace'
SENSITIVE_HEADERS = ('authorization', 'cookie', 'set-cookie', 'x-api-key', 'proxy-authorization')
SENSITIVE_NAME = re.compile(r'token|password|passwd|secret|key|authorization|cookie', re.I)
TABLES = ('projects', 'module_groups', 'modules', 'environments', 'cases', 'features', 'suites', 'schedules')
ALL_TABLES = TABLES + ('settings', 'runs', 'taps', 'interfaces', 'lab_history', 'llm_profiles')
UUID_RE = re.compile(r'^[0-9a-fA-F-]{8,64}$')


def migrate_legacy_data():
    """One-time, non-destructive copy of a pre-1.0 workspace (~/.local_test_workspace) into the package data folder."""
    legacy_db = LEGACY_ROOT / 'workspace.sqlite3'
    if ROOT == LEGACY_ROOT or DB.exists() or not legacy_db.exists() or os.environ.get('TEST_WORKSPACE_HOME'):
        return False
    ROOT.mkdir(parents=True, exist_ok=True)
    with contextlib.closing(sqlite3.connect(legacy_db)) as source, contextlib.closing(sqlite3.connect(DB)) as target:
        source.backup(target)  # consistent copy even if WAL is active
    evidence = LEGACY_ROOT / 'evidence'
    if evidence.is_dir() and not ARTIFACTS.exists():
        shutil.copytree(evidence, ARTIFACTS)
    return True


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def uid():
    return str(uuid.uuid4())


# --------------------------------------------------------------------------- storage

class ConflictError(ValueError):
    """Someone else saved the record after it was loaded (shared database)."""


_UNSET = object()


def on_network_drive(path):
    """True for UNC paths and mapped network drives: SQLite's WAL mode is unsafe there."""
    text = str(path)
    if text.startswith('\\\\'):
        return True
    if os.name == 'nt':
        try:
            import ctypes
            return ctypes.windll.kernel32.GetDriveTypeW(os.path.splitdrive(text)[0] + '\\') == 4  # DRIVE_REMOTE
        except Exception:
            return False
    return False


@contextlib.contextmanager
def _open(**kwargs):
    """Connection that waits for other writers (no 'database is locked') and is always closed:
    sqlite3's own context manager only commits, and a lingering handle blocks other people sharing the file."""
    con = sqlite3.connect(DB, timeout=30, **kwargs)
    try:
        with con:
            yield con
    finally:
        con.close()


def initialize():
    ROOT.mkdir(parents=True, exist_ok=True)
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    with _open() as con:
        con.execute('PRAGMA journal_mode=' + ('DELETE' if on_network_drive(DB) else 'WAL'))
        for table in ALL_TABLES:
            con.execute(f'CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')


def reset_workspace(remove_evidence=True):
    """Wipes the current workspace (database and, by default, evidence/): irreversible, meant for
    "start from zero". Secrets in the OS credential manager are untouched; they are not tied to this database."""
    for suffix in ('', '-wal', '-shm', '-journal'):
        path = Path(str(DB) + suffix)
        if path.exists():
            try:
                path.unlink()
            except OSError as exc:
                raise ValueError(
                    f'No se pudo borrar «{path.name}»: está en uso. Cierra el scheduler (scheduler.bat) y '
                    'cualquier otra ventana o proceso de la aplicación, y vuelve a intentar.') from exc
    if remove_evidence and ARTIFACTS.exists():
        shutil.rmtree(ARTIFACTS, ignore_errors=True)
    initialize()


def list_items(table):
    initialize()
    with _open() as con:
        return [json.loads(row[0]) for row in con.execute(f'SELECT payload FROM {table} ORDER BY rowid DESC')]


def list_project_items(table, project_id):
    """Items of the project; without a project (None) every item is returned."""
    items = list_items(table)
    if project_id is None:
        return items
    return [item for item in items if item.get('project_id') == project_id]


def get(table, identifier):
    initialize()
    with _open() as con:
        row = con.execute(f'SELECT payload FROM {table} WHERE id=?', (identifier,)).fetchone()
    return json.loads(row[0]) if row else None


def save(table, item, expected_updated_at=_UNSET):
    """Insert or replace. With expected_updated_at the write is refused (ConflictError) if the stored record
    changed since it was loaded, so two people editing the same record cannot silently overwrite each other."""
    initialize()
    item = copy.deepcopy(item)
    item.setdefault('id', uid())
    if expected_updated_at is not _UNSET:
        with transaction() as con:
            row = con.execute(f'SELECT payload FROM {table} WHERE id=?', (item['id'],)).fetchone()
            stored = json.loads(row[0]).get('updated_at') if row else None
            if stored != expected_updated_at:
                raise ConflictError('Otra persona modificó este registro mientras lo editabas. Recarga la página y vuelve a aplicar tus cambios.')
            return save_in(con, table, item)
    item['updated_at'] = now()
    with _open() as con:
        con.execute(f'INSERT OR REPLACE INTO {table} VALUES (?,?)', (item['id'], json.dumps(item, ensure_ascii=False)))
    return item


def delete(table, identifier):
    initialize()
    with _open() as con:
        con.execute(f'DELETE FROM {table} WHERE id=?', (identifier,))


@contextlib.contextmanager
def transaction():
    """Single SQLite transaction; any exception rolls everything back."""
    initialize()
    con = sqlite3.connect(DB, timeout=30, isolation_level=None)
    try:
        con.execute('BEGIN IMMEDIATE')
        yield con
        con.execute('COMMIT')
    except BaseException:
        con.execute('ROLLBACK')
        raise
    finally:
        con.close()


def save_in(con, table, item):
    item = copy.deepcopy(item)
    item.setdefault('id', uid())
    item['updated_at'] = now()
    con.execute(f'INSERT OR REPLACE INTO {table} VALUES (?,?)', (item['id'], json.dumps(item, ensure_ascii=False)))
    return item


def get_setting(name, default=None):
    setting = get('settings', name)
    return setting.get('value', default) if setting else default


def set_setting(name, value):
    save('settings', {'id': name, 'value': value})


# --------------------------------------------------------------------------- projects

def get_active_project_id():
    return get_setting('active_project_id')


def set_active_project(project_id):
    if project_id is not None:
        project = get('projects', project_id)
        if project is None:
            raise ValueError('Proyecto inexistente')
        if project.get('disabled'):
            raise ValueError('Este proyecto está deshabilitado; habilítalo primero para seleccionarlo.')
    set_setting('active_project_id', project_id)


def set_project_enabled(project_id, enabled):
    project = get('projects', project_id)
    if project is None:
        raise ValueError('Proyecto inexistente')
    project['disabled'] = not enabled
    saved = save('projects', project)
    if not enabled and get_active_project_id() == project_id:
        set_active_project(None)
    return saved


def _project_name_taken(name, exclude_id=None):
    return any(p['id'] != exclude_id and p['name'].strip().lower() == name.lower() for p in list_items('projects'))


def create_project(name, description=''):
    name = name.strip()
    if not name:
        raise ValueError('El nombre del proyecto es obligatorio')
    if _project_name_taken(name):
        raise ValueError(f'Ya existe un proyecto llamado «{name}»')
    project = save('projects', {'name': name, 'description': description.strip(), 'version': 1})
    if get_active_project_id() is None:
        set_active_project(project['id'])
    return project


def update_project(project_id, name, description=''):
    project = get('projects', project_id)
    if project is None:
        raise ValueError('Proyecto inexistente')
    name = name.strip()
    if not name:
        raise ValueError('El nombre del proyecto es obligatorio')
    if _project_name_taken(name, exclude_id=project_id):
        raise ValueError(f'Ya existe un proyecto llamado «{name}»')
    project.update({'name': name, 'description': description.strip()})
    return save('projects', project)


def project_stats(project_id):
    if get('projects', project_id) is None:
        raise ValueError('Proyecto inexistente')
    return {
        table: sum(item.get('project_id') == project_id for item in list_items(table))
        for table in ('module_groups', 'modules', 'environments', 'cases', 'features', 'suites', 'schedules', 'taps')
    }


PROJECT_RESOURCE_LABELS = {'module_groups': 'módulo(s)', 'modules': 'componente(s)', 'environments': 'ambiente(s)', 'cases': 'caso(s)',
                           'features': 'funcionalidad(es)', 'suites': 'suite(s)', 'schedules': 'programación(es)', 'taps': 'tap(s) de observación'}


def _purge_project_history(project_id):
    """Removes a project's runs and observed interfaces (with the runs' evidence files). Not counted as
    'blocking' content in project_stats (a user doesn't consciously manage history the way they manage
    modules/cases), but leaving it behind as an orphan once the project is gone serves no one either."""
    for run in list_items('runs'):
        if run.get('project_id') != project_id:
            continue
        for name in (run.get('screenshot'), run.get('trace')):
            if name:
                path = ARTIFACTS / Path(name).name
                if path.is_file():
                    path.unlink()
        delete('runs', run['id'])
    for interface in list_items('interfaces'):
        if interface.get('project_id') == project_id:
            delete('interfaces', interface['id'])


def delete_project(project_id):
    if get('projects', project_id) is None:
        raise ValueError('Proyecto inexistente')
    stats = project_stats(project_id)
    blocking = {table: count for table, count in stats.items() if count}
    if blocking:
        detail = ', '.join(f'{count} {PROJECT_RESOURCE_LABELS.get(table, table)}' for table, count in blocking.items())
        raise ValueError(f'No se puede eliminar: tiene {detail}. Bórralos o muévelos a otro proyecto primero.')
    _purge_project_history(project_id)
    delete('projects', project_id)
    if get_active_project_id() == project_id:
        set_active_project(None)


CASCADE_TABLES = ('module_groups', 'modules', 'environments', 'cases', 'features', 'suites', 'schedules', 'taps')


def delete_project_cascade(project_id):
    """Deletes the project AND every resource that belongs to it: irreversible, unlike the safe delete_project()
    above (which refuses when there is still content). Lab history is per-author, not per-project, so it is
    left untouched."""
    if get('projects', project_id) is None:
        raise ValueError('Proyecto inexistente')
    _purge_project_history(project_id)
    with transaction() as con:
        for table in CASCADE_TABLES:
            ids = [item['id'] for item in list_items(table) if item.get('project_id') == project_id]
            for item_id in ids:
                con.execute(f'DELETE FROM {table} WHERE id=?', (item_id,))
        con.execute('DELETE FROM projects WHERE id=?', (project_id,))
    if get_active_project_id() == project_id:
        set_active_project(None)


def adopt_unassigned(project_id):
    """Assigns legacy records that have no project to the given project."""
    if get('projects', project_id) is None:
        raise ValueError('Proyecto inexistente')
    adopted = {}
    for table in ('module_groups', 'modules', 'environments', 'cases', 'features', 'suites', 'schedules', 'taps'):
        pending = [item for item in list_items(table) if not item.get('project_id')]
        for item in pending:
            item['project_id'] = project_id
            save(table, item)
        adopted[table] = len(pending)
    return adopted


# --------------------------------------------------------------------------- módulos (dominio/propiedad: agrupan componentes)

def _module_group_name_taken(name, project_id, exclude_id=None):
    return any(g['id'] != exclude_id and g.get('project_id') == project_id and g['name'].strip().lower() == name.lower()
               for g in list_items('module_groups'))


def create_module_group(name, project_id, description=''):
    name = (name or '').strip()
    if not name:
        raise ValueError('El nombre del módulo es obligatorio')
    if _module_group_name_taken(name, project_id):
        raise ValueError(f'Ya existe un módulo llamado «{name}» en este proyecto')
    item = {'name': name, 'description': (description or '').strip()}
    if project_id is not None:
        item['project_id'] = project_id
    return save('module_groups', item)


def update_module_group(group_id, name, description=''):
    group = get('module_groups', group_id)
    if group is None:
        raise ValueError('Módulo inexistente')
    name = (name or '').strip()
    if not name:
        raise ValueError('El nombre del módulo es obligatorio')
    if _module_group_name_taken(name, group.get('project_id'), exclude_id=group_id):
        raise ValueError(f'Ya existe un módulo llamado «{name}» en este proyecto')
    group.update({'name': name, 'description': (description or '').strip()})
    return save('module_groups', group)


def delete_module_group(group_id):
    if get('module_groups', group_id) is None:
        raise ValueError('Módulo inexistente')
    linked = [m for m in list_items('modules') if group_id in component_module_group_ids(m)]
    if linked:
        raise ValueError(f'No se puede eliminar: tiene {len(linked)} componente(s) ligado(s). Desvincúlalos primero.')
    delete('module_groups', group_id)


COMPONENT_STATUSES = ('development', 'qa', 'ready', 'production')
COMPONENT_STATUS_LABELS = {'development': 'Desarrollo', 'qa': 'En pruebas (QA)', 'ready': 'Listo para producción', 'production': 'En producción'}


def set_component_classification(component_id, module_group_ids=None, status=None):
    """Liga un componente (manual o importado) a uno o varios Módulos y/o fija su Estado de ciclo de vida.
    Un componente puede pertenecer a más de un Módulo a la vez (p. ej. un backend compartido entre dos
    dominios). A diferencia de update_component(), funciona sobre cualquier componente: esto es metadata de
    clasificación, no datos que el contrato declare."""
    component = get('modules', component_id)
    if component is None:
        raise ValueError('Componente inexistente')
    ids = list(dict.fromkeys(module_group_ids or []))
    for group_id in ids:
        group = get('module_groups', group_id)
        if group is None:
            raise ValueError('Módulo inexistente')
        if component.get('project_id') is not None and group.get('project_id') != component.get('project_id'):
            raise ValueError('El módulo no pertenece al proyecto activo')
    if status is not None and status not in COMPONENT_STATUSES:
        raise ValueError('Estado de componente inválido')
    component['module_group_ids'] = ids
    if status is not None:
        component['status'] = status
    return save('modules', component)


# --------------------------------------------------------------------------- funcionalidades (capacidad de negocio: agrupan suites/flujos)

def _feature_name_taken(name, project_id, exclude_id=None):
    return any(f['id'] != exclude_id and f.get('project_id') == project_id and f['name'].strip().lower() == name.lower()
               for f in list_items('features'))


def create_feature(name, project_id, description='', external_ref=''):
    name = (name or '').strip()
    if not name:
        raise ValueError('El nombre de la funcionalidad es obligatorio')
    if _feature_name_taken(name, project_id):
        raise ValueError(f'Ya existe una funcionalidad llamada «{name}» en este proyecto')
    item = {'name': name, 'description': (description or '').strip(), 'external_ref': (external_ref or '').strip()}
    if project_id is not None:
        item['project_id'] = project_id
    return save('features', item)


def update_feature(feature_id, name, description='', external_ref=''):
    feature = get('features', feature_id)
    if feature is None:
        raise ValueError('Funcionalidad inexistente')
    name = (name or '').strip()
    if not name:
        raise ValueError('El nombre de la funcionalidad es obligatorio')
    if _feature_name_taken(name, feature.get('project_id'), exclude_id=feature_id):
        raise ValueError(f'Ya existe una funcionalidad llamada «{name}» en este proyecto')
    feature.update({'name': name, 'description': (description or '').strip(), 'external_ref': (external_ref or '').strip()})
    return save('features', feature)


def delete_feature(feature_id):
    if get('features', feature_id) is None:
        raise ValueError('Funcionalidad inexistente')
    linked = [s for s in list_items('suites') if s.get('feature_id') == feature_id]
    if linked:
        raise ValueError(f'No se puede eliminar: tiene {len(linked)} suite(s) ligada(s). Desvincúlalas primero.')
    delete('features', feature_id)


def last_run_for_suite(suite_id):
    """El último run decisivo (no cancelado/omitido) de una suite, o None si nunca se ejecutó."""
    runs = [r for r in list_items('runs') if r.get('type') == 'suite' and r.get('suite_id') == suite_id and r.get('status') in ('passed', 'failed', 'error')]
    return max(runs, key=lambda r: r.get('started_at', '')) if runs else None


def feature_health(feature_id):
    """Para la trazabilidad de negocio: de las suites ligadas a la funcionalidad, cuántas pasan en su última corrida."""
    suites = [s for s in list_items('suites') if s.get('feature_id') == feature_id]
    rows = [{'suite': s, 'last_run': last_run_for_suite(s['id'])} for s in suites]
    passing = sum(1 for r in rows if r['last_run'] and r['last_run']['status'] == 'passed')
    return {'rows': rows, 'passing': passing, 'total': len(rows)}


def suite_steps(suite):
    """The suite's ordered steps. Suites saved without explicit steps get one default step per case."""
    if suite.get('steps'):
        return copy.deepcopy(suite['steps'])
    taken, steps = [], []
    for case_id in suite.get('case_ids', []):
        alias = slugify_alias((get('cases', case_id) or {}).get('name') or 'paso', taken)
        taken.append(alias)
        steps.append({'case_id': case_id, 'alias': alias, 'environment_id': None, 'enrich': []})
    return steps


def save_suite(name, environment_id, case_ids, project_id=None, **options):
    """Creates/updates a suite after checking that environment and cases share its project.

    options: id, on_failure ('continue'|'stop'), retries, retry_delay_s, variables, feature_id (qué capacidad de
             negocio valida este flujo; opcional),
             steps (list of {case_id, alias, environment_id, enrich}: a flow across modules; replaces case_ids),
             expected_updated_at (refuse the write if someone else saved the suite meanwhile).
    """
    steps = options.get('steps')
    if steps is not None:
        case_ids = [step.get('case_id') for step in steps]
    if not (name or '').strip():
        raise ValueError('El nombre de la suite es obligatorio')
    environment = get('environments', environment_id)
    if environment is None:
        raise ValueError('Ambiente inexistente')
    if not case_ids:
        raise ValueError('Selecciona al menos un caso')
    if project_id is not None and environment.get('project_id') != project_id:
        raise ValueError('El ambiente no pertenece al proyecto activo')
    for case_id in case_ids:
        case = get('cases', case_id)
        if case is None:
            raise ValueError('Caso inexistente')
        if project_id is not None and case.get('project_id') != project_id:
            raise ValueError('Un caso no pertenece al proyecto activo')
    on_failure = options.get('on_failure', 'continue')
    if on_failure not in ('continue', 'stop'):
        raise ValueError('Política de fallo inválida')
    retries = int(options.get('retries', 0))
    if not 0 <= retries <= 5:
        raise ValueError('Los reintentos deben estar entre 0 y 5')
    delay = float(options.get('retry_delay_s', 0))
    if not 0 <= delay <= 300:
        raise ValueError('La espera entre reintentos debe estar entre 0 y 300 s')
    variables = options.get('variables') or {}
    if not isinstance(variables, dict):
        raise ValueError('Las variables de suite deben ser un objeto')
    feature_id = options.get('feature_id') or None
    if feature_id:
        feature = get('features', feature_id)
        if feature is None:
            raise ValueError('Funcionalidad inexistente')
        if project_id is not None and feature.get('project_id') != project_id:
            raise ValueError('La funcionalidad no pertenece al proyecto activo')
    item = {'name': name.strip(), 'environment_id': environment_id, 'case_ids': list(case_ids),
            'on_failure': on_failure, 'retries': retries, 'retry_delay_s': delay, 'variables': variables, 'feature_id': feature_id}
    if steps is not None:
        item['steps'] = _validated_steps(steps, environment, project_id)
    if options.get('id'):
        item['id'] = options['id']
    if project_id is not None:
        item['project_id'] = project_id
    if 'expected_updated_at' in options:
        return save('suites', item, expected_updated_at=options['expected_updated_at'])
    return save('suites', item)


def _validated_steps(steps, default_environment, project_id):
    clean, taken = [], []
    for index, step in enumerate(steps, 1):
        alias = (step.get('alias') or '').strip() or slugify_alias((get('cases', step['case_id']) or {}).get('name') or 'paso', taken)
        if not ALIAS_RE.fullmatch(alias):
            raise ValueError(f'Paso {index}: el nombre «{alias}» no es válido (letras, números, _ y -; máx. 41)')
        if alias in taken:
            raise ValueError(f'Paso {index}: el nombre «{alias}» está repetido en la suite')
        env_id = step.get('environment_id') or None
        if env_id:
            env = get('environments', env_id)
            if env is None:
                raise ValueError(f'Paso {index}: ambiente inexistente')
            if project_id is not None and env.get('project_id') != project_id:
                raise ValueError(f'Paso {index}: el ambiente no pertenece al proyecto de la suite')
        problems = validate_enrichment(step.get('enrich') or [], taken)
        if problems:
            raise ValueError(f'Paso {index} («{alias}»): ' + '; '.join(problems))
        taken.append(alias)
        clean.append({'case_id': step['case_id'], 'alias': alias, 'environment_id': env_id, 'enrich': copy.deepcopy(step.get('enrich') or [])})
    return clean


# --------------------------------------------------------------------------- OpenAPI

MAX_SPEC_BYTES = 10_000_000
MAX_REF_DEPTH = 200  # a non-cyclic $ref chain deeper than this would otherwise risk Python's own RecursionError


def parse_openapi(raw):
    if isinstance(raw, str) and len(raw.encode('utf-8', errors='ignore')) > MAX_SPEC_BYTES:
        raise ValueError(f'El contrato supera el límite de {MAX_SPEC_BYTES // 1_000_000} MB.')
    data = yaml.safe_load(raw)
    if not isinstance(data, dict) or not (data.get('openapi') or data.get('swagger')) or not isinstance(data.get('paths'), dict):
        raise ValueError('Se requiere un documento OpenAPI/Swagger válido con paths.')

    def resolve(value, stack=()):
        if len(stack) > MAX_REF_DEPTH:
            raise ValueError(f'La cadena de referencias $ref es demasiado profunda (más de {MAX_REF_DEPTH} niveles).')
        if isinstance(value, dict) and '$ref' in value:
            reference = value['$ref']
            if not isinstance(reference, str) or not reference.startswith('#/'):
                raise ValueError('Solo se permiten referencias $ref locales.')
            if reference in stack:                                                  # recursive models (trees, comments with replies…) are normal: cut the loop here
                return {'description': f'Estructura recursiva ({reference.rsplit("/", 1)[-1]}): se detiene aquí', 'x-ltw-recursive': reference}
            target = data
            try:
                for part in reference[2:].split('/'):
                    target = target[part.replace('~1', '/').replace('~0', '~')]
            except (KeyError, IndexError, TypeError):
                raise ValueError(f'Referencia $ref inexistente: {reference}')
            resolved = resolve(copy.deepcopy(target), stack + (reference,))
            extras = {key: resolve(item, stack) for key, item in value.items() if key != '$ref'}
            if isinstance(resolved, dict):
                resolved.update(extras)
            return resolved
        if isinstance(value, dict):
            return {key: resolve(item, stack) for key, item in value.items()}
        if isinstance(value, list):
            return [resolve(item, stack) for item in value]
        return value

    data = resolve(data)
    operations = []
    for path, methods in data['paths'].items():
        if not isinstance(methods, dict):
            continue
        for method, spec in methods.items():
            if method.lower() not in ('get', 'post', 'put', 'patch', 'delete', 'head', 'options') or not isinstance(spec, dict):
                continue
            operations.append({'method': method.upper(), 'path': path, 'summary': spec.get('summary', ''), 'parameters': spec.get('parameters', []),
                               'requestBody': spec.get('requestBody', {}), 'responses': spec.get('responses', {}), 'tags': spec.get('tags') or []})
    servers = data.get('servers') or []
    if not servers and data.get('host'):                                              # Swagger 2.0 declares host + basePath + schemes instead of servers
        schemes = data.get('schemes') or ['https']
        servers = [{'url': f'{"https" if "https" in schemes else schemes[0]}://{data["host"]}{data.get("basePath", "")}'.rstrip('/')}]
    return {'name': data.get('info', {}).get('title', 'API importada'), 'version': str(data.get('info', {}).get('version', '')), 'operations': operations, 'servers': servers, 'source_spec': data}


def import_openapi(raw, project_id=None, source_url=None):
    module = parse_openapi(raw)
    module['id'] = uid()
    module['is_backend'] = True    # an OpenAPI/Swagger contract always describes a backend
    module['is_frontend'] = False
    module['manual'] = False
    if source_url:
        module['source_url'] = source_url
    if project_id is not None:
        module['project_id'] = project_id
    return save('modules', module)


def component_flags(component):
    """(is_backend, is_frontend): a component can be both at once — a full-stack monolith (Next.js with API
    routes, Django/Rails serving HTML and API from one process) is ONE deployable unit that does both, not
    two. Tolerant of records saved before this existed, which only had an exclusive `type` ('backend'|'frontend')."""
    if 'is_backend' in component or 'is_frontend' in component:
        return bool(component.get('is_backend')), bool(component.get('is_frontend'))
    legacy = component.get('type', 'backend')
    return legacy != 'frontend', legacy == 'frontend'


def component_kind_label(component):
    backend, frontend = component_flags(component)
    if backend and frontend:
        return 'Backend + Frontend'
    return 'Frontend' if frontend else 'Backend'


def component_module_group_ids(component):
    """Los Módulos de un componente. Tolerante de registros guardados antes de que un componente pudiera
    pertenecer a más de uno a la vez (que solo tenían `module_group_id`, singular)."""
    if 'module_group_ids' in component:
        return list(component['module_group_ids'] or [])
    legacy = component.get('module_group_id')
    return [legacy] if legacy else []


def environment_flags(env):
    """(is_backend, is_frontend): what this environment is meant to be used for. Unset (any environment saved
    before this existed) defaults to both — unrestricted, exactly the old behavior — so nothing that already
    worked silently stops being offered; narrowing it (e.g. a pure frontend dev server like :4200 that has no
    API of its own) is an explicit, opt-in choice."""
    return bool(env.get('is_backend', True)), bool(env.get('is_frontend', True))


def environment_kind_label(env):
    backend, frontend = environment_flags(env)
    if backend and frontend:
        return 'Backend + Frontend'
    if frontend:
        return 'Frontend'
    return 'Backend' if backend else 'Sin uso declarado'


def create_component(name, project_id, is_backend=True, is_frontend=False, environment_ids=None, module_group_ids=None):
    """A component with no OpenAPI contract: just an inventory entry (name, what it exposes, optionally linked
    to one or more environments and Módulos) for a piece of the solution with nothing to import — typically a
    frontend, a backend you haven't documented yet, or a full-stack component that is both at once. No
    operations catalog: exploración automática and per-operation case creation don't apply (there is nothing
    to read). Use import_openapi() instead when there is a contract."""
    name = (name or '').strip()
    if not name:
        raise ValueError('El nombre es obligatorio')
    if not is_backend and not is_frontend:
        raise ValueError('El componente debe exponer backend, frontend, o ambos')
    env_ids = _validated_environment_ids(environment_ids, project_id)
    group_ids = list(dict.fromkeys(module_group_ids or []))
    for group_id in group_ids:
        group = get('module_groups', group_id)
        if group is None:
            raise ValueError('Módulo inexistente')
        if project_id is not None and group.get('project_id') != project_id:
            raise ValueError('El módulo no pertenece al proyecto activo')
    item = {'name': name, 'is_backend': bool(is_backend), 'is_frontend': bool(is_frontend), 'operations': [], 'servers': [], 'version': '',
            'manual': True, 'environment_ids': env_ids, 'module_group_ids': group_ids, 'status': 'development'}
    if project_id is not None:
        item['project_id'] = project_id
    return save('modules', item)


def _validated_environment_ids(environment_ids, project_id):
    ids = list(dict.fromkeys(environment_ids or []))   # de-dup, keep order
    for env_id in ids:
        env = get('environments', env_id)
        if env is None:
            raise ValueError('Ambiente inexistente')
        if project_id is not None and env.get('project_id') != project_id:
            raise ValueError('Un ambiente no pertenece al proyecto activo')
    return ids


def update_component(component_id, name, is_backend, is_frontend, environment_ids=None):
    """Renames a component and/or changes what it exposes, for any component (manual or imported): the display
    name and the backend/frontend classification are the user's own judgment, not something the contract
    dictates. Never touches operations/version/servers/source_url — those stay exactly as the contract (or a
    later re-import) declares them; re-importing the same source always creates a separate record, so renaming
    here is never silently overwritten."""
    component = get('modules', component_id)
    if component is None:
        raise ValueError('Componente inexistente')
    name = (name or '').strip()
    if not name:
        raise ValueError('El nombre es obligatorio')
    if not is_backend and not is_frontend:
        raise ValueError('El componente debe exponer backend, frontend, o ambos')
    env_ids = _validated_environment_ids(environment_ids, component.get('project_id'))
    component.update({'name': name, 'is_backend': bool(is_backend), 'is_frontend': bool(is_frontend), 'environment_ids': env_ids})
    component.pop('type', None)
    return save('modules', component)


def move_component_to_project(component_id, project_id):
    """Moves a component to a different project — the fix for 'se creó bajo el proyecto activo equivocado',
    ya que hoy no hay selector de proyecto por formulario (el activo del encabezado decide siempre). Bloqueado
    si el componente ya tiene Casos: moverlos también es una operación mayor, fuera del alcance de deshacer un
    clic equivocado — hay que moverlos o borrarlos primero. Los Ambientes y Módulos ligados pertenecen al
    proyecto anterior y no tendrían sentido en el nuevo, así que se desligan (nunca se transfieren)."""
    component = get('modules', component_id)
    if component is None:
        raise ValueError('Componente inexistente')
    project = get('projects', project_id)
    if project is None:
        raise ValueError('Proyecto inexistente')
    if component.get('project_id') == project_id:
        raise ValueError('El componente ya pertenece a ese proyecto')
    used = [c for c in list_items('cases') if c.get('module_id') == component_id]
    if used:
        raise ValueError(f'No se puede mover: {len(used)} caso(s) lo usan. Muévelos o bórralos primero.')
    cleared = {'environments': len(component.get('environment_ids') or []), 'modules': len(component.get('module_group_ids') or [])}
    component['project_id'] = project_id
    component['environment_ids'] = []
    component['module_group_ids'] = []
    return save('modules', component), cleared


def set_component_environments(component_id, environment_ids):
    """Links any component (manual or imported) to the set of environments where it is known to run —
    typically one per stage of the pipeline (dev/QA/staging/producción), since it's the same deployable
    promoted across all of them, not a single fixed place."""
    component = get('modules', component_id)
    if component is None:
        raise ValueError('Componente inexistente')
    component['environment_ids'] = _validated_environment_ids(environment_ids, component.get('project_id'))
    return save('modules', component)


def link_component_environment(component_id, environment_id):
    """Adds one environment to a component's known environments, idempotently (used right after a contract
    import registers/reuses an environment, so the link survives instead of relying only on URL matching)."""
    component = get('modules', component_id)
    if component is None:
        raise ValueError('Componente inexistente')
    ids = list(component.get('environment_ids') or [])
    if environment_id not in ids:
        ids.append(environment_id)
        component['environment_ids'] = ids
        save('modules', component)
    return component


def component_tags(component):
    """Las etiquetas (`tags`) que el propio contrato OpenAPI declara en sus operaciones — la misma
    clasificación que agrupa los endpoints en Swagger UI — para filtrar un catálogo grande sin inventar
    una jerarquía nueva encima."""
    seen = []
    for op in component.get('operations') or []:
        for tag in op.get('tags') or []:
            if tag not in seen:
                seen.append(tag)
    return sorted(seen)


def component_environments(component):
    """Every environment this component is known to run in: explicitly linked ones (any component can have
    several — the same deployable promoted through dev/QA/staging/producción), plus, for components saved
    before explicit linking existed, any environment whose base_url still matches the contract's declared
    server (so they keep resolving without needing to be re-linked by hand)."""
    ids = list(component.get('environment_ids') or ([component['environment_id']] if component.get('environment_id') else []))
    envs = [e for e in (get('environments', i) for i in ids) if e]
    base = module_base_url(component)
    if base and component.get('project_id') is not None:
        for env in list_project_items('environments', component['project_id']):
            if env['id'] not in ids and env.get('base_url', '').rstrip('/') == base.rstrip('/'):
                envs.append(env)
    return envs


def component_environment(component):
    """The single 'default' environment of a component (first of component_environments()), for call sites
    that only need one — e.g. preselecting exploración automática. None if it has none linked/resolvable."""
    envs = component_environments(component)
    return envs[0] if envs else None


def component_features(component_id):
    """Funcionalidades que dependen de este componente: cualquier Suite con un paso contra un Caso de este
    componente, a través de su Funcionalidad (si la tiene) — la traza inversa de Funcionalidad → Suite."""
    cases_here = {c['id'] for c in list_items('cases') if c.get('module_id') == component_id}
    if not cases_here:
        return []
    feature_ids = []
    for suite in list_items('suites'):
        if not suite.get('feature_id') or suite['feature_id'] in feature_ids:
            continue
        if any(step.get('case_id') in cases_here for step in suite_steps(suite)):
            feature_ids.append(suite['feature_id'])
    return [f for f in (get('features', fid) for fid in feature_ids) if f]


SPEC_GUESSES = ('openapi.json', 'openapi.yaml', 'swagger.json', 'swagger.yaml', 'v3/api-docs', 'v2/api-docs', 'api-docs', 'swagger/v1/swagger.json',
                'docs/openapi.json', 'api/openapi.json', 'api/swagger.json')
SWAGGER_DEMO_SPEC = 'petstore.swagger.io/v2/swagger.json'                            # the default baked into an unconfigured Swagger UI distribution
MAX_SPEC_FETCHES = 14


def normalize_spec_url(url):
    """GitHub page links (…/blob/branch/file) become raw links; anything else is returned as typed."""
    url = (url or '').strip()
    match = re.match(r'^https?://github\.com/([^/]+)/([^/]+)/blob/(.+)$', url)
    if match:
        return f'https://raw.githubusercontent.com/{match.group(1)}/{match.group(2)}/{match.group(3)}'
    return url


def looks_like_openapi(text):
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return False
    return isinstance(data, dict) and bool(data.get('openapi') or data.get('swagger')) and isinstance(data.get('paths'), dict)


def spec_links_in_page(text, page_url):
    """Where a Swagger UI / Redoc / docs page says its contract lives (initializer scripts, `url:` settings, `spec-url`, links to .json/.yaml)."""
    found = []
    patterns = (r'["\']?url["\']?\s*:\s*["\']([^"\']+)["\']', r'spec-url\s*=\s*["\']([^"\']+)["\']', r'data-url\s*=\s*["\']([^"\']+)["\']',
                r'href\s*=\s*["\']([^"\']*(?:openapi|swagger|api-docs)[^"\']*)["\']', r'["\']([^"\'\s]+\.(?:json|ya?ml))["\']',
                r'(https?://[^\s"\'`,<>]+\.(?:json|ya?ml))')   # last two: scripts that name the file in a variable or in a host → URL map
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.I):
            candidate = urljoin(page_url, match.group(1).strip())
            if candidate.startswith(('http://', 'https://')) and candidate not in found and not re.search(r'\.(css|js|png|ico|html)(\?|$)', candidate):
                found.append(candidate)
    scripts = [urljoin(page_url, m.group(1)) for m in re.finditer(r'<script[^>]+src\s*=\s*["\']([^"\']*(?:initializer|swagger-config|config)[^"\']*)["\']', text, flags=re.I)]
    return found, scripts


def _rank_links(links, page_url):
    """Links on the page's own host first; the Swagger UI demo contract only as a last resort."""
    host = urlparse(page_url).netloc
    return sorted(links, key=lambda u: (urlparse(u).netloc != host, SWAGGER_DEMO_SPEC in u))


def fetch_openapi(url, client=None):
    """Downloads a contract from a direct link, a GitHub page, or a Swagger UI/Redoc/docs page (the contract is looked up from it).
    Returns {'raw', 'source_url', 'tried'}; raises ValueError listing what was tried."""
    start = normalize_spec_url(url)
    parsed = urlparse(start)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('URL inválida: debe empezar por http:// o https://')
    own = client is None
    client = client or httpx.Client(timeout=20, follow_redirects=True, trust_env=False, headers={'User-Agent': 'local-test-workspace', 'Accept': 'application/json, application/yaml, text/html;q=0.8, */*;q=0.5'})
    tried = []

    def get(target):
        if len(tried) >= MAX_SPEC_FETCHES:
            return None
        tried.append(target)
        try:
            with client.stream('GET', target) as response:
                if response.status_code >= 400:
                    return None
                body = b''
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > MAX_SPEC_BYTES:
                        raise ValueError('El contrato supera 10 MB')
                return body.decode('utf-8', 'replace')
        except httpx.HTTPError:
            return None
    try:
        first = get(start)
        if first is not None and looks_like_openapi(first):
            return {'raw': first, 'source_url': start, 'tried': tried}
        links, scripts = spec_links_in_page(first or '', start)                       # a 404 on the typed address (e.g. an API root) still allows the well-known paths
        for script in scripts[:3]:
            body = get(script)
            if body:
                more, _ = spec_links_in_page(body, script)
                links += [m for m in more if m not in links]
        links = _rank_links(links, start)
        origin = f'{parsed.scheme}://{parsed.netloc}'
        base = start.rstrip('/') + '/'
        guesses = [urljoin(origin + '/', g) for g in SPEC_GUESSES] + [urljoin(base, g) for g in SPEC_GUESSES[:4]]
        for candidate in links + [g for g in guesses if g not in links]:
            body = get(candidate)
            if body and looks_like_openapi(body):
                return {'raw': body, 'source_url': candidate, 'tried': tried}
        if first is None:
            raise ValueError(f'No se encontró un contrato en {start}: la dirección no responde con contenido y tampoco las rutas habituales ({len(tried)} probadas). '
                             '¿Está el servicio levantado? Si conoces la URL exacta del contrato, pégala.')
        raise ValueError(f'La dirección no es un contrato OpenAPI/Swagger y no encontré uno enlazado desde la página. Probé {len(tried)} dirección(es); '
                         'pega la URL directa del archivo (.json/.yaml) o súbelo.')
    finally:
        if own:
            client.close()


def import_openapi_url(url, project_id=None, client=None):
    fetched = fetch_openapi(url, client)
    return import_openapi(fetched['raw'], project_id, source_url=fetched['source_url'])


def contract_tags(raw):
    """Las etiquetas distintas que un contrato declara en sus operaciones, para poder elegir cuáles importar
    antes de guardar nada (p. ej. un contrato con 500 operaciones del que solo interesan 10)."""
    parsed = parse_openapi(raw)
    seen = []
    for op in parsed['operations']:
        for tag in op.get('tags') or []:
            if tag not in seen:
                seen.append(tag)
    return sorted(seen)


def attach_contract(component_id, raw, source_url=None, tags=None):
    """Enriches an EXISTING component with a contract's operations/version/servers, instead of creating a new
    record: the component is registered first (name, lo que expone, ambientes) and the contract is an optional,
    later step — only meaningful for a component that exposes backend. Never touches name, classification,
    module or environment links: those are the user's own, set at registration time. With `tags`, only keeps
    the operations that declare at least one of those tags — e.g. importing 10 of a contract's 500 operations
    instead of all of it; the rest of the contract (version, servers) is still read normally."""
    component = get('modules', component_id)
    if component is None:
        raise ValueError('Componente inexistente')
    if not component_flags(component)[0]:
        raise ValueError('Este componente no expone backend; actívalo en Identidad antes de importar un contrato.')
    parsed = parse_openapi(raw)
    operations = parsed['operations']
    wanted = set(tags or [])
    if wanted:
        operations = [op for op in operations if wanted & set(op.get('tags') or [])]
        if not operations:
            raise ValueError('Ninguna operación del contrato tiene esas etiquetas.')
    component.update({'operations': operations, 'version': parsed['version'], 'servers': parsed['servers'],
                      'source_spec': parsed['source_spec'], 'manual': False})
    if source_url:
        component['source_url'] = source_url
    return save('modules', component)


def attach_contract_from_url(component_id, url, client=None, tags=None):
    fetched = fetch_openapi(url, client)
    return attach_contract(component_id, fetched['raw'], source_url=fetched['source_url'], tags=tags)


HTTP_METHODS = ('GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS')


def add_manual_operation(component_id, method, path, summary=''):
    """Cataloga un endpoint a mano en un componente backend, sin contrato: antes de escribir un Caso (con sus
    aserciones), a veces solo hace falta dejar constancia de que el endpoint existe y cómo se llama. Se agrega
    a la misma lista `operations` que usa un contrato importado, así que la tabla de operaciones y «Crear
    caso» funcionan igual para ambos — lo único que falta son los detalles que solo un contrato declara
    (parámetros, schema de respuesta)."""
    component = get('modules', component_id)
    if component is None:
        raise ValueError('Componente inexistente')
    if not component_flags(component)[0]:
        raise ValueError('Este componente no expone backend.')
    method = (method or '').strip().upper()
    if method not in HTTP_METHODS:
        raise ValueError('Método HTTP inválido')
    path = (path or '').strip()
    if not path:
        raise ValueError('La ruta es obligatoria')
    operations = list(component.get('operations') or [])
    operations.append({'method': method, 'path': path, 'summary': (summary or '').strip(), 'parameters': [], 'requestBody': {},
                       'responses': {}, 'tags': [], 'manual': True})
    component['operations'] = operations
    return save('modules', component)


def update_operation(component_id, index, method, path, summary=''):
    """Edita cualquier operación del catálogo, venga del contrato o agregada a mano. Si viene del contrato, el
    cambio no persiste al reimportar: `attach_contract` reemplaza todo el catálogo por lo que el contrato diga
    en ese momento, para que el catálogo siga reflejando fielmente al contrato."""
    component = get('modules', component_id)
    if component is None:
        raise ValueError('Componente inexistente')
    operations = list(component.get('operations') or [])
    if not (0 <= index < len(operations)):
        raise ValueError('Operación inexistente')
    method = (method or '').strip().upper()
    if method not in HTTP_METHODS:
        raise ValueError('Método HTTP inválido')
    path = (path or '').strip()
    if not path:
        raise ValueError('La ruta es obligatoria')
    operations[index] = {**operations[index], 'method': method, 'path': path, 'summary': (summary or '').strip()}
    component['operations'] = operations
    return save('modules', component)


def remove_operation(component_id, index):
    """Quita cualquier operación del catálogo, venga del contrato o agregada a mano. Si viene del contrato,
    reaparece al reimportarlo (ver `update_operation`): para excluirla de forma permanente, importa solo las
    etiquetas que sí quieras."""
    return remove_operations(component_id, [index])


def remove_operations(component_id, indices):
    """Igual que `remove_operation`, pero quita varias de una sola vez (p. ej. limpiar de golpe lo que dejó una
    exploración o un contrato con ruido) — un único guardado en vez de uno por fila."""
    component = get('modules', component_id)
    if component is None:
        raise ValueError('Componente inexistente')
    operations = list(component.get('operations') or [])
    wanted = set(indices)
    if not wanted or any(not (0 <= i < len(operations)) for i in wanted):
        raise ValueError('Operación inexistente')
    component['operations'] = [op for i, op in enumerate(operations) if i not in wanted]
    return save('modules', component)


def add_component_view(component_id, name, path=''):
    """Cataloga una vista/pantalla a mano en un componente frontend — el equivalente a un endpoint, del lado
    de la UI: antes de grabar un Caso UI completo, deja constancia de que esa pantalla existe y dónde vive."""
    component = get('modules', component_id)
    if component is None:
        raise ValueError('Componente inexistente')
    if not component_flags(component)[1]:
        raise ValueError('Este componente no expone frontend.')
    name = (name or '').strip()
    if not name:
        raise ValueError('El nombre es obligatorio')
    views = list(component.get('views') or [])
    views.append({'name': name, 'path': (path or '').strip()})
    component['views'] = views
    return save('modules', component)


def remove_component_view(component_id, index):
    component = get('modules', component_id)
    if component is None:
        raise ValueError('Componente inexistente')
    views = list(component.get('views') or [])
    if not (0 <= index < len(views)):
        raise ValueError('Vista inexistente')
    views.pop(index)
    component['views'] = views
    return save('modules', component)


# --------------------------------------------------------------------------- token refresh

def token_needs_refresh(environment):
    """True if the environment has a refresh configured and either has no token yet or it is at/past
    its known expiry (30s safety margin). With no known expiry, a token already present is trusted
    as-is (refreshing it is then only reactive, on a 401)."""
    auth = environment.get('auth') or {}
    refresh = auth.get('refresh')
    if not refresh or not refresh.get('enabled', True):
        return False
    secret_name = auth.get('secret') or auth.get('env_var', '')
    if not (secret_name and secret_get(secret_name)):
        return True
    expires_at = auth.get('token_expires_at')
    if not expires_at:
        return False
    try:
        return dt.datetime.now(dt.timezone.utc) >= dt.datetime.fromisoformat(expires_at) - dt.timedelta(seconds=30)
    except ValueError:
        return False


def refresh_token(environment, variables=None):
    """Runs an environment's configured token refresh (an HTTP request or a local command) and writes
    the result into the secret it targets. Remembers when the new token expires if the refresh declares
    it (`expires_path`), so future calls know whether to refresh proactively. Raises ValueError with a
    clear reason on any failure; never writes a partial or empty token."""
    auth = environment.get('auth') or {}
    cfg = auth.get('refresh')
    if not cfg:
        raise ValueError('Este ambiente no tiene configurada una actualización automática de token.')
    target = (cfg.get('target_secret') or '').strip() or auth.get('secret') or auth.get('env_var')
    if not target:
        raise ValueError('No hay un secreto de destino para guardar el token actualizado.')
    variables = {**environment.get('variables', {}), **(variables or {})}
    secrets_used = set()
    expires_in = None
    mode = cfg.get('mode', 'http')
    if mode == 'command':
        command = (cfg.get('command') or '').strip()
        if not command:
            raise ValueError('Falta el comando para actualizar el token.')
        import subprocess
        try:
            result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=cfg.get('timeout', 30))
        except subprocess.TimeoutExpired:
            raise ValueError('El comando de actualización de token tardó demasiado (se agotó el tiempo).')
        if result.returncode != 0:
            raise ValueError(f'El comando de actualización terminó con error ({result.returncode}): {(result.stderr or result.stdout or "").strip()[:300]}')
        token = result.stdout.strip()
    else:
        url = substitute(cfg.get('url', ''), variables, secrets_used)
        headers = substitute(cfg.get('headers') or {}, variables, secrets_used)
        body = substitute(cfg.get('body'), variables, secrets_used)
        missing = find_unresolved(url, headers, body)
        if missing:
            raise ValueError('Variables sin resolver en la actualización de token: ' + ', '.join(missing))
        validate_base_url(url)
        try:
            with httpx.Client(timeout=cfg.get('timeout', 20), trust_env=False) as client:
                response = client.request(cfg.get('method', 'POST'), url, headers=headers, json=body if body is not None else None)
        except httpx.HTTPError as exc:
            raise ValueError(f'No se pudo contactar el endpoint de actualización de token: {exc}')
        if response.status_code >= 400:
            raise ValueError(f'La actualización de token respondió {response.status_code}: {response.text[:300]}')
        try:
            payload = response.json()
        except ValueError:
            raise ValueError('La respuesta de actualización de token no es JSON.')
        try:
            token = extract_path(payload, cfg.get('token_path', '$.access_token'))
        except Exception:
            raise ValueError(f'No se pudo extraer el token con la ruta «{cfg.get("token_path", "$.access_token")}».')
        if cfg.get('expires_path'):
            try:
                expires_in = float(extract_path(payload, cfg['expires_path']))
            except Exception:
                expires_in = None
    if not isinstance(token, str) or not token.strip():
        raise ValueError('La actualización de token no devolvió un texto válido.')
    token = token.strip()
    secret_set(target, token)
    saved = copy.deepcopy(environment)
    saved.setdefault('auth', {})['token_refreshed_at'] = now()
    if expires_in is not None:
        saved['auth']['token_expires_at'] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=expires_in)).isoformat()
    else:
        saved['auth'].pop('token_expires_at', None)
    save('environments', saved)
    return token


def module_base_url(module):
    """Absolute base URL a module declares (relative servers are resolved against where the contract came from); None if it cannot be known."""
    for server in module.get('servers') or []:
        target = (server or {}).get('url', '')
        if '{' in target:
            continue
        if target.startswith(('http://', 'https://')):
            return target.rstrip('/')
        if module.get('source_url') and target:
            return urljoin(module['source_url'], target).rstrip('/')
    if not module.get('servers') and module.get('source_url'):                       # e.g. FastAPI declares none: the service lives where its contract was served
        parts = urlparse(module['source_url'])
        return f'{parts.scheme}://{parts.netloc}'
    return None


def ensure_environment_for_module(project_id, module):
    """Finds (by exact base_url match) or creates the project's environment for a module's declared server.
    Unlike ensure_environment_for_url, keeps any path prefix the server declares (e.g. /v1): a whole
    contract commonly lives under one. Returns (environment, created); (None, False) if the module doesn't
    resolve to an absolute base URL (relative server with no source_url, or unresolved {variables})."""
    base = module_base_url(module)
    if not base:
        return None, False
    normalized = base.rstrip('/')
    for env in list_project_items('environments', project_id):
        if env.get('base_url', '').rstrip('/') == normalized:
            return env, False
    env = save('environments', {'name': module['name'][:60], 'project_id': project_id, 'base_url': normalized,
                                'auth': {'type': 'none', 'secret': '', 'env_var': '', 'header': 'X-API-Key'}, 'variables': {},
                                'is_backend': True, 'is_frontend': False})   # always comes from an OpenAPI contract: unambiguously a backend
    return env, True


def operation_response_schema(operation, status='200'):
    """JSON Schema declared by the contract for a response, if any (OpenAPI 3 / Swagger 2)."""
    response = (operation.get('responses') or {}).get(str(status)) or {}
    for media in (response.get('content') or {}).values():
        if isinstance(media, dict) and isinstance(media.get('schema'), dict):
            return media['schema']
    return response.get('schema') if isinstance(response.get('schema'), dict) else None


# --------------------------------------------------------------------------- secrets

def _keyring():
    import keyring
    return keyring


def secret_names():
    return sorted(get_setting('secret_names', []) or [])


def secret_set(name, value):
    if not re.fullmatch(r'[\w.-]{1,64}', name or ''):
        raise ValueError('Nombre de secreto inválido (letras, números, . _ -)')
    if not value:
        raise ValueError('El valor del secreto no puede estar vacío')
    _keyring().set_password(SECRET_SERVICE, name, value)
    names = set(secret_names()); names.add(name)
    set_setting('secret_names', sorted(names))


def secret_get(name):
    """OS credential store first; environment variable with the same name as fallback."""
    try:
        value = _keyring().get_password(SECRET_SERVICE, name)
    except Exception:
        value = None
    return value or os.environ.get(name) or None


def secret_delete(name):
    try:
        _keyring().delete_password(SECRET_SERVICE, name)
    except Exception:
        pass
    set_setting('secret_names', [n for n in secret_names() if n != name])


# --------------------------------------------------------------------------- variables

VAR_RE = re.compile(r'\{\{\s*([\w.:-]+)\s*\}\}')


def substitute(value, variables, secrets_used=None):
    """Replaces {{name}} and {{secret:NAME}}; unknown names are left untouched."""
    def replace(match):
        name = match.group(1)
        if name.startswith('secret:'):
            secret = secret_get(name[7:])
            if secret is None:
                return match.group(0)
            if secrets_used is not None:
                secrets_used.add(secret)
            return secret
        return str(variables[name]) if name in variables else match.group(0)

    if isinstance(value, str):
        return VAR_RE.sub(replace, value)
    if isinstance(value, list):
        return [substitute(x, variables, secrets_used) for x in value]
    if isinstance(value, dict):
        return {k: substitute(v, variables, secrets_used) for k, v in value.items()}
    return value


def find_unresolved(*values):
    """Names of {{variables}} still present after substitution."""
    found = set()

    def walk(value):
        if isinstance(value, str):
            found.update(m.group(1) for m in VAR_RE.finditer(value))
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)
    for value in values:
        walk(value)
    return sorted(found)


def scrub(value, secrets):
    """Removes known secret values from any nested structure before persisting."""
    secrets = [s for s in secrets if s and len(s) >= 4]
    if not secrets:
        return value
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, '[REDACTED]')
        return value
    if isinstance(value, list):
        return [scrub(x, secrets) for x in value]
    if isinstance(value, dict):
        return {k: scrub(v, secrets) for k, v in value.items()}
    return value


def redact_headers(headers):
    return {k: ('[REDACTED]' if k.lower() in SENSITIVE_HEADERS else v) for k, v in headers.items()}


# --------------------------------------------------------------------------- JSON paths

class PathError(KeyError):
    pass


_TOKEN = re.compile(r"\[(\d+|\*)\]|\['([^']*)'\]|\[\"([^\"]*)\"\]|\.?([^.\[\]]+)")


def extract_path(data, path):
    """JSONPath subset: $.a.b[0]['k'][*] and legacy a.b.0. Raises PathError if missing."""
    path = (path or '').strip()
    if path.startswith('$'):
        path = path[1:]
    current = [data]
    wildcard = False
    for match in _TOKEN.finditer(path):
        index, single, double, name = match.groups()
        next_values = []
        for node in current:
            if index == '*':
                if not isinstance(node, list):
                    raise PathError(path)
                next_values.extend(node)
                wildcard = True
            elif index is not None or (name is not None and name.isdigit() and isinstance(node, list)):
                position = int(index if index is not None else name)
                if not isinstance(node, list) or position >= len(node):
                    raise PathError(path)
                next_values.append(node[position])
            else:
                key = single if single is not None else double if double is not None else name
                if not isinstance(node, dict) or key not in node:
                    raise PathError(path)
                next_values.append(node[key])
        current = next_values
    return current if wildcard else current[0]


JSON_TYPES = ('string', 'number', 'integer', 'boolean', 'array', 'object', 'null')


def _type_ok(value, name):
    if name == 'number':
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == 'integer':
        return isinstance(value, int) and not isinstance(value, bool)
    expected = {'string': str, 'boolean': bool, 'array': list, 'object': dict, 'null': type(None)}[name]
    return isinstance(value, expected)


ASSERTION_TYPES = {
    'status': {'label': 'Código HTTP igual a', 'fields': ['expected']},
    'status_in': {'label': 'Código HTTP en lista (200,201)', 'fields': ['expected']},
    'response_time_max': {'label': 'Tiempo máximo (ms)', 'fields': ['expected']},
    'header_exists': {'label': 'Header existe', 'fields': ['name']},
    'header_equals': {'label': 'Header igual a', 'fields': ['name', 'expected']},
    'header_contains': {'label': 'Header contiene', 'fields': ['name', 'expected']},
    'json_exists': {'label': 'JSONPath existe', 'fields': ['path']},
    'json_not_exists': {'label': 'JSONPath no existe', 'fields': ['path']},
    'json_equals': {'label': 'JSONPath igual a', 'fields': ['path', 'expected']},
    'json_not_equals': {'label': 'JSONPath distinto de', 'fields': ['path', 'expected']},
    'json_type': {'label': 'JSONPath es de tipo', 'fields': ['path', 'expected']},
    'json_length': {'label': 'JSONPath longitud igual a', 'fields': ['path', 'expected']},
    'json_regex': {'label': 'JSONPath cumple regex', 'fields': ['path', 'expected']},
    'json_contains': {'label': 'JSONPath contiene', 'fields': ['path', 'expected']},
    'numeric_greater': {'label': 'JSONPath mayor que', 'fields': ['path', 'expected']},
    'numeric_greater_equal': {'label': 'JSONPath mayor o igual que', 'fields': ['path', 'expected']},
    'numeric_less': {'label': 'JSONPath menor que', 'fields': ['path', 'expected']},
    'numeric_less_equal': {'label': 'JSONPath menor o igual que', 'fields': ['path', 'expected']},
    'json_schema': {'label': 'Cuerpo cumple JSON Schema', 'fields': ['schema']},
    'json_matches': {'label': 'Cuerpo JSON idéntico al esperado (ignorando campos)', 'fields': ['expected']},
    'body_equals': {'label': 'Cuerpo idéntico al texto esperado', 'fields': ['expected']},
    'contains': {'label': 'Cuerpo contiene texto', 'fields': ['expected']},
    'not_contains': {'label': 'Cuerpo no contiene texto', 'fields': ['expected']},
    'regex': {'label': 'Cuerpo cumple regex', 'fields': ['expected']},
    'non_empty': {'label': 'Cuerpo no vacío', 'fields': []},
    'empty': {'label': 'Cuerpo vacío', 'fields': []},
}


def validate_assertion_rule(rule):
    """Static validation used by the visual editor. Returns an error message or None."""
    if not isinstance(rule, dict):
        return 'La aserción debe ser un objeto'
    kind = rule.get('type')
    spec = ASSERTION_TYPES.get(kind)
    if spec is None:
        return f'Tipo de aserción no soportado: {kind}'
    for field in spec['fields']:
        if rule.get(field) in (None, ''):
            return f'Falta el campo «{field}» en {kind}'
    if kind == 'json_schema' and not isinstance(rule.get('schema'), dict):
        return 'json_schema requiere un schema (objeto)'
    if kind == 'json_type' and rule.get('expected') not in JSON_TYPES:
        return 'Tipo JSON inválido'
    if kind == 'json_matches' and (not isinstance(rule.get('ignore', []), list) or not all(isinstance(x, str) for x in rule.get('ignore', []))):
        return '«ignore» debe ser una lista de rutas JSONPath'
    if kind in ('regex', 'json_regex'):
        try:
            re.compile(str(rule.get('expected', '')))
        except re.error as exc:
            return f'Expresión regular inválida: {exc}'
    if kind in ('status', 'response_time_max', 'json_length', 'numeric_greater', 'numeric_greater_equal', 'numeric_less', 'numeric_less_equal'):
        try:
            float(rule['expected'])
        except (TypeError, ValueError):
            return 'El valor esperado debe ser numérico'
    return None


def check_assertions(response, assertions, duration_ms=None):
    results = []
    for rule in assertions:
        kind = rule.get('type')
        try:
            actual, passed = _evaluate(response, rule, kind, duration_ms)
        except PathError:
            actual, passed = 'missing', kind == 'json_not_exists'
        except json.JSONDecodeError:
            actual, passed = 'missing/invalid JSON', False
        except Exception as exc:  # malformed rule must fail the assertion, never crash the run
            actual, passed = f'invalid: {exc}', False
        results.append({'rule': rule, 'passed': passed, 'actual': actual})
    return results


def _json_at(response, rule):
    return extract_path(response.json(), rule.get('path', ''))


def _evaluate(response, rule, kind, duration_ms):
    expected = rule.get('expected')
    if kind == 'status':
        return response.status_code, response.status_code == int(expected)
    if kind == 'status_in':
        options = [int(x) for x in (expected if isinstance(expected, list) else str(expected).split(','))]
        return response.status_code, response.status_code in options
    if kind == 'response_time_max':
        actual = duration_ms if duration_ms is not None else response.elapsed.total_seconds() * 1000
        return actual, actual <= float(expected)
    if kind == 'header_exists':
        actual = response.headers.get(rule.get('name', ''))
        return actual, actual is not None
    if kind == 'header_equals':
        actual = response.headers.get(rule.get('name', ''))
        return actual, actual == str(expected if expected is not None else '')
    if kind == 'header_contains':
        actual = response.headers.get(rule.get('name', ''))
        return actual, actual is not None and str(expected) in actual
    if kind == 'json_equals':
        actual = _json_at(response, rule)
        return actual, actual == expected
    if kind == 'json_not_equals':
        actual = _json_at(response, rule)
        return actual, actual != expected
    if kind == 'json_exists':
        return _json_at(response, rule), True
    if kind == 'json_not_exists':
        try:
            _json_at(response, rule)
        except PathError:
            return 'missing', True
        return 'present', False
    if kind == 'json_type':
        actual = _json_at(response, rule)
        if expected not in JSON_TYPES:
            raise TypeError('tipo JSON inválido')
        return type(actual).__name__, _type_ok(actual, expected)
    if kind == 'json_length':
        actual = _json_at(response, rule)
        return len(actual), len(actual) == int(expected)
    if kind == 'json_regex':
        actual = _json_at(response, rule)
        return actual, re.search(str(expected), str(actual)) is not None
    if kind == 'json_contains':
        actual = _json_at(response, rule)
        return actual, (expected in actual if isinstance(actual, (list, dict)) else str(expected) in str(actual))
    if kind in ('numeric_greater', 'numeric_greater_equal', 'numeric_less', 'numeric_less_equal'):
        actual = _json_at(response, rule)
        if isinstance(actual, bool) or not isinstance(actual, (int, float)):
            return 'missing/invalid number', False
        limit = float(expected)
        return actual, {'numeric_greater': actual > limit, 'numeric_greater_equal': actual >= limit,
                        'numeric_less': actual < limit, 'numeric_less_equal': actual <= limit}[kind]
    if kind == 'json_schema':
        import jsonschema
        schema = rule.get('schema')
        if not isinstance(schema, dict):
            raise TypeError('schema debe ser un objeto')
        jsonschema.Draft202012Validator.check_schema(schema)
        errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(response.json()), key=lambda e: list(map(str, e.path)))
        if errors:
            return [f'{"/".join(map(str, e.path)) or "(raíz)"}: {e.message}' for e in errors[:5]], False
        return 'válido', True
    if kind == 'json_matches':
        actual_body, wanted = response.json(), copy.deepcopy(expected)
        for path in rule.get('ignore', []):
            remove_path(actual_body, path); remove_path(wanted, path)
        differences = json_diff(wanted, actual_body)
        return (differences or 'idéntico'), not differences
    if kind == 'body_equals':
        return response.text[:1000], response.text == str(expected if expected is not None else '')
    if kind == 'contains':
        return response.text[:1000], str(expected if expected is not None else '') in response.text
    if kind == 'not_contains':
        return response.text[:1000], str(expected if expected is not None else '') not in response.text
    if kind == 'regex':
        return response.text[:1000], re.search(str(expected), response.text) is not None
    if kind == 'non_empty':
        return response.text, bool(response.text)
    if kind == 'empty':
        return response.text, not response.text
    return 'unsupported', False



def _tokens(path):
    path = (path or '').strip()
    if path.startswith('$'):
        path = path[1:]
    tokens = []
    for match in _TOKEN.finditer(path):
        index, single, double, name = match.groups()
        if index == '*':
            tokens.append(('*', None))
        elif index is not None:
            tokens.append(('i', int(index)))
        else:
            tokens.append(('k', single if single is not None else double if double is not None else name))
    return tokens


def remove_path(data, path):
    """Deletes the value(s) at a JSONPath-subset path (supports [*]); missing paths are ignored."""
    tokens = _tokens(path)

    def walk(node, i):
        kind, value = tokens[i]
        last = i == len(tokens) - 1
        if kind == '*':
            if isinstance(node, list):
                if last:
                    node.clear()
                else:
                    for item in node:
                        walk(item, i + 1)
            return
        if isinstance(node, list) and (kind == 'i' or (kind == 'k' and str(value).isdigit())):
            position = int(value)
            if position < len(node):
                if last:
                    del node[position]
                else:
                    walk(node[position], i + 1)
            return
        if kind == 'k' and isinstance(node, dict) and value in node:
            if last:
                del node[value]
            else:
                walk(node[value], i + 1)
    if tokens:
        walk(data, 0)
    return data


def json_diff(expected, actual, path='$', limit=10):
    """Human-readable differences between two JSON values (first `limit`)."""
    found = []

    def walk(a, b, where):
        if len(found) >= limit:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in a:
                if key not in b:
                    found.append(f'{where}.{key}: falta en la respuesta')
                else:
                    walk(a[key], b[key], f'{where}.{key}')
            for key in b:
                if key not in a:
                    found.append(f'{where}.{key}: campo nuevo en la respuesta')
        elif isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                found.append(f'{where}: longitud {len(b)} (esperada {len(a)})')
            for index, (x, y) in enumerate(zip(a, b)):
                walk(x, y, f'{where}[{index}]')
        elif a != b or type(a) is not type(b):
            found.append(f'{where}: obtenido {json.dumps(b, ensure_ascii=False)[:80]} (esperado {json.dumps(a, ensure_ascii=False)[:80]})')
    walk(expected, actual, path)
    return found[:limit]


_VOLATILE_KEY = re.compile(r'created|updated|modified|timestamp|expires|date|time|nonce|trace|request_?id|session|token|uuid|etag', re.I)
_VOLATILE_VALUE = re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}|^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)


def suggest_volatile_paths(data):
    """Paths whose values usually change between calls (dates, uuids, tokens, epoch times): candidates to ignore."""
    found = set()

    def segment(key):
        return f'.{key}' if re.fullmatch(r'[A-Za-z_][\w-]*', key) else f"['{key}']"

    def walk(node, path):
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, path + segment(str(key)))
        elif isinstance(node, list):
            if node:
                walk(node[0], path + '[*]')
        else:
            key = re.split(r'[.\[\]\']+', path.rstrip(']'))[-1] if path else ''
            if isinstance(node, str) and _VOLATILE_VALUE.search(node):
                found.add(path)
            elif isinstance(node, (int, float)) and not isinstance(node, bool) and (node >= 10 ** 12 or (_VOLATILE_KEY.search(key) and node >= 10 ** 9)):
                found.add(path)
            elif isinstance(node, str) and _VOLATILE_KEY.search(key) and re.search(r'token|nonce|session|etag|trace', key, re.I):
                found.add(path)
    walk(data, '$')
    return sorted(found)


def infer_schema(value):
    """Small JSON Schema describing the structure (types, required keys, first array item)."""
    if isinstance(value, bool):
        return {'type': 'boolean'}
    if isinstance(value, int):
        return {'type': 'integer'}
    if isinstance(value, float):
        return {'type': 'number'}
    if isinstance(value, str):
        return {'type': 'string'}
    if value is None:
        return {'type': 'null'}
    if isinstance(value, list):
        schema = {'type': 'array'}
        if value:
            schema['items'] = infer_schema(value[0])
        return schema
    return {'type': 'object', 'required': sorted(value), 'properties': {k: infer_schema(v) for k, v in value.items()}}


def sample_value_for_schema(schema):
    """Un valor plausible para un fragmento de JSON Schema: prioriza 'example'/'default'/'enum' si el contrato
    los declara, si no cae a un placeholder según el tipo. No adivina el significado de negocio — solo deja
    la petición lista para completar en vez de vacía."""
    if not isinstance(schema, dict):
        return ''
    if 'example' in schema:
        return schema['example']
    if 'default' in schema:
        return schema['default']
    if schema.get('enum'):
        return schema['enum'][0]
    kind = schema.get('type')
    if kind in ('integer', 'number'):
        return 0
    if kind == 'boolean':
        return False
    if kind == 'array':
        item = sample_value_for_schema(schema.get('items') or {})
        return [item] if item not in ('', None) else []
    if kind == 'object' or schema.get('properties'):
        return {k: sample_value_for_schema(v) for k, v in (schema.get('properties') or {}).items()}
    return ''


def sample_request_for_operation(operation):
    """Query params (con sus nombres, listos para completar) y un body de ejemplo armados desde lo que el
    contrato OpenAPI declara para esta operación — para que «Probar» no abra una petición vacía que el propio
    endpoint va a rechazar por faltarle lo mínimo que exige."""
    query = {}
    for param in operation.get('parameters') or []:
        if param.get('in') == 'query':
            query[param['name']] = sample_value_for_schema(param.get('schema') or {})
    body = None
    content = (operation.get('requestBody') or {}).get('content') or {}
    json_schema = (content.get('application/json') or {}).get('schema')
    if json_schema:
        body = sample_value_for_schema(json_schema)
    return {'query': query, 'body': body}


def snapshot_assertions(status, body_text, mode='exact', ignore=()):
    """Turns an observed response into deterministic assertions.

    mode: 'status' (only the HTTP code), 'structure' (code + inferred JSON Schema), 'exact' (code + identical body).
    """
    if mode not in ('status', 'structure', 'exact'):
        raise ValueError('Modo de respuesta esperada inválido')
    rules = [{'type': 'status', 'expected': int(status)}]
    if mode == 'status':
        return rules
    try:
        parsed = json.loads(body_text)
    except (TypeError, ValueError):
        parsed = None
        is_json = False
    else:
        is_json = True
    if mode == 'structure':
        if not is_json:
            raise ValueError('La respuesta no es JSON: usa «exacta» o «solo código»')
        rules.append({'type': 'json_schema', 'schema': infer_schema(parsed)})
    elif is_json:
        wanted = copy.deepcopy(parsed)
        paths = [p for p in ignore if p]
        for path in paths:
            remove_path(wanted, path)
        rules.append({'type': 'json_matches', 'expected': wanted, 'ignore': paths})
    else:
        rules.append({'type': 'body_equals', 'expected': body_text})
    return rules


def normalize_url(value, scheme='https'):
    """'google.com/x' -> 'https://google.com/x'. Values that already carry http(s):// are returned untouched."""
    value = (value or '').strip()
    if not value or '://' in value:
        return value
    if scheme not in ('http', 'https'):
        raise ValueError('Protocolo inválido (http o https)')
    return f'{scheme}://{value.lstrip("/")}'


def validate_base_url(url, required=True):
    """Same rule as split_url (http/https, hostname, no embedded user:pass) without discarding the path/query."""
    value = (url or '').strip()
    if not value:
        if required:
            raise ValueError('URL base inválida (use http:// o https:// sin usuario/clave)')
        return value
    parsed = urlparse(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('URL base inválida (use http:// o https:// sin usuario/clave)')
    return value


def split_url(url):
    """'https://h:8443/a/b?x=1' -> ('https://h:8443', '/a/b?x=1'); raises ValueError on invalid URLs."""
    parsed = urlparse((url or '').strip())
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('URL inválida (use http:// o https:// sin usuario/clave)')
    path = parsed.path or '/'
    return f'{parsed.scheme}://{parsed.netloc}', path + (f'?{parsed.query}' if parsed.query else '')


def ensure_environment_for_url(project_id, url):
    """Finds (or creates) the project's environment for the URL origin. Returns (environment, path)."""
    origin, path = split_url(url)
    for env in list_project_items('environments', project_id):
        if env.get('base_url', '').rstrip('/') == origin:
            return env, path
    env = save('environments', {'name': urlparse(origin).netloc, 'project_id': project_id, 'base_url': origin,
                                'auth': {'type': 'none'}, 'variables': {}})
    return env, path


def environment_for_project(env, project_id):
    """The environment itself if it belongs to the project; otherwise the project's environment for the same base URL (created as a copy if missing)."""
    if env.get('project_id') == project_id:
        return env
    for existing in list_project_items('environments', project_id):
        if existing.get('base_url', '').rstrip('/') == env['base_url'].rstrip('/'):
            return existing
    clone = {k: copy.deepcopy(v) for k, v in env.items() if k not in ('id', 'updated_at')}
    clone['project_id'] = project_id
    return save('environments', clone)


def check_suite_origin(suite_id, origin):
    """Cases only run against the suite's environment: refuse adding a case aimed at another host."""
    suite = get('suites', suite_id)
    if suite is None:
        raise ValueError('Suite inexistente')
    env = get('environments', suite.get('environment_id'))
    if env is None:
        raise ValueError('La suite no tiene un ambiente válido')
    if env.get('base_url', '').rstrip('/') != origin.rstrip('/'):
        raise ValueError(f'La suite «{suite["name"]}» se ejecuta contra «{env["name"]}» ({env["base_url"]}); '
                         f'este destino es {origin}. Elige otra suite o guarda sin agregar a una suite.')
    return suite


def add_cases_to_suite(suite_id, case_ids, origin=None):
    """Appends cases (once) to an existing suite, keeping its policies and variables."""
    suite = check_suite_origin(suite_id, origin) if origin else get('suites', suite_id)
    if suite is None:
        raise ValueError('Suite inexistente')
    ids = list(suite['case_ids']) + [c for c in case_ids if c not in suite['case_ids']]
    extra = {}
    if suite.get('steps'):                       # keep the flow definition; new cases join as plain steps
        steps = suite_steps(suite)
        taken = [s['alias'] for s in steps]
        for case_id in ids[len(suite['case_ids']):]:
            alias = slugify_alias((get('cases', case_id) or {}).get('name') or 'paso', taken)
            taken.append(alias)
            steps.append({'case_id': case_id, 'alias': alias, 'environment_id': None, 'enrich': []})
        extra['steps'] = steps
    return save_suite(suite['name'], suite['environment_id'], ids, suite.get('project_id'), id=suite['id'],
                      on_failure=suite.get('on_failure', 'continue'), retries=suite.get('retries', 0),
                      retry_delay_s=suite.get('retry_delay_s', 0), variables=suite.get('variables'), feature_id=suite.get('feature_id'), **extra)


def check_connectivity(url, timeout=5.0):
    """DNS -> TCP -> TLS -> HTTP probe of a URL. Never raises for network failures; reports each step."""
    origin, path = split_url(url)
    parsed = urlparse(origin)
    host, https = parsed.hostname, parsed.scheme == 'https'
    port = parsed.port or (443 if https else 80)
    steps = []

    def step(name, ok, ms, detail):
        steps.append({'name': name, 'ok': ok, 'ms': round(ms, 1), 'detail': detail})
        return ok

    started = time.perf_counter()
    try:
        addresses = sorted({info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
        step('DNS', True, (time.perf_counter() - started) * 1000, ', '.join(addresses[:3]))
    except OSError as exc:
        step('DNS', False, (time.perf_counter() - started) * 1000, f'No se pudo resolver «{host}»: {exc}')
        return {'url': url, 'ok': False, 'steps': steps}
    started = time.perf_counter()
    try:
        sock = socket.create_connection((host, port), timeout=timeout)
        step('TCP', True, (time.perf_counter() - started) * 1000, f'Conexión al puerto {port}')
    except OSError as exc:
        step('TCP', False, (time.perf_counter() - started) * 1000, f'Puerto {port} inaccesible: {exc}')
        return {'url': url, 'ok': False, 'steps': steps}
    try:
        if https:
            started = time.perf_counter()
            try:
                with ssl.create_default_context().wrap_socket(sock, server_hostname=host) as tls:
                    cert = tls.getpeercert() or {}
                    step('TLS', True, (time.perf_counter() - started) * 1000, f'{tls.version()} · vence {cert.get("notAfter", "n/d")}')
            except (ssl.SSLError, OSError) as exc:
                step('TLS', False, (time.perf_counter() - started) * 1000, f'Certificado/handshake: {exc}')
                return {'url': url, 'ok': False, 'steps': steps}
    finally:
        sock.close()
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            response = client.get(origin + path)
        step('HTTP', True, (time.perf_counter() - started) * 1000,
             f'{response.status_code} {response.reason_phrase} · {len(response.content)} bytes' + (f' · {response.headers["server"]}' if 'server' in response.headers else ''))
    except httpx.HTTPError as exc:
        step('HTTP', False, (time.perf_counter() - started) * 1000, str(exc)[:200] or type(exc).__name__)
    return {'url': url, 'ok': all(item['ok'] for item in steps), 'steps': steps}


def dataset_cases(template, rows, project_id, mode='exact', ignore=()):
    """One deterministic case per parameter row.

    template: case dict using {{placeholders}}; rows: [{'name', 'variables': {..}, 'status': int|None, 'body': text|None}].
    When a row carries an observed response (status/body) the assertions are snapshotted from it (see snapshot_assertions);
    otherwise the template's own assertions are used.
    """
    if not rows:
        raise ValueError('Agrega al menos una fila de parámetros')
    cases = []
    for index, row in enumerate(rows, 1):
        variables = {k: v for k, v in (row.get('variables') or {}).items()}
        item = {k: copy.deepcopy(v) for k, v in template.items() if k not in ('id', 'updated_at')}
        item.update({'name': f'{template.get("name", "Caso")} · {row.get("name") or index}', 'type': 'api',
                     'project_id': project_id, 'variables': variables})
        if row.get('status') is not None:
            item['assertions'] = snapshot_assertions(row['status'], row.get('body') or '', mode, ignore)
        cases.append(item)
    return [save('cases', item) for item in cases]


# --------------------------------------------------------------------------- enrichment between steps

class EnrichmentError(ValueError):
    pass


ALIAS_RE = re.compile(r'^[A-Za-z_][\w-]{0,40}$')
ENRICH_TARGETS = {'body': 'Body', 'headers': 'Header', 'query': 'Query', 'path': 'Ruta'}
ENRICH_ACTIONS = {'set': 'Asignar / agregar', 'remove': 'Quitar', 'merge': 'Combinar objeto'}
SOURCE_TYPES = {'literal': 'Valor fijo', 'step': 'Respuesta de un paso anterior', 'var': 'Variable', 'template': 'Texto con referencias'}
STEP_REF = re.compile(r'\{\{@([A-Za-z_][\w-]*):([^}]*)\}\}')


def slugify_alias(name, taken=()):
    base = re.sub(r'[^A-Za-z0-9_]+', '_', (name or 'paso').strip()).strip('_') or 'paso'
    if base[0].isdigit():
        base = 'p_' + base
    base = base[:36]
    alias, number = base, 2
    while alias in taken:
        alias, number = f'{base}_{number}', number + 1
    return alias


def set_path(data, path, value):
    """Sets (creating intermediate objects) the value at a JSONPath-subset path: $.a.b, $.a[0].c."""
    tokens = _tokens(path)
    if not tokens:
        raise ValueError('La ruta no puede estar vacía')
    node = data
    for position, (kind, key) in enumerate(tokens):
        last = position == len(tokens) - 1
        following = None if last else tokens[position + 1][0]
        if kind == '*':
            raise ValueError('«[*]» no se puede usar para asignar')
        if kind == 'k' and isinstance(node, list) and str(key).isdigit():
            kind, key = 'i', int(key)
        if kind == 'k':
            if not isinstance(node, dict):
                raise ValueError(f'No se puede asignar «{key}» porque el valor anterior no es un objeto')
            if last:
                node[key] = value
            else:
                if key not in node or node[key] is None:
                    node[key] = [] if following == 'i' else {}
                elif not isinstance(node[key], (dict, list)):
                    raise ValueError(f'«{key}» ya tiene un valor que no es un objeto ni una lista; no se sobrescribe')
                node = node[key]
        else:
            if not isinstance(node, list):
                raise ValueError(f'No se puede usar el índice [{key}] porque el valor anterior no es una lista')
            if key > len(node):
                raise ValueError(f'Índice [{key}] fuera de rango (la lista tiene {len(node)} elementos)')
            if key == len(node):
                node.append(value if last else ([] if following == 'i' else {}))
            elif last:
                node[key] = value
            if not last:
                node = node[key]
                if not isinstance(node, (dict, list)):
                    raise ValueError(f'El elemento [{key}] no es un objeto ni una lista')
    return data


def resolve_source(source, context, variables):
    kind = source.get('type')
    if kind == 'literal':
        return copy.deepcopy(source.get('value'))
    if kind == 'var':
        name = source.get('name', '')
        if name not in variables:
            raise EnrichmentError(f'la variable «{name}» no está definida')
        return variables[name]
    if kind == 'step':
        alias, path = source.get('step', ''), (source.get('path') or '').strip()
        step = context.get(alias)
        if step is None:
            raise EnrichmentError(f'el paso «{alias}» aún no se ejecutó o no devolvió respuesta')
        if path in ('', '$'):
            return copy.deepcopy(step['body'])
        try:
            return copy.deepcopy(extract_path(step['body'], path))
        except PathError:
            raise EnrichmentError(f'«{path}» no existe en la respuesta del paso «{alias}»')
    if kind == 'template':
        def inject(match):
            value = resolve_source({'type': 'step', 'step': match.group(1), 'path': match.group(2)}, context, variables)
            return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        return substitute(STEP_REF.sub(inject, str(source.get('value', ''))), variables)
    raise EnrichmentError(f'origen no soportado «{kind}»')


def _as_text(value):
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def describe_enrichment(op):
    source = op.get('source') or {}
    kind = source.get('type')
    origin = {'literal': lambda: json.dumps(source.get('value'), ensure_ascii=False)[:40],
              'step': lambda: f'paso {source.get("step")} {source.get("path") or "(respuesta completa)"}',
              'var': lambda: f'variable {source.get("name")}',
              'template': lambda: f'texto «{str(source.get("value", ""))[:40]}»'}.get(kind, lambda: '?')()
    where = {'body': 'body', 'headers': 'header', 'query': 'query', 'path': 'ruta'}.get(op.get('target'), '?')
    key = op.get('path') or ''
    if op.get('action') == 'remove':
        return f'Quitar {where} {key}'.strip()
    verb = 'Combinar en' if op.get('action') == 'merge' else 'Asignar'
    return f'{verb} {where} {key} ← {origin}'.replace('  ', ' ')


def apply_enrichment(request, ops, context, variables=None, strict=True):
    """Modifies request {'path','headers','query','body'} in place. Returns (descriptions of applied ops, problems).

    strict=True raises EnrichmentError at the first problem (real runs: nothing is sent);
    strict=False collects the problems and keeps going (previews)."""
    applied, problems = [], []
    for number, op in enumerate(ops or [], 1):
        try:
            action, target, key = op.get('action'), op.get('target'), (op.get('path') or '').strip()
            value = resolve_source(op.get('source') or {}, context, variables or {}) if action in ('set', 'merge') else None
            if target == 'path':
                if action != 'set':
                    raise EnrichmentError('la ruta solo admite «Asignar»')
                request['path'] = _as_text(value)
            elif target in ('headers', 'query'):
                store = request[target]
                if action == 'remove':
                    store.pop(key, None)
                elif action == 'set':
                    store[key] = _as_text(value)
                elif isinstance(value, dict):
                    store.update({k: _as_text(v) for k, v in value.items()})
                else:
                    raise EnrichmentError('«Combinar» necesita que el origen sea un objeto')
            elif target == 'body':
                if action == 'remove':
                    if request['body'] is not None and key:
                        remove_path(request['body'], key)
                elif action == 'set':
                    if key in ('', '$'):
                        request['body'] = value
                    else:
                        if request['body'] is None:
                            request['body'] = {}
                        set_path(request['body'], key, value)
                else:
                    if not isinstance(value, dict):
                        raise EnrichmentError('«Combinar» necesita que el origen sea un objeto')
                    if request['body'] is None:
                        request['body'] = {}
                    if key in ('', '$'):
                        if not isinstance(request['body'], dict):
                            raise EnrichmentError('el body no es un objeto')
                        request['body'].update(value)
                    else:
                        try:
                            node = extract_path(request['body'], key)
                        except PathError:
                            node = None
                        if not isinstance(node, dict):
                            set_path(request['body'], key, {})
                            node = extract_path(request['body'], key)
                        node.update(value)
            else:
                raise EnrichmentError(f'destino no soportado «{target}»')
            applied.append(describe_enrichment(op))
        except (EnrichmentError, ValueError) as exc:
            message = f'Enriquecimiento {number} ({describe_enrichment(op)}): {exc}'
            if strict:
                raise EnrichmentError(message)
            problems.append(message)
    return applied, problems


def validate_enrichment(ops, previous_aliases):
    """Static checks for the editor and for save_suite. References may only point at EARLIER steps."""
    problems = []
    if not isinstance(ops, list):
        return ['las reglas de enriquecimiento deben ser una lista']
    for number, op in enumerate(ops, 1):
        label = f'regla {number}'
        if not isinstance(op, dict) or op.get('action') not in ENRICH_ACTIONS or op.get('target') not in ENRICH_TARGETS:
            problems.append(f'{label}: acción o destino inválidos')
            continue
        action, target, key = op['action'], op['target'], (op.get('path') or '').strip()
        if target in ('headers', 'query') and action != 'merge' and not key:
            problems.append(f'{label}: indica el nombre del {"header" if target == "headers" else "parámetro"}')
        if target == 'path' and action != 'set':
            problems.append(f'{label}: la ruta solo admite «Asignar»')
        if target == 'body' and action == 'remove' and not key:
            problems.append(f'{label}: indica qué campo quitar')
        if target == 'body' and key and not key.startswith('$'):
            problems.append(f'{label}: la ruta del body debe empezar con $ (p. ej. $.cliente.id)')
        if action == 'remove':
            continue
        source = op.get('source') or {}
        kind = source.get('type')
        if kind not in SOURCE_TYPES:
            problems.append(f'{label}: elige el origen del valor')
        elif kind == 'literal' and 'value' not in source:
            problems.append(f'{label}: falta el valor fijo')
        elif kind == 'var' and not (source.get('name') or '').strip():
            problems.append(f'{label}: falta el nombre de la variable')
        elif kind == 'step' and source.get('step') not in previous_aliases:
            problems.append(f'{label}: el paso «{source.get("step")}» no existe o no es anterior a este')
        elif kind == 'template':
            for alias in STEP_REF.findall(str(source.get('value', ''))):
                if alias[0] not in previous_aliases:
                    problems.append(f'{label}: el paso «{alias[0]}» no existe o no es anterior a este')
    return problems


def _parse_body(text):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def history_context(steps):
    """Response of the latest recorded run of each step's case (what a preview can use without calling anything)."""
    runs = list_items('runs')
    context = {}
    for step in steps:
        for run in runs:
            if run.get('case_id') == step['case_id'] and run.get('type') == 'api' and run.get('response') is not None:
                context[step['alias']] = {'http_status': run.get('http_status'), 'headers': run['response'].get('headers', {}),
                                          'body': _parse_body(run['response'].get('body'))}
                break
    return context


def preview_step(suite_or_steps, index, extra_context=None):
    """What step `index` would send after its enrichment, using recorded responses of earlier steps."""
    steps = suite_steps(suite_or_steps) if isinstance(suite_or_steps, dict) else suite_or_steps
    step = steps[index]
    case = get('cases', step['case_id'])
    if case is None:
        raise ValueError('El caso del paso ya no existe')
    context = {**history_context(steps[:index]), **(extra_context or {})}
    request = {'path': case.get('path', ''), 'headers': redact_headers(copy.deepcopy(case.get('headers') or {})),
               'query': copy.deepcopy(case.get('query') or {}), 'body': copy.deepcopy(case.get('body'))}
    variables = {**(case.get('variables') or {})}
    applied, problems = apply_enrichment(request, step.get('enrich') or [], context, variables, strict=False)
    request['headers'] = redact_headers(request['headers'])          # same as the history: tokens are never displayed
    waiting = [s['alias'] for s in steps[:index] if s['alias'] not in context]
    return {'method': case.get('method'), 'request': request, 'applied': applied, 'problems': problems, 'without_history': waiting}


def run_extractions(response, rules):
    """Pulls named values out of a response for chaining. Returns (values, errors)."""
    values, errors = {}, []
    for rule in rules or []:
        name = rule.get('name')
        source = rule.get('source', 'json')
        try:
            if not name or not re.fullmatch(r'[\w.-]+', name):
                raise ValueError('nombre de variable inválido')
            if source == 'json':
                values[name] = extract_path(response.json(), rule.get('path', ''))
            elif source == 'header':
                header = response.headers.get(rule.get('path', ''))
                if header is None:
                    raise PathError(rule.get('path', ''))
                values[name] = header
            elif source == 'status':
                values[name] = response.status_code
            elif source == 'regex':
                match = re.search(rule.get('path', ''), response.text)
                if not match:
                    raise PathError(rule.get('path', ''))
                values[name] = match.group(1) if match.groups() else match.group(0)
            else:
                raise ValueError(f'origen no soportado: {source}')
        except (PathError, ValueError, re.error, TypeError) as exc:
            errors.append(f'{name or "?"}: no se pudo extraer ({exc})')
    return values, errors


# --------------------------------------------------------------------------- API execution

def _bounded(value, limit=50000):
    """JSON bodies are kept as sent (so the history shows what left); oversized ones are truncated."""
    text = json.dumps(value, ensure_ascii=False, default=str)
    return value if len(text) <= limit else text[:limit] + '…[truncado]'


def execute_api(case, environment, variables=None, persist=True, context=None, enrich=None, meta=None):
    """Runs only explicitly selected cases; callers must control allowed target hosts.

    Variable precedence (low -> high): environment, case.variables, values passed by the caller (suite / chaining).
    persist=False is used by the Laboratory for ad-hoc requests that must not enter the history.
    context/enrich: responses of earlier steps of a flow and the rules that add or modify fields of THIS request
    (applied after variable substitution; a failing rule aborts before anything is sent).
    """
    variables = {**environment.get('variables', {}), **(case.get('variables') or {}), **(variables or {})}
    secrets_used = set()
    run = {'id': uid(), 'case_id': case.get('id'), 'case_name': case.get('name', ''), 'type': 'api', 'started_at': now(),
           'environment_id': environment['id'], 'project_id': case.get('project_id'), 'case_snapshot': case, **(meta or {})}
    try:
        base = substitute(environment.get('base_url', ''), variables, secrets_used).rstrip('/')
        path = substitute(case.get('path', ''), variables, secrets_used)
        headers = substitute(case.get('headers', {}), variables, secrets_used)
        body = substitute(case.get('body'), variables, secrets_used)
        query = substitute(case.get('query', {}), variables, secrets_used)
        missing = find_unresolved(base, path, headers, body, query)
        if missing:
            raise ValueError('Variables sin resolver: ' + ', '.join(missing))
        enriched = []
        if enrich:
            request = {'path': path, 'headers': dict(headers), 'query': dict(query or {}), 'body': copy.deepcopy(body)}
            enriched, _ = apply_enrichment(request, enrich, context or {}, variables, strict=True)
            path, headers, query, body = request['path'], request['headers'], request['query'], request['body']
        url = base + ('/' if not path.startswith('/') else '') + path
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('URL de destino inválida.')
        auth = environment.get('auth', {'type': 'none'})
        kind = auth.get('type', 'none')
        if kind in ('bearer', 'api_key'):
            secret_name = auth.get('secret') or auth.get('env_var', '')
            auto_refresh = bool(auth.get('refresh')) and auth['refresh'].get('enabled', True)
            if auto_refresh and token_needs_refresh(environment):
                try:
                    refresh_token(environment, variables)
                except Exception as exc:
                    raise ValueError(f'No se pudo actualizar el token: {exc}')
            token = secret_get(secret_name) if secret_name else None
            if not token:
                raise ValueError('Falta el secreto/variable de entorno de autenticación.')
            secrets_used.add(token)
            if kind == 'bearer':
                headers['Authorization'] = f'Bearer {token}'
            else:
                headers[auth.get('header', 'X-API-Key')] = token
        elif kind != 'none':
            raise ValueError('Autenticación no soportada en esta versión.')
        with httpx.Client(timeout=case.get('timeout', 20), follow_redirects=False, trust_env=False) as client:
            response = client.request(case['method'], url, headers=headers, json=body if body is not None else None, params=query)
            if response.status_code == 401 and kind in ('bearer', 'api_key') and auto_refresh:
                try:
                    refresh_token(environment, variables)
                    retried_token = secret_get(secret_name)
                except Exception:
                    retried_token = None
                if retried_token:
                    secrets_used.add(retried_token)
                    headers[('Authorization' if kind == 'bearer' else auth.get('header', 'X-API-Key'))] = (
                        f'Bearer {retried_token}' if kind == 'bearer' else retried_token)
                    response = client.request(case['method'], url, headers=headers, json=body if body is not None else None, params=query)
        duration_ms = round(response.elapsed.total_seconds() * 1000, 2)
        assertions = check_assertions(response, case.get('assertions', []), duration_ms)
        extracted, extract_errors = run_extractions(response, case.get('extract'))
        ok = bool(assertions) and all(x['passed'] for x in assertions) and not extract_errors
        run.update({'status': 'passed' if ok else 'failed', 'http_status': response.status_code, 'duration_ms': duration_ms,
                    'assertions': assertions, 'extracted': extracted,
                    'request': {'method': case['method'], 'url': url, 'headers': redact_headers(headers), 'query': query,
                                'body': _bounded(body)},
                    'enriched': enriched,
                    'response': {'headers': redact_headers(dict(response.headers)), 'body': response.text[:50000]}})
        if extract_errors:
            run['error'] = '; '.join(extract_errors)[:500]
    except Exception as exc:
        run.update({'status': 'error', 'error': str(exc)[:500], 'error_type': type(exc).__name__,
                    'network_error': isinstance(exc, httpx.TransportError)})   # language-independent: OS messages are localized
    run = scrub(run, secrets_used)
    run['finished_at'] = now()
    from . import logs
    logs.event('run.finished', run_id=run['id'], case=run['case_name'], status=run['status'], type='api', persisted=persist)
    return save('runs', run) if persist else run


# --------------------------------------------------------------------------- evidence

def evidence_path(run_id, filename):
    """Resolves an evidence file only if it lives inside the evidence directory."""
    if not UUID_RE.fullmatch(run_id or ''):
        raise ValueError('Identificador de ejecución inválido')
    base = ARTIFACTS.resolve()
    target = (base / Path(filename).name).resolve()
    if base not in target.parents or not target.name.startswith(run_id):
        raise ValueError('Ruta de evidencia no permitida')
    if not target.is_file():
        raise FileNotFoundError('La evidencia ya no existe (puede haber sido purgada)')
    return target


def purge_evidence(max_age_days=30, max_runs=1000):
    """Retention: removes old runs and their files. Returns counts."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=max_age_days)
    runs = sorted(list_items('runs'), key=lambda r: r.get('started_at', ''))
    keep_from = max(0, len(runs) - max_runs)
    removed_runs = removed_files = 0
    for index, run in enumerate(runs):
        try:
            old = dt.datetime.fromisoformat(run.get('started_at', now())) < cutoff
        except ValueError:
            old = False
        if old or index < keep_from:
            for name in (run.get('screenshot'), run.get('trace')):
                if name:
                    path = ARTIFACTS / Path(name).name
                    if path.is_file():
                        path.unlink(); removed_files += 1
            delete('runs', run['id']); removed_runs += 1
    return {'runs': removed_runs, 'files': removed_files}


# --------------------------------------------------------------------------- portability

MAX_ENTRY_BYTES = 10_000_000
MAX_TOTAL_BYTES = 100_000_000
MAX_ENTRIES = 5000
REFERENCE_FIELDS = {'project_id': 'projects', 'module_id': 'modules', 'environment_id': 'environments',
                    'case_id': 'cases', 'suite_id': 'suites', 'feature_id': 'features'}


def _sanitize_for_export(table, obj):
    obj = copy.deepcopy(obj)
    if table == 'environments':
        obj.pop('secrets', None)
        obj['variables'] = {k: v for k, v in obj.get('variables', {}).items() if not SENSITIVE_NAME.search(k)}
    elif table == 'schedules':
        obj['enabled'] = False
    elif table == 'cases':
        obj['headers'] = {k: v for k, v in (obj.get('headers') or {}).items() if k.lower() not in SENSITIVE_HEADERS}
    elif table == 'runs':
        for key in ('request', 'response', 'screenshot', 'trace'):
            obj.pop(key, None)
    elif table == 'modules':
        obj.pop('source_spec', None)
    return obj


def _closure(project_id=None, case_ids=None, suite_ids=None):
    """Selects records for a project / case / suite export including their dependencies."""
    selected = {t: {} for t in TABLES}

    def add(table, item):
        if item:
            selected[table][item['id']] = item

    if case_ids or suite_ids:
        case_ids = list(case_ids or [])
        for suite_id in suite_ids or []:
            suite = get('suites', suite_id)
            if suite is None:
                raise ValueError('Suite inexistente')
            add('suites', suite)
            add('environments', get('environments', suite.get('environment_id')))
            for step in suite.get('steps') or []:
                if step.get('environment_id'):
                    add('environments', get('environments', step['environment_id']))
            case_ids += list(suite.get('case_ids', []))
        for case_id in case_ids:
            case = get('cases', case_id)
            if case is None:
                raise ValueError('Caso inexistente')
            add('cases', case)
            add('modules', get('modules', case['module_id']) if case.get('module_id') else None)
        for table in ('suites', 'cases', 'environments', 'modules'):
            for item in list(selected[table].values()):
                if item.get('project_id'):
                    add('projects', get('projects', item['project_id']))
    elif project_id:
        add('projects', get('projects', project_id))
        for table in TABLES[1:]:
            for item in list_project_items(table, project_id):
                add(table, item)
    else:
        for table in TABLES:
            for item in list_items(table):
                add(table, item)
    return selected


def export_workspace(destination, include_runs=False, project_id=None, case_ids=None, suite_ids=None):
    """Whole workspace, one project, or selected cases/suites (with dependencies)."""
    destination = Path(destination)
    selected = _closure(project_id, case_ids, suite_ids)
    scope = 'selection' if (case_ids or suite_ids) else 'project' if project_id else 'workspace'
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json', json.dumps({'format': 'local-test-workspace', 'schema_version': 1, 'created_at': now(), 'scope': scope}, indent=2))
        for table in TABLES:
            for obj in selected[table].values():
                z.writestr(f'{table}/{obj["id"]}.json', json.dumps(_sanitize_for_export(table, obj), ensure_ascii=False))
        if include_runs and scope == 'workspace':
            for obj in list_items('runs'):
                z.writestr(f'runs/{obj["id"]}.json', json.dumps(_sanitize_for_export('runs', obj), ensure_ascii=False))
    return destination


def _safe_entry_name(name):
    return not (name.startswith('/') or '\\' in name or '..' in name.split('/') or ':' in name or '\x00' in name)


def read_package(source):
    """Validates a ZIP without touching the database. Returns {'manifest', 'records': [(table, obj)]}."""
    try:
        archive = zipfile.ZipFile(source)
    except zipfile.BadZipFile:
        raise ValueError('El archivo no es un ZIP válido.')
    with archive as z:
        entries = z.infolist()
        if len(entries) > MAX_ENTRIES or sum(e.file_size for e in entries) > MAX_TOTAL_BYTES:
            raise ValueError('Paquete demasiado grande.')
        names = [e.filename for e in entries]
        if len(set(names)) != len(names):
            raise ValueError('Paquete con entradas duplicadas.')
        if 'manifest.json' not in names:
            raise ValueError('Falta manifest.json.')
        records, manifest = [], None
        for e in entries:
            if not _safe_entry_name(e.filename) or e.is_dir():
                raise ValueError('Entrada ZIP inválida.')
            if (e.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Entrada ZIP inválida (enlace simbólico).')
            if e.file_size > MAX_ENTRY_BYTES or (e.compress_size and e.file_size / e.compress_size > 200 and e.file_size > 100_000):
                raise ValueError('Entrada ZIP sospechosa (tamaño/ratio).')
            raw = z.open(e).read(MAX_ENTRY_BYTES + 1)
            if len(raw) > MAX_ENTRY_BYTES:
                raise ValueError('Entrada ZIP demasiado grande.')
            try:
                obj = json.loads(raw)
            except ValueError:
                raise ValueError(f'JSON inválido en {e.filename}.')
            if e.filename == 'manifest.json':
                manifest = obj
                continue
            parts = e.filename.split('/')
            if len(parts) != 2 or parts[0] not in TABLES or not parts[1].endswith('.json'):
                raise ValueError('Entrada ZIP inválida.')
            if not isinstance(obj, dict) or not isinstance(obj.get('id'), str) or not UUID_RE.fullmatch(obj['id']):
                raise ValueError(f'Registro inválido en {e.filename}.')
            if 'name' in obj and not isinstance(obj['name'], str):
                raise ValueError(f'Nombre inválido en {e.filename}.')
            if parts[1] != obj['id'] + '.json':
                raise ValueError(f'El nombre de {e.filename} no coincide con su id.')
            if 'case_ids' in obj and (not isinstance(obj['case_ids'], list) or not all(isinstance(x, str) for x in obj['case_ids'])):
                raise ValueError(f'case_ids inválido en {e.filename}.')
            records.append((parts[0], obj))
    if not isinstance(manifest, dict) or manifest.get('format') != 'local-test-workspace' or manifest.get('schema_version') != 1:
        raise ValueError('Formato o versión incompatible.')
    return {'manifest': manifest, 'records': records}


def preview_import(source, strategy='merge'):
    """What an import would do, without changing anything."""
    if strategy not in ('merge', 'replace', 'new'):
        raise ValueError('Estrategia inválida')
    package = read_package(source)
    summary = {t: {'total': 0, 'new': 0, 'existing': 0} for t in TABLES}
    items, warnings = [], []
    ids = {obj['id'] for _, obj in package['records']}
    for table, obj in package['records']:
        exists = strategy != 'new' and get(table, obj['id']) is not None
        summary[table]['total'] += 1
        summary[table]['existing' if exists else 'new'] += 1
        label = obj.get('name') or obj['id'][:8]
        items.append({'table': table, 'name': label, 'action': ('omitir' if strategy == 'merge' else 'reemplazar') if exists else 'crear'})
        for field, ref_table in REFERENCE_FIELDS.items():
            ref = obj.get(field)
            if ref and ref not in ids and get(ref_table, ref) is None:
                warnings.append(f'{table}/{label}: la referencia {field} no existe; se vaciará')
        for case_id in obj.get('case_ids', []):
            if case_id not in ids and get('cases', case_id) is None:
                warnings.append(f'suite {label}: el caso {case_id[:8]} no existe y se omitirá')
        for env_id in obj.get('environment_ids', []):
            if env_id not in ids and get('environments', env_id) is None:
                warnings.append(f'{table}/{label}: un ambiente ligado ya no existe y se quitará')
        for group_id in obj.get('module_group_ids', []):
            if group_id not in ids and get('module_groups', group_id) is None:
                warnings.append(f'{table}/{label}: un módulo ligado ya no existe y se quitará')
        if table == 'schedules':
            warnings.append(f'programación {label}: se importará desactivada')
    return {'scope': package['manifest'].get('scope', 'workspace'), 'summary': summary, 'items': items, 'warnings': sorted(set(warnings))}


def import_workspace(source, strategy='merge'):
    """Validates everything first, then writes in a single transaction (all or nothing)."""
    if strategy not in ('merge', 'replace', 'new'):
        raise ValueError('Estrategia inválida')
    package = read_package(source)
    data = package['records']
    imported = {t: 0 for t in TABLES}
    ids = {obj['id'] for _, obj in data}
    id_map = {obj['id']: uid() for _, obj in data} if strategy == 'new' else {}
    prepared = []
    for table, obj in data:
        obj = copy.deepcopy(obj)
        if strategy == 'new':
            obj['id'] = id_map[obj['id']]
        for field, ref_table in REFERENCE_FIELDS.items():
            ref = obj.get(field)
            if not ref:
                continue
            if ref in id_map:
                obj[field] = id_map[ref]
            elif ref not in ids and get(ref_table, ref) is None:
                obj[field] = None
        if 'case_ids' in obj:
            obj['case_ids'] = [id_map.get(x, x) for x in obj['case_ids'] if x in ids or get('cases', x) is not None]
        if table == 'modules' and obj.get('environment_ids'):
            obj['environment_ids'] = [id_map.get(e, e) for e in obj['environment_ids'] if e in ids or e in id_map or get('environments', e)]
        if table == 'modules' and obj.get('module_group_ids'):
            obj['module_group_ids'] = [id_map.get(g, g) for g in obj['module_group_ids'] if g in ids or g in id_map or get('module_groups', g)]
        if table == 'suites' and obj.get('steps'):    # flow steps (UI cases also have a 'steps' key: their browser steps): remap case / environment ids, drop steps whose case is gone
            kept = set(obj['case_ids'])
            steps = []
            for step in obj['steps']:
                step['case_id'] = id_map.get(step.get('case_id'), step.get('case_id'))
                env = step.get('environment_id')
                if env:
                    step['environment_id'] = id_map.get(env, env) if (env in ids or env in id_map or get('environments', env)) else None
                if step['case_id'] in kept:
                    steps.append(step)
            obj['steps'] = steps
        if table == 'schedules':
            obj['enabled'] = False
        prepared.append((table, obj))
    with transaction() as con:
        for table, obj in prepared:
            exists = con.execute(f'SELECT 1 FROM {table} WHERE id=?', (obj['id'],)).fetchone()
            if exists and strategy == 'merge':
                continue
            save_in(con, table, obj)
            imported[table] += 1
    from . import logs
    logs.event('workspace.imported', strategy=strategy, counts=imported)
    return imported
