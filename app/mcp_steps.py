"""Traduce los pasos declarativos de un Caso UI (ver automation.STEP_ACTIONS) a llamadas al servidor Playwright
MCP (ver mcp_bridge.py/mcp_client.py), para el modo «Extensión de Chrome (MCP)» — equivalente al loop de
automation.execute_ui, pero hablando HTTP/JSON-RPC en vez de la API de Playwright.

La pieza que no tiene equivalente directo es resolver un locator: Playwright MCP no acepta un locator
estructurado como {by, value, role, name} — hay que buscarlo en el árbol de accesibilidad (browser_find /
browser_snapshot, que lo devuelven como texto con forma de YAML: `rol "nombre" [ref=eNN]`) y parsear esa línea.
Eso significa que no todos los locators de LTW resuelven igual de bien acá: `testid` no es soportado (el árbol
de accesibilidad no expone data-testid), y `label`/`placeholder` son mejor esfuerzo (funcionan si ese es el
único texto accesible del campo).
"""
import re
import time
from urllib.parse import urlparse
from . import mcp_client

_SNAPSHOT_LINE = re.compile(r'^\s*-?\s*(?P<role>[a-zA-Z][a-zA-Z_]*)(?:\s+"(?P<name>[^"]*)")?.*\[ref=(?P<ref>e\d+)\]')
_INTERACTIVE_ROLES = {'textbox', 'combobox', 'checkbox', 'radio', 'spinbutton', 'searchbox'}


def _candidates(session, text_hint=None):
    result = session.call_tool('browser_find', {'text': text_hint}) if text_hint else session.call_tool('browser_snapshot', {})
    matches = []
    for line in mcp_client.text_of(result).splitlines():
        found = _SNAPSHOT_LINE.search(line)
        if found:
            matches.append(found.groupdict())
    return matches


def resolve_ref(session, spec):
    """Devuelve el `ref` (p. ej. "e35") del elemento que coincide con el locator, o None si no se encontró."""
    by = spec.get('by')
    exact = bool(spec.get('exact'))
    if by == 'testid':
        raise ValueError('El modo «Extensión de Chrome (MCP)» no puede resolver locators por testid todavía — usá «texto» o «rol» para este paso.')
    if by == 'role':
        name = spec.get('name') or None
        candidates = [c for c in _candidates(session, name) if c['role'] == spec.get('role')]
        if name:
            candidates = [c for c in candidates if (c['name'] or '') == name] if exact else \
                         [c for c in candidates if name.lower() in (c['name'] or '').lower()]
    elif by in ('text', 'label', 'placeholder'):
        value = spec.get('value', '')
        candidates = _candidates(session, value)
        if by != 'text':
            # acá interesa el control (casilla de texto y similares), no el texto de la etiqueta/placeholder en sí
            narrowed = [c for c in candidates if c['role'] in _INTERACTIVE_ROLES]
            candidates = narrowed or candidates
        if exact:
            narrowed = [c for c in candidates if (c['name'] or '') == value]
            candidates = narrowed or candidates
    else:
        raise ValueError(f'Locator no soportado en modo MCP: «{by}»')
    if not candidates:
        return None
    if spec.get('first'):
        return candidates[0]['ref']
    if spec.get('nth') is not None:
        index = int(spec['nth'])
        return candidates[index]['ref'] if 0 <= index < len(candidates) else None
    return candidates[0]['ref']


def _require_ref(session, spec):
    ref = resolve_ref(session, spec)
    if ref is None:
        raise ValueError(f'No se encontró ningún elemento para el locator {spec}.')
    return ref


def _element_description(spec):
    return spec.get('name') or spec.get('value') or spec.get('role') or 'elemento'


def _page_url(text):
    match = re.search(r'^- Page URL:\s*(\S+)', text, re.M)
    return match.group(1) if match else None


def run_mcp_steps(session, steps, base, allowed_hosts, timeout_ms, run_steps):
    """Mismo contrato que el loop nativo de automation.execute_ui — agrega a `run_steps` (la misma lista que
    vive en `run['steps']`) a medida que avanza, en vez de devolverla al final, para que un paso que falla a
    mitad de camino deje los pasos anteriores igual de visibles que en el modo nativo. Devuelve la última
    «Page URL» vista."""
    from . import automation  # import diferido: automation importa este módulo, así se evita el ciclo
    deadline_s = int(timeout_ms) / 1000
    last_url = None
    for index, step in enumerate(steps):
        action = step['action']
        outcome = {'index': index, 'action': action}
        run_steps.append(outcome)
        if action == 'navigate':
            url = automation._resolve_url(base, step['url'], allowed_hosts)
            result = session.call_tool('browser_navigate', {'url': url})
            text = mcp_client.text_of(result)
            outcome['mcp_log'] = text[:2000]
            last_url = _page_url(text) or last_url
            if last_url and _host_of(last_url) not in allowed_hosts:
                # A diferencia del modo nativo (page.route(...).abort(), un corte de red real), acá no hay forma
                # de interceptar la navegación antes de que pase — esto solo detecta DESPUÉS del hecho que una
                # redirección sacó la página de los hosts permitidos, y corta ahí.
                raise ValueError(f'Navegación fuera del host autorizado (terminó en {last_url}).')
        elif action == 'assert_url':
            if step['expected'] not in (last_url or ''):
                raise AssertionError(f'URL actual «{last_url}» no contiene «{step["expected"]}»')
        elif action in ('wait_visible', 'assert_visible', 'assert_not_visible'):
            want_visible = action != 'assert_not_visible'
            deadline = time.monotonic() + deadline_s
            found = resolve_ref(session, step['locator']) is not None
            while found != want_visible and time.monotonic() < deadline:
                time.sleep(0.2)
                found = resolve_ref(session, step['locator']) is not None
            if found != want_visible:
                raise AssertionError('El elemento no quedó ' + ('visible' if want_visible else 'oculto') + ' a tiempo.')
        elif action in ('assert_text', 'assert_value'):
            # Probado contra el servidor real: leer un valor con browser_evaluate dio resultados incorrectos
            # cuando hubo otra acción (otro fill/click) entre resolver el ref y usarlo — el árbol de
            # accesibilidad se regenera en cada acción y los refs no quedan tan estables como para confiar en
            # una lectura diferida. Mejor rechazar explícito que arriesgar una aserción que mienta.
            raise ValueError(f'El modo «Extensión de Chrome (MCP)» todavía no soporta «{automation.STEP_ACTIONS[action]["label"]}» '
                              '— usá «Verificar visible»/«Verificar oculto» para este paso, o cambiá a «Sesión guardada»/«Navegador en vivo».')
        else:
            ref = _require_ref(session, step['locator'])
            element = _element_description(step['locator'])
            if action == 'click':
                outcome['mcp_log'] = mcp_client.text_of(session.call_tool('browser_click', {'target': ref, 'element': element}))[:2000]
            elif action == 'fill':
                outcome['mcp_log'] = mcp_client.text_of(session.call_tool('browser_type', {'target': ref, 'element': element, 'text': str(step['value'])}))[:2000]
            elif action == 'press':
                outcome['mcp_log'] = mcp_client.text_of(session.call_tool('browser_press_key', {'key': str(step['value'])}))[:2000]
            elif action in ('check', 'uncheck'):
                fields = [{'target': ref, 'name': element, 'type': 'checkbox', 'value': 'true' if action == 'check' else 'false'}]
                outcome['mcp_log'] = mcp_client.text_of(session.call_tool('browser_fill_form', {'fields': fields}))[:2000]
            elif action == 'select_option':
                outcome['mcp_log'] = mcp_client.text_of(session.call_tool('browser_select_option', {'target': ref, 'element': element, 'values': [str(step['value'])]}))[:2000]
            else:
                raise ValueError(f'Acción no soportada en modo MCP: «{action}»')
        outcome['passed'] = True
    return last_url


def _host_of(url):
    return urlparse(url).hostname


def capture_screenshot(session, path):
    """Captura la página actual del puente MCP (equivalente a page.screenshot(..., full_page=True) del modo
    nativo) y la guarda en `path` — mismo nombre/carpeta que ya usa el modo nativo, ver execute_ui."""
    session.call_tool('browser_take_screenshot', {'fullPage': True, 'scale': 'css', 'filename': str(path)})
