from nicegui import ui
from .. import core
from .common import frame, guard, confirm, empty_state, require_project, protected_page

KIND_LABELS = {'input': 'Entrada', 'output': 'Salida'}
APPLIES_LABELS = {'user_story': 'Historia de usuario', 'test_case': 'Caso de prueba', 'report': 'Reporte'}


@protected_page('/spec-templates')
def spec_templates_list():
    with frame('Plantillas', '/spec-templates'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.label('Biblioteca global (compartida entre proyectos) y las propias de este proyecto — adopta una global para personalizarla, o promueve la tuya para compartirla.').classes('text-sm text-gray-500')
        ui.button('Nueva plantilla propia', icon='add', on_click=lambda: ui.navigate.to('/spec-templates/edit')).props('color=primary')

        all_templates = core.list_items('spec_templates')
        global_templates = sorted([t for t in all_templates if t.get('project_id') is None], key=lambda t: t['name'])
        local_templates = sorted([t for t in all_templates if t.get('project_id') == pid], key=lambda t: t['name'])

        def template_row(t, badge_label, badge_color, action_label=None, action=None):
            with ui.row().classes('items-center gap-2 w-full no-wrap cursor-pointer hover:bg-gray-50') \
                    .on('click', lambda _, tid=t['id']: ui.navigate.to(f'/spec-templates/edit?id={tid}')):
                ui.badge(badge_label, color=badge_color)
                ui.badge(KIND_LABELS.get(t['kind'], t['kind']), color='grey-5')
                ui.label(t['name']).classes('text-sm font-medium')
                ui.label(APPLIES_LABELS.get(t['applies_to'], t['applies_to'])).classes('text-xs text-gray-500')
                ui.space()
                if action_label and action:
                    ui.button(action_label, on_click=lambda _, t=t: action(t)).props('flat dense size=sm color=primary').on('click.stop', lambda: None)

        def do_adopt(t):
            core.adopt_template(t['id'], pid)
            ui.notify(f'«{t["name"]}» adoptada a este proyecto', type='positive')
            ui.navigate.reload()

        with ui.card().classes('w-full'):
            ui.label('Biblioteca global').classes('font-semibold')
            if not global_templates:
                empty_state('Sin plantillas globales todavía.')
            for t in global_templates:
                template_row(t, 'Por defecto' if t.get('is_builtin') else 'Global', 'primary', 'Adoptar', do_adopt)

        with ui.card().classes('w-full'):
            ui.label(f'Propias de este proyecto ({len(local_templates)})').classes('font-semibold')
            if not local_templates:
                empty_state('Todavía no adoptaste ni creaste ninguna plantilla propia.')
            for t in local_templates:
                template_row(t, 'Propia', 'grey-7')


@protected_page('/spec-templates/edit')
def spec_template_detail(id: str = ''):
    with frame('Plantilla' if id else 'Nueva plantilla', '/spec-templates'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.link('← Volver a Plantillas', '/spec-templates').classes('text-sm')

        current = core.get('spec_templates', id) if id else None
        if id and current is None:
            ui.label('Esta plantilla ya no existe.').classes('text-amber-700')
            return
        is_global = bool(current) and current.get('project_id') is None
        is_mine = bool(current) and current.get('project_id') == pid

        d = {'body': [dict(b) for b in (current or {}).get('body', [])]}

        with ui.card().classes('w-full'):
            with ui.row().classes('items-center gap-2'):
                ui.icon('description', color='primary').classes('text-2xl')
                ui.label(current['name'] if current else 'Nueva plantilla').classes('text-xl font-semibold')
                if is_global:
                    ui.badge('Global — solo lectura, adoptala para editarla', color='primary')

            disabled = is_global
            name = ui.input('Nombre', value=(current or {}).get('name', '')).props('outlined dense').classes('w-full').mark('template-name')
            description = ui.textarea('Descripción (opcional)', value=(current or {}).get('description', '')).props('outlined dense autogrow').classes('w-full')
            with ui.row().classes('w-full gap-3'):
                kind = ui.select(KIND_LABELS, value=(current or {}).get('kind', 'input'), label='Tipo').props('outlined dense').classes('w-44')
                applies_to = ui.select(APPLIES_LABELS, value=(current or {}).get('applies_to', 'user_story'), label='Aplica a').props('outlined dense').classes('w-60')
            if disabled:
                name.disable(); description.disable(); kind.disable(); applies_to.disable()

            ui.separator().classes('my-2')
            ui.label('Campos / secciones (en orden)').classes('font-semibold')

            @ui.refreshable
            def body_rows():
                if not d['body']:
                    ui.label('Ninguno todavía.').classes('text-sm text-gray-400')
                for b in d['body']:
                    with ui.row().classes('items-center gap-2 w-full no-wrap'):
                        ui.input('Etiqueta', value=b.get('label', '')).props('outlined dense').classes('grow').on_value_change(lambda e, b=b: b.__setitem__('label', e.value))
                        ui.input('Clave', value=b.get('field', '')).props('outlined dense').classes('w-48').on_value_change(lambda e, b=b: b.__setitem__('field', e.value))
                        if not disabled:
                            ui.button(icon='delete', on_click=lambda _, b=b: (d['body'].remove(b), body_rows.refresh())).props('flat round dense color=negative')
            body_rows()
            if not disabled:
                ui.button('Agregar campo', icon='add', on_click=lambda: (d['body'].append({'field': '', 'label': ''}), body_rows.refresh())).props('outline dense color=primary').mark('template-add-field')

            if is_global:
                def adopt():
                    core.adopt_template(current['id'], pid)
                    ui.notify('Plantilla adoptada a este proyecto', type='positive')
                    ui.navigate.to('/spec-templates')
                ui.button('Adoptar a este proyecto', icon='content_copy', on_click=guard(adopt)).props('color=primary mt-2').mark('template-adopt')
                return

            def save():
                if current:
                    core.update_spec_template(current['id'], name.value, description.value or '', d['body'])
                    ui.notify('Plantilla actualizada', type='positive')
                    ui.navigate.to(f'/spec-templates/edit?id={current["id"]}')
                else:
                    template = core.create_spec_template(name.value, kind.value, applies_to.value, d['body'], pid, description.value or '')
                    ui.notify('Plantilla creada', type='positive')
                    ui.navigate.to(f'/spec-templates/edit?id={template["id"]}')
            ui.button('Guardar cambios' if current else 'Crear plantilla', icon='save', on_click=guard(save)).props('color=primary mt-2').mark('template-save')

            if current and is_mine:
                def promote():
                    core.promote_template(current['id'])
                    ui.notify('Copia publicada en la biblioteca global', type='positive')
                    ui.navigate.to('/spec-templates')
                ui.button('Promover a la biblioteca global', icon='publish', on_click=guard(promote)).props('outline dense color=primary mt-2').mark('template-promote')

                def remove(t=current):
                    core.delete_spec_template(t['id'])
                    ui.notify('Plantilla eliminada', type='positive')
                    ui.navigate.to('/spec-templates')
                ui.button('Eliminar plantilla', icon='delete', on_click=lambda: confirm(f'¿Eliminar la plantilla «{current["name"]}»?', remove)) \
                    .props('flat dense color=negative mt-2').mark('template-delete')
