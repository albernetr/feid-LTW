"""Local suite runner, Playwright UI cases and persistent schedule dispatch."""
import datetime as dt
import json
import os
import threading
import time
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from . import core, logs

LOCATOR_KINDS = ('label', 'text', 'role', 'testid', 'placeholder')
STEP_ACTIONS = {
    'navigate': {'label': 'Ir a URL', 'needs': ['url']},
    'click': {'label': 'Clic', 'needs': ['locator']},
    'fill': {'label': 'Escribir texto', 'needs': ['locator', 'value']},
    'press': {'label': 'Presionar tecla', 'needs': ['locator', 'value']},
    'check': {'label': 'Marcar casilla', 'needs': ['locator']},
    'uncheck': {'label': 'Desmarcar casilla', 'needs': ['locator']},
    'select_option': {'label': 'Elegir opción', 'needs': ['locator', 'value']},
    'wait_visible': {'label': 'Esperar visible', 'needs': ['locator']},
    'assert_visible': {'label': 'Verificar visible', 'needs': ['locator']},
    'assert_not_visible': {'label': 'Verificar oculto', 'needs': ['locator']},
    'assert_text': {'label': 'Verificar texto', 'needs': ['locator', 'expected']},
    'assert_value': {'label': 'Verificar valor', 'needs': ['locator', 'expected']},
    'assert_url': {'label': 'Verificar URL contiene', 'needs': ['expected']},
}


def validate_steps(steps):
    """Returns a list of human-readable problems (empty when the steps are valid)."""
    problems = []
    if not isinstance(steps, list) or not steps:
        return ['El caso necesita al menos un paso']
    for index, step in enumerate(steps, 1):
        if not isinstance(step, dict) or step.get('action') not in STEP_ACTIONS:
            problems.append(f'Paso {index}: acción no soportada «{step.get("action") if isinstance(step, dict) else step}»')
            continue
        for need in STEP_ACTIONS[step['action']]['needs']:
            if need == 'locator':
                spec = step.get('locator')
                if not isinstance(spec, dict) or spec.get('by') not in LOCATOR_KINDS:
                    problems.append(f'Paso {index}: locator inválido')
                elif spec['by'] == 'role' and not spec.get('role'):
                    problems.append(f'Paso {index}: el locator de rol requiere el rol')
                elif spec['by'] != 'role' and not spec.get('value'):
                    problems.append(f'Paso {index}: el locator requiere un valor')
            elif step.get(need) in (None, ''):
                problems.append(f'Paso {index}: falta «{need}»')
    return problems


def build_locator(page, spec):
    locator = _base_locator(page, spec)
    if spec.get('first'):
        return locator.first
    if spec.get('nth') is not None:
        return locator.nth(int(spec['nth']))
    return locator


def _base_locator(page, spec):
    kind = spec.get('by')
    value = spec.get('value', '')
    exact = bool(spec.get('exact', False))  # Playwright default: case-insensitive substring match
    if kind == 'label':
        return page.get_by_label(value, exact=exact)
    if kind == 'text':
        return page.get_by_text(value, exact=exact)
    if kind == 'role':
        return page.get_by_role(spec['role'], name=spec.get('name') or None)
    if kind == 'testid':
        return page.get_by_test_id(value)
    if kind == 'placeholder':
        return page.get_by_placeholder(value, exact=exact)
    raise ValueError('Locator no soportado: ' + str(kind))


def _resolve_url(base, target, allowed_host):
    if urlparse(target).scheme:
        url = target
    else:
        url = urljoin(base.rstrip('/') + '/', target.lstrip('/'))
    if urlparse(url).hostname != allowed_host:
        raise ValueError('Navegación fuera del host autorizado.')
    return url


def _use_system_browsers():
    """Frozen (PyInstaller) builds look for Chromium inside the bundle; use the standard Playwright cache instead."""
    import sys
    if not getattr(sys, 'frozen', False) or os.environ.get('PLAYWRIGHT_BROWSERS_PATH'):
        return
    if sys.platform == 'win32':
        cache = os.path.join(os.environ.get('LOCALAPPDATA') or os.path.join(os.path.expanduser('~'), 'AppData', 'Local'), 'ms-playwright')
    elif sys.platform == 'darwin':
        cache = os.path.expanduser('~/Library/Caches/ms-playwright')
    else:
        cache = os.path.expanduser('~/.cache/ms-playwright')
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = cache


def execute_ui(case, environment, variables=None):
    """Execute declarative UI steps; browser is isolated per case. Keeps screenshot (always) and trace (on failure)."""
    variables = {**environment.get('variables', {}), **(variables or {})}
    secrets_used = set()
    run = {'id': core.uid(), 'case_id': case['id'], 'case_name': case.get('name', ''), 'type': 'ui',
           'project_id': case.get('project_id'), 'case_snapshot': case, 'environment_id': environment['id'],
           'started_at': core.now(), 'steps': []}
    browser = None
    try:
        steps = core.substitute(case.get('steps', []), variables, secrets_used)
        missing = core.find_unresolved(steps)
        if missing:
            raise ValueError('Variables sin resolver: ' + ', '.join(missing))
        problems = validate_steps(steps)
        if problems:
            raise ValueError('; '.join(problems))
        base = environment.get('ui_base_url') or environment.get('base_url', '')
        allowed_host = urlparse(base).hostname
        if not allowed_host:
            raise ValueError('Configura la URL base del ambiente.')
        _use_system_browsers()
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(accept_downloads=False)
            context.tracing.start(screenshots=True, snapshots=True)
            page = context.new_page()
            page.set_default_timeout(int(case.get('timeout_ms', 10000)))

            def guard(route):  # navigations/redirects to other hosts are blocked at network level
                if route.request.is_navigation_request() and urlparse(route.request.url).hostname != allowed_host:
                    route.abort()
                else:
                    route.continue_()
            page.route('**/*', guard)
            try:
                for index, step in enumerate(steps):
                    action = step['action']
                    outcome = {'index': index, 'action': action}
                    run['steps'].append(outcome)
                    if action == 'navigate':
                        page.goto(_resolve_url(base, step['url'], allowed_host), wait_until='domcontentloaded')
                    elif action == 'assert_url':
                        if step['expected'] not in page.url:
                            raise AssertionError(f'URL actual «{page.url}» no contiene «{step["expected"]}»')
                    else:
                        loc = build_locator(page, step['locator'])
                        if action == 'click': loc.click()
                        elif action == 'fill': loc.fill(str(step['value']))
                        elif action == 'press': loc.press(str(step['value']))
                        elif action == 'check': loc.check()
                        elif action == 'uncheck': loc.uncheck()
                        elif action == 'select_option': loc.select_option(str(step['value']))
                        elif action in ('wait_visible', 'assert_visible'): loc.wait_for(state='visible')
                        elif action == 'assert_not_visible': loc.wait_for(state='hidden')
                        elif action == 'assert_text':
                            deadline = time.monotonic() + int(case.get('timeout_ms', 10000)) / 1000
                            text = loc.inner_text()
                            while step['expected'] not in text and time.monotonic() < deadline:
                                time.sleep(0.1)
                                text = loc.inner_text()
                            if step['expected'] not in text:
                                raise AssertionError(f'Texto esperado «{step["expected"]}» no encontrado en «{text[:80]}»')
                        elif action == 'assert_value':
                            expected = str(step['expected'])
                            deadline = time.monotonic() + int(case.get('timeout_ms', 10000)) / 1000
                            value = loc.input_value()
                            while value != expected and time.monotonic() < deadline:
                                time.sleep(0.1)
                                value = loc.input_value()
                            if value != expected:
                                raise AssertionError('Valor distinto del esperado')
                    outcome['passed'] = True
                run['status'] = 'passed'
            except Exception as exc:
                if run['steps']:
                    run['steps'][-1]['passed'] = False
                run['status'] = 'failed'
                run['error'] = f'{type(exc).__name__}: {str(exc)}'[:700]
            shot = core.ARTIFACTS / (run['id'] + '.png')
            try:
                page.screenshot(path=str(shot), full_page=True)
                run['screenshot'] = shot.name
            except Exception:
                pass
            if run['status'] != 'passed':
                trace = core.ARTIFACTS / (run['id'] + '-trace.zip')
                try:
                    context.tracing.stop(path=str(trace))
                    run['trace'] = trace.name
                except Exception:
                    pass
            else:
                context.tracing.stop()
            context.close()
            browser.close()
            browser = None
    except Exception as exc:
        run['status'] = 'failed'
        run['error'] = f'{type(exc).__name__}: {str(exc)}'[:700]
        if browser:
            try: browser.close()
            except Exception: pass
    run = core.scrub(run, secrets_used)
    run['finished_at'] = core.now()
    logs.event('run.finished', run_id=run['id'], case=run['case_name'], status=run['status'], type='ui')
    return core.save('runs', run)


# --------------------------------------------------------------------------- suites

def new_cancel_token():
    return threading.Event()


def _run_case(case, environment, variables, context=None, enrich=None, meta=None):
    if case.get('type') == 'ui':
        return execute_ui(case, environment, variables)
    return core.execute_api(case, environment, variables, context=context, enrich=enrich, meta=meta)


def _response_context(result):
    """What later steps may reference: status, headers and the JSON (or text) body of this step's response."""
    response = result.get('response')
    if response is None:
        return None
    try:
        body = json.loads(response.get('body', ''))
    except ValueError:
        body = response.get('body', '')
    return {'http_status': result.get('http_status'), 'headers': response.get('headers', {}), 'body': body}


def execute_suite(suite, cancel=None, on_progress=None):
    """Runs cases in order with shared variables, retries, failure policy and cooperative cancel."""
    environment = core.get('environments', suite['environment_id'])
    if environment is None:
        raise ValueError('Ambiente inexistente')
    on_failure = suite.get('on_failure', 'continue')
    retries = int(suite.get('retries', 0))
    delay = float(suite.get('retry_delay_s', 0))
    shared = dict(suite.get('variables') or {})
    summary = {'id': core.uid(), 'type': 'suite', 'suite_id': suite['id'], 'suite_name': suite.get('name', ''),
               'project_id': suite.get('project_id'), 'started_at': core.now(), 'case_runs': [],
               'policy': {'on_failure': on_failure, 'retries': retries}}
    halt = None  # None | 'stopped' | 'cancelled'
    context = {}  # alias -> response of that step; lets a later step (maybe in another module) use it
    for step in core.suite_steps(suite):
        case_id, alias = step['case_id'], step['alias']
        if halt is None and cancel is not None and cancel.is_set():
            halt = 'cancelled'
        if halt:
            summary['case_runs'].append({'case_id': case_id, 'status': 'cancelled' if halt == 'cancelled' else 'skipped'})
            continue
        case = core.get('cases', case_id)
        step_env = core.get('environments', step['environment_id']) if step.get('environment_id') else environment
        if case is None or step_env is None:
            reason = 'Caso inexistente' if case is None else 'Ambiente del paso inexistente'
            summary['case_runs'].append({'case_id': case_id, 'alias': alias, 'status': 'error', 'error': reason})
            if on_failure == 'stop':
                halt = 'stopped'
            continue
        attempts = 0
        while True:
            attempts += 1
            result = _run_case(case, step_env, shared, context, step.get('enrich'),
                               {'suite_id': suite['id'], 'suite_name': suite.get('name', ''), 'alias': alias, 'step_index': len(summary['case_runs']) + 1})
            if result['status'] == 'passed' or attempts > int(case.get('retries', retries)):
                break
            if cancel is not None:
                if cancel.wait(delay):
                    break
            elif delay:
                time.sleep(delay)
        if result['status'] == 'passed':
            shared.update(result.get('extracted') or {})
        captured = _response_context(result)
        if captured is not None:
            context[alias] = captured
        entry = {'case_id': case_id, 'alias': alias, 'case_name': case.get('name', ''), 'run_id': result['id'], 'status': result['status'],
                 'attempts': attempts, 'environment': step_env.get('name', '')}
        if result.get('error'):
            entry['error'] = result['error']
        summary['case_runs'].append(entry)
        if on_progress:
            on_progress(entry)
        if result['status'] != 'passed' and on_failure == 'stop':
            halt = 'stopped'
    statuses = [r['status'] for r in summary['case_runs']]
    if 'cancelled' in statuses:
        summary['status'] = 'cancelled'
    else:
        summary['status'] = 'passed' if statuses and all(s == 'passed' for s in statuses) else 'failed'
    summary['finished_at'] = core.now()
    logs.event('suite.finished', suite=summary['suite_name'], status=summary['status'], cases=len(statuses))
    return core.save('runs', summary)


# --------------------------------------------------------------------------- schedules

FREQUENCIES = {'daily': 'Diario', 'weekdays': 'Lunes a viernes', 'weekly': 'Semanal', 'once': 'Una sola vez', 'interval': 'Cada N minutos'}
MISSED_POLICIES = {'run_once': 'Ejecutar una vez al reiniciar', 'skip': 'Omitir ejecuciones perdidas'}


def _zone(name):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        raise ValueError(f'Zona horaria inválida: {name}')


def next_due(schedule, from_time=None):
    """Next UTC instant for the schedule; wall time evaluated in its IANA timezone."""
    zone = _zone(schedule['timezone'])
    now_utc = from_time or dt.datetime.now(dt.timezone.utc)
    current = now_utc.astimezone(zone)
    frequency = schedule['frequency']
    if frequency not in FREQUENCIES:
        raise ValueError('Frecuencia inválida')
    if frequency == 'interval':
        minutes = int(schedule.get('interval_minutes') or 0)
        if not 1 <= minutes <= 10080:
            raise ValueError('El intervalo debe estar entre 1 y 10080 minutos')
        return (now_utc + dt.timedelta(minutes=minutes)).astimezone(dt.timezone.utc).isoformat()
    if frequency == 'once':
        try:
            moment = dt.datetime.fromisoformat(schedule['run_at']).replace(tzinfo=zone)
        except (KeyError, ValueError, TypeError):
            raise ValueError('Fecha y hora de ejecución inválidas (use AAAA-MM-DDTHH:MM)')
        if moment <= current:
            raise ValueError('La fecha de la ejecución única ya pasó')
        return moment.astimezone(dt.timezone.utc).isoformat()
    try:
        hour, minute = map(int, schedule['time'].split(':'))
    except (KeyError, ValueError, AttributeError):
        raise ValueError('Hora inválida (HH:MM)')
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError('Hora inválida')
    if frequency == 'weekly' and not 0 <= int(schedule.get('weekday', 0)) <= 6:
        raise ValueError('Día de semana inválido')
    for offset in range(0, 9):
        day = current.date() + dt.timedelta(days=offset)
        if frequency == 'weekdays' and day.weekday() >= 5:
            continue
        if frequency == 'weekly' and day.weekday() != int(schedule['weekday']):
            continue
        candidate = dt.datetime.combine(day, dt.time(hour, minute), zone)
        if candidate > current:
            return candidate.astimezone(dt.timezone.utc).isoformat()
    raise ValueError('No se pudo calcular próxima ejecución')


def create_schedule(suite_id, frequency, at='00:00', timezone='UTC', weekday=0, *, run_at=None,
                    interval_minutes=None, missed_policy='run_once'):
    suite = core.get('suites', suite_id)
    if suite is None:
        raise ValueError('Suite inexistente')
    if missed_policy not in MISSED_POLICIES:
        raise ValueError('Política de ejecuciones perdidas inválida')
    item = {'suite_id': suite_id, 'project_id': suite.get('project_id'), 'frequency': frequency, 'time': at,
            'timezone': timezone, 'weekday': weekday, 'enabled': True, 'missed_policy': missed_policy}
    if run_at:
        item['run_at'] = run_at
    if interval_minutes:
        item['interval_minutes'] = int(interval_minutes)
    item['next_run_at'] = next_due(item)
    return core.save('schedules', item)


def describe_schedule(item):
    frequency = item.get('frequency')
    if frequency == 'interval':
        return f'Cada {item.get("interval_minutes")} min'
    if frequency == 'once':
        return f'Una vez: {item.get("run_at")} ({item.get("timezone")})'
    return f'{FREQUENCIES.get(frequency, frequency)} {item.get("time")} ({item.get("timezone")})'


def dispatch_due(now_utc=None, grace_seconds=120):
    """Call from ONE local scheduler process. Missed runs follow the schedule's policy."""
    current = now_utc or dt.datetime.now(dt.timezone.utc)
    completed = []
    for schedule in core.list_items('schedules'):
        if not schedule.get('enabled') or not schedule.get('next_run_at'):
            continue
        due = dt.datetime.fromisoformat(schedule['next_run_at'])
        if due > current:
            continue
        missed = (current - due).total_seconds() > grace_seconds
        should_run = not (missed and schedule.get('missed_policy', 'run_once') == 'skip')
        # Advance before running so an execution error won't cause endless replays.
        if schedule['frequency'] == 'once':
            schedule['enabled'] = False
        else:
            schedule['next_run_at'] = next_due(schedule, current)
        schedule['last_trigger_at'] = core.now()
        if missed:
            schedule['last_missed_at'] = core.now()
        schedule['last_outcome'] = 'ejecutada' if should_run else 'omitida (perdida)'
        core.save('schedules', schedule)
        logs.event('schedule.triggered', schedule=schedule['id'], missed=missed, ran=should_run)
        suite = core.get('suites', schedule['suite_id'])
        if suite and should_run:
            try:
                completed.append(execute_suite(suite))
            except Exception as exc:
                logs.event('schedule.error', schedule=schedule['id'], error=str(exc))
    return completed


class SchedulerLockError(RuntimeError):
    pass


class SchedulerLock:
    """Single scheduler per workspace: lock file with heartbeat so stale locks self-heal."""
    STALE_AFTER = 120

    def __init__(self):
        self.path = core.ROOT / 'scheduler.lock'
        self.held = False

    def _payload(self):
        return json.dumps({'pid': os.getpid(), 'heartbeat': time.time()})

    def acquire(self):
        core.ROOT.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                try:
                    os.write(fd, self._payload().encode())
                finally:
                    os.close(fd)
                self.held = True
                return self
            except FileExistsError:
                try:
                    age = time.time() - float(json.loads(self.path.read_text()).get('heartbeat', 0))
                except (ValueError, OSError):
                    age = self.STALE_AFTER + 1
                if age <= self.STALE_AFTER:
                    raise SchedulerLockError('Ya hay otro scheduler activo para este workspace.')
                try:
                    self.path.unlink()
                except OSError:
                    raise SchedulerLockError('No se pudo recuperar un bloqueo antiguo.')
        raise SchedulerLockError('No se pudo adquirir el bloqueo del scheduler.')

    def heartbeat(self):
        if self.held:
            self.path.write_text(self._payload())

    def release(self):
        if self.held:
            try:
                self.path.unlink()
            except OSError:
                pass
            self.held = False


def scheduler_active():
    """True when a live scheduler holds the lock (used by the UI)."""
    path = core.ROOT / 'scheduler.lock'
    try:
        return time.time() - float(json.loads(path.read_text()).get('heartbeat', 0)) <= SchedulerLock.STALE_AFTER
    except (ValueError, OSError):
        return False


def serve_scheduler(interval=30, should_stop=None):
    core.initialize()
    lock = SchedulerLock().acquire()
    logs.event('scheduler.started', pid=os.getpid())
    try:
        while not (should_stop and should_stop()):
            lock.heartbeat()
            dispatch_due(grace_seconds=max(120, interval * 2))
            time.sleep(interval)
    finally:
        lock.release()
        logs.event('scheduler.stopped')
