import re
from nicegui import ui
from .. import core, spec_report
from .common import frame, guard, confirm, empty_state, require_project, open_evidence_in_new_tab, protected_page, remembered, doc_typography, live_doc_html, typography_button
from ..layouts import Panel, workspace_layout

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
              'priority': 'Prioridad', 'type': 'Tipo',
              'suite_status': 'Suite: estado', 'suite_kpis': 'Suite: indicadores (tasa/variación/ejecuciones)',
              'suite_trend': 'Suite: tendencia', 'suite_members': 'Suite: miembros',
              'case_status': 'Caso ejecutable: estado', 'case_target': 'Caso ejecutable: método y ruta',
              'case_kpis': 'Caso ejecutable: indicadores (tasa/variación/ejecuciones/respuesta media)',
              'case_trend': 'Caso ejecutable: tendencia', 'case_recent_runs': 'Caso ejecutable: corridas recientes',
              'evidence_status': 'Evidencia: estado', 'evidence_summary': 'Evidencia: resumen de pasos',
              'evidence_verdict': 'Evidencia: veredicto del modelo (si se pidió)', 'evidence_steps': 'Evidencia: pasos de la corrida'},
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


_TEMPLATE_TABS = [('user_story', 'Historias de usuario'), ('test_case', 'Casos de prueba'), ('report', 'Reportes')]


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

        def template_row(t, badge_label, badge_color, actions=()):
            # `actions`: lista de dicts {icon, tooltip, color, on_click, disabled} — on_click=None (la estrella
            # YA default) o disabled=True (eliminar/desvincular bloqueado por uso) rinden el mismo ui.button,
            # solo que sin handler o con la prop 'disable' — así el tamaño es SIEMPRE el mismo botón, nunca un
            # ui.icon aparte (que rendía más chico que los botones de al lado). `click.stop` evita que el click
            # de un botón dispare también el click de la fila entera (que navega a editar la plantilla).
            with ui.row().classes('items-center gap-2 w-full no-wrap cursor-pointer hover:bg-gray-50') \
                    .on('click', lambda _, tid=t['id']: ui.navigate.to(f'/spec-templates/edit?id={tid}')):
                ui.badge(badge_label, color=badge_color)
                ui.label(t['name']).classes('text-sm font-medium')
                n = core.count_template_usage(t['id'])
                ui.label(f'— {n}').classes('text-xs text-gray-400').tooltip('Historias/Casos de prueba que la tienen asignada')
                ui.space()
                for a in actions:
                    ui.button(icon=a['icon'], on_click=(lambda _, t=t, fn=a['on_click']: fn(t)) if a.get('on_click') else None) \
                        .props(f'flat dense round color={a["color"]}' + (' disable' if a.get('disabled') else '')) \
                        .tooltip(a['tooltip']).on('click.stop', lambda: None).mark(f'template-row-{a["name"]}-{t["id"]}')

        def do_adopt(t):
            core.adopt_template(t['id'], pid)
            ui.notify(f'«{t["name"]}» adoptada a este proyecto', type='positive')
            ui.navigate.reload()

        def do_promote(t):
            core.promote_template(t['id'])
            ui.notify(f'Copia de «{t["name"]}» publicada en la biblioteca global', type='positive')
            ui.navigate.reload()

        def do_set_default(t):
            core.set_default_template(pid, t['applies_to'], t['id'])
            ui.notify(f'«{t["name"]}» es ahora la plantilla por defecto', type='positive')
            ui.navigate.reload()

        def do_remove(t, inherited):
            def remove():
                core.delete_spec_template(t['id'])
                ui.notify('Plantilla desvinculada de este proyecto' if inherited else 'Plantilla eliminada', type='positive')
                ui.navigate.reload()
            message = (f'¿Desvincular «{t["name"]}» de este proyecto? No se borra ningún contenido — sigue '
                      f'disponible en la Biblioteca global, la podés volver a adoptar cuando quieras.' if inherited
                      else f'¿Eliminar la plantilla «{t["name"]}»? No se puede deshacer.')
            confirm(message, remove, confirm_label='Desvincular' if inherited else 'Eliminar')

        def tabbed_templates(templates, row_actions):
            tab_key, set_tab_key = remembered('spec_templates_tab', default='user_story')
            with ui.tabs(value=tab_key, on_change=lambda e: set_tab_key(e.value)).props('dense no-caps').classes('w-full') as tabs:
                for key, label in _TEMPLATE_TABS:
                    ui.tab(key, label=f'{label} ({sum(1 for t in templates if t["applies_to"] == key)})')
            with ui.tab_panels(tabs, value=tab_key).classes('w-full'):
                for key, label in _TEMPLATE_TABS:
                    with ui.tab_panel(key).classes('p-0'):
                        rows = [t for t in templates if t['applies_to'] == key]
                        if not rows:
                            empty_state('Nada acá todavía.')
                        for t in rows:
                            template_row(t, *row_actions(t))

        with ui.card().classes('w-full'):
            ui.label(f'Disponibles en este proyecto ({len(local_templates)})').classes('font-semibold')

            def local_row(t):
                inherited = bool(t.get('cloned_from'))
                actions = []
                if not inherited:   # promover solo tiene sentido para una plantilla de verdad propia
                    actions.append({'name': 'promote', 'icon': 'publish', 'tooltip': 'Promover a la biblioteca global', 'color': 'primary', 'on_click': do_promote})
                if t['applies_to'] in ('user_story', 'test_case'):
                    if core.get_default_template_id(pid, t['applies_to']) == t['id']:
                        actions.append({'name': 'default', 'icon': 'star', 'tooltip': 'Es la plantilla por defecto', 'color': 'amber-8'})
                    else:
                        actions.append({'name': 'default', 'icon': 'star_outline', 'tooltip': 'Establecer como plantilla por defecto', 'color': 'grey-7', 'on_click': do_set_default})
                n = core.count_template_usage(t['id'])
                remove_tooltip = ('Desvincular de este proyecto' if inherited else 'Eliminar') if n == 0 else \
                    (f'No se puede {"desvincular" if inherited else "eliminar"}: {n} Historia(s)/Caso(s) de prueba la tienen asignada — '
                     f'no es posible mientras esté en uso, para esta versión.')
                actions.append({'name': 'remove', 'icon': 'link_off' if inherited else 'delete', 'tooltip': remove_tooltip, 'color': 'negative',
                               'on_click': (lambda t, inherited=inherited: do_remove(t, inherited)) if n == 0 else None, 'disabled': n > 0})
                return ('Heredada' if inherited else 'Propia', 'blue-grey-6' if inherited else 'grey-7', actions)
            tabbed_templates(local_templates, local_row)

        with ui.card().classes('w-full'):
            ui.label('Biblioteca global').classes('font-semibold')

            def global_row(t):
                return ('Del sistema' if t.get('is_builtin') else 'Global', 'primary',
                       [{'name': 'adopt', 'icon': 'get_app', 'tooltip': 'Adoptar a este proyecto', 'color': 'primary', 'on_click': do_adopt}])
            tabbed_templates(global_templates, global_row)


@protected_page('/spec-templates/edit')
def spec_template_detail(id: str = ''):
    title_text = 'Plantilla' if id else 'Nueva plantilla'
    with frame(title_text, '/spec-templates', full_width=True, doc_style=True):
        if not require_project():
            return
        pid = core.get_active_project_id()
        # Mismo layout que Historias de usuario (ver user_stories.py::story_detail) y Casos de prueba (ver
        # test_case_specs.py::test_spec_detail), vía workspace_layout (Nivel 1): documento/vista previa al
        # centro-izquierda, "Configuración" a la derecha en pestañas con riel de íconos (general/secciones),
        # separador ajustable, colapsable con un clic en el ícono ya activo, modo compacto/scroll completo.
        compact, set_compact = remembered('template_layout_compact', default=True)
        workspace_handle = {'value': None}   # lo llena el workspace_layout() de más abajo

        # Persistencia de workspace_layout remapeada a la clave vieja de ancho de separador
        # (template_split_width), para no perder la preferencia ya guardada de nadie con esta migración.
        def get_pref(key, default):
            return remembered('template_split_width' if key.endswith('_split_value') else key, default)[0]

        def set_pref(key, value):
            remembered('template_split_width' if key.endswith('_split_value') else key)[1](value)

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
        d = {'body': core.normalize_template_body((current or {}).get('body', []), (current or {}).get('applies_to', 'report')),
             'linked_story_fields': dict((current or {}).get('linked_story_fields') or {})}

        # name/description/kind/applies_to/body_rows: se asignan recién dentro de render_general/render_sections
        # (nonlocal) — ambos corren durante la llamada a workspace_layout, antes de que el usuario pueda
        # disparar _refresh/preview/save, así que están siempre asignados para cuando de verdad se necesitan.
        name = description = kind = applies_to = body_rows = canvas_rows = linked_story_panel = None
        view_mode = {'value': 'list'}   # 'list' | 'canvas' (Fase 2: diseñador visual) — mismo d['body'], 2 vistas

        def _refresh():
            if body_rows:
                body_rows.refresh()
            if canvas_rows:
                canvas_rows.refresh()
            if linked_story_panel:
                linked_story_panel.refresh()
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
                        elif is_mine and current.get('cloned_from'):
                            ui.badge('Heredada — clonada de la biblioteca global, se puede editar/desvincular (no promover)', color='blue-grey-6')
                    ui.button(icon='open_in_new', on_click=guard(preview)).props('flat round dense').mark('template-preview') \
                        .tooltip('Vista previa con datos de ejemplo, en una pestaña nueva')
                with ui.row().classes('gap-1 shrink-0'):
                    ui.button(icon='fullscreen_exit' if compact else 'fullscreen', on_click=toggle_compact) \
                        .props('flat round dense').mark('template-toggle-compact') \
                        .tooltip('Cambiar a modo con scroll completo' if compact else 'Cambiar a modo compacto (sin scroll, ancho completo)')

                    def toggle_center_mode_ui():
                        workspace_handle['value'].toggle_center_mode()
                        center_mode_button.refresh()

                    @ui.refreshable
                    def center_mode_button():
                        mode = get_pref('template_center_mode', 'tabs')
                        ui.button(icon='vertical_split' if mode == 'tabs' else 'view_column', on_click=toggle_center_mode_ui) \
                            .props('flat round dense').mark('template-toggle-center-mode') \
                            .tooltip('Ver los paneles del centro uno al lado del otro' if mode == 'tabs' else 'Volver a verlos en pestañas')
                    center_mode_button()
                    typography_button(lambda: document_view.refresh())

            def render_general():
                nonlocal name, description, kind, applies_to
                name = ui.input('Nombre', value=(current or {}).get('name', '')).props('outlined dense').classes('w-full').mark('template-name')
                description = ui.textarea('Descripción (opcional)', value=(current or {}).get('description', '')).props('outlined dense autogrow').classes('w-full')
                with ui.row().classes('w-full gap-3'):
                    kind = ui.select(KIND_LABELS, value=(current or {}).get('kind', 'input'), label='Tipo').props('outlined dense').classes('grow').mark('template-kind')
                    applies_to = ui.select(APPLIES_LABELS, value=(current or {}).get('applies_to', 'user_story'), label='Aplica a').props('outlined dense').classes('grow').mark('template-applies-to')
                if disabled:
                    name.disable(); description.disable(); kind.disable(); applies_to.disable()

            def render_sections():
                nonlocal body_rows, canvas_rows
                with ui.row().classes('items-center justify-between w-full'):
                    ui.label('Secciones y campos').classes('font-semibold')
                    ui.icon('info', size='xs', color='grey').classes('cursor-help').tooltip(
                        'Un «campo existente» ya tiene su propio editor (Como/Quiero/Para, criterios, pasos, ...) y no '
                        'declara tipo. Un «campo nuevo» lo define esta plantilla: elegí qué tipo de dato es. Una '
                        '«sección» agrupa campos (o subsecciones, anidables) bajo un nombre. El Ancho ubica hermanos '
                        'consecutivos lado a lado (Completo o Mitad acá; en la «Vista de lienzo» también Tercio y '
                        'Cuarto), tanto en el panel de Campos como en el documento; en una plantilla de salida, '
                        'además puede mostrarse como pestaña propia en el visor interactivo. La «Vista de lienzo» '
                        'deja arrastrar campos y tarjetas en vez de usar los selectores — las dos vistas editan lo '
                        'mismo.')
                ui.toggle({'list': 'Vista de lista', 'canvas': 'Vista de lienzo'}, value=view_mode['value']) \
                    .props('dense no-caps').mark('template-view-mode') \
                    .on_value_change(lambda e: (view_mode.__setitem__('value', e.value), _refresh()))

                def _field_catalog():
                    is_output = kind.value == 'output'
                    known = core.KNOWN_FIELDS_BY_APPLIES_TO.get(applies_to.value, ())
                    labels = KNOWN_FIELD_LABELS.get(applies_to.value, {})
                    # Una plantilla de SALIDA puede sugerir reusar un campo custom que ya
                    # existe en alguna plantilla de ENTRADA del proyecto, en vez de que
                    # quien la edita tenga que escribir a mano un field_key y confiar en
                    # que coincida — ver core.custom_field_catalog.
                    suggestions = core.custom_field_catalog(pid) if is_output else []
                    return is_output, known, labels, suggestions

                @ui.refreshable
                def _body_rows():
                    if view_mode['value'] != 'list':
                        return
                    is_output, known, labels, suggestions = _field_catalog()

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
                body_rows = _body_rows
                body_rows()

                # ------------------------------------------------------------------- Vista de lienzo (Fase 2)
                # Arrastrar y soltar sobre una grilla de 12 columnas (core.pack_grid_rows/node_col_span) — misma
                # app['body'] que la Vista de lista de arriba, solo otra forma de editarla. Patrón de arrastre
                # (draggable=true + ondragstart crudo para iniciar, .on('dragstart',...) para que Python se
                # entere) igual al ya probado en app/layouts/workspace.py (arrastrar una pestaña al centro).
                drag_state = {'kind': None, 'siblings': None, 'index': None, 'field_key': None}
                selected = {'node': None}
                WIDTH_OPTIONS = {12: 'Completo (12/12)', 6: 'Mitad (6/12)', 4: 'Tercio (4/12)', 3: 'Cuarto (3/12)'}

                def _drop(target_siblings, target_index):
                    if disabled:
                        return
                    if drag_state['kind'] == 'move' and drag_state['siblings'] is not None:
                        origin_siblings, origin_index = drag_state['siblings'], drag_state['index']
                        node = origin_siblings.pop(origin_index)
                        insert_at = target_index - 1 if origin_siblings is target_siblings and origin_index < target_index else target_index
                        target_siblings.insert(max(0, insert_at), node)
                        selected['node'] = node
                    elif drag_state['kind'] == 'new':
                        _, _, labels, _ = _field_catalog()
                        node = _new_field_node()
                        if drag_state['field_key'] != CUSTOM_SENTINEL:
                            node['field_key'], node['field_type'] = drag_state['field_key'], None
                            node['label'] = labels.get(drag_state['field_key'], drag_state['field_key'])
                        target_siblings.insert(target_index, node)
                        selected['node'] = node
                    drag_state['kind'] = None
                    _refresh()

                def _inspector():
                    node = selected['node']
                    if not node:
                        ui.label('Hacé clic en una tarjeta para editarla.').classes('text-sm text-gray-400')
                        return
                    with ui.row().classes('items-center gap-2 w-full no-wrap'):
                        ui.input('Etiqueta', value=node.get('label', '')).props('outlined dense').classes('grow') \
                            .on_value_change(lambda e, node=node: (node.__setitem__('label', e.value), _refresh()))
                        ui.select(WIDTH_OPTIONS, value=core.node_col_span(node), label='Ancho').props('outlined dense').classes('w-36') \
                            .on_value_change(lambda e, node=node: (node.__setitem__('col_span', e.value), _refresh()))
                        if not disabled:
                            def remove_selected(node=node):
                                for siblings in _all_sibling_lists(d['body']):
                                    if node in siblings:
                                        siblings.remove(node)
                                        break
                                selected['node'] = None
                                _refresh()
                            ui.button(icon='delete', on_click=remove_selected).props('flat round dense color=negative')
                    if node['kind'] == 'field':
                        _, _, labels, _ = _field_catalog()
                        bound = labels.get(node.get('field_key'), node.get('field_key')) if node.get('field_type') is None \
                            else f'Campo propio ({core.CUSTOM_FIELD_TYPE_LABELS.get(node.get("field_type"), node.get("field_type"))})'
                        ui.label(f'Campo: {bound} — para cambiarlo, usá la Vista de lista').classes('text-xs text-gray-400')

                def _all_sibling_lists(nodes):
                    yield nodes
                    for n in nodes:
                        if n.get('kind') == 'group':
                            yield from _all_sibling_lists(n.get('children') or [])

                def _card(node, siblings, index):
                    span = core.node_col_span(node)
                    with ui.element('div').style(f'grid-column:span {span};min-width:0') \
                            .on('dragover.prevent', lambda: None).on('drop', lambda s=siblings, i=index: _drop(s, i)):
                        with ui.card().classes('w-full p-2 gap-0').style('cursor:pointer') \
                                .on('click', lambda node=node: (selected.__setitem__('node', node), canvas_rows.refresh())):
                            with ui.row().classes('items-center gap-1 no-wrap w-full'):
                                if not disabled:
                                    handle = ui.icon('drag_indicator', size='xs', color='grey').classes('cursor-grab')
                                    handle.props(f'draggable=true ondragstart="event.dataTransfer.setData(\'text/plain\',\'{node["id"]}\')"') \
                                        .on('dragstart', lambda s=siblings, i=index: drag_state.update(kind='move', siblings=s, index=i, field_key=None))
                                ui.icon('folder' if node['kind'] == 'group' else 'description', size='xs', color='grey')
                                ui.label(node.get('label') or '(sin etiqueta)').classes('text-sm font-medium ellipsis')
                            ui.label(f'{span}/12').classes('text-xs text-gray-400')
                        if node['kind'] == 'group':
                            with ui.column().classes('w-full').style('margin-left:12px;border-left:2px solid #e5e7eb;padding-left:10px'):
                                _grid(node.setdefault('children', []))

                def _grid(nodes):
                    with ui.element('div').style('display:grid;grid-template-columns:repeat(12,1fr);gap:8px;width:100%'):
                        for index, node in enumerate(nodes):
                            _card(node, nodes, index)
                        if not disabled:
                            with ui.element('div').style('grid-column:span 12;min-height:30px;border:1px dashed #d1d5db;border-radius:6px;display:flex;align-items:center;justify-content:center') \
                                    .on('dragover.prevent', lambda: None).on('drop', lambda s=nodes: _drop(s, len(s))):
                                ui.label('Soltar acá para agregar al final').classes('text-xs text-gray-400')

                def _palette():
                    is_output, known, labels, suggestions = _field_catalog()
                    with ui.column().classes('gap-1').style('width:220px;flex-shrink:0'):
                        ui.label('Campos (arrastrá al lienzo)').classes('text-xs text-gray-500 font-semibold')
                        for key in known:
                            chip = ui.chip(labels.get(key, key), icon='drag_indicator').props('outline dense square')
                            chip.props(f'draggable=true ondragstart="event.dataTransfer.setData(\'text/plain\',\'{key}\')"') \
                                .on('dragstart', lambda key=key: drag_state.update(kind='new', field_key=key, siblings=None))
                        chip = ui.chip('Campo nuevo (propio)', icon='add').props('outline dense square color=primary')
                        chip.props(f'draggable=true ondragstart="event.dataTransfer.setData(\'text/plain\',\'{CUSTOM_SENTINEL}\')"') \
                            .on('dragstart', lambda: drag_state.update(kind='new', field_key=CUSTOM_SENTINEL, siblings=None))

                @ui.refreshable
                def _canvas_rows():
                    if view_mode['value'] != 'canvas':
                        return
                    with ui.row().classes('w-full gap-4 items-start no-wrap'):
                        with ui.column().classes('grow gap-2').style('min-width:0'):
                            if not d['body']:
                                ui.label('Ninguno todavía — arrastrá un campo de la derecha.').classes('text-sm text-gray-400')
                            _grid(d['body'])
                        if not disabled:
                            _palette()
                    ui.separator()
                    _inspector()
                canvas_rows = _canvas_rows
                canvas_rows()

                kind.on_value_change(lambda e: _refresh())
                applies_to.on_value_change(lambda e: _refresh())

                if not disabled:
                    with ui.row().classes('gap-2 mt-2'):
                        ui.button('Agregar campo', icon='add', on_click=lambda: (d['body'].append(_new_field_node()), _refresh())) \
                            .props('outline dense color=primary').mark('template-add-field')
                        ui.button('Agregar sección', icon='add', on_click=lambda: (d['body'].append(_new_group_node()), _refresh())) \
                            .props('outline dense color=primary').mark('template-add-group')

            def render_linked_story():
                nonlocal linked_story_panel

                @ui.refreshable
                def _panel():
                    if not (applies_to.value == 'test_case' and kind.value == 'input'):
                        ui.label('Esto solo aplica a una plantilla de ENTRADA de Caso de prueba.').classes('text-sm text-gray-400')
                        return
                    ui.label('Por cada plantilla de Historia de usuario/Requerimiento del proyecto, elegí qué campos suyos se '
                             'muestran en el previsualizador del Caso de prueba cuando está ligado a una Historia que la usa — '
                             'sin elegir ninguno, no se muestra nada de la Historia más allá de su título.').classes('text-sm text-gray-500')
                    parents = core.visible_templates('input', 'user_story', pid)
                    if not parents:
                        empty_state('Este proyecto no tiene plantillas de Historia de usuario todavía.')
                        return
                    for parent in parents:
                        fields = list(core.iter_template_fields(parent.get('body')))
                        if not fields:
                            continue
                        options = {f['field_key']: f.get('label') or f['field_key'] for f in fields}
                        current_keys = [k for k in d['linked_story_fields'].get(parent['id'], []) if k in options]
                        ui.select(options, multiple=True, clearable=True, value=current_keys, label=parent['name']) \
                            .props('outlined dense use-chips').classes('w-full').mark(f'template-linked-story-{parent["id"]}') \
                            .on_value_change(lambda e, parent=parent: d['linked_story_fields'].__setitem__(parent['id'], e.value))
                linked_story_panel = _panel
                _panel()

            def side_extra():
                if is_global:
                    def adopt():
                        core.adopt_template(current['id'], pid)
                        ui.notify('Plantilla adoptada a este proyecto', type='positive')
                        ui.navigate.to('/spec-templates')
                    ui.button('Adoptar a este proyecto', icon='get_app', on_click=guard(adopt)).props('color=primary').mark('template-adopt')
                else:
                    def save():
                        if current:
                            core.update_spec_template(current['id'], name.value, description.value or '', d['body'],
                                                      linked_story_fields=d['linked_story_fields'])
                            ui.notify('Plantilla actualizada', type='positive')
                            ui.navigate.to(f'/spec-templates/edit?id={current["id"]}')
                        else:
                            template = core.create_spec_template(name.value, kind.value, applies_to.value, d['body'], pid, description.value or '',
                                                                 linked_story_fields=d['linked_story_fields'])
                            ui.notify('Plantilla creada', type='positive')
                            ui.navigate.to(f'/spec-templates/edit?id={template["id"]}')
                    ui.button('Guardar cambios' if current else 'Crear plantilla', icon='save', on_click=guard(save)).props('color=primary').mark('template-save')

                    if current and is_mine:
                        is_inherited = bool(current.get('cloned_from'))
                        if not is_inherited:   # promover solo tiene sentido para una plantilla de verdad propia
                            def promote():
                                core.promote_template(current['id'])
                                ui.notify('Copia publicada en la biblioteca global', type='positive')
                                ui.navigate.to('/spec-templates')
                            ui.button('Promover a la biblioteca global', icon='publish', on_click=guard(promote)).props('outline dense color=primary').mark('template-promote')

                        def remove(t=current):
                            core.delete_spec_template(t['id'])
                            ui.notify('Plantilla desvinculada de este proyecto' if is_inherited else 'Plantilla eliminada', type='positive')
                            ui.navigate.to('/spec-templates')
                        usage = core.count_template_usage(current['id'])
                        remove_label = 'Desvincular de este proyecto' if is_inherited else 'Eliminar plantilla'
                        if usage:
                            ui.button(remove_label, icon='link_off' if is_inherited else 'delete').props('flat dense color=negative disable').mark('template-delete') \
                                .tooltip(f'No se puede {"desvincular" if is_inherited else "eliminar"}: {usage} Historia(s)/Caso(s) de prueba la tienen asignada.')
                        else:
                            message = (f'¿Desvincular «{current["name"]}» de este proyecto? No se borra ningún contenido — sigue disponible '
                                      f'en la Biblioteca global.' if is_inherited else f'¿Eliminar la plantilla «{current["name"]}»? No se puede deshacer.')
                            ui.button(remove_label, icon='link_off' if is_inherited else 'delete',
                                     on_click=lambda: confirm(message, remove, confirm_label='Desvincular' if is_inherited else 'Eliminar')) \
                                .props('flat dense color=negative').mark('template-delete')

            @ui.refreshable
            def document_view():
                draft = {'name': name.value or 'Vista previa', 'applies_to': applies_to.value, 'body': d['body']}
                try:
                    data = spec_report.build_template_preview(draft)
                    ui.html(live_doc_html(spec_report.render_sections_html(data['sections']), doc_typography()[0]), sanitize=False).classes('w-full')
                except ValueError as exc:
                    ui.label(str(exc)).classes('text-sm text-amber-700')

            def render_document():
                ui.label('Con datos de ejemplo — para abrirla en una pestaña nueva usá el ícono junto al título.').classes('text-xs text-gray-500')
                document_view()

            with ui.element('div').classes('w-full').style('height: calc(100vh - 210px)' if compact else ''):
                # draggable por defecto (True): general/sections se pueden arrastrar al centro para verlos uno
                # al lado del otro con el documento — misma versatilidad que ya tenía Historias de usuario.
                workspace_handle['value'] = workspace_layout(
                    side_panels=[
                        Panel('general', 'General', 'tune', render_general),
                        Panel('sections', 'Secciones y campos', 'account_tree', render_sections),
                        Panel('linked_story', 'Historias relacionadas', 'link', render_linked_story),
                    ],
                    center_anchors=[Panel('document', '', '', render_document)],
                    prefix='template', get_pref=get_pref, set_pref=set_pref,
                    side_title='Configuración', side_icon='tune', side_extra=side_extra,
                    split_limits=(40, 96), fill_height=compact,
                )
            name.on_value_change(lambda e: document_view.refresh())
            description.on_value_change(lambda e: document_view.refresh())
