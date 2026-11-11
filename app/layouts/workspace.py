"""Nivel 1: el layout de "workspace" (splitter documento/centro vs. panel lateral con riel vertical de
íconos, arrastrar cualquier pestaña del riel al centro, alternar centro en pestañas o dividido) —
generalización portable del bloque que hoy existe copiado a mano en `app/pages/user_stories.py` y
`app/pages/test_case_specs.py` (y, en una variante más simple, en `app/pages/workspace_page.py`).

Sin ningún import de `app.core` ni de `app.pages`. Monta sobre lo que `app_shell` (Nivel 0) ya haya armado —
se llama DENTRO de su `with`, no lo reemplaza."""
import dataclasses
from typing import Callable, List, Optional

from nicegui import app, ui

from ._types import Panel


@dataclasses.dataclass
class WorkspaceHandle:
    """Lo que `workspace_layout()` devuelve — para que la página anfitriona pueda, además de lo que ya hace el
    usuario con el mouse (clic en el riel, arrastrar al centro), disparar las mismas acciones por código (p.
    ej. un botón de menú "mover tal panel al centro")."""
    add_to_center: Callable[[str], None]
    remove_from_center: Callable[[str], None]
    toggle_center_mode: Callable[[], None]


def _default_get_pref(key, default):
    """Fallback de persistencia si el caller no inyecta `get_pref`/`set_pref` — copia defensiva de
    `remembered()` (`app/pages/common.py`), no importada de ahí para no acoplar este paquete a `app.pages`."""
    try:
        storage = app.storage.user
    except Exception:
        return default
    return storage.get(key, default) if hasattr(storage, 'get') else default


def _default_set_pref(key, value):
    try:
        app.storage.user[key] = value
    except Exception:
        pass


def workspace_layout(
    side_panels: List[Panel],
    center_anchors: List[Panel],
    *,
    prefix: str,
    get_pref: Optional[Callable[[str, object], object]] = None,
    set_pref: Optional[Callable[[str, object], None]] = None,
    rail_width: int = 56,
    split_limits: tuple = (40, 96),
    max_center_panels: int = 3,
    collapsible: bool = True,
    fallback_key: str = '',
    side_title: str = 'Fields',
    side_icon: str = 'tune',
    side_extra: Optional[Callable[[], None]] = None,
    fill_height: bool = True,
) -> WorkspaceHandle:
    """Dibuja el layout completo (llamarlo directamente adentro de la página, no como context manager — todo
    el contenido sale de `Panel.render` de cada panel que se le pase).

    - `side_extra`: contenido fijo, SIEMPRE visible (no gobernado por ninguna pestaña), entre el título del
      panel lateral y el riel — para un control que tiene que verse pase lo que pase se seleccione en el riel
      (p. ej. un selector de qué conjunto de paneles usar).

    - `side_panels`: aparecen en el riel vertical de la derecha Y como pestaña del panel lateral; arrastrables
      al centro (una copia en vivo, no un movimiento — ver `Panel.render`) si `draggable=True`.
    - `center_anchors`: siempre disponibles como entrada del centro, NUNCA aparecen en el riel (p. ej. un panel
      "Documento" que siempre está ahí). El primero (o `fallback_key`, si se da) es el que nunca se puede
      cerrar y al que el centro cae si se cierra todo lo demás.
    - `prefix`: OBLIGATORIO — namespace de las claves de persistencia (`{prefix}_split_value`/
      `{prefix}_center_mode`); si se llama `workspace_layout()` dos veces en la misma página, cada llamada
      necesita su propio `prefix` o sus preferencias se van a pisar.
    - `get_pref`/`set_pref`: ambos o ninguno — persistencia inyectada (firma `(key, default) -> value` /
      `(key, value) -> None`); sin ninguno de los dos, usa un fallback propio basado en
      `nicegui.app.storage.user`, sin depender de `app.pages.common.remembered`.
    - Solo se persiste la posición del separador y el modo de centro (pestañas/dividido) — cuáles paneles
      están abiertos en el centro y cuál pestaña del riel está activa NO se persisten, a propósito (hoy
      tampoco se persisten en `user_stories.py`).
    - `fill_height`: True (default) asume que lo que te rodea te da una altura definida (p. ej. un `div` con
      `style('height:...')`) y hace que el splitter/los paneles la llenen, cada uno con su propio scroll
      interno. False es para cuando NO hay una altura definida alrededor (la página entera scrollea en vez de
      cada panel por separado) — forzar height:100% ahí colapsa todo a 0px, visualmente en blanco."""
    if (get_pref is None) != (set_pref is None):
        raise ValueError('get_pref y set_pref deben darse juntos, o ninguno de los dos')
    if get_pref is None:
        get_pref, set_pref = _default_get_pref, _default_set_pref

    all_panels = {panel.key: panel for panel in list(center_anchors) + list(side_panels)}
    effective_fallback = fallback_key or (center_anchors[0].key if center_anchors else
                                          (side_panels[0].key if side_panels else ''))

    split_value = get_pref(f'{prefix}_split_value', 75)

    S = {
        'center_mode': get_pref(f'{prefix}_center_mode', 'tabs'),
        'center_open': [effective_fallback] if effective_fallback else [],
        'collapsed': False,
        'active_tab': side_panels[0].key if side_panels else '',
        'split_before_collapse': split_value,
    }
    drag_state = {'key': None}
    field_panels = None
    main_split = None

    def handle_rail_click(key):
        """Clic en el ícono YA activo del riel colapsa/expande el panel lateral (estilo VS Code); clic en OTRO
        ícono cambia de pestaña y lo deja expandido. Al colapsar, el separador se corre solo para devolverle
        ese ancho al panel central."""
        if not collapsible:
            S['active_tab'] = key
            return
        if S['active_tab'] == key:
            S['collapsed'] = not S['collapsed']
        else:
            S['active_tab'] = key
            S['collapsed'] = False
        field_panels.set_visibility(not S['collapsed'])
        if S['collapsed']:
            S['split_before_collapse'] = main_split.value
            main_split.set_value(95)
        else:
            main_split.set_value(S.get('split_before_collapse', split_value))

    def add_to_center(key):
        if not key or key not in all_panels or key in S['center_open']:
            return
        if len(S['center_open']) >= max_center_panels:
            ui.notify(f'Ya tenés {max_center_panels} paneles abiertos en el centro — cerrá uno primero', type='warning')
            return
        S['center_open'].append(key)
        center_area.refresh()

    def remove_from_center(key):
        if key == effective_fallback or key not in S['center_open']:
            return
        S['center_open'].remove(key)
        center_area.refresh()

    def toggle_center_mode():
        S['center_mode'] = 'split' if S['center_mode'] == 'tabs' else 'tabs'
        set_pref(f'{prefix}_center_mode', S['center_mode'])
        center_area.refresh()

    def panel_card(key):
        panel = all_panels[key]
        with ui.card().classes('w-full').mark(f'{prefix}-center-{key}').style('height:100%;overflow:auto' if fill_height else ''):
            if key != effective_fallback:
                with ui.row().classes('items-center justify-between w-full'):
                    with ui.row().classes('items-center gap-1'):
                        ui.icon(panel.icon, size='xs', color='grey')
                        ui.label(panel.label).classes('text-xs text-gray-500')
                    ui.button(icon='close', on_click=lambda k=key: remove_from_center(k)) \
                        .props('flat round dense size=sm').mark(f'{prefix}-center-close-{key}')
            panel.render()

    def nested_split(keys):
        if len(keys) == 1:
            panel_card(keys[0])
            return
        with ui.splitter(value=round(100 / len(keys))).classes('w-full').style('height:100%' if fill_height else '') as sp:
            with sp.before:
                panel_card(keys[0])
            with sp.after:
                nested_split(keys[1:])

    @ui.refreshable
    def center_area():
        open_keys = [k for k in S['center_open'] if k in all_panels] or ([effective_fallback] if effective_fallback else [])
        with ui.column().classes('w-full gap-0').style('flex:1 1 0;min-height:0;overflow:hidden' if fill_height else '') \
                .on('dragover.prevent', lambda: None) \
                .on('drop', lambda: add_to_center(drag_state['key'])):
            if not open_keys:
                return
            if S['center_mode'] == 'split' and len(open_keys) >= 2:
                nested_split(open_keys[:max_center_panels])
            elif len(open_keys) == 1:
                panel_card(open_keys[0])
            else:
                with ui.tabs().props('dense no-caps').classes('w-full') as center_tabs:
                    for key in open_keys:
                        panel = all_panels[key]
                        ui.tab(key, label=panel.label, icon=panel.icon)
                with ui.tab_panels(center_tabs, value=open_keys[0]).classes('w-full').style('height:100%'):
                    for key in open_keys:
                        with ui.tab_panel(key).classes('p-0').style('height:100%'):
                            panel_card(key)

    @ui.refreshable
    def fields_section():
        nonlocal field_panels
        if not any(panel.key == S['active_tab'] for panel in side_panels):
            S['active_tab'] = side_panels[0].key if side_panels else ''
        with ui.row().classes('w-full no-wrap gap-0').style('min-height:420px;justify-content:flex-end'):
            with ui.tab_panels(None, value=S['active_tab']).props('vertical').style('flex:1 1 0;min-width:0;padding:16px') as field_panels:
                for panel in side_panels:
                    with ui.tab_panel(panel.key).classes('gap-3 p-0'):
                        panel.render()
            # Dual-wired a propósito: `ondragstart` (prop cruda) porque algunos navegadores exigen un
            # dataTransfer.setData() síncrono para iniciar el arrastre; `.on('dragstart', ...)` porque esa
            # prop no puede llamar de vuelta a Python — solo deja constancia en `drag_state`.
            with ui.tabs().props('vertical dense no-caps').classes('shrink-0').style(f'width:{rail_width}px;border-left:1px solid #e5e7eb') as field_rail:
                for panel in side_panels:
                    tip = f'{panel.label} (arrastrable al centro)' if panel.draggable else panel.label
                    tab = ui.tab(panel.key, label='', icon=panel.icon).tooltip(tip).mark(f'{prefix}-rail-{panel.key}')
                    if panel.draggable:
                        tab.props(f'draggable=true ondragstart="event.dataTransfer.setData(\'text/plain\',\'{panel.key}\')"') \
                           .on('dragstart', lambda gid=panel.key: drag_state.__setitem__('key', gid))
                    tab.on('click', lambda gid=panel.key: handle_rail_click(gid))
            field_panels.bind_value_from(field_rail, 'value')
            field_rail.set_value(S['active_tab'])

    with ui.splitter(value=split_value, limits=split_limits,
                      on_change=lambda e: set_pref(f'{prefix}_split_value', e.value)) \
            .classes('w-full').style('height:100%' if fill_height else '').mark(f'{prefix}-main-split') as main_split:
        with main_split.after:
            if side_panels:
                with ui.column().classes('w-full gap-4').style('height:100%;overflow:auto' if fill_height else ''):
                    with ui.card().classes('w-full p-0').style('overflow:visible' if fill_height else ''):
                        with ui.row().classes('items-center gap-2 p-4 pb-0'):
                            ui.icon(side_icon, color='primary').classes('text-2xl')
                            ui.label(side_title).classes('text-xl font-semibold')
                        if side_extra:
                            with ui.column().classes('w-full gap-3 px-4 pt-2'):
                                side_extra()
                        fields_section()
        with main_split.before:
            with ui.column().classes('w-full gap-4 min-w-0').style('height:100%' if fill_height else ''):
                center_area()

    return WorkspaceHandle(add_to_center=add_to_center, remove_from_center=remove_from_center, toggle_center_mode=toggle_center_mode)
