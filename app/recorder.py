"""Hybrid recorder: launches Playwright codegen and imports its Python output through the AST.

The generated script is NEVER executed: it is parsed with ast and only a whitelisted
subset of calls is translated into declarative steps. Everything else is reported.
"""
import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse
import httpx
from . import core

DEFAULT_LIVE_PORT = 9222

LOCATORS = {'get_by_label': 'label', 'get_by_text': 'text', 'get_by_test_id': 'testid',
            'get_by_placeholder': 'placeholder', 'get_by_role': 'role'}
ACTIONS = {'click': 'click', 'fill': 'fill', 'press': 'press', 'check': 'check', 'uncheck': 'uncheck',
           'select_option': 'select_option', 'dblclick': None, 'hover': None}
EXPECTS = {'to_be_visible': 'assert_visible', 'to_contain_text': 'assert_text', 'to_have_text': 'assert_text',
           'to_have_value': 'assert_value', 'to_be_hidden': 'assert_not_visible'}


def _literal(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return _MISSING


_MISSING = object()


def _locator(node):
    """page.get_by_xxx(...) [.first | .nth(n)] -> locator spec, or None."""
    if isinstance(node, ast.Attribute) and node.attr == 'first':
        spec = _locator(node.value)
        return dict(spec, first=True) if spec and 'nth' not in spec else None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'nth' and len(node.args) == 1:
        index = _literal(node.args[0])
        spec = _locator(node.func.value)
        return dict(spec, nth=index) if spec and isinstance(index, int) and not isinstance(index, bool) and 'first' not in spec else None
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return None
    kind = LOCATORS.get(node.func.attr)
    if kind is None or not isinstance(node.func.value, ast.Name) or node.func.value.id != 'page':
        return None
    if not node.args:
        return None
    value = _literal(node.args[0])
    if not isinstance(value, str):
        return None
    spec = {'by': kind}
    if kind == 'role':
        spec['role'] = value
        for keyword in node.keywords:
            if keyword.arg == 'name':
                name = _literal(keyword.value)
                if not isinstance(name, str):
                    return None
                spec['name'] = name
            elif keyword.arg == 'exact':
                if _literal(keyword.value) is True:
                    spec['exact'] = True
            else:
                return None
    else:
        spec['value'] = value
        for keyword in node.keywords:
            if keyword.arg != 'exact':
                return None
            if _literal(keyword.value) is True:
                spec['exact'] = True
    return spec


def import_codegen(script):
    """Returns {'steps': [...], 'unsupported': [{'line', 'code', 'reason'}]}."""
    try:
        tree = ast.parse(script)
    except SyntaxError as exc:
        raise ValueError(f'El script no es Python válido: {exc.msg} (línea {exc.lineno})')
    steps, unsupported = [], []
    lines = script.splitlines()

    def report(node, reason):
        line = getattr(node, 'lineno', 0)
        unsupported.append({'line': line, 'code': lines[line - 1].strip() if 0 < line <= len(lines) else '', 'reason': reason})

    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        func = call.func
        if not isinstance(func, ast.Attribute):
            # expect(...).to_x() is also an Attribute; bare calls (print, etc.) are ignored
            continue
        # page.goto("url")
        if isinstance(func.value, ast.Name) and func.value.id == 'page':
            if func.attr == 'goto':
                url = _literal(call.args[0]) if call.args else _MISSING
                if not isinstance(url, str) or urlparse(url).scheme not in ('http', 'https', ''):
                    report(node, 'URL no literal o con esquema no permitido')
                else:
                    steps.append({'action': 'navigate', 'url': url, '_line': node.lineno})
            elif func.attr in ('wait_for_timeout', 'wait_for_load_state', 'set_default_timeout', 'close', 'pause'):
                pass
            elif func.attr in LOCATORS:
                pass
            else:
                report(node, f'page.{func.attr}() no está soportado')
            continue
        # expect(page.get_by_xxx(...)).to_be_visible()
        if func.attr in EXPECTS and isinstance(func.value, ast.Call) and isinstance(func.value.func, ast.Name) and func.value.func.id == 'expect':
            target = func.value.args[0] if func.value.args else None
            spec = _locator(target) if target is not None else None
            if spec is None:
                report(node, 'expect() sobre un locator no soportado')
                continue
            step = {'action': EXPECTS[func.attr], 'locator': spec, '_line': node.lineno}
            if EXPECTS[func.attr] in ('assert_text', 'assert_value'):
                expected = _literal(call.args[0]) if call.args else _MISSING
                if not isinstance(expected, str):
                    report(node, 'texto esperado no literal (regex u otro)')
                    continue
                step['expected'] = expected
            steps.append(step)
            continue
        # page.get_by_xxx(...).click() / .fill("v")
        if func.attr in ACTIONS:
            action = ACTIONS[func.attr]
            if action is None:
                report(node, f'{func.attr}() no está soportado')
                continue
            spec = _locator(func.value)
            if spec is None:
                report(node, 'locator no soportado (solo label/text/role/testid/placeholder directos)')
                continue
            step = {'action': action, 'locator': spec, '_line': node.lineno}
            if action in ('fill', 'press', 'select_option'):
                value = _literal(call.args[0]) if call.args else _MISSING
                if not isinstance(value, str):
                    report(node, 'valor no literal')
                    continue
                step['value'] = value
            steps.append(step)
            continue
        housekeeping = isinstance(func.value, ast.Name) and func.value.id in ('browser', 'context', 'playwright') and func.attr in ('close', 'launch')
        if not housekeeping:
            report(node, f'llamada {func.attr}() no reconocida; se ignora y no se ejecuta')
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, 'module', None) or ', '.join(a.name for a in node.names)
            if not module.split('.')[0] in ('playwright', 're'):
                report(node, f'import «{module}» no permitido; no se ejecuta código importado')
    steps.sort(key=lambda s: s['_line'])
    for step in steps:
        step.pop('_line')
    unsupported.sort(key=lambda u: u['line'])
    return {'steps': steps, 'unsupported': unsupported}


def _playwright_command():
    """['python','-m','playwright'] normally; the bundled Node driver when running as a frozen .exe."""
    if getattr(sys, 'frozen', False):
        from playwright._impl._driver import compute_driver_executable
        driver = compute_driver_executable()
        return [str(part) for part in (driver if isinstance(driver, tuple) else (driver,))]
    return [sys.executable, '-m', 'playwright']


def _env():
    env = dict(os.environ)
    if getattr(sys, 'frozen', False):
        from playwright._impl._driver import get_driver_env
        env.update(get_driver_env())
        if 'PLAYWRIGHT_BROWSERS_PATH' not in os.environ:
            from .automation import _use_system_browsers
            _use_system_browsers()
            env['PLAYWRIGHT_BROWSERS_PATH'] = os.environ['PLAYWRIGHT_BROWSERS_PATH']
    return env


def _checked_url(url):
    parsed = urlparse((url or '').strip())
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('URL inválida (use http:// o https://)')
    return url.strip()


def _navigation_failure(result):
    """Playwright's CLI closes the window and exits as soon as the first navigation fails (wrong protocol, host
    down, TLS error…) instead of leaving it open with the error on screen - without this, that failure is
    completely silent to whoever clicked the button: the window just vanishes. Returns a short Spanish message,
    or None if nothing points to a navigation problem."""
    text = ((result.stderr or '') + (result.stdout or ''))
    match = re.search(r'^Error:\s*(.+)$', text, re.M)
    if match:
        return f'No se pudo navegar a esa dirección: {match.group(1)}. Revisa el protocolo (http/https) y que el servicio esté encendido.'
    if result.returncode != 0:
        return f'El navegador se cerró con un error (código {result.returncode}). Revisa la dirección y que el servicio esté encendido.'
    return None


def launch_codegen(url, timeout=900):
    """Opens Playwright codegen in a browser window and returns the generated script text."""
    url = _checked_url(url)
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / 'recording.py'
        result = subprocess.run(_playwright_command() + ['codegen', '--target', 'python', '-o', str(output), url],
                                check=False, timeout=timeout, env=_env(), capture_output=True, text=True)
        script = output.read_text(encoding='utf-8') if output.exists() else ''
        if not script:
            failure = _navigation_failure(result)
            if failure:
                raise ValueError(failure)
        return script


def capture_session(url, timeout=900):
    """Opens the same codegen window as launch_codegen, but to log in by hand instead of recording steps — even
    through an identity provider on another domain (SSO, MFA) that a Caso UI could never navigate to on its own
    (host bloqueado, ver automation.execute_ui). Playwright saves the resulting cookies/localStorage when the
    window closes; that's what a later Caso UI replays against to start already logged in (ver
    core.save_ui_session / Ambientes → «Sesión guardada»)."""
    url = _checked_url(url)
    with tempfile.TemporaryDirectory() as tmp:
        state_path = Path(tmp) / 'state.json'
        result = subprocess.run(_playwright_command() + ['codegen', '--target', 'python', '--save-storage', str(state_path), url],
                                check=False, timeout=timeout, env=_env(), capture_output=True, text=True)
        if not state_path.exists():
            failure = _navigation_failure(result)
            raise ValueError(failure or 'No se guardó ninguna sesión (¿cerraste la ventana sin llegar a iniciar sesión?).')
        try:
            state = json.loads(state_path.read_text(encoding='utf-8'))
        except ValueError:
            raise ValueError('El archivo de sesión que generó Playwright no es válido.')
        if not state.get('cookies') and not state.get('origins'):
            raise ValueError('La sesión capturada está vacía: inicia sesión en la ventana antes de cerrarla.')
        return state


def open_browser(url, timeout=900):
    """Just browse: a visible Chromium window with no recording and nothing saved."""
    url = _checked_url(url)
    result = subprocess.run(_playwright_command() + ['open', url], check=False, timeout=timeout, env=_env(), capture_output=True, text=True)
    failure = _navigation_failure(result)
    if failure:
        raise ValueError(failure)


# --------------------------------------------------------------------------- live browser (CDP) for SSO/MFA that
# ties a session to the actual browser/device, not just the cookie — replaying captured cookies into a fresh
# headless context (ver capture_session/core.save_ui_session) can get rejected by that kind of IdP even though
# the cookies are valid. This keeps a real, visible Chromium open (its own on-disk profile, so the login survives
# closing/reopening it) and Casos UI connect to it live instead of starting a new context — see
# automation.execute_ui.

def _chromium_executable():
    from .automation import _use_system_browsers
    _use_system_browsers()
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        return p.chromium.executable_path


def _live_profile_dir(environment_id):
    path = core.ROOT / 'ui_browser_profiles' / environment_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def live_browser_running(port, timeout=1.0):
    """True si hay un Chromium con depuración remota escuchando en ese puerto (endpoint CDP estándar)."""
    try:
        return httpx.get(f'http://127.0.0.1:{port}/json/version', timeout=timeout).status_code == 200
    except Exception:
        return False


def launch_live_browser(environment_id, url, port=DEFAULT_LIVE_PORT, timeout=20):
    """Abre un Chromium visible con un perfil propio de este ambiente (persiste en disco: la sesión sobrevive a
    cerrar y volver a abrir esta ventana) y depuración remota habilitada. A diferencia de capture_session (que
    exporta las cookies una sola vez), esta ventana se queda abierta — Casos UI posteriores se conectan a ella en
    vivo en lugar de repetir la sesión en un contexto nuevo."""
    if live_browser_running(port):
        raise ValueError(f'Ya hay un navegador en vivo abierto en el puerto {port} — cerralo primero si querés reiniciarlo.')
    url = _checked_url(url)
    executable = _chromium_executable()
    profile_dir = _live_profile_dir(environment_id)
    popen_kwargs = {'env': _env(), 'close_fds': True}
    if sys.platform == 'win32':
        popen_kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP | getattr(subprocess, 'DETACHED_PROCESS', 0)
    else:
        popen_kwargs['start_new_session'] = True
    subprocess.Popen([executable, f'--remote-debugging-port={port}', f'--user-data-dir={profile_dir}',
                       '--no-first-run', '--no-default-browser-check', url], **popen_kwargs)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if live_browser_running(port):
            return
        time.sleep(0.3)
    raise ValueError('El navegador no terminó de abrir a tiempo (¿el puerto ya estaba ocupado por otra cosa?).')


def close_live_browser(port):
    if not live_browser_running(port):
        return
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        p.chromium.connect_over_cdp(f'http://127.0.0.1:{port}').close()


def delete_live_profile(environment_id):
    """Borra el perfil en disco del navegador en vivo de este ambiente (si había uno) — p. ej. al eliminar el
    ambiente. No falla si el navegador sigue abierto (carpeta bloqueada): queda para limpiarse después."""
    import shutil
    shutil.rmtree(core.ROOT / 'ui_browser_profiles' / environment_id, ignore_errors=True)
