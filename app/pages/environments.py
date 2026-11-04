import json
from nicegui import run, ui
from .. import core
from .common import frame, guard, confirm, empty_state, require_project, kv_editor, protected_page

AUTH_LABELS = {'none': 'Sin autenticación', 'bearer': 'Bearer', 'api_key': 'API Key'}


def _delete_environment(env_id, env_name, on_done):
    def attempt():
        affected, step_count = set(), 0
        for s in core.list_items('suites'):
            if s.get('environment_id') == env_id:
                affected.add(s['id'])
            for step in core.suite_steps(s):
                if step.get('environment_id') == env_id:
                    affected.add(s['id'])
                    step_count += 1
        if affected:
            detail = f' ({step_count} paso(s) con ambiente propio)' if step_count else ''
            ui.notify(f'No se puede eliminar: lo usan {len(affected)} flujo(s){detail}', type='negative', multi_line=True)
            return
        core.delete('environments', env_id)
        ui.notify('Ambiente eliminado', type='positive')
        on_done()
    confirm(f'¿Eliminar el ambiente «{env_name}»?', attempt)


@protected_page('/environments')
def environments_list():
    with frame('Ambientes y secretos', '/environments'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        items = core.list_project_items('environments', pid)

        ui.button('Nuevo ambiente', icon='add', on_click=lambda: ui.navigate.to('/environments/edit')).props('color=primary')

        if not items:
            empty_state('No hay ambientes en este proyecto.')
        else:
            columns = [
                {'name': 'name', 'label': 'Nombre', 'field': 'name', 'align': 'left', 'sortable': True},
                {'name': 'base_url', 'label': 'URL base', 'field': 'base_url', 'align': 'left'},
                {'name': 'kind', 'label': 'Tipo', 'field': 'kind', 'align': 'center'},
                {'name': 'auth', 'label': 'Autenticación', 'field': 'auth', 'align': 'left'},
                {'name': 'variables', 'label': 'Variables', 'field': 'variables', 'align': 'center'},
                {'name': 'actions', 'label': '', 'field': 'id', 'align': 'right'},
            ]

            def rows():
                return [{'id': e['id'], 'name': e['name'], 'base_url': e['base_url'], 'kind': core.environment_kind_label(e),
                        'auth': AUTH_LABELS.get(e['auth']['type'], e['auth']['type']),
                        'variables': len(e.get('variables') or {})} for e in items]

            table = ui.table(columns=columns, rows=rows(), row_key='id', pagination=15).classes('w-full').mark('environments-table')
            table.props('flat bordered')
            table.add_slot('body-cell-base_url', '''<q-td :props="props"><span class="font-mono text-sm text-gray-700">{{ props.value }}</span></q-td>''')
            table.add_slot('body-cell-kind', r'''
                <q-td :props="props">
                    <q-badge :color="props.value === 'Frontend' ? 'purple' : (props.value === 'Backend' ? 'blue-grey' : 'teal')">{{ props.value }}</q-badge>
                </q-td>
            ''')
            table.add_slot('body-cell-auth', '''<q-td :props="props"><q-badge color="grey-6">{{ props.value }}</q-badge></q-td>''')
            table.add_slot('body-cell-variables', r'''
                <q-td :props="props">
                    <q-chip v-if="props.value" dense size="sm" color="blue-1" text-color="dark">{{ props.value }}</q-chip>
                    <span v-else class="text-grey-5">—</span>
                </q-td>
            ''')
            table.add_slot('body-cell-actions', r'''
                <q-td :props="props" class="text-right" @click.stop>
                    <q-btn flat dense round icon="edit" color="grey-8" @click="$parent.$emit('editEnv', props.row)">
                        <q-tooltip>Editar</q-tooltip>
                    </q-btn>
                    <q-btn flat dense round icon="delete" color="negative" @click="$parent.$emit('deleteEnv', props.row)">
                        <q-tooltip>Eliminar</q-tooltip>
                    </q-btn>
                </q-td>
            ''')
            table.on('rowClick', lambda e: ui.navigate.to(f'/environments/edit?id={e.args[1]["id"]}'))
            table.on('editEnv', lambda e: ui.navigate.to(f'/environments/edit?id={e.args["id"]}'))
            table.on('deleteEnv', lambda e: _delete_environment(e.args['id'], e.args['name'], ui.navigate.reload))
            ui.label('Haz clic en una fila (o en editar) para ver el detalle; elimina directamente con el icono.').classes('text-sm text-gray-500')

        with ui.card().classes('w-full mt-2'):
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
            names = core.secret_names()
            if names:
                with ui.row().classes('w-full gap-2 flex-wrap mt-2'):
                    for secret_item in names:
                        def drop(n=secret_item):
                            core.secret_delete(n)
                            ui.navigate.reload()
                        with ui.row().classes('items-center gap-1 border rounded px-2 py-1'):
                            ui.icon('key', color='grey').classes('text-sm')
                            ui.label(secret_item).classes('font-mono text-sm')
                            ui.button(icon='close', on_click=lambda _, n=secret_item, r=drop: confirm(f'¿Eliminar el secreto «{n}»?', r)).props('flat round dense size=sm color=negative')


@protected_page('/environments/edit')
def environment_edit(id: str = ''):
    with frame('Ambiente' if id else 'Nuevo ambiente', '/environments'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        current = core.get('environments', id) if id else None
        if id and current is None:
            ui.label('Este ambiente ya no existe.').classes('text-amber-700')
            return
        if current and current.get('project_id') != pid:
            ui.notify('Ese ambiente no pertenece al proyecto activo; no se puede editar desde aquí.', type='warning')
            current = None
        ui.link('← Volver a Ambientes', '/environments').classes('text-sm')

        variables = dict((current or {}).get('variables', {}))
        auth0 = (current or {}).get('auth', {'type': 'none'})

        with ui.card().classes('w-full'):
            ui.label(current['name'] if current else 'Nuevo ambiente').classes('text-xl font-semibold')
            ui.separator().classes('my-2')
            with ui.row().classes('w-full gap-3'):
                name = ui.input('Nombre', value=(current or {}).get('name', 'QA')).props('outlined dense').classes('w-60').mark('env-name')
                base = ui.input('URL base (API)', value=(current or {}).get('base_url', ''), placeholder='https://qa.ejemplo.com').props('outlined dense').classes('grow').mark('env-base-url')
            ui_base = ui.input('URL base de la interfaz (si es distinta; opcional)', value=(current or {}).get('ui_base_url', '')).props('outlined dense').classes('w-full').mark('env-ui-base-url')
            backend0, frontend0 = core.environment_flags(current) if current else (True, True)
            with ui.row().classes('items-center gap-4'):
                env_backend = ui.checkbox('Sirve backend (API)', value=backend0).mark('env-is-backend')
                env_frontend = ui.checkbox('Sirve frontend (UI)', value=frontend0).mark('env-is-frontend')
            ui.label('P. ej. un servidor de desarrollo de frontend (localhost:4200) normalmente no sirve API: desmarca «backend» para que no se ofrezca '
                     'en la exploración automática de un contrato.').classes('text-xs text-gray-500')
            auth = ui.select({'none': 'Sin autenticación', 'bearer': 'Bearer token', 'api_key': 'API Key'}, value=auth0.get('type', 'none'), label='Autenticación').props('outlined dense').classes('w-60')
            names = core.secret_names()
            with ui.column().classes('w-full gap-2').bind_visibility_from(auth, 'value', lambda v: v != 'none'):
                with ui.row().classes('gap-3 w-full'):
                    secret = ui.select(names, value=auth0.get('secret') if auth0.get('secret') in names else None, label='Secreto guardado en el sistema', clearable=True).props('outlined dense').classes('w-72')
                    envvar = ui.input('…o variable de entorno', value=auth0.get('env_var', ''), placeholder='QA_TOKEN').props('outlined dense').classes('w-60')
                    header_name = ui.input('Header (solo API Key)', value=auth0.get('header', 'X-API-Key')).props('outlined dense').classes('w-48')
                ui.label('El valor nunca se guarda en la base ni en exportaciones. Créalo en «Secretos» desde la lista de ambientes.').classes('text-gray-500 text-sm')

                ui.separator().classes('my-2')
                refresh0 = auth0.get('refresh') or {}

                def words(v=None):
                    """'clave' (fem.) para API Key, 'token' (masc.) para Bearer — ambos son técnicamente lo
                    mismo (un valor guardado que se inyecta en un header), pero llamarlo «token» en los dos
                    confunde: una API Key casi siempre es estática (se pega desde un panel), un Bearer casi
                    siempre se obtiene por login. El mecanismo de abajo sigue siendo el mismo para ambos a
                    propósito; solo cambia cómo se nombra, con la concordancia de género correcta."""
                    is_key = (v or auth.value) == 'api_key'
                    noun = 'clave' if is_key else 'token'
                    return {'noun': noun, 'el': 'la' if is_key else 'el', 'al': 'a la' if is_key else 'al',
                            'del': 'de la' if is_key else 'del', 'ado': 'a' if is_key else 'o'}

                with ui.row().classes('items-center gap-2'):
                    ui.icon('autorenew', color='primary')
                    ui.label(f'Obtención de {words()["noun"]} (opcional)').classes('font-medium') \
                        .bind_text_from(auth, 'value', lambda v: f'Obtención de {words(v)["noun"]} (opcional)')
                ui.label(f'Describe cómo conseguir {words()["el"]} {words()["noun"]} aunque no quieras que corra solo: déjalo en blanco '
                         'si no aplica, o complétalo para poder pedirlo con el botón de abajo cuando lo necesites.').classes('text-xs text-gray-500') \
                    .bind_text_from(auth, 'value', lambda v: f'Describe cómo conseguir {words(v)["el"]} {words(v)["noun"]} aunque no quieras que corra solo: '
                                     'déjalo en blanco si no aplica, o complétalo para poder pedirlo con el botón de abajo cuando lo necesites.')
                refresh_auto = ui.checkbox(f'Además, actualizar {words()["el"]} {words()["noun"]} automáticamente si falta, expira, o el servicio responde 401',
                                           value=refresh0.get('enabled', True)).mark('env-refresh-auto') \
                    .bind_text_from(auth, 'value', lambda v: f'Además, actualizar {words(v)["el"]} {words(v)["noun"]} automáticamente '
                                     'si falta, expira, o el servicio responde 401')
                refresh_mode = ui.select({'http': 'Petición HTTP', 'command': 'Comando del sistema'},
                                         value=refresh0.get('mode', 'http'), label='Mecanismo').props('outlined dense').classes('w-60').mark('env-refresh-mode')
                with ui.column().classes('w-full gap-2').bind_visibility_from(refresh_mode, 'value', lambda v: v == 'http'):
                    with ui.row().classes('w-full gap-3'):
                        refresh_method = ui.select(['GET', 'POST', 'PUT'], value=refresh0.get('method', 'POST'), label='Método').props('outlined dense').classes('w-32')
                        refresh_url = ui.input(f'URL del endpoint de {words()["noun"]}', value=refresh0.get('url', ''), placeholder='https://auth.ejemplo.com/oauth/token') \
                            .props('outlined dense').classes('grow').mark('env-refresh-url')
                        auth.on_value_change(lambda e: refresh_url.props(f'label="URL del endpoint de {words(e.value)["noun"]}"'))
                    ui.label('Headers y body admiten {{variables}} y {{secret:NOMBRE}} (p. ej. client_id/client_secret guardados aparte).').classes('text-xs text-gray-500')
                    refresh_headers = dict(refresh0.get('headers') or {})
                    kv_editor(refresh_headers, 'Header', 'Valor')
                    refresh_body = ui.textarea('Body (JSON, opcional)',
                                               value=json.dumps(refresh0['body'], ensure_ascii=False) if refresh0.get('body') is not None else '') \
                        .props('outlined dense autogrow').classes('w-full font-mono').mark('env-refresh-body')
                    with ui.row().classes('w-full gap-3'):
                        refresh_token_path = ui.input(f'Ruta JSONPath {words()["al"]} {words()["noun"]}', value=refresh0.get('token_path', '$.access_token')) \
                            .props('outlined dense').classes('grow').mark('env-refresh-token-path')
                        auth.on_value_change(lambda e: refresh_token_path.props(f'label="Ruta JSONPath {words(e.value)["al"]} {words(e.value)["noun"]}"'))
                        refresh_expires_path = ui.input('Ruta JSONPath a la duración en segundos (opcional)', value=refresh0.get('expires_path', '')) \
                            .props('outlined dense').classes('grow').mark('env-refresh-expires-path')
                with ui.column().classes('w-full gap-2').bind_visibility_from(refresh_mode, 'value', lambda v: v == 'command'):
                    with ui.row().classes('items-center gap-2 bg-amber-50 rounded px-3 py-2 w-full'):
                        ui.icon('warning', color='warning')
                        ui.label('El scheduler ejecuta este comando sin supervisión, en esta máquina. Úsalo solo con scripts de confianza.').classes('text-sm text-amber-800')
                    refresh_command = ui.input('Comando', value=refresh0.get('command', ''), placeholder='mi-cli login --print-token') \
                        .props('outlined dense').classes('w-full font-mono').mark('env-refresh-command')
                refresh_target = ui.input(f'Guardar {words()["el"]} {words()["noun"]} en este secreto (vacío = el mismo de arriba)', value=refresh0.get('target_secret', '')) \
                    .props('outlined dense').classes('w-full').mark('env-refresh-target')
                auth.on_value_change(lambda e: refresh_target.props(
                    f'label="Guardar {words(e.value)["el"]} {words(e.value)["noun"]} en este secreto (vacío = el mismo de arriba)"'))

                def collect_refresh_config():
                    """None if nothing was filled in — left blank is a valid 'no obtención automática' state,
                    not an error."""
                    if refresh_mode.value == 'command':
                        if not (refresh_command.value or '').strip():
                            return None
                        cfg = {'mode': 'command', 'command': refresh_command.value.strip()}
                    else:
                        if not (refresh_url.value or '').strip():
                            return None
                        core.validate_base_url(refresh_url.value)
                        if not (refresh_token_path.value or '').strip():
                            w = words()
                            raise ValueError(f'Escribe la ruta JSONPath {w["del"]} {w["noun"]} (p. ej. $.access_token).')
                        cfg = {'mode': 'http', 'method': refresh_method.value, 'url': refresh_url.value.strip(),
                               'headers': {k: v for k, v in refresh_headers.items() if k.strip()},
                               'token_path': refresh_token_path.value.strip()}
                        body_text = (refresh_body.value or '').strip()
                        if body_text:
                            try:
                                cfg['body'] = json.loads(body_text)
                            except ValueError:
                                raise ValueError(f'El body de actualización de {words()["noun"]} no es JSON válido.')
                        if (refresh_expires_path.value or '').strip():
                            cfg['expires_path'] = refresh_expires_path.value.strip()
                    cfg['target_secret'] = (refresh_target.value or '').strip()
                    cfg['enabled'] = refresh_auto.value
                    return cfg

                async def test_refresh():
                    w = words()
                    if not current:
                        raise ValueError(f'Guarda el ambiente primero para poder obtener {w["el"]} {w["noun"]}.')
                    cfg = collect_refresh_config()
                    if not cfg:
                        raise ValueError(f'Configura cómo se obtiene {w["el"]} {w["noun"]} antes de probarlo.')
                    probe = {**current, 'auth': {**current.get('auth', {}), 'refresh': cfg}}
                    token = await run.io_bound(core.refresh_token, probe, {})
                    noun_cap = w['noun'].capitalize()
                    ui.notify(f'{noun_cap} actualizad{w["ado"]}: termina en «…{token[-4:]}».' if len(token) > 4 else f'{noun_cap} actualizad{w["ado"]}.', type='positive')
                refresh_test_btn = ui.button(f'Obtener {words()["noun"]} ahora', icon='play_arrow', on_click=guard(test_refresh)).props('outline dense').mark('env-refresh-test')
                auth.on_value_change(lambda e: refresh_test_btn.props(f'label="Obtener {words(e.value)["noun"]} ahora"'))

            ui.separator().classes('my-2')
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
                if not env_backend.value and not env_frontend.value:
                    raise ValueError('El ambiente debe servir backend, frontend, o ambos')
                clean = {k: v for k, v in variables.items() if k.strip()}
                auth_item = {'type': auth.value, 'secret': secret.value or '', 'env_var': (envvar.value or '').strip(), 'header': header_name.value or 'X-API-Key'}
                refresh_cfg = collect_refresh_config() if auth.value != 'none' else None
                if refresh_cfg:
                    auth_item['refresh'] = refresh_cfg
                    if current and current.get('auth', {}).get('token_expires_at') and current['auth'].get('refresh') == refresh_cfg:
                        auth_item['token_expires_at'] = current['auth']['token_expires_at']  # unchanged config: keep what we already know
                item = {'name': clean_name, 'project_id': pid, 'base_url': base.value.strip(), 'ui_base_url': (ui_base.value or '').strip(),
                        'is_backend': env_backend.value, 'is_frontend': env_frontend.value, 'auth': auth_item, 'variables': clean}
                if current:
                    item['id'] = current['id']
                core.save('environments', item)
                ui.notify('Ambiente guardado', type='positive')
                ui.navigate.to('/environments')
            ui.separator().classes('my-2')
            with ui.row().classes('gap-2'):
                ui.button('Guardar ambiente', icon='save', on_click=guard(save)).props('color=primary').mark('env-save')
                ui.button('Cancelar', on_click=lambda: ui.navigate.to('/environments')).props('flat')
