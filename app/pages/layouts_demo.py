"""Demo de app/layouts/ (Nivel 0 + Nivel 1) — sin nada de app.core, solo para ejercitarlo y verlo en vivo, y
para que tests/test_layouts.py tenga rutas fijas y reales contra las que probar. No están en NAV/NAV_GROUPS a
propósito: son documentación viva, no pantallas reales de LTW."""
from nicegui import ui
from ..layouts import Panel, app_shell, workspace_layout


def _header_right():
    ui.label('(demo — sin selector de proyecto ni usuario)').classes('text-sm text-gray-500')


def _drawer_content():
    ui.label('Sin navegación real en esta demo').classes('text-sm text-gray-500 p-2')


@ui.page('/layouts/demo')
def layouts_demo():
    def render_document():
        ui.label('Documento').classes('text-xl font-bold')
        ui.markdown('Panel **ancla** de centro: siempre disponible, nunca se puede cerrar.')

    def render_general():
        ui.label('Campos de ejemplo').classes('font-semibold')
        ui.input('Título', value='Ejemplo').props('outlined dense').classes('w-full')
        ui.input('Prioridad', value='Media').props('outlined dense').classes('w-full')

    def render_detalles():
        ui.label('Otro grupo').classes('font-semibold')
        ui.textarea('Notas').props('outlined dense').classes('w-full')

    with app_shell('Demo de layouts', app_name='LTW (demo)', full_width=True,
                    header_right=_header_right, drawer_content=_drawer_content):
        with ui.column().classes('w-full p-4 gap-4'):
            ui.label('Demo de layouts').classes('text-2xl font-semibold')
            with ui.element('div').classes('w-full').style('height:70vh'):
                workspace_layout(
                    side_panels=[
                        Panel('general', 'General', 'edit_note', render_general),
                        Panel('detalles', 'Detalles', 'list_alt', render_detalles),
                    ],
                    center_anchors=[Panel('document', 'Documento', 'description', render_document)],
                    prefix='layouts_demo',
                )


@ui.page('/layouts/demo-handle-test')
def layouts_demo_handle_test():
    """Ruta fija (no un `@ui.page` dentro de un test) para ejercitar el `WorkspaceHandle` devuelto por
    `workspace_layout` — el drag real (HTML5 dragstart/drop) no lo puede simular el harness de NiceGUI;
    `add_to_center`/`remove_from_center`/`toggle_center_mode` son el mismo camino de código que un botón o
    menú de la página anfitriona usaría para hacer lo mismo sin arrastrar nada."""
    handle = workspace_layout(
        side_panels=[Panel('a', 'A', 'star', lambda: ui.label('panel a'))],
        center_anchors=[Panel('document', 'Documento', 'description', lambda: ui.label('doc'))],
        prefix='handle_test',
    )
    ui.button('add-a', on_click=lambda: handle.add_to_center('a')).mark('btn-add-a')
    ui.button('remove-a', on_click=lambda: handle.remove_from_center('a')).mark('btn-remove-a')
    ui.button('toggle-mode', on_click=handle.toggle_center_mode).mark('btn-toggle-mode')


@ui.page('/layouts/demo-extra-test')
def layouts_demo_extra_test():
    """Ruta fija para probar `side_extra` (contenido fijo arriba del riel, no gobernado por ninguna pestaña)
    y `fill_height=False` (cuando quien envuelve a workspace_layout no le da una altura definida — el caso de
    una página con scroll completo en vez de cada panel con su propio scroll)."""
    def extra():
        ui.label('Siempre visible').mark('extra-always-visible')

    workspace_layout(
        side_panels=[Panel('a', 'A', 'star', lambda: ui.label('panel a'))],
        center_anchors=[Panel('document', 'Documento', 'description', lambda: ui.label('doc'))],
        prefix='extra_test', side_extra=extra, fill_height=False,
    )


@ui.page('/layouts/demo-cap-test')
def layouts_demo_cap_test():
    """Ruta fija para probar el tope de `max_center_panels` (3 por defecto: aquí 3 paneles de riel + 1 ancla
    = 4 posibles, uno de más)."""
    def render_label(key):
        ui.label(key)

    handle = workspace_layout(
        side_panels=[Panel(key, key, 'star', lambda k=key: render_label(k)) for key in ('a', 'b', 'c')],
        center_anchors=[Panel('document', 'Documento', 'description', lambda: ui.label('doc'))],
        prefix='cap_test',
        max_center_panels=3,
    )
    for key in ('a', 'b', 'c'):
        ui.button(f'add-{key}', on_click=lambda k=key: handle.add_to_center(k)).mark(f'btn-add-{key}')
