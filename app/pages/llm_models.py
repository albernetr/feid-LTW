from nicegui import run, ui
from .. import core, llm
from .common import frame, guard, confirm, empty_state, protected_page


@protected_page('/models')
def models_list():
    with frame('Modelos de IA', '/models'):
        ui.label('Registra aquí cada modelo al que te puedas conectar (local o en la nube); después elígelo desde «Usar este», '
                  'o desde el selector de la pestaña Agente del Espacio de trabajo, sin volver a pegar URL ni clave.').classes('text-sm text-gray-500')
        ui.button('Nuevo modelo', icon='add', on_click=lambda: ui.navigate.to('/models/edit')).props('color=primary')

        profiles = llm.list_profiles()
        active_id = llm.active_profile_id()
        if not profiles:
            empty_state('No hay modelos registrados todavía.')
            return

        def activate(profile_id, name):
            def attempt():
                try:
                    llm.activate_profile(profile_id)
                    ui.notify(f'«{name}» es ahora el modelo activo', type='positive')
                    ui.navigate.reload()
                except (llm.LLMError, ValueError) as exc:
                    ui.notify(str(exc), type='negative', multi_line=True)
            attempt()

        def remove(profile_id, name):
            def attempt():
                llm.delete_profile(profile_id)
                ui.notify(f'«{name}» eliminado', type='positive')
                ui.navigate.reload()
            confirm(f'¿Eliminar el modelo «{name}» y su clave guardada?', attempt)

        columns = [
            {'name': 'name', 'label': 'Nombre', 'field': 'name', 'align': 'left', 'sortable': True},
            {'name': 'preset', 'label': 'Proveedor', 'field': 'preset', 'align': 'left'},
            {'name': 'model', 'label': 'Modelo', 'field': 'model', 'align': 'left'},
            {'name': 'scope', 'label': 'Alcance', 'field': 'scope', 'align': 'center'},
            {'name': 'active', 'label': 'En uso', 'field': 'active', 'align': 'center'},
            {'name': 'actions', 'label': '', 'field': 'id', 'align': 'right'},
        ]

        def rows():
            return [{'id': p['id'], 'name': p['name'], 'preset': llm.PRESETS.get(p['preset'], {}).get('label', p['preset']),
                     'model': p['model'], 'scope': 'Local' if llm.is_local(p['base_url']) else 'Nube', 'active': p['id'] == active_id}
                    for p in profiles]

        table = ui.table(columns=columns, rows=rows(), row_key='id', pagination=15).classes('w-full').mark('models-table')
        table.props('flat bordered')
        table.add_slot('body-cell-scope', r'''
            <q-td :props="props">
                <q-badge :color="props.value === 'Local' ? 'teal' : 'orange'">{{ props.value }}</q-badge>
            </q-td>
        ''')
        table.add_slot('body-cell-active', r'''
            <q-td :props="props">
                <q-badge v-if="props.value" color="positive">En uso</q-badge>
                <span v-else class="text-grey-5">—</span>
            </q-td>
        ''')
        table.add_slot('body-cell-actions', r'''
            <q-td :props="props" class="text-right" @click.stop>
                <q-btn v-if="!props.row.active" flat dense round icon="bolt" color="primary" @click="$parent.$emit('activate', props.row)">
                    <q-tooltip>Usar este modelo</q-tooltip>
                </q-btn>
                <q-btn flat dense round icon="edit" color="grey-8" @click="$parent.$emit('editModel', props.row)">
                    <q-tooltip>Editar</q-tooltip>
                </q-btn>
                <q-btn flat dense round icon="delete" color="negative" @click="$parent.$emit('deleteModel', props.row)">
                    <q-tooltip>Eliminar</q-tooltip>
                </q-btn>
            </q-td>
        ''')
        table.on('activate', lambda e: activate(e.args['id'], e.args['name']))
        table.on('editModel', lambda e: ui.navigate.to(f'/models/edit?id={e.args["id"]}'))
        table.on('deleteModel', lambda e: remove(e.args['id'], e.args['name']))
        ui.label('El modelo «en uso» es el que de verdad consulta la pestaña Agente del Espacio de trabajo.').classes('text-xs text-gray-500')


@protected_page('/models/edit')
def model_edit(id: str = ''):
    with frame('Modelo' if id else 'Nuevo modelo', '/models'):
        current = llm.get_profile(id) if id else None
        if id and current is None:
            ui.label('Este modelo ya no existe.').classes('text-amber-700')
            return
        ui.link('← Volver a Modelos', '/models').classes('text-sm')

        with ui.card().classes('w-full'):
            ui.label(current['name'] if current else 'Nuevo modelo').classes('text-xl font-semibold')
            ui.label('Las suscripciones de chat (Claude Max, ChatGPT Plus) no incluyen clave de API; hace falta una clave de API '
                     'o un modelo local.').classes('text-xs text-gray-500')
            ui.separator().classes('my-2')
            cfg = current or {'preset': 'ollama', 'protocol': 'openai', 'base_url': llm.PRESETS['ollama']['base_url'],
                               'model': llm.PRESETS['ollama']['model'], 'auth': 'none', 'allow_cloud': False, 'timeout': 120}
            name = ui.input('Nombre', value=(current or {}).get('name', ''), placeholder='P. ej. «Foundry — GPT-6-Astra»').props('outlined dense').classes('w-full')
            preset = ui.select({k: v['label'] for k, v in llm.PRESETS.items()}, value=cfg['preset'] if cfg['preset'] in llm.PRESETS else 'custom', label='Proveedor').props('outlined dense').classes('w-full')
            protocol = ui.select(llm.PROTOCOLS, value=cfg['protocol'], label='Protocolo').props('outlined dense').classes('w-full')
            url = ui.input('URL base', value=cfg['base_url']).props('outlined dense').classes('w-full')
            model = ui.input('Modelo (o nombre del despliegue)', value=cfg['model']).props('outlined dense').classes('w-full')
            auth = ui.select(llm.AUTH_STYLES, value=cfg['auth'], label='Autenticación').props('outlined dense').classes('w-full')
            key = ui.input('Clave de API', password=True, password_toggle_button=True,
                            placeholder='(vacía = conservar la guardada)' if current else '').props('outlined dense').classes('w-full')
            cloud = ui.switch('Permitir enviar datos fuera de esta máquina', value=cfg['allow_cloud'])
            timeout = ui.number('Tiempo de espera (s)', value=cfg['timeout'], min=5, max=600, step=10).props('outlined dense').classes('w-40')

            def on_preset(event):
                chosen = llm.PRESETS[event.value]
                protocol.set_value(chosen['protocol'])
                auth.set_value(chosen['auth'])
                if chosen['base_url']:
                    url.set_value(chosen['base_url'])
                model.set_value(chosen['model'])
            preset.on_value_change(on_preset)

            def current_form():
                return {'id': (current or {}).get('id'), 'name': name.value, 'preset': preset.value, 'protocol': protocol.value,
                        'base_url': url.value, 'model': model.value, 'auth': auth.value, 'allow_cloud': cloud.value, 'timeout': timeout.value}

            def save():
                llm.save_profile(current_form(), api_key=key.value or None)
                ui.notify('Modelo guardado', type='positive')
                ui.navigate.to('/models')

            async def probe():
                form = current_form()
                override = key.value or (core.secret_get(llm.profile_secret_name(form['id'])) if form['id'] else None)
                probe_config = {k: form[k] for k in llm.PROFILE_FIELDS}
                try:
                    result = await run.io_bound(llm.test_connection, probe_config, override)
                    ui.notify(f'Conexión correcta · {result["summary"]}', type='positive')
                except llm.LLMError as exc:
                    ui.notify(str(exc), type='negative', multi_line=True)

            ui.separator().classes('my-2')
            with ui.row().classes('gap-2'):
                ui.button('Guardar modelo', icon='save', on_click=guard(save)).props('color=primary')
                ui.button('Probar conexión', icon='bolt', on_click=guard(probe)).props('outline')
                ui.button('Cancelar', on_click=lambda: ui.navigate.to('/models')).props('flat')
