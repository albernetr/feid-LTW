"""Visor interactivo de reportes de Especificación (Historia de usuario o Caso de prueba sueltos): a diferencia
de los formatos descargables (HTML/PDF/Word/Markdown — siempre una lista vertical simple), acá las secciones
que la plantilla de salida marcó como `as_tab=True` (ver core.py) se vuelven pestañas propias — reusando
LITERALMENTE el mismo mecanismo de pestañas/vista dividida que ya construyó Historias de usuario para su panel
central (Fase 6), factorizado en common.tabbed_split_view."""
from nicegui import ui
from .. import core, spec_report
from .common import frame, require_project, protected_page, remembered, tabbed_split_view, doc_typography, live_doc_html, typography_button


def _output_templates(pid):
    return [t for t in core.list_items('spec_templates') if t.get('kind') == 'output' and t.get('applies_to') == 'report'
            and (t.get('project_id') is None or t.get('project_id') == pid)]


def _split_tab_groups(sections):
    """Separa, al primer nivel del árbol de un reporte, los grupos `as_tab=True` (se vuelven pestañas propias)
    del resto (que queda en el panel "Documento", inline, en su orden original)."""
    tabs, rest = [], []
    for section in sections:
        if section.get('kind') == 'group' and section.get('as_tab'):
            tabs.append(section)
        else:
            rest.append(section)
    return tabs, rest


def _render_viewer(title, back_label, back_route, build_data):
    with frame(title, back_route, full_width=True, doc_style=True):
        if not require_project():
            return
        pid = core.get_active_project_id()
        compact, set_compact = remembered('spec_viewer_compact', default=True)
        mode, set_mode = remembered('spec_viewer_mode', default='tabs')
        templates = _output_templates(pid)
        if not templates:
            with ui.column().classes('w-full p-4 gap-2'):
                ui.link(back_label, back_route).classes('text-sm')
                ui.label('No hay plantillas de salida disponibles para este proyecto.').classes('text-amber-700')
            return
        default_tpl = next((t['id'] for t in templates if 'detallada' in t['name'].lower()), templates[0]['id'])

        with ui.column().classes('w-full p-4 gap-4 ltw-doc'):
            with ui.row().classes('w-full items-center justify-between no-wrap'):
                with ui.column().classes('gap-0'):
                    ui.link(back_label, back_route).classes('text-sm')
                    ui.label(title).classes('ltw-doc-title text-2xl font-semibold')
                with ui.row().classes('items-center gap-2'):
                    template_select = ui.select({t['id']: t['name'] for t in templates}, value=default_tpl, label='Plantilla de salida') \
                        .props('outlined dense').classes('w-64').mark('viewer-template')

                    mode_box = {'value': mode}

                    @ui.refreshable
                    def mode_button():
                        ui.button(icon='vertical_split' if mode_box['value'] == 'tabs' else 'view_column',
                                  on_click=lambda: (mode_box.__setitem__('value', 'split' if mode_box['value'] == 'tabs' else 'tabs'),
                                                    set_mode(mode_box['value']), mode_button.refresh(), body.refresh())) \
                            .props('flat round dense').mark('viewer-toggle-mode') \
                            .tooltip('Ver las pestañas lado a lado' if mode_box['value'] == 'tabs' else 'Volver a pestañas')
                    mode_button()

                    def toggle_compact():
                        set_compact(not compact)
                        ui.navigate.reload()
                    ui.button(icon='fullscreen_exit' if compact else 'fullscreen', on_click=toggle_compact) \
                        .props('flat round dense').mark('viewer-toggle-compact')
                    typography_button(lambda: body.refresh())

            @ui.refreshable
            def body():
                template = core.get('spec_templates', template_select.value)
                data = build_data(template)
                typography = doc_typography()[0]
                tab_sections, rest_sections = _split_tab_groups(data['sections'])
                panels = [('document', 'Documento', 'description',
                          (lambda rest=rest_sections: ui.html(live_doc_html(spec_report.render_sections_html(rest), typography)).classes('w-full')))]
                for i, section in enumerate(tab_sections):
                    panels.append((f'tab{i}', section.get('label') or f'Sección {i + 1}', 'tab',
                                   (lambda section=section: ui.html(live_doc_html(spec_report.render_sections_html(section['children']), typography)).classes('w-full'))))
                with ui.element('div').classes('w-full').style('height: calc(100vh - 170px)' if compact else ''):
                    tabbed_split_view(panels, mode=mode_box['value'], max_open=max(len(panels), 1), compact=compact)
            template_select.on_value_change(lambda e: body.refresh())
            body()


@protected_page('/stories/view')
def story_viewer(id: str = ''):
    story = core.get('user_stories', id) if id else None
    if not story:
        with frame('Historia de usuario', '/stories', doc_style=True):
            ui.link('← Volver a Historias de usuario', '/stories').classes('text-sm')
            ui.label('Esta historia ya no existe.').classes('text-amber-700')
        return
    _render_viewer(story['title'], '← Volver a la historia', f'/stories/edit?id={story["id"]}',
                   lambda tpl: spec_report.build_story_report_data(story, tpl))


@protected_page('/test-specs/view')
def test_spec_viewer(id: str = ''):
    spec = core.get('test_case_specs', id) if id else None
    if not spec:
        with frame('Caso de prueba', '/test-specs', doc_style=True):
            ui.link('← Volver a Casos de prueba', '/test-specs').classes('text-sm')
            ui.label('Este caso de prueba ya no existe.').classes('text-amber-700')
        return
    _render_viewer(spec['title'], '← Volver al caso de prueba', f'/test-specs/edit?id={spec["id"]}',
                   lambda tpl: spec_report.build_test_case_report_data(spec, tpl))
