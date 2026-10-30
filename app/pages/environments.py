from nicegui import ui
from .. import core
from .common import frame, guard, confirm, empty_state, require_project, kv_editor


@ui.page('/environments')
def environments(edit: str = ''):
    with frame('Ambientes y secretos', '/environments'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        current = core.get('environments', edit) if edit else None
        if current and current.get('project_id') != pid:
            ui.notify('Ese ambiente no pertenece al proyecto activo; no se puede editar desde aquí.', type='warning')
            current = None
        variables = dict((current or {}).get('variables', {}))
        auth0 = (current or {}).get('auth', {'type': 'none'})

        with ui.card().classes('w-full'):
            ui.label('Editar ambiente' if current else 'Nuevo ambiente').classes('text-lg font-semibold')
            with ui.row().classes('w-full gap-3'):
                name = ui.input('Nombre', value=(current or {}).get('name', 'QA')).props('outlined dense').classes('w-60').mark('env-name')
                base = ui.input('URL base (API)', value=(current or {}).get('base_url', ''), placeholder='https://qa.ejemplo.com').props('outlined dense').classes('grow').mark('env-base-url')
            ui_base = ui.input('URL base de la interfaz (si es distinta; opcional)', value=(current or {}).get('ui_base_url', '')).props('outlined dense').classes('w-full').mark('env-ui-base-url')
            auth = ui.select({'none': 'Sin autenticación', 'bearer': 'Bearer token', 'api_key': 'API Key'}, value=auth0.get('type', 'none'), label='Autenticación').props('outlined dense').classes('w-60')
            names = core.secret_names()
            with ui.column().classes('w-full gap-2').bind_visibility_from(auth, 'value', lambda v: v != 'none'):
                with ui.row().classes('gap-3 w-full'):
                    secret = ui.select(names, value=auth0.get('secret') if auth0.get('secret') in names else None, label='Secreto guardado en el sistema', clearable=True).props('outlined dense').classes('w-72')
                    envvar = ui.input('…o variable de entorno', value=auth0.get('env_var', ''), placeholder='QA_TOKEN').props('outlined dense').classes('w-60')
                    header_name = ui.input('Header (solo API Key)', value=auth0.get('header', 'X-API-Key')).props('outlined dense').classes('w-48')
                ui.label('El valor nunca se guarda en la base ni en exportaciones. Créalo en «Secretos» más abajo.').classes('text-gray-500 text-sm')
            ui.label('Variables ({{nombre}} en rutas, headers, body y pasos UI)').classes('font-medium')
            kv_editor(variables, 'Variable', 'Valor')

            def save():
                core.validate_base_url(base.value)
                core.validate_base_url(ui_base.value, required=False)
                clean_name = (name.value or '').strip()
                if not clean_name:
                    raise ValueError('El nombre es obligatorio')
                others = [e for e in core.list_project_items('environments', pid) if not current or e['id'] != current['id']]
                if any(e['name'].strip().lower() == clean_name.lower() for e in others):
                    raise ValueError(f'Ya existe un ambiente llamado «{clean_name}» en este proyecto')
                if auth.value != 'none' and not (secret.value or (envvar.value or '').strip()):
                    raise ValueError('Elige un secreto o indica una variable de entorno')
                clean = {k: v for k, v in variables.items() if k.strip()}
                item = {'name': clean_name, 'project_id': pid, 'base_url': base.value.strip(), 'ui_base_url': (ui_base.value or '').strip(),
                        'auth': {'type': auth.value, 'secret': secret.value or '', 'env_var': (envvar.value or '').strip(), 'header': header_name.value or 'X-API-Key'},
                        'variables': clean}
                if current:
                    item['id'] = current['id']
                core.save('environments', item)
                ui.notify('Ambiente guardado', type='positive')
                ui.navigate.to('/environments')
            with ui.row().classes('gap-2'):
                ui.button('Guardar ambiente', icon='save', on_click=guard(save)).props('color=primary')
                if current:
                    ui.button('Cancelar edición', on_click=lambda: ui.navigate.to('/environments')).props('flat')

        items = core.list_project_items('environments', pid)
        if not items:
            empty_state('No hay ambientes en este proyecto.')
        for env in items:
            with ui.card().classes('w-full'):
                with ui.row().classes('items-center gap-3 w-full'):
                    ui.label(env['name']).classes('font-semibold')
                    ui.label(env['base_url']).classes('font-mono text-sm text-gray-600')
                    ui.badge({'none': 'Sin autenticación', 'bearer': 'Bearer', 'api_key': 'API Key'}.get(env['auth']['type'], env['auth']['type']), color='grey')
                    ui.space()
                    ui.button(icon='edit', on_click=lambda _, i=env['id']: ui.navigate.to(f'/environments?edit={i}')).props('flat round dense').tooltip('Editar').mark(f'env-edit-{env["id"]}')

                    def remove(e=env):
                        affected, step_count = set(), 0
                        for s in core.list_items('suites'):
                            if s.get('environment_id') == e['id']:
                                affected.add(s['id'])
                            for step in core.suite_steps(s):
                                if step.get('environment_id') == e['id']:
                                    affected.add(s['id'])
                                    step_count += 1
                        if affected:
                            detail = f' ({step_count} paso(s) con ambiente propio)' if step_count else ''
                            raise ValueError(f'No se puede eliminar: lo usan {len(affected)} suite(s){detail}')
                        core.delete('environments', e['id'])
                        ui.navigate.reload()
                    ui.button(icon='delete', on_click=lambda _, e=env, r=remove: confirm(f'¿Eliminar el ambiente «{e["name"]}»?', r)).props('flat round dense color=negative').tooltip('Eliminar').mark(f'env-delete-{env["id"]}')

        with ui.card().classes('w-full'):
            ui.label('Secretos (almacén seguro del sistema operativo)').classes('text-lg font-semibold')
            ui.label('Se guardan en Windows Credential Manager / Keychain / Secret Service. Úsalos como {{secret:nombre}} o en la autenticación del ambiente.').classes('text-gray-500 text-sm')
            with ui.row().classes('items-end gap-3'):
                secret_name = ui.input('Nombre').props('outlined dense').classes('w-52')
                secret_value = ui.input('Valor', password=True, password_toggle_button=True).props('outlined dense').classes('w-72')

                def store():
                    core.secret_set((secret_name.value or '').strip(), secret_value.value or '')
                    ui.notify('Secreto guardado', type='positive')
                    ui.navigate.reload()
                ui.button('Guardar secreto', icon='lock', on_click=guard(store)).props('outline')
            for secret_item in core.secret_names():
                with ui.row().classes('items-center gap-2'):
                    ui.icon('key', color='grey')
                    ui.label(secret_item).classes('font-mono')
                    ui.label('••••••••').classes('text-gray-400')

                    def drop(n=secret_item):
                        core.secret_delete(n)
                        ui.navigate.reload()
                    ui.button(icon='delete', on_click=lambda _, n=secret_item, r=drop: confirm(f'¿Eliminar el secreto «{n}»?', r)).props('flat round dense color=negative')
