"""Integraciones (Jira / Azure DevOps): configurar cómo adjuntar la evidencia de una corrida a un ticket o work
item, usando credenciales propias del usuario — mismo almacén que la autenticación de un Ambiente
(core.secret_set/secret_get)."""
from nicegui import ui, run
from .. import core, integrations
from .common import frame, guard, confirm, empty_state, require_project

PLATFORM_ICON = {'jira': 'bug_report', 'azdo': 'account_tree'}


@ui.page('/integrations')
def integrations_list():
    with frame('Integraciones', '/integrations'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.button('Nueva integración', icon='add', on_click=lambda: ui.navigate.to('/integrations/edit')).props('color=primary')
        items = core.list_project_items('integrations', pid)
        if not items:
            empty_state('No hay integraciones. Configura Jira o Azure DevOps para adjuntar evidencia a un ticket/work item con un clic.')
        for item in items:
            with ui.card().classes('w-full'):
                with ui.row().classes('items-center gap-3 w-full no-wrap'):
                    ui.icon(PLATFORM_ICON.get(item['platform'], 'extension')).classes('text-2xl')
                    with ui.column().classes('gap-0 grow'):
                        ui.label(item['name']).classes('font-semibold')
                        ui.label(core.INTEGRATION_PLATFORMS.get(item['platform'], item['platform'])).classes('text-sm text-gray-500')

                    async def test(i=item):
                        result = await run.io_bound(integrations.test_connection, i)
                        ui.notify(f'Conexión correcta: {result}', type='positive')
                    ui.button('Probar conexión', icon='wifi_tethering', on_click=guard(test)).props('outline dense no-caps')
                    ui.button(icon='edit', on_click=lambda _, i=item['id']: ui.navigate.to(f'/integrations/edit?id={i}')).props('flat round').tooltip('Editar')

                    def remove(i=item):
                        core.delete('integrations', i['id'])
                        ui.navigate.reload()
                    ui.button(icon='delete', on_click=lambda _, i=item, r=remove: confirm(f'¿Eliminar la integración «{i["name"]}»?', r)).props('flat round color=negative')


@ui.page('/integrations/edit')
def integration_edit(id: str = ''):
    with frame('Integración', '/integrations'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        current = core.get('integrations', id) if id else None
        if id and current is None:
            ui.label('Esta integración ya no existe.')
            return
        config0 = (current or {}).get('config') or {}

        with ui.card().classes('w-full max-w-2xl gap-3'):
            name = ui.input('Nombre', value=(current or {}).get('name', '')).props('outlined dense').classes('w-full')
            platform = ui.select(core.INTEGRATION_PLATFORMS, value=(current or {}).get('platform', 'jira'), label='Plataforma').props('outlined dense').classes('w-60')

            names = core.secret_names()
            secret = ui.select(names, value=config0.get('secret') if config0.get('secret') in names else None,
                               label='Secreto (token API de Jira / PAT de Azure DevOps)', clearable=True).props('outlined dense').classes('w-full')
            ui.label('El valor nunca se guarda en la base ni en exportaciones. Créalo acá o desde «Ambientes» → Secretos.').classes('text-gray-500 text-xs')
            with ui.row().classes('items-end gap-2'):
                new_secret_name = ui.input('Nombre del secreto nuevo').props('outlined dense').classes('w-56')
                new_secret_value = ui.input('Valor', password=True, password_toggle_button=True).props('outlined dense').classes('w-60')

                def store_secret():
                    secret_name = (new_secret_name.value or '').strip()
                    core.secret_set(secret_name, new_secret_value.value or '')
                    secret.set_options(core.secret_names(), value=secret_name)
                    new_secret_name.value, new_secret_value.value = '', ''
                    ui.notify('Secreto guardado', type='positive')
                ui.button('Guardar secreto', icon='lock', on_click=guard(store_secret)).props('outline dense')

            with ui.column().classes('w-full gap-2').bind_visibility_from(platform, 'value', lambda v: v == 'jira'):
                site_url = ui.input('URL del sitio (Jira Cloud)', value=config0.get('site_url', ''), placeholder='https://acme.atlassian.net').props('outlined dense').classes('w-full')
                email = ui.input('Email', value=config0.get('email', '')).props('outlined dense').classes('w-full')
            with ui.column().classes('w-full gap-2').bind_visibility_from(platform, 'value', lambda v: v == 'azdo'):
                organization = ui.input('Organización', value=config0.get('organization', '')).props('outlined dense').classes('w-full')
                azdo_project = ui.input('Proyecto', value=config0.get('project', '')).props('outlined dense').classes('w-full')

            def build_config():
                if platform.value == 'jira':
                    return {'site_url': site_url.value, 'email': email.value, 'secret': secret.value}
                return {'organization': organization.value, 'project': azdo_project.value, 'secret': secret.value}

            def save():
                options = dict(id=(current or {}).get('id'))
                if current:
                    options['expected_updated_at'] = current.get('updated_at')
                core.save_integration(name.value or '', pid, platform.value, build_config(), **options)
                ui.notify('Integración guardada', type='positive')
                ui.navigate.to('/integrations')
            with ui.row().classes('gap-3'):
                ui.button('Guardar', icon='save', on_click=guard(save)).props('color=primary')
                ui.button('Volver', on_click=lambda: ui.navigate.to('/integrations')).props('flat')
