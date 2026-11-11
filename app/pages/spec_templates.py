import re
from nicegui import ui
from .. import core, spec_report
from .common import frame, guard, confirm, empty_state, require_project, open_evidence_in_new_tab, protected_page, remembered, doc_typography, live_doc_html, typography_button

KIND_LABELS = {'input': 'Entrada', 'output': 'Salida'}
APPLIES_LABELS = {'user_story': 'Historia de usuario', 'test_case': 'Caso de prueba', 'report': 'Reporte'}

# Nombres legibles de los campos FIJOS conocidos (core.KNOWN_FIELDS_BY_APPLIES_TO) — solo para el selector
# "Campo existente" del editor; no es un contrato de datos, por eso vive acá y no en core.py.
KNOWN_FIELD_LABELS = {
    'user_story': {'title': 'Título', 'feature_id': 'Funcionalidad', 'priority': 'Prioridad', 'status': 'Estado',
                  'as_a': 'Como (rol)', 'i_want': 'Quiero (acción)', 'so_that': 'Para (beneficio)', 'content': 'Contenido (formato libre)',
                  'criteria': 'Criterios de aceptación', 'given': 'Dado (contexto inicial)', 'when': 'Cuando (acción)', 'then': 'Entonces (resultado esperado)',
                  'definition_of_ready': 'Definición de Listo', 'definition_of_done': 'Definición de Hecho',
                  'business_rules': 'Reglas de negocio', 'assumptions': 'Supuestos', 'risks': 'Riesgos', 'out_of_scope': 'Fuera de alcance',
                  'story_points': 'Story points', 'assigned_to': 'Asignado a', 'depends_on': 'Depende de'},
    'test_case': {'title': 'Título', 'story_id': 'Historia de usuario', 'feature_id': 'Funcionalidad', 'linked_case_id': 'Caso API/UI automatizado',
                  'preconditions': 'Precondición', 'steps': 'Pasos de ejecución', 'expected': 'Resultado esperado', 'priority': 'Prioridad', 'type': 'Tipo'},
    'report': {'story': 'Historia de usuario', 'as_a': 'Como (rol)', 'i_want': 'Quiero (acción)', 'so_that': 'Para (beneficio)',
              'content': 'Contenido (formato libre)', 'criteria': 'Criterios de aceptación', 'definition_of_ready': 'Definición de Listo',
              'definition_of_done': 'Definición de Hecho', 'business_rules': 'Reglas de negocio', 'assumptions': 'Supuestos',
              'business_risks': 'Riesgos (redactados)', 'out_of_scope': 'Fuera de alcance', 'dependencies': 'Depende de',
              'test_cases': 'Casos de prueba', 'traceability': 'Trazabilidad', 'matrix': 'Matriz HU → Casos → Estado',
              'summary': 'Resumen', 'coverage': 'Cobertura', 'risks': 'Riesgos (calculados)', 'story_points': 'Story points',
              'assigned_to': 'Asignado a', 'preconditions': 'Precondición', 'steps': 'Pasos de ejecución', 'expected': 'Resultado esperado',
              'priority': 'Prioridad', 'type': 'Tipo'},
}
CUSTOM_SENTINEL = '__custom__'
SUGGEST_PREFIX = '__suggest__'

# Íconos curados para una SECCIÓN (nodo 'group') — el riel dinámico de Historia de usuario/Caso de prueba
# (ver core.template_top_level_groups) usa este ícono para su pestaña; sin elegir uno, cae a 'folder'.
_ICON_SEP = '@@'   # ver el comentario junto a icon_select más abajo — nunca llega a pantalla
GROUP_ICON_OPTIONS = {
    'folder': 'Carpeta (general)', 'edit_note': 'Notas', 'description': 'Documento', 'checklist': 'Lista',
    'fact_check': 'Validación', 'business_center': 'Negocio', 'science': 'Ciencia / pruebas',
    'flag': 'Bandera', 'bookmark': 'Marcador', 'label': 'Etiqueta', 'build': 'Herramientas',
    'security': 'Seguridad', 'insights': 'Métricas',
}


def _slug(label):
    return re.sub(r'[^a-z0-9]+', '_', (label or '').strip().lower()).strip('_') or core.uid()


def _new_field_node():
    return {'id': core.uid(), 'kind': 'field', 'label': '', 'field_key': '', 'field_type': 'text', 'width': 'full'}


def _new_group_node():
    return {'id': core.uid(), 'kind': 'group', 'label': 'Nueva sección', 'width': 'full', 'as_tab': False, 'children': []}


@protected_page('/spec-templates')
def spec_templates_list():
    with frame('Plantillas', '/spec-templates', doc_style=True):
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
    title_text = 'Plantilla' if id else 'Nueva plantilla'
    with frame(title_text, '/spec-templates', full_width=True, doc_style=True):
        if not require_project():
            return
        pid = core.get_active_project_id()
        # Mismo layout que Historias de usuario (ver user_stories.py::story_detail): documento/vista previa al
        # centro-izquierda, "Campos" (acá: Configuración) a la derecha en pestañas con riel de íconos, separador
        # ajustable, colapsable con un clic en el ícono ya activo (estilo VS Code), y modo compacto/scroll completo.
        compact, set_compact = remembered('template_layout_compact', default=True)
        main_split_value, set_main_split_value_pref = remembered('template_split_width', default=75)
        S = {'active_field_tab': 'general', 'fields_collapsed': False}

        def handle_rail_click(key):
            if S['active_field_tab'] == key:
                S['fields_collapsed'] = not S['fields_collapsed']
            else:
                S['active_field_tab'] = key
                S['fields_collapsed'] = False
            field_panels.set_visibility(not S['fields_collapsed'])
            if S['fields_collapsed']:
                S['split_before_collapse'] = main_split.value
                main_split.set_value(95)
            else:
                main_split.set_value(S.get('split_before_collapse', main_split_value))

        current = core.get('spec_templates', id) if id else None
        if id and current is None:
            with ui.column().classes('w-full p-4 gap-2'):
                ui.link('← Volver a Plantillas', '/spec-templates').classes('text-sm')
                ui.label('Esta plantilla ya no existe.').classes('text-amber-700')
            return
        is_global = bool(current) and current.get('project_id') is None
        is_mine = bool(current) and current.get('project_id') == pid
        disabled = is_global

        # normalize_template_body: una plantilla guardada ANTES de este esquema (sobre todo una global, que
        # nunca se vuelve a guardar sola) puede seguir teniendo nodos planos viejos sin 'kind' — normalizar acá
        # garantiza que render_node (que sí asume la forma de árbol) nunca reciba uno crudo.
        d = {'body': core.normalize_template_body((current or {}).get('body', []), (current or {}).get('applies_to', 'report'))}

        def _refresh():
            # body_rows/document_view se definen más abajo en esta misma función — Python resuelve nombres de
            # alcance envolvente en el momento de la LLAMADA, no en el de la definición de este closure (mismo
            # patrón ya usado en user_stories.py entre criteria_rows y document_view), así que referenciarlos
            # acá arriba es seguro siempre que ya existan cuando el usuario de verdad haga clic en algo.
            body_rows.refresh()
            document_view.refresh()

        def toggle_compact():
            set_compact(not compact)
            ui.navigate.reload()

        def preview():
            draft = {'name': name.value or 'Vista previa', 'applies_to': applies_to.value, 'body': d['body']}
            html_text = spec_report.render_spec_html(spec_report.build_template_preview(draft))
            filename = f'{(current or {}).get("id", "draft")}-template-preview.html'
            (core.ARTIFACTS / filename).write_text(html_text, encoding='utf-8')
            open_evidence_in_new_tab((current or {}).get('id', 'draft'), filename)

        with ui.column().classes('w-full p-4 gap-4 ltw-doc'):
            with ui.row().classes('w-full items-center justify-between no-wrap'):
                with ui.row().classes('items-center gap-2'):
                    with ui.column().classes('gap-0'):
                        ui.link('← Volver a Plantillas', '/spec-templates').classes('text-sm')
                        ui.label(current['name'] if current else 'Nueva plantilla').classes('ltw-doc-title text-2xl font-semibold')
                        if is_global:
                            ui.badge('Global — solo lectura, adoptala para editarla', color='primary')
                    ui.button(icon='open_in_new', on_click=guard(preview)).props('flat round dense').mark('template-preview') \
                        .tooltip('Vista previa con datos de ejemplo, en una pestaña nueva')
                with ui.row().classes('gap-1 shrink-0'):
                    ui.button(icon='fullscreen_exit' if compact else 'fullscreen', on_click=toggle_compact) \
                        .props('flat round dense').mark('template-toggle-compact') \
                        .tooltip('Cambiar a modo con scroll completo' if compact else 'Cambiar a modo compacto (sin scroll, ancho completo)')
                    typography_button(lambda: document_view.refresh())

            with ui.element('div').classes('w-full').style('height: calc(100vh - 210px)' if compact else ''):
                with ui.splitter(value=main_split_value, limits=(40, 96), on_change=lambda e: set_main_split_value_pref(e.value)) \
                        .classes('w-full').style('height:100%' if compact else '') as main_split:
                    with main_split.after:
                        with ui.column().classes('w-full gap-4').style('height:100%;overflow:auto' if compact else ''):
                            with ui.card().classes('w-full p-0').style('overflow:visible' if compact else ''):
                                with ui.row().classes('items-center gap-2 p-4 pb-0'):
                                    ui.icon('tune', color='primary').classes('text-2xl')
                                    ui.label('Configuración').classes('text-xl font-semibold')

                                with ui.row().classes('w-full no-wrap gap-0').style('min-height:420px;justify-content:flex-end'):
                                    with ui.tab_panels(None, value='general').props('vertical').style('flex:1 1 0;min-width:0;padding:16px') as field_panels:
                                        with ui.tab_panel('general').classes('gap-3 p-0'):
                                            name = ui.input('Nombre', value=(current or {}).get('name', '')).props('outlined dense').classes('w-full').mark('template-name')
                                            description = ui.textarea('Descripción (opcional)', value=(current or {}).get('description', '')).props('outlined dense autogrow').classes('w-full')
                                            with ui.row().classes('w-full gap-3'):
                                                kind = ui.select(KIND_LABELS, value=(current or {}).get('kind', 'input'), label='Tipo').props('outlined dense').classes('grow').mark('template-kind')
                                                applies_to = ui.select(APPLIES_LABELS, value=(current or {}).get('applies_to', 'user_story'), label='Aplica a').props('outlined dense').classes('grow').mark('template-applies-to')
                                            if disabled:
                                                name.disable(); description.disable(); kind.disable(); applies_to.disable()

                                        with ui.tab_panel('sections').classes('gap-3 p-0'):
                                            with ui.row().classes('items-center justify-between w-full'):
                                                ui.label('Secciones y campos').classes('font-semibold')
                                                ui.icon('info', size='xs', color='grey').classes('cursor-help').tooltip(
                                                    'Un «campo existente» ya tiene su propio editor (Como/Quiero/Para, criterios, pasos, ...) y no '
                                                    'declara tipo. Un «campo nuevo» lo define esta plantilla: elegí qué tipo de dato es. Una '
                                                    '«sección» agrupa campos (o subsecciones, anidables) bajo un nombre. Cualquier campo o sección '
                                                    'puede ser Ancho completo o Mitad — dos nodos hermanos consecutivos en Mitad quedan lado a lado, '
                                                    'tanto en el panel de Campos como en el documento; en una plantilla de salida, además puede '
                                                    'mostrarse como pestaña propia en el visor interactivo.')

                                            @ui.refreshable
                                            def body_rows():
                                                is_output = kind.value == 'output'
                                                known = core.KNOWN_FIELDS_BY_APPLIES_TO.get(applies_to.value, ())
                                                labels = KNOWN_FIELD_LABELS.get(applies_to.value, {})
                                                # Una plantilla de SALIDA puede sugerir reusar un campo custom que ya
                                                # existe en alguna plantilla de ENTRADA del proyecto, en vez de que
                                                # quien la edita tenga que escribir a mano un field_key y confiar en
                                                # que coincida — ver core.custom_field_catalog.
                                                suggestions = core.custom_field_catalog(pid) if is_output else []

                                                def render_node(node, siblings, index, depth):
                                                    def move(delta, siblings=siblings, index=index):
                                                        j = index + delta
                                                        if 0 <= j < len(siblings):
                                                            siblings[index], siblings[j] = siblings[j], siblings[index]
                                                            _refresh()

                                                    with ui.column().classes('w-full gap-1').style(f'margin-left:{depth * 28}px'):
                                                        with ui.row().classes('items-center gap-2 w-full no-wrap'):
                                                            ui.icon((node.get('icon') or 'folder') if node['kind'] == 'group' else 'description', size='sm', color='grey')
                                                            ui.input('Etiqueta', value=node.get('label', '')).props('outlined dense').classes('grow') \
                                                                .mark('template-node-label').on_value_change(lambda e, node=node: node.__setitem__('label', e.value)) \
                                                                .on('blur', lambda: document_view.refresh())
                                                            if node['kind'] == 'group':
                                                                # 'option'/'selected-item': la lista (y el valor ya elegido) muestran el ícono real
                                                                # junto al nombre, no solo texto. OJO: para un ui.select con `options` dict, NiceGUI
                                                                # NUNCA manda la CLAVE al cliente — solo {value: índice, label: texto} (ver
                                                                # ChoiceElement._update_options) — así que `props.opt.value` es un índice, no 'folder'.
                                                                # Por eso el nombre del ícono va codificado DENTRO del label (separador IICON_SEP,
                                                                # nunca se muestra: el slot lo separa antes de pintar nada) en vez de leerlo de `value`.
                                                                # La variable del slot que expone el runtime de NiceGUI (ver static/nicegui.js:
                                                                # Vue.h({props: {props: {...}}}, {props: slotProps})) se llama `props`, NO `scope`
                                                                # (ese es el nombre habitual en ejemplos sueltos de Quasar/Vue, acá es otro).
                                                                icon_options = {k: f'{k}{_ICON_SEP}{v}' for k, v in GROUP_ICON_OPTIONS.items()}
                                                                icon_select = ui.select(icon_options, value=node.get('icon') or 'folder', label='Ícono') \
                                                                    .props('outlined dense').classes('w-44').mark('template-node-icon') \
                                                                    .on_value_change(lambda e, node=node: (node.__setitem__('icon', e.value), _refresh()))
                                                                icon_select.add_slot('option', '''
                                                                    <q-item v-bind="props.itemProps">
                                                                        <q-item-section avatar><q-icon :name="props.opt.label.split('@@')[0]" /></q-item-section>
                                                                        <q-item-section><q-item-label>{{ props.opt.label.split('@@')[1] }}</q-item-label></q-item-section>
                                                                    </q-item>
                                                                ''')
                                                                icon_select.add_slot('selected-item', '''
                                                                    <div class="row items-center no-wrap">
                                                                        <q-icon :name="props.opt.label.split('@@')[0]" class="q-mr-xs" />
                                                                        <div>{{ props.opt.label.split('@@')[1] }}</div>
                                                                    </div>
                                                                ''')
                                                            if node['kind'] == 'field':
                                                                options = {k: labels.get(k, k) for k in known}
                                                                options[CUSTOM_SENTINEL] = 'Campo nuevo (definido por esta plantilla)'
                                                                for i, s in enumerate(suggestions):
                                                                    options[f'{SUGGEST_PREFIX}{i}'] = (f'{s["field_key"]} · {core.CUSTOM_FIELD_TYPE_LABELS.get(s["field_type"], s["field_type"])} '
                                                                                                       f'(de «{s["template_name"]}»)')
                                                                choice = node['field_key'] if node['field_key'] in known else CUSTOM_SENTINEL

                                                                def on_choice(e, node=node):
                                                                    if e.value == CUSTOM_SENTINEL:
                                                                        if node['field_key'] in known:
                                                                            node['field_key'] = _slug(node.get('label'))
                                                                        node['field_type'] = node.get('field_type') or 'text'
                                                                    elif e.value.startswith(SUGGEST_PREFIX):
                                                                        s = suggestions[int(e.value[len(SUGGEST_PREFIX):])]
                                                                        node['field_key'] = s['field_key']
                                                                        node['field_type'] = s['field_type']
                                                                        if not node.get('label'):
                                                                            node['label'] = s['label']
                                                                    else:
                                                                        node['field_key'] = e.value
                                                                        node['field_type'] = None
                                                                    _refresh()
                                                                ui.select(options, value=choice, label='Campo').props('outlined dense').classes('w-64') \
                                                                    .mark('template-node-field').on_value_change(on_choice)
                                                                if choice == CUSTOM_SENTINEL:
                                                                    ui.select(core.CUSTOM_FIELD_TYPE_LABELS, value=node.get('field_type') or 'text', label='Tipo') \
                                                                        .props('outlined dense').classes('w-40').mark('template-node-type') \
                                                                        .on_value_change(lambda e, node=node: node.__setitem__('field_type', e.value))
                                                            ui.select({'full': 'Completo', 'half': 'Mitad'}, value=node.get('width', 'full'), label='Ancho') \
                                                                .props('outlined dense').classes('w-32').mark('template-node-width') \
                                                                .on_value_change(lambda e, node=node: (node.__setitem__('width', e.value), _refresh()))
                                                            if is_output and node['kind'] == 'group':
                                                                ui.checkbox('Pestaña en el visor', value=bool(node.get('as_tab'))).mark('template-node-as-tab') \
                                                                    .on_value_change(lambda e, node=node: node.__setitem__('as_tab', e.value))
                                                            if not disabled:
                                                                ui.button(icon='arrow_upward', on_click=lambda: move(-1)).props('flat round dense').mark('template-node-up')
                                                                ui.button(icon='arrow_downward', on_click=lambda: move(1)).props('flat round dense').mark('template-node-down')
                                                                ui.button(icon='delete', on_click=lambda node=node: (siblings.remove(node), _refresh())) \
                                                                    .mark('template-node-delete') \
                                                                    .props('flat round dense color=negative')
                                                        if node['kind'] == 'group':
                                                            children = node.setdefault('children', [])
                                                            for child_index, child in enumerate(children):
                                                                render_node(child, children, child_index, depth + 1)
                                                            if not disabled:
                                                                with ui.row().classes('gap-2').style(f'margin-left:{(depth + 1) * 28}px'):
                                                                    ui.button('Agregar campo', icon='add', on_click=lambda children=children: (children.append(_new_field_node()), _refresh())) \
                                                                        .props('flat dense color=primary').mark('template-add-child-field')
                                                                    ui.button('Agregar grupo', icon='add', on_click=lambda children=children: (children.append(_new_group_node()), _refresh())) \
                                                                        .props('flat dense color=primary').mark('template-add-child-group')

                                                if not d['body']:
                                                    ui.label('Ninguno todavía.').classes('text-sm text-gray-400')
                                                for i, node in enumerate(d['body']):
                                                    render_node(node, d['body'], i, 0)
                                            body_rows()
                                            kind.on_value_change(lambda e: _refresh())
                                            applies_to.on_value_change(lambda e: _refresh())

                                            if not disabled:
                                                with ui.row().classes('gap-2 mt-2'):
                                                    ui.button('Agregar campo', icon='add', on_click=lambda: (d['body'].append(_new_field_node()), _refresh())) \
                                                        .props('outline dense color=primary').mark('template-add-field')
                                                    ui.button('Agregar sección', icon='add', on_click=lambda: (d['body'].append(_new_group_node()), _refresh())) \
                                                        .props('outline dense color=primary').mark('template-add-group')

                                    with ui.tabs().props('vertical dense no-caps').classes('shrink-0').style('width:56px;border-left:1px solid #e5e7eb') as field_rail:
                                        ui.tab('general', label='', icon='tune').tooltip('General').mark('template-rail-general') \
                                            .on('click', lambda: handle_rail_click('general'))
                                        ui.tab('sections', label='', icon='account_tree').tooltip('Secciones y campos').mark('template-rail-sections') \
                                            .on('click', lambda: handle_rail_click('sections'))
                                field_panels.bind_value_from(field_rail, 'value')
                                field_rail.set_value('general')

                                if is_global:
                                    def adopt():
                                        core.adopt_template(current['id'], pid)
                                        ui.notify('Plantilla adoptada a este proyecto', type='positive')
                                        ui.navigate.to('/spec-templates')
                                    ui.button('Adoptar a este proyecto', icon='content_copy', on_click=guard(adopt)).props('color=primary mt-2').mark('template-adopt')
                                else:
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

                    with main_split.before:
                        with ui.column().classes('w-full gap-4 min-w-0').style('height:100%' if compact else ''):
                            with ui.card().classes('w-full').mark('template-document').style('height:100%;overflow:auto' if compact else ''):
                                ui.label('Con datos de ejemplo — para abrirla en una pestaña nueva usá el ícono junto al título.').classes('text-xs text-gray-500')

                                @ui.refreshable
                                def document_view():
                                    draft = {'name': name.value or 'Vista previa', 'applies_to': applies_to.value, 'body': d['body']}
                                    try:
                                        data = spec_report.build_template_preview(draft)
                                        ui.html(live_doc_html(spec_report.render_sections_html(data['sections']), doc_typography()[0])).classes('w-full')
                                    except ValueError as exc:
                                        ui.label(str(exc)).classes('text-sm text-amber-700')
                                document_view()
                                name.on_value_change(lambda e: document_view.refresh())
                                description.on_value_change(lambda e: document_view.refresh())
