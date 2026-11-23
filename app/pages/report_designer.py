"""Diseñador visual de reportes (Reportería, pieza NUEVA y separada de spec_templates.py, que no se toca):
contenedores en fila/columna (estilo Dreamweaver/Webflow — nunca x/y de píxeles) dentro de tres regiones
fijas Encabezado/Cuerpo/Pie. Fase 1: 'container'/'line'/'table' (literal). Fase 2: 'text'/'image' (fijos) y
'list'/'checklist'. Fase 3: 'field' (dinámico) y `table` en modo 'field' -- ver core.LAYOUT_NODE_KINDS.
Fase 4: 'repeat' (clona sus hijos una vez por fila real de un campo propio tipo Tabla, con más libertad
visual que una celda de tabla -- un 'field' hijo con source='row' saca su valor de esa fila) y `table` en
modo 'listing' (una fila por cada registro REAL del proyecto -- HU o Caso de prueba completos, no filas de
un campo de un solo registro -- para un reporte simple tipo "listado" de todas las Historias de usuario)."""
import re
import tempfile
from pathlib import Path
from nicegui import ui, run
from .. import core, report_doc as rd, report_render
from .common import (frame, guard, confirm, empty_state, require_project, protected_page, custom_table_editor,
                     read_upload, remembered, doc_typography, live_doc_html, typography_button)
from .spec_templates import KNOWN_FIELD_LABELS
from ..layouts import Panel, workspace_layout

APPLIES_LABELS = {'user_story': 'Historia de usuario', 'test_case': 'Caso de prueba', 'report': 'Reporte (Suite/Caso/Evidencia/Matriz)'}
WIDTH_OPTIONS = {12: 'Completo (12/12)', 6: 'Mitad (6/12)', 4: 'Tercio (4/12)', 3: 'Cuarto (3/12)'}
# Tabla del proyecto donde viven los registros reales para previsualizar un 'field' con su valor real (en vez
# de lorem ipsum) -- 'report' no tiene una tabla única (Suite/Caso/Evidencia/HU/TC/Matriz comparten el pool
# KNOWN_REPORT_FIELDS sin un resolvedor único), así que esa combinación siempre usa placeholders por ahora.
PREVIEW_TABLE_BY_APPLIES_TO = {'user_story': 'user_stories', 'test_case': 'test_case_specs'}
_LOREM = 'Lorem ipsum dolor sit amet, consectetur adipiscing elit.'
_NODE_ICON = {'container': 'crop_din', 'line': 'horizontal_rule', 'table': 'table_chart', 'text': 'text_fields',
             'image': 'image', 'list': 'format_list_bulleted', 'checklist': 'checklist', 'field': 'data_object',
             'repeat': 'repeat'}
PALETTE_ITEMS = [
    ('container-row', 'Contenedor (fila)', 'view_column'),
    ('container-column', 'Contenedor (columna)', 'view_agenda'),
    ('line', 'Línea', 'horizontal_rule'),
    ('table', 'Tabla', 'table_chart'),
    ('text', 'Texto', 'text_fields'),
    ('image', 'Imagen', 'image'),
    ('list', 'Lista', 'format_list_bulleted'),
    ('checklist', 'Checklist', 'checklist'),
    ('field', 'Campo', 'data_object'),
    ('repeat', 'Repetir filas (campo Tabla)', 'repeat'),
]
_REGIONS = (('header', 'Encabezado'), ('body', 'Cuerpo'), ('footer', 'Pie de página'))


def _new_node(new_kind):
    if new_kind == 'container-row':
        return {'id': core.uid(), 'kind': 'container', 'direction': 'row', 'col_span': 12, 'gap': 16, 'background': None, 'border': False, 'children': []}
    if new_kind == 'container-column':
        return {'id': core.uid(), 'kind': 'container', 'direction': 'column', 'col_span': 12, 'gap': 16, 'background': None, 'border': False, 'children': []}
    if new_kind == 'line':
        return {'id': core.uid(), 'kind': 'line', 'col_span': 12, 'orientation': 'horizontal', 'thickness': 1, 'color': '#d1d5db'}
    if new_kind == 'table':
        return {'id': core.uid(), 'kind': 'table', 'col_span': 12, 'mode': 'literal', 'headers': ['Columna 1', 'Columna 2'], 'rows': []}
    if new_kind == 'text':
        return {'id': core.uid(), 'kind': 'text', 'col_span': 12, 'value': 'Texto', 'heading': False, 'level': 2}
    if new_kind == 'image':
        return {'id': core.uid(), 'kind': 'image', 'col_span': 12, 'file': None, 'label': 'Imagen'}
    if new_kind == 'list':
        return {'id': core.uid(), 'kind': 'list', 'col_span': 12, 'items': ['Elemento 1'], 'ordered': False}
    if new_kind == 'checklist':
        return {'id': core.uid(), 'kind': 'checklist', 'col_span': 12, 'items': [{'label': 'Opción 1', 'checked': False}]}
    if new_kind == 'repeat':
        return {'id': core.uid(), 'kind': 'repeat', 'col_span': 12, 'field_key': '', 'children': []}
    return {'id': core.uid(), 'kind': 'field', 'col_span': 12, 'source': 'fixed', 'field_key': '', 'label': ''}


def _node_label(node):
    kind = node['kind']
    if kind == 'container':
        return f"Contenedor ({'Fila' if node.get('direction') == 'row' else 'Columna'})"
    if kind == 'line':
        return 'Línea'
    if kind == 'table':
        if node.get('mode') == 'field':
            return f"Tabla (campo: {node.get('label') or node.get('field_key') or 'sin elegir'})"
        if node.get('mode') == 'listing':
            return f"Tabla (listado: {len(node.get('columns') or [])} columna(s))"
        return f"Tabla ({len(node.get('rows') or [])} fila(s))"
    if kind == 'text':
        return f"Texto ({node.get('value') or '(vacío)'})"[:40]
    if kind == 'image':
        file_ref = node.get('file')
        return f"Imagen ({file_ref['filename']})" if file_ref else 'Imagen (sin subir)'
    if kind == 'list':
        return f"Lista ({len(node.get('items') or [])} elemento(s))"
    if kind == 'checklist':
        return f"Checklist ({len(node.get('items') or [])} opción(es))"
    if kind == 'repeat':
        return f"Repetir filas (campo: {node.get('field_key') or 'sin elegir'})"
    # 'field'
    if node.get('source') == 'row':
        return f"Campo (fila: {node.get('label') or 'columna sin elegir'})"
    return f"Campo ({node.get('label') or node.get('field_key') or 'sin elegir'})"


def _field_catalog(applies_to, input_template):
    """Campos elegibles para un 'field' (o para el selector de una Tabla en modo 'campo', ver
    _table_field_catalog): el fijo de KNOWN_FIELD_LABELS[applies_to] + los campos propios (field_type
    declarado) de la Plantilla de entrada asociada al diseño, si hay una."""
    options = dict(KNOWN_FIELD_LABELS.get(applies_to, {}))
    if input_template:
        for node in core.iter_template_fields(input_template.get('body')):
            if node.get('field_type'):
                options[node['field_key']] = node.get('label') or node['field_key']
    return options


def _template_only_field_keys(input_template):
    if not input_template:
        return set()
    return {n['field_key'] for n in core.iter_template_fields(input_template.get('body')) if n.get('field_type')}


def _table_field_catalog(input_template):
    """Campos propios TIPO TABLA de la Plantilla de entrada asociada -- sin plantilla asociada, o sin
    ninguno de ese tipo, no hay nada para elegir (una Tabla en modo 'campo' sin field_key se descarta al
    guardar, ver core._clean_layout_node)."""
    if not input_template:
        return {}
    return {n['field_key']: n.get('label') or n['field_key'] for n in core.iter_template_fields(input_template.get('body'))
           if n.get('field_type') == 'table'}


def _resolve_field_value(field_key, source, record, row=None, column_index=None):
    """Valor real de un 'field'. Con `source='row'` no se mira `record` en absoluto: se resuelve contra la
    fila actual que un 'repeat' ancestro está clonando (`row`, una lista de celdas) usando `column_index` --
    None si no hay fila (fuera de un 'repeat', o sin datos reales todavía) o la fila tiene menos columnas que
    `column_index` (cae al lorem ipsum, mismo criterio que cualquier otro 'field' sin dato). Con
    'fixed'/'template', None si no hay registro, el campo está vacío, o tiene una forma compleja (lista/
    tabla/adjunto) que esta fase no intenta mostrar como texto plano (cae al lorem ipsum también)."""
    if source == 'row':
        if row is None or column_index is None or column_index >= len(row):
            return None
        value = row[column_index]
        return str(value) if value not in (None, '') else None
    if record is None or not field_key:
        return None
    value = (record.get('custom_fields') or {}).get(field_key) if source == 'template' else record.get(field_key)
    if isinstance(value, (list, dict)) or value in (None, ''):
        return None
    return str(value)


def _resolve_table_field_value(field_key, record):
    if record is None or not field_key:
        return None
    value = (record.get('custom_fields') or {}).get(field_key)
    if isinstance(value, dict) and isinstance(value.get('headers'), list) and value['headers']:
        return value
    return None


def _file_url(file_ref):
    return f'/evidence/{file_ref["id"]}/{file_ref["id"]}-{file_ref["filename"]}'


def layout_to_blocks(nodes, record=None, row=None, applies_to=None, project_id=None):
    """Punto de entrada: empaqueta HERMANOS en filas de 12 columnas (core.pack_grid_rows -- el mismo motor que
    ya usan report_tree.py y el editor de Plantillas) antes de convertir a bloques, así el ancho (col_span) de
    un elemento SUELTO (sin envolverlo a mano en un Contenedor fila) ya alcanza para que quede en línea con
    sus vecinos -- "poder colocar elementos en línea" sin que haga falta un contenedor explícito para eso.
    `record`: la Historia/Caso de prueba elegida para previsualizar (o None) -- ver _resolve_field_value.
    `row`: la fila actual que un 'repeat' ancestro está clonando (o None fuera de uno) -- se enhebra sin
    tocarla hasta un 'field' hijo con source='row'. `applies_to`/`project_id`: el tipo y proyecto del DISEÑO
    (no del registro de previsualización) -- solo los usa una `table` en modo 'listing' (ver
    _listing_table_block), que es siempre del proyecto completo, independiente de cualquier registro elegido."""
    blocks = []
    for row_nodes in core.pack_grid_rows(nodes or []):
        if len(row_nodes) == 1:
            blocks.append(_node_to_block(row_nodes[0], record, row, applies_to, project_id))
        else:
            cells = [{'span': core.node_col_span(n), 'children': [_node_to_block(n, record, row, applies_to, project_id)]} for n in row_nodes]
            blocks.append(rd.row(cells))
    return blocks


def _listing_table_block(node, applies_to, project_id):
    """Tabla 'listing': una fila por cada registro REAL del proyecto (todas las Historias de usuario o Casos
    de prueba, según `applies_to` del DISEÑO) -- a diferencia de 'field' (los datos de UN registro elegido),
    acá siempre son los datos reales del proyecto completo, nunca un placeholder/lorem ipsum (no hay "sin
    dato" posible: si el proyecto no tiene registros, la tabla sale con encabezados y sin filas, igual que
    cualquier listado vacío)."""
    columns = node.get('columns') or []
    labels = [c['label'] for c in columns] or ['Columna']
    table = PREVIEW_TABLE_BY_APPLIES_TO.get(applies_to)
    if not table or not project_id:
        return rd.table(labels, [])
    records = core.list_project_items(table, project_id)
    rows = [[_resolve_field_value(c['field_key'], c['source'], record) or '—' for c in columns] for record in records]
    return rd.table(labels, rows)


def _node_to_block(node, record=None, row=None, applies_to=None, project_id=None):
    """Traduce UN nodo a su bloque de report_doc.py -- casi no hace falta un renderer nuevo, un contenedor
    fila/columna ES `rd.row`/`rd.group` (ver el plan de la sesión)."""
    kind = node.get('kind')
    if kind == 'container':
        children = node.get('children') or []
        if node.get('direction') == 'row':
            # Fila EXPLÍCITA (pedida a propósito, no por empaquetado automático): todos los hijos van en una
            # sola fila con el ancho que cada uno declare, sin re-empaquetar -- a diferencia de 'column', que
            # sí vuelve a pasar por layout_to_blocks (empaquetado automático también puertas adentro).
            cells = [{'span': c.get('col_span', 12), 'children': [_node_to_block(c, record, row, applies_to, project_id)]} for c in children]
            return rd.row(cells, background=node.get('background'), border=bool(node.get('border')), gap=node.get('gap', 16))
        return rd.group(layout_to_blocks(children, record, row, applies_to, project_id), background=node.get('background'), border=bool(node.get('border')))
    if kind == 'line':
        return rd.divider(node.get('orientation', 'horizontal'), node.get('thickness', 1), node.get('color', '#d1d5db'))
    if kind == 'table':
        if node.get('mode') == 'field':
            table_value = _resolve_table_field_value(node.get('field_key'), record)
            if table_value:
                return rd.table(table_value['headers'], table_value.get('rows') or [])
            label = node.get('label') or node.get('field_key') or 'Tabla'
            return rd.table([label, label], [])
        if node.get('mode') == 'listing':
            return _listing_table_block(node, applies_to, project_id)
        return rd.table(node.get('headers') or [], node.get('rows') or [])
    if kind == 'text':
        value = node.get('value') or ''
        return rd.heading(value, node.get('level', 2)) if node.get('heading') else rd.text(value)
    if kind == 'image':
        file_ref = node.get('file')
        if file_ref:
            return rd.file(_file_url(file_ref), node.get('label') or file_ref['filename'], image=True,
                           path=str(core.ARTIFACTS / f'{file_ref["id"]}-{file_ref["filename"]}'))
        return rd.text(f'[{node.get("label") or "Imagen"} -- sin subir]')
    if kind == 'list':
        return rd.bullet_list(node.get('items') or [], ordered=bool(node.get('ordered')))
    if kind == 'checklist':
        return rd.checks([{'label': i['label'], 'ok': bool(i.get('checked'))} for i in (node.get('items') or [])])
    if kind == 'repeat':
        # Clona `children` una vez por fila REAL del campo tipo Tabla elegido -- sin registro, o sin filas
        # todavía, una sola pasada de los hijos con row=None (cada 'field' hijo source='row' cae a su lorem
        # ipsum, igual que cualquier 'field' sin dato: nunca una sección vacía/oculta, ver el plan).
        children = node.get('children') or []
        table_value = _resolve_table_field_value(node.get('field_key'), record)
        rows = table_value.get('rows') if table_value else None
        if not rows:
            return rd.group(layout_to_blocks(children, record, row, applies_to, project_id))
        cloned = []
        for i, row_cells in enumerate(rows):
            if i:
                cloned.append(rd.divider('horizontal', 1, '#e5e7eb'))
            cloned += layout_to_blocks(children, record, row_cells, applies_to, project_id)
        return rd.group(cloned)
    # 'field': dato real si hay registro elegido y el campo tiene valor; lorem ipsum como respaldo -- nunca
    # una sección vacía/oculta por falta de dato (ese era justo el problema del editor viejo, ver el plan).
    value = _resolve_field_value(node.get('field_key'), node.get('source'), record, row, node.get('column_index'))
    return rd.text(value if value is not None else _LOREM)


def _stem(text_value):
    return re.sub(r'[\\/:*?"<>|]+', '_', text_value or 'diseno').replace(' ', '_')


@protected_page('/report-designer')
def report_designer_list():
    with frame('Diseños de reporte', '/report-designer', doc_style=True):
        if not require_project():
            return
        pid = core.get_active_project_id()
        ui.label('Diseñador visual tipo Dreamweaver/Webflow: contenedores en fila/columna dentro de Encabezado/'
                 'Cuerpo/Pie -- complementa (no reemplaza) el editor de Plantillas.').classes('text-sm text-gray-500')
        ui.button('Nuevo diseño', icon='add', on_click=lambda: ui.navigate.to('/report-designer/edit')).props('color=primary')

        layouts = sorted(core.list_project_items('report_layouts', pid), key=lambda t: t['name'])
        if not layouts:
            empty_state('Ningún diseño todavía.')
            return
        for layout in layouts:
            with ui.row().classes('items-center gap-2 w-full no-wrap cursor-pointer hover:bg-gray-50') \
                    .on('click', lambda _, lid=layout['id']: ui.navigate.to(f'/report-designer/edit?id={lid}')):
                ui.badge(APPLIES_LABELS.get(layout['applies_to'], layout['applies_to']), color='primary')
                ui.label(layout['name']).classes('text-sm font-medium')
                ui.space()

                def remove(layout=layout):
                    core.delete_report_layout(layout['id'])
                    ui.notify('Diseño eliminado', type='positive')
                    ui.navigate.reload()

                def ask_remove(_, layout=layout, remove=remove):
                    confirm(f'¿Eliminar el diseño «{layout["name"]}»? No se puede deshacer.', remove)
                ui.button(icon='delete', on_click=ask_remove) \
                    .props('flat dense round color=negative').tooltip('Eliminar').on('click.stop', lambda: None)


@protected_page('/report-designer/edit')
def report_designer_edit(id: str = ''):
    title_text = 'Diseño de reporte' if id else 'Nuevo diseño de reporte'
    with frame(title_text, '/report-designer', full_width=True, doc_style=True):
        if not require_project():
            return
        pid = core.get_active_project_id()
        current = core.get('report_layouts', id) if id else None
        if id and current is None:
            with ui.column().classes('w-full p-4 gap-2'):
                ui.link('← Volver a Diseños de reporte', '/report-designer').classes('text-sm')
                ui.label('Este diseño ya no existe.').classes('text-amber-700')
            return

        d = {'header': list((current or {}).get('header') or []),
             'body': list((current or {}).get('body') or []),
             'footer': list((current or {}).get('footer') or [])}
        drag_state = {'kind': None, 'siblings': None, 'index': None, 'new_kind': None}
        selected = {'node': None}
        state = {'input_template_id': (current or {}).get('input_template_id'), 'preview_record_id': None}

        def get_pref(key, default):
            # Primera vez que se abre el diseñador (nada guardado todavía): arranca en 'split' -- Lienzo y
            # Documento son los 2 paneles MAYORES del área de diseño, se ven juntos por defecto -- en vez del
            # 'tabs' por defecto de workspace_layout (pensado para cuando el centro es documento + asistente,
            # un caso distinto). Una vez que el usuario lo cambia a mano, esa elección queda y se respeta.
            if key == 'report_designer_center_mode':
                default = 'split'
            return remembered(key, default)[0]

        def set_pref(key, value):
            remembered(key)[1](value)

        workspace_handle = {'value': None}

        def toggle_center_mode_ui():
            workspace_handle['value'].toggle_center_mode()
            center_mode_button.refresh()

        @ui.refreshable
        def center_mode_button():
            mode = get_pref('report_designer_center_mode', 'split')
            ui.button(icon='vertical_split' if mode == 'tabs' else 'view_column', on_click=toggle_center_mode_ui) \
                .props('flat round dense').mark('layout-toggle-center-mode') \
                .tooltip('Ver el Lienzo y el Documento lado a lado' if mode == 'tabs' else 'Ver el Lienzo y el Documento en pestañas, uno a la vez')

        with ui.row().classes('items-center gap-2 w-full no-wrap'):
            name = ui.input('Nombre', value=(current or {}).get('name', '')).props('outlined dense').classes('grow').mark('layout-name')
            applies_to = ui.select(APPLIES_LABELS, value=(current or {}).get('applies_to', 'report'), label='Aplica a') \
                .props('outlined dense').classes('w-64').mark('layout-applies-to')
            center_mode_button()
            typography_button(lambda: document_view.refresh())
        description = ui.input('Descripción', value=(current or {}).get('description', '')).props('outlined dense').classes('w-full').mark('layout-description')

        @ui.refreshable
        def _input_template_row():
            templates = core.visible_templates('input', applies_to.value, pid)
            options = {'': 'Ninguna (solo campos fijos)'}
            options.update({t['id']: t['name'] for t in templates})
            current_id = state['input_template_id'] if state['input_template_id'] in options else ''

            def on_change(e):
                state['input_template_id'] = e.value or None
                _refresh(tree=True, inspector=True, document=True)
            ui.select(options, value=current_id, label='Plantilla de entrada asociada (amplía el catálogo de Campo con sus campos propios)') \
                .props('outlined dense').classes('w-full').mark('layout-input-template').on_value_change(on_change)

        @ui.refreshable
        def _preview_record_row():
            table = PREVIEW_TABLE_BY_APPLIES_TO.get(applies_to.value)
            if not table:
                ui.label('Vista previa con dato real: no disponible para "Aplica a: Reporte" en esta fase -- siempre se muestran placeholders.') \
                    .classes('text-xs text-gray-400')
                return
            records = core.list_project_items(table, pid)
            options = {'': 'Ninguno (usar lorem ipsum / la etiqueta como placeholder)'}
            options.update({r['id']: (r.get('title') or r['id'][:8]) for r in records})
            current_id = state['preview_record_id'] if state['preview_record_id'] in options else ''

            def on_change(e):
                state['preview_record_id'] = e.value or None
                document_view.refresh()
            ui.select(options, value=current_id, label='Registro de previsualización (para ver el valor real de los Campo)') \
                .props('outlined dense').classes('w-full').mark('layout-preview-record').on_value_change(on_change)

        _input_template_row()
        _preview_record_row()

        def _on_applies_to_change(e):
            state['preview_record_id'] = None
            _input_template_row.refresh()
            _preview_record_row.refresh()
            _refresh(tree=True, inspector=True, document=True)
        applies_to.on_value_change(_on_applies_to_change)

        def _get_preview_record():
            table = PREVIEW_TABLE_BY_APPLIES_TO.get(applies_to.value)
            if not table or not state['preview_record_id']:
                return None
            return core.get(table, state['preview_record_id'])

        def _all_sibling_lists():
            def _siblings_in(nodes):
                yield nodes
                for n in nodes:
                    if n.get('kind') in ('container', 'repeat'):
                        yield from _siblings_in(n.get('children') or [])
            for region_key, _ in _REGIONS:
                yield from _siblings_in(d[region_key])

        def _find_ancestor_repeat(node_id):
            """El 'repeat' ancestro más cercano de `node_id` (o None si no está dentro de uno) -- para que el
            panel de Propiedades de un 'field' sepa si ofrecer "Columna de la fila" además del catálogo normal."""
            def _search(nodes, current_repeat):
                for n in nodes:
                    next_repeat = n if n['kind'] == 'repeat' else current_repeat
                    if n['id'] == node_id:
                        return current_repeat
                    found = _search(n.get('children') or [], next_repeat)
                    if found is not None:
                        return found
                return None
            for region_key, _ in _REGIONS:
                found = _search(d[region_key], None)
                if found is not None:
                    return found
            return None

        def _refresh(tree=False, inspector=False, document=False):
            """Las 3 áreas (árbol/propiedades/vista previa) son paneles SEPARADOS de workspace_layout ahora --
            cada una se refresca a demanda, nunca todas juntas por reflejo. Esto es, de hecho, lo que resuelve
            el bug de foco perdido al tipear (ver core memoria de sesión): refrescar `document_view` en cada
            tecla es seguro porque vive en otro panel/otro árbol del DOM que el input que se está editando."""
            if tree:
                _tree.refresh()
            if inspector:
                _inspector_panel.refresh()
            if document:
                document_view.refresh()

        def _drop(target_siblings, target_index):
            if drag_state['kind'] == 'move' and drag_state['siblings'] is not None:
                origin_siblings, origin_index = drag_state['siblings'], drag_state['index']
                node = origin_siblings.pop(origin_index)
                insert_at = target_index - 1 if origin_siblings is target_siblings and origin_index < target_index else target_index
                target_siblings.insert(max(0, insert_at), node)
                selected['node'] = node
            elif drag_state['kind'] == 'new':
                node = _new_node(drag_state['new_kind'])
                target_siblings.insert(target_index, node)
                selected['node'] = node
            drag_state['kind'] = None
            _refresh(tree=True, inspector=True, document=True)

        def _render_node(node, siblings, index):
            span = node.get('col_span', 12)
            with ui.element('div').style(f'grid-column:span {span};min-width:0') \
                    .on('dragover.prevent', lambda: None).on('drop', lambda s=siblings, i=index: _drop(s, i)):
                border = '2px solid #2563eb' if selected['node'] is node else '1px solid #e5e7eb'
                with ui.card().classes('w-full p-2 gap-0').style(f'cursor:pointer;border:{border}') \
                        .on('click', lambda node=node: (selected.__setitem__('node', node), _refresh(tree=True, inspector=True))):
                    with ui.row().classes('items-center gap-1 no-wrap w-full'):
                        handle = ui.icon('drag_indicator', size='xs', color='grey').classes('cursor-grab')
                        handle.props(f'draggable=true ondragstart="event.dataTransfer.setData(\'text/plain\',\'{node["id"]}\')"') \
                            .on('dragstart', lambda s=siblings, i=index: drag_state.update(kind='move', siblings=s, index=i, new_kind=None))
                        ui.icon(_NODE_ICON.get(node['kind'], 'crop_square'), size='xs', color='grey')
                        ui.label(_node_label(node)).classes('text-sm font-medium ellipsis')
                    ui.label(f'{span}/12').classes('text-xs text-gray-400')
                if node['kind'] in ('container', 'repeat'):
                    with ui.column().classes('w-full').style('margin-left:10px;border-left:2px solid #e5e7eb;padding-left:8px;padding-top:6px'):
                        _render_children(node.setdefault('children', []))

        def _render_children(nodes):
            """SIEMPRE la misma grilla de 12 columnas, sea un Contenedor fila/columna o una región de primer
            nivel (Encabezado/Cuerpo/Pie): el `col_span` de cada hijo decide si queda en línea con el
            siguiente o pasa a una fila nueva (el grid de CSS empaqueta solo, sin que haga falta envolver a
            mano en un Contenedor fila) -- layout_to_blocks (core.pack_grid_rows) hace exactamente lo mismo
            del lado del documento exportado, así que el lienzo y la vista previa siempre quedan de acuerdo."""
            with ui.element('div').style('display:grid;grid-template-columns:repeat(12,1fr);gap:8px;width:100%'):
                for index, node in enumerate(nodes):
                    _render_node(node, nodes, index)
                with ui.element('div').style('grid-column:span 12;min-height:28px;border:1px dashed #d1d5db;border-radius:6px;'
                                              'display:flex;align-items:center;justify-content:center') \
                        .on('dragover.prevent', lambda: None).on('drop', lambda s=nodes: _drop(s, len(s))):
                    ui.label('Soltar acá').classes('text-xs text-gray-400')

        def _palette():
            # Panel del riel lateral ("Elementos") -- a propósito separado del Lienzo: éste solo tiene
            # Encabezado/Cuerpo/Pie, nada más (pedido explícito del usuario).
            ui.label('Elementos (arrastrá a una región)').classes('text-xs text-gray-500 font-semibold')
            with ui.column().classes('gap-1 w-full').style('overflow-x:hidden'):
                for new_kind, label, icon in PALETTE_ITEMS:
                    chip = ui.chip(label, icon=icon).props('outline dense square').style('width:100%;justify-content:flex-start')
                    chip.props(f'draggable=true ondragstart="event.dataTransfer.setData(\'text/plain\',\'{new_kind}\')"') \
                        .on('dragstart', lambda new_kind=new_kind: drag_state.update(kind='new', new_kind=new_kind, siblings=None))

        @ui.refreshable
        def _tree():
            with ui.column().classes('w-full gap-2'):
                for region_key, region_label in _REGIONS:
                    with ui.card().classes('w-full p-3'):
                        ui.label(region_label).classes('text-sm font-semibold text-gray-600')
                        _render_children(d[region_key])

        @ui.refreshable
        def _inspector_panel():
            node = selected['node']
            if not node:
                ui.label('Hacé clic en un elemento del árbol para editarlo.').classes('text-sm text-gray-400')
                return
            with ui.row().classes('items-center gap-2 w-full no-wrap'):
                ui.select(WIDTH_OPTIONS, value=node.get('col_span', 12), label='Ancho (dentro de una fila)').props('outlined dense').classes('w-56') \
                    .on_value_change(lambda e, node=node: (node.__setitem__('col_span', e.value), _refresh(tree=True, document=True)))

                def remove_selected(node=node):
                    for siblings in _all_sibling_lists():
                        if node in siblings:
                            siblings.remove(node)
                            break
                    selected['node'] = None
                    _refresh(tree=True, inspector=True, document=True)
                ui.button(icon='delete', on_click=remove_selected).props('flat round dense color=negative')
            if node['kind'] == 'container':
                with ui.row().classes('items-center gap-2 w-full no-wrap mt-2'):
                    ui.select({'row': 'Fila', 'column': 'Columna'}, value=node.get('direction', 'column'), label='Dirección') \
                        .props('outlined dense').classes('w-32') \
                        .on_value_change(lambda e, node=node: (node.__setitem__('direction', e.value), _refresh(tree=True, document=True)))
                    ui.number('Separación (px)', value=node.get('gap', 16), min=0, max=64).props('outlined dense').classes('w-36') \
                        .on_value_change(lambda e, node=node: (node.__setitem__('gap', int(e.value or 0)), _refresh(document=True)))
                    ui.input('Color de fondo', value=node.get('background') or '').props('outlined dense').classes('w-40') \
                        .on_value_change(lambda e, node=node: (node.__setitem__('background', (e.value or '').strip() or None), _refresh(document=True)))
                    ui.checkbox('Borde', value=bool(node.get('border'))) \
                        .on_value_change(lambda e, node=node: (node.__setitem__('border', e.value), _refresh(document=True)))
            elif node['kind'] == 'line':
                with ui.row().classes('items-center gap-2 w-full no-wrap mt-2'):
                    ui.select({'horizontal': 'Horizontal', 'vertical': 'Vertical'}, value=node.get('orientation', 'horizontal'), label='Orientación') \
                        .props('outlined dense').classes('w-36') \
                        .on_value_change(lambda e, node=node: (node.__setitem__('orientation', e.value), _refresh(document=True)))
                    ui.number('Grosor (px)', value=node.get('thickness', 1), min=1, max=20).props('outlined dense').classes('w-32') \
                        .on_value_change(lambda e, node=node: (node.__setitem__('thickness', int(e.value or 1)), _refresh(document=True)))
                    ui.input('Color', value=node.get('color') or '#d1d5db').props('outlined dense').classes('w-32') \
                        .on_value_change(lambda e, node=node: (node.__setitem__('color', (e.value or '').strip() or '#d1d5db'), _refresh(document=True)))
            elif node['kind'] == 'table':
                input_template = core.get('spec_templates', state['input_template_id']) if state['input_template_id'] else None
                with ui.row().classes('items-center gap-2 w-full no-wrap mt-2'):
                    ui.select({'literal': 'Contenido literal (lo escribo yo)', 'field': 'Campo de la plantilla asociada (tipo Tabla)',
                              'listing': 'Listado de registros del proyecto (una fila por cada uno)'},
                             value=node.get('mode', 'literal'), label='Origen de los datos').props('outlined dense').classes('w-80') \
                        .on_value_change(lambda e, node=node: (node.__setitem__('mode', e.value), _refresh(tree=True, inspector=True, document=True)))
                if node.get('mode') == 'field':
                    table_catalog = _table_field_catalog(input_template)
                    if not table_catalog:
                        ui.label('La Plantilla de entrada asociada (arriba) no define ningún campo propio tipo Tabla todavía.') \
                            .classes('text-xs text-amber-700 mt-2')
                    else:
                        current_key = node.get('field_key') if node.get('field_key') in table_catalog else None

                        def on_table_field_change(e, node=node, catalog=table_catalog):
                            node['field_key'] = e.value or ''
                            node['label'] = catalog.get(e.value, e.value or '')
                            _refresh(tree=True, document=True)
                        ui.select(table_catalog, value=current_key, label='Campo (tipo Tabla)').props('outlined dense').classes('w-72 mt-2') \
                            .on_value_change(on_table_field_change)
                elif node.get('mode') == 'listing':
                    if not PREVIEW_TABLE_BY_APPLIES_TO.get(applies_to.value):
                        ui.label('Listado: no disponible para "Aplica a: Reporte" en esta fase -- elegí Historia de usuario o Caso de prueba.') \
                            .classes('text-xs text-amber-700 mt-2')
                    else:
                        catalog = _field_catalog(applies_to.value, input_template)
                        template_only = _template_only_field_keys(input_template)
                        if not catalog:
                            ui.label('No hay campos para elegir todavía.').classes('text-xs text-amber-700 mt-2')
                        else:
                            ui.label('Columnas (en orden, una fila real por cada registro del proyecto):').classes('text-xs text-gray-500 mt-2')

                            @ui.refreshable
                            def _listing_columns_rows(node=node):
                                columns = node.setdefault('columns', [])
                                for i, col in enumerate(columns):
                                    with ui.row().classes('items-center gap-2 w-full no-wrap'):
                                        ui.label(col.get('label') or col.get('field_key')).classes('grow text-sm')
                                        ui.button(icon='delete', on_click=lambda columns=columns, i=i: (
                                            columns.pop(i), _listing_columns_rows.refresh(), _refresh(tree=True, document=True))) \
                                            .props('flat round dense color=negative')
                            _listing_columns_rows()

                            def on_add_column(e, node=node, catalog=catalog, template_only=template_only):
                                if not e.value:
                                    return
                                columns = node.setdefault('columns', [])
                                columns.append({'field_key': e.value, 'source': 'template' if e.value in template_only else 'fixed',
                                               'label': catalog.get(e.value, e.value)})
                                add_column.set_value(None)
                                _listing_columns_rows.refresh()
                                _refresh(tree=True, document=True)
                            add_column = ui.select(catalog, value=None, label='Agregar columna').props('outlined dense').classes('w-72 mt-2') \
                                .on_value_change(on_add_column)
                else:
                    ui.label('Contenido de la tabla:').classes('text-xs text-gray-500 mt-2')
                    custom_table_editor({'data': node}, 'data', lambda: document_view.refresh())
            elif node['kind'] == 'text':
                with ui.row().classes('items-center gap-2 w-full no-wrap mt-2'):
                    ui.checkbox('Es un título', value=bool(node.get('heading'))) \
                        .on_value_change(lambda e, node=node: (node.__setitem__('heading', e.value), _refresh(inspector=True, document=True)))
                    if node.get('heading'):
                        ui.number('Nivel', value=node.get('level', 2), min=1, max=4).props('outlined dense').classes('w-24') \
                            .on_value_change(lambda e, node=node: (node.__setitem__('level', int(e.value or 2)), _refresh(document=True)))
                # Sin _refresh(tree=True)/refrescarse a sí mismo acá: recrear el árbol o este mismo panel en
                # cada tecla le borraría el foco al textarea (ver core memoria de sesión) -- la etiqueta del
                # nodo en el árbol queda desactualizada hasta el próximo refresh real (cosmético, aceptado).
                # document_view SÍ se refresca en cada tecla: al vivir en otro panel, no le afecta el foco.
                ui.textarea('Contenido', value=node.get('value', '')).props('outlined dense').classes('w-full mt-2') \
                    .on_value_change(lambda e, node=node: (node.__setitem__('value', e.value), document_view.refresh()))
            elif node['kind'] == 'image':
                ui.input('Etiqueta', value=node.get('label', '')).props('outlined dense').classes('w-64 mt-2') \
                    .on_value_change(lambda e, node=node: (node.__setitem__('label', e.value), document_view.refresh()))
                file_ref = node.get('file')
                ui.label(f'Archivo: {file_ref["filename"]}' if file_ref else 'Ningún archivo todavía.').classes('text-xs text-gray-500')

                async def on_upload(event, node=node):
                    try:
                        raw = await read_upload(event)
                        node['file'] = core.save_custom_field_file(raw, event.file.name, event.file.content_type)
                        _refresh(tree=True, document=True)
                    except Exception as exc:
                        ui.notify(str(exc) or type(exc).__name__, type='negative', multi_line=True)
                ui.upload(on_upload=on_upload, auto_upload=True).props('flat bordered accept="image/*"').classes('w-full')
            elif node['kind'] == 'list':
                ui.checkbox('Numerada', value=bool(node.get('ordered'))) \
                    .on_value_change(lambda e, node=node: (node.__setitem__('ordered', e.value), document_view.refresh()))

                @ui.refreshable
                def _list_rows(node=node):
                    items = node.setdefault('items', [])
                    for i, item in enumerate(items):
                        with ui.row().classes('items-center gap-2 w-full no-wrap'):
                            ui.input(value=item).props('outlined dense').classes('grow') \
                                .on_value_change(lambda e, items=items, i=i: (items.__setitem__(i, e.value), document_view.refresh()))
                            ui.button(icon='delete', on_click=lambda items=items, i=i: (items.pop(i), _list_rows.refresh(), _refresh(tree=True, document=True))) \
                                .props('flat round dense color=negative')
                _list_rows()
                ui.button('Agregar elemento', icon='add', on_click=lambda node=node: (node.setdefault('items', []).append('Elemento'), _list_rows.refresh(), _refresh(tree=True, document=True))) \
                    .props('outline dense color=primary')
            elif node['kind'] == 'checklist':
                @ui.refreshable
                def _checklist_rows(node=node):
                    items = node.setdefault('items', [])
                    for i, item in enumerate(items):
                        with ui.row().classes('items-center gap-2 w-full no-wrap'):
                            ui.checkbox(value=bool(item.get('checked'))) \
                                .on_value_change(lambda e, item=item: (item.__setitem__('checked', e.value), document_view.refresh()))
                            ui.input(value=item.get('label', '')).props('outlined dense').classes('grow') \
                                .on_value_change(lambda e, item=item: (item.__setitem__('label', e.value), document_view.refresh()))
                            ui.button(icon='delete', on_click=lambda items=items, i=i: (items.pop(i), _checklist_rows.refresh(), _refresh(tree=True, document=True))) \
                                .props('flat round dense color=negative')
                _checklist_rows()
                ui.button('Agregar opción', icon='add',
                         on_click=lambda node=node: (node.setdefault('items', []).append({'label': 'Opción', 'checked': False}), _checklist_rows.refresh(), _refresh(tree=True, document=True))) \
                    .props('outline dense color=primary')
            elif node['kind'] == 'repeat':
                input_template = core.get('spec_templates', state['input_template_id']) if state['input_template_id'] else None
                table_catalog = _table_field_catalog(input_template)
                if not table_catalog:
                    ui.label('La Plantilla de entrada asociada (arriba) no define ningún campo propio tipo Tabla todavía.') \
                        .classes('text-xs text-amber-700 mt-2')
                else:
                    current_key = node.get('field_key') if node.get('field_key') in table_catalog else None

                    def on_repeat_field_change(e, node=node):
                        node['field_key'] = e.value or ''
                        _refresh(tree=True, document=True)
                    ui.select(table_catalog, value=current_key, label='Campo (tipo Tabla) a repetir por fila').props('outlined dense').classes('w-80 mt-2') \
                        .on_value_change(on_repeat_field_change)
                ui.label('Arrastrá elementos acá adentro: se clonan una vez por cada fila real de ese campo. '
                         'Un Campo hijo con origen "Columna de la fila" saca su valor de esa fila.').classes('text-xs text-gray-500 mt-2')
            elif node['kind'] == 'field':
                input_template = core.get('spec_templates', state['input_template_id']) if state['input_template_id'] else None
                catalog = _field_catalog(applies_to.value, input_template)
                template_only = _template_only_field_keys(input_template)
                ancestor_repeat = _find_ancestor_repeat(node['id'])
                if ancestor_repeat:
                    def on_origin_change(e, node=node):
                        if e.value == 'row':
                            node['source'] = 'row'
                            node['column_index'] = node.get('column_index', 0)
                            node['field_key'] = ''
                            node['label'] = f"Columna {node['column_index'] + 1}"
                        else:
                            node['source'] = 'fixed'
                            node['field_key'] = ''
                            node['label'] = ''
                        _refresh(tree=True, inspector=True, document=True)
                    ui.select({'record': 'Campo del registro', 'row': 'Columna de la fila (este Repetir filas)'},
                             value='row' if node.get('source') == 'row' else 'record', label='Origen') \
                        .props('outlined dense').classes('w-80 mt-2').on_value_change(on_origin_change)
                if node.get('source') == 'row':
                    column_options = {i: f'Columna {i + 1}' for i in range(10)}
                    current_index = node.get('column_index', 0)

                    def on_column_change(e, node=node):
                        node['column_index'] = e.value
                        node['label'] = f'Columna {e.value + 1}'
                        _refresh(tree=True, document=True)
                    ui.select(column_options, value=current_index, label='Columna (según el orden real de la tabla)').props('outlined dense').classes('w-72 mt-2') \
                        .on_value_change(on_column_change)
                elif not catalog:
                    ui.label('No hay campos para elegir todavía: "Aplica a" no tiene campos fijos conocidos y no hay '
                             'Plantilla de entrada asociada (arriba) con campos propios.').classes('text-xs text-amber-700 mt-2')
                else:
                    current_key = node.get('field_key') if node.get('field_key') in catalog else None

                    def on_field_change(e, node=node, catalog=catalog, template_only=template_only):
                        node['field_key'] = e.value or ''
                        node['source'] = 'template' if e.value in template_only else 'fixed'
                        node['label'] = catalog.get(e.value, e.value or '')
                        _refresh(tree=True, document=True)
                    ui.select(catalog, value=current_key, label='Campo').props('outlined dense').classes('w-72 mt-2') \
                        .on_value_change(on_field_change)

        @ui.refreshable
        def document_view():
            record = _get_preview_record()
            header_blocks = layout_to_blocks(d['header'], record, applies_to=applies_to.value, project_id=pid)
            body_blocks = layout_to_blocks(d['body'], record, applies_to=applies_to.value, project_id=pid)
            footer_blocks = layout_to_blocks(d['footer'], record, applies_to=applies_to.value, project_id=pid)
            if not (header_blocks or body_blocks or footer_blocks):
                ui.label('Arrastrá elementos al árbol (riel de la derecha) para ver la vista previa acá.').classes('text-sm text-gray-400')
                return
            parts = []
            if header_blocks:
                parts.append('<div style="padding-bottom:12px;border-bottom:1px dashed #d1d5db;margin-bottom:16px">'
                             + report_render.render_html_fragment(header_blocks) + '</div>')
            parts.append(report_render.render_html_fragment(body_blocks))
            if footer_blocks:
                parts.append('<div style="padding-top:12px;border-top:1px dashed #d1d5db;margin-top:16px">'
                             + report_render.render_html_fragment(footer_blocks) + '</div>')
            ui.html(live_doc_html(''.join(parts), doc_typography()[0]), sanitize=False).classes('w-full')

        async def _export(fmt):
            record = _get_preview_record()
            header_blocks = layout_to_blocks(d['header'], record, applies_to=applies_to.value, project_id=pid)
            body_blocks = layout_to_blocks(d['body'], record, applies_to=applies_to.value, project_id=pid)
            footer_blocks = layout_to_blocks(d['footer'], record, applies_to=applies_to.value, project_id=pid)
            title = name.value or 'Diseño'
            if fmt == 'pdf':
                body_doc = rd.doc(title, body_blocks)
                with tempfile.TemporaryDirectory() as folder:
                    target = Path(folder) / 'r.pdf'
                    await run.io_bound(report_render.render_layout_pdf, header_blocks, body_doc, footer_blocks, target)
                    ui.download(target.read_bytes(), f'{_stem(title)}.pdf')
            elif fmt == 'docx':
                body_doc = rd.doc(title, body_blocks)
                content = await run.io_bound(report_render.render_layout_docx, header_blocks, body_doc, footer_blocks)
                ui.download(content, f'{_stem(title)}.docx')
            else:
                full_doc = rd.doc(title, header_blocks + body_blocks + footer_blocks)
                ui.download(report_render.render_html(full_doc).encode('utf-8'), f'{_stem(title)}.html')
            ui.notify('Exportado', type='positive')

        def save():
            if current:
                core.update_report_layout(current['id'], name.value, applies_to.value, d['header'], d['body'], d['footer'],
                                          description.value or '', input_template_id=state['input_template_id'])
                ui.notify('Diseño actualizado', type='positive')
                ui.navigate.to(f'/report-designer/edit?id={current["id"]}')
            else:
                layout = core.create_report_layout(name.value, applies_to.value, pid, d['header'], d['body'], d['footer'],
                                                   description.value or '', input_template_id=state['input_template_id'])
                ui.notify('Diseño creado', type='positive')
                ui.navigate.to(f'/report-designer/edit?id={layout["id"]}')

        def side_extra():
            # Sin estado propio -- a diferencia del árbol/inspector, se puede reconstruir tranquilo cada vez
            # que el panel lateral se refresca, sin perder nada (mismo criterio que user_stories.py).
            ui.button('Guardar cambios' if current else 'Crear diseño', icon='save', on_click=guard(save)).props('color=primary').classes('w-full').mark('layout-save')
            with ui.row().classes('gap-2 w-full'):
                ui.button('HTML', icon='download', on_click=guard(lambda: _export('html'))).props('outline dense color=primary')
                ui.button('PDF', icon='picture_as_pdf', on_click=guard(lambda: _export('pdf'))).props('outline dense color=primary')
                ui.button('Word', icon='description', on_click=guard(lambda: _export('docx'))).props('outline dense color=primary')
            if current:
                def remove():
                    core.delete_report_layout(current['id'])
                    ui.notify('Diseño eliminado', type='positive')
                    ui.navigate.to('/report-designer')
                ui.button('Eliminar diseño', icon='delete', on_click=lambda: confirm(f'¿Eliminar el diseño «{current["name"]}»? No se puede deshacer.', remove)) \
                    .props('flat dense color=negative').classes('w-full')

        # Mismo bloque Nivel 1 (`workspace_layout`) que ya usan Historias de usuario/Casos de prueba -- acá con
        # DOS anclas de centro (Lienzo y Documento, los 2 paneles MAYORES del área de diseño): por defecto se
        # ven lado a lado (center_mode='split', ver get_pref de arriba), con un botón para alternar a pestañas
        # (verlos de a uno). El Lienzo solo tiene Encabezado/Cuerpo/Pie -- "Elementos" (la paleta para
        # arrastrar) y "Propiedades" (el detalle del nodo seleccionado) son las 2 pestañas del riel lateral.
        # center_footer (Propiedades fijo abajo del centro) se probó y se descartó: ese contenedor usa
        # overflow:hidden, así que una tabla con muchas filas lo recorta sin dejar forma de hacer scroll hasta
        # verlo -- una pestaña aparte, con su propio scroll interno, no tiene ese problema.
        with ui.element('div').classes('w-full').style('height: calc(100vh - 230px)'):
            workspace_handle['value'] = workspace_layout(
                side_panels=[Panel('palette', 'Elementos', 'add_box', _palette), Panel('inspector', 'Propiedades', 'tune', _inspector_panel)],
                center_anchors=[Panel('tree', 'Lienzo', 'account_tree', _tree), Panel('document', 'Documento', 'description', document_view)],
                prefix='report_designer', get_pref=get_pref, set_pref=set_pref,
                side_title='Elementos', side_icon='add_box', side_extra=side_extra,
                fill_height=True,
            )
        workspace_handle['value'].add_to_center('document')
