"""Nivel 0: el shell genérico de una app (header + drawer colapsable + columna de contenido) — generalización
portable de `app/pages/common.py::frame()`. Sin ningún import de `app.core` ni de `app.pages`: lo específico de
cada proyecto (selector de proyecto activo, menú de usuario, el menú de navegación) entra como callbacks
inyectados (`header_right`/`drawer_content`), no como código hardcodeado acá."""
from contextlib import contextmanager
from typing import Callable, Optional, Sequence

from nicegui import ui

# Mismo recipe que MINI_CSS en app/pages/common.py (drawer mini-icono con texto oculto) — copiado, no
# importado, para que este módulo no dependa de app.pages.common.
MINI_CSS = '''<style>
.q-drawer--mini .q-btn__content .block{font-size:0 !important;width:0 !important;height:0 !important;overflow:hidden !important}
.q-drawer--mini .q-btn__content{justify-content:center !important}
.q-drawer--mini .q-btn__content .q-icon{margin:0 !important}
.layout-pane{height:100%;overflow:auto} .q-splitter__separator{background:#e5e7eb}
.layout-pane .q-tab-panel{min-width:0} .layout-pane pre{white-space:pre-wrap !important;word-break:break-word}
.layout-pane .nicegui-code{max-width:100%}
</style>'''


@contextmanager
def app_shell(
    title: str,
    *,
    app_name: str = 'App',
    wide: bool = False,
    doc_style: bool = False,
    full_width: bool = False,
    header_right: Optional[Callable[[], None]] = None,
    drawer_content: Optional[Callable[[], None]] = None,
    extra_head_html: Sequence[str] = (),
    doc_css: str = '',
    doc_class: str = 'layout-doc',
):
    """Generalización de `frame()`: mismo contrato de `wide`/`doc_style`/`full_width` (ver docstring de
    `frame()` en `app/pages/common.py`), pero sin nada específico de ningún proyecto.

    - `header_right`: se llama DENTRO de `ui.header()`, después del título — reemplaza lo que en LTW es el
      selector de proyecto activo + menú de usuario.
    - `drawer_content`: se llama DENTRO del `ui.left_drawer()` — reemplaza el menú `NAV`/`NAV_GROUPS` de LTW.
    - `extra_head_html`: strings de `<script>`/`<style>` a inyectar (equivalente a `ARIA_SCRIPT`/
      `HTML2CANVAS_SCRIPT` en LTW) — este módulo no los conoce ni los asume, el caller decide cuáles hacen
      falta para su propio proyecto.
    - `doc_css`/`doc_class`: si `doc_style=True`, se inyecta `doc_css` (si no viene vacío) y el contenido se
      envuelve en la clase `doc_class` (por defecto `layout-doc`, NO el `ltw-doc` de LTW — un CSS de "aire de
      documento" que apunte a `.ltw-doc` no se aplicaría acá sin ajustarlo a este nombre de clase)."""
    ui.colors(primary='#2563eb')
    for html in extra_head_html:
        ui.add_head_html(html)
    if doc_style and doc_css:
        ui.add_head_html(doc_css)
    ui.page_title(f'{title} · {app_name}')
    drawer = ui.left_drawer(value=True, bordered=True).classes('bg-gray-50 pt-4')
    if wide:
        ui.add_head_html(MINI_CSS)
        drawer.props('mini mini-to-overlay mini-width=64 width=240')
        drawer.on('mouseenter', lambda: drawer.props(remove='mini'))
        drawer.on('mouseleave', lambda: drawer.props('mini'))
    with ui.header(elevated=False).classes('bg-white text-gray-800 border-b items-center gap-3 px-4'):
        ui.button(icon='menu', on_click=drawer.toggle).props('flat round dense').tooltip('Mostrar u ocultar el menú')
        ui.label(app_name).classes('text-lg font-semibold')
        ui.space()
        if header_right:
            header_right()
    with drawer:
        if drawer_content:
            drawer_content()
    if wide or full_width:
        with ui.column().classes('w-full gap-0 p-0'):
            yield
        return
    with ui.column().classes('w-full p-4 gap-4' + (f' max-w-7xl mx-auto {doc_class}' if doc_style else ' max-w-6xl mx-auto')):
        ui.label(title).classes(f'{doc_class}-title text-2xl font-semibold' if doc_style else 'text-2xl font-semibold')
        yield
