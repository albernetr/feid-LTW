"""Conjuntos de datos: valores de referencia (nombres, RFCs, situación laboral, rangos de sueldo…) para usarlos
como {{random:nombre}} / {{random:nombre.columna}} en cualquier caso — cada aparición sortea una fila al azar del
conjunto, de nuevo en cada envío. Se crean subiendo un .txt/.csv/.json, o a mano (columna por columna, fila por
fila) — y, una vez creados, siempre se pueden editar acá, vinieron de un archivo o no. Para que varios campos de
la misma conversación compartan la fila sorteada (la misma persona en todo el flujo), un Flujo declara un
«Sorteo» con este conjunto (ver /suites/edit) en vez de referenciarlo directo como {{random:...}}."""
import random
from nicegui import ui
from .. import core
from .common import frame, guard, confirm, empty_state, require_project, read_upload


def dataset_grid_editor(columns, rows):
    """Editor visual de un conjunto (columnas + filas), tipo planilla: agrega/renombra/quita columnas, agrega/quita
    filas, edita cualquier celda. `columns` (lista de nombres) y `rows` (lista de dict) se mutan en el lugar."""
    @ui.refreshable
    def view():
        with ui.element('div').classes('w-full overflow-auto'):
            with ui.row().classes('items-start gap-1 no-wrap'):
                for idx, col in enumerate(list(columns)):
                    with ui.column().classes('gap-1').style('min-width:170px'):
                        with ui.row().classes('items-center gap-1 no-wrap'):
                            # Por índice, no por nombre capturado: cada tecleo busca/actualiza columns[i] al vuelo
                            # (en vez de esperar a perder el foco) para que un clic inmediato en «Agregar columna»/
                            # «Agregar fila» justo al lado nunca le gane de carrera al renombre y lo pise.
                            def rename(e, i=idx):
                                new = (e.value or '').strip()
                                old = columns[i]
                                if not new or new == old or new in columns:
                                    return
                                columns[i] = new
                                for row in rows:
                                    row[new] = row.pop(old, '')
                            ui.input(value=col, placeholder='columna').props('outlined dense').classes('grow').on_value_change(rename)

                            def remove_col(_, i=idx):
                                if len(columns) <= 1:
                                    ui.notify('Necesitás al menos una columna', type='negative')
                                    return
                                removed = columns.pop(i)
                                for row in rows:
                                    row.pop(removed, None)
                                view.refresh()
                            ui.button(icon='close', on_click=remove_col).props('flat round dense size=sm color=negative').tooltip('Quitar columna')
                        for row in rows:
                            def edit_cell(e, r=row, i=idx):
                                r[columns[i]] = e.value
                            ui.input(value=row.get(col, '')).props('outlined dense').classes('w-full').on_value_change(edit_cell)

                def add_col():
                    name = f'columna{len(columns) + 1}'
                    columns.append(name)
                    for row in rows:
                        row.setdefault(name, '')
                    view.refresh()
                ui.button(icon='add', on_click=add_col).props('flat round dense color=primary').tooltip('Agregar columna').classes('mt-7')
        if not rows:
            ui.label('Sin filas todavía.').classes('text-gray-500 text-sm mt-1')

        def add_row():
            rows.append({c: '' for c in columns})
            view.refresh()

        def remove_last_row():
            if rows:
                rows.pop()
                view.refresh()
        with ui.row().classes('gap-2 mt-2'):
            ui.button('Agregar fila', icon='add', on_click=add_row).props('flat dense color=primary')
            ui.button('Quitar última fila', icon='remove', on_click=remove_last_row).props('flat dense color=grey-8')
    view()
    return view


@ui.page('/datasets')
def datasets_page():
    with frame('Conjuntos de datos', '/datasets'):
        if not require_project():
            return
        pid = core.get_active_project_id()
        view = {'mode': 'list', 'id': None}   # 'list' | 'edit'

        def edit_dataset(dataset_id):
            view.update(mode='edit', id=dataset_id)
            content.refresh()

        def back_to_list():
            view.update(mode='list', id=None)
            content.refresh()

        def dataset_editor(dataset_id):
            dataset = core.get('datasets', dataset_id)
            ui.button('← Volver a la lista', on_click=back_to_list).props('flat dense no-caps').classes('mb-1')
            if dataset is None:
                ui.label('Ese conjunto ya no existe.').classes('text-amber-700')
                return
            with ui.card().classes('w-full gap-2'):
                ui.label(f'Editando «{dataset["name"]}»').classes('text-lg font-semibold')
                name_input = ui.input('Nombre', value=dataset['name']).props('outlined dense').classes('w-72')
                columns = list(dataset['columns'])
                rows = [dict(r) for r in dataset['rows']]
                dataset_grid_editor(columns, rows)

                def save():
                    clean_rows = [r for r in rows if any((v or '').strip() for v in r.values())]
                    core.save_dataset(name_input.value, pid, columns, clean_rows, id=dataset['id'])
                    ui.notify('Conjunto actualizado', type='positive')
                    back_to_list()
                with ui.row().classes('gap-2 mt-2'):
                    ui.button('Guardar cambios', icon='save', on_click=guard(save)).props('color=primary')
                    ui.button('Volver sin guardar', on_click=back_to_list).props('flat')

        def dataset_list():
            with ui.card().classes('w-full'):
                ui.label('Nuevo conjunto de datos').classes('text-lg font-semibold')
                ui.label('Subí un archivo, o armalo a mano abajo.').classes('text-sm text-gray-500')
                ui.label('Un .txt (un valor por línea), un .csv (primera fila = columnas) o un .json '
                          '(lista de objetos, o lista de valores sueltos).').classes('text-xs text-gray-500')
                pending = {}
                preview_box = ui.column().classes('w-full gap-2')

                async def on_upload(event):
                    try:
                        raw = await read_upload(event)
                        columns, rows = core.parse_dataset_file(event.file.name, raw)
                    except ValueError as exc:
                        preview_box.clear()
                        ui.notify(str(exc), type='negative', multi_line=True)
                        return
                    pending.update(filename=event.file.name, columns=columns, rows=rows)
                    show_preview()

                def show_preview():
                    preview_box.clear()
                    with preview_box:
                        default_name = pending['filename'].rsplit('.', 1)[0]
                        name_input = ui.input('Nombre del conjunto', value=default_name).props('outlined dense').classes('w-72')
                        ui.label(f'{len(pending["rows"])} fila(s) · columnas: {", ".join(pending["columns"])}').classes('text-sm text-gray-600')
                        with ui.element('div').classes('w-full overflow-auto').style('max-height:260px'):
                            cols = [{'name': c, 'label': c, 'field': c, 'align': 'left'} for c in pending['columns']]
                            ui.table(columns=cols, rows=pending['rows'][:10], row_key=pending['columns'][0]).classes('w-full').props('dense flat bordered')
                        if len(pending['rows']) > 10:
                            ui.label(f'… y {len(pending["rows"]) - 10} fila(s) más.').classes('text-xs text-gray-500')

                        def save():
                            core.save_dataset(name_input.value, pid, pending['columns'], pending['rows'])
                            ui.notify(f'Conjunto «{name_input.value}» guardado', type='positive')
                            pending.clear()
                            preview_box.clear()
                            table_view.refresh()
                        ui.button('Guardar conjunto', icon='save', on_click=guard(save)).props('color=primary')
                ui.upload(label='Elige o arrastra un archivo', on_upload=on_upload, auto_upload=True, max_file_size=core.MAX_DATASET_BYTES) \
                    .props('accept=.txt,.csv,.json flat bordered').classes('w-full')
                preview_box

                ui.separator().classes('my-2')
                ui.label('O creá uno a mano').classes('font-medium text-sm')
                manual = {'columns': ['valor'], 'rows': [{'valor': ''}]}
                manual_name = ui.input('Nombre del conjunto').props('outlined dense').classes('w-72')
                dataset_grid_editor(manual['columns'], manual['rows'])

                def save_manual():
                    clean_rows = [r for r in manual['rows'] if any((v or '').strip() for v in r.values())]
                    core.save_dataset(manual_name.value, pid, manual['columns'], clean_rows)
                    ui.notify(f'Conjunto «{manual_name.value}» guardado', type='positive')
                    manual_name.set_value('')
                    manual['columns'][:] = ['valor']
                    manual['rows'][:] = [{'valor': ''}]
                    table_view.refresh()
                ui.button('Guardar conjunto', icon='save', on_click=guard(save_manual)).props('outline color=primary').classes('mt-2')

            @ui.refreshable
            def table_view():
                items = core.list_project_items('datasets', pid)
                if not items:
                    empty_state('No hay conjuntos de datos todavía. Subí uno o creá uno a mano, arriba.')
                    return
                for dataset in items:
                    with ui.card().classes('w-full'):
                        with ui.row().classes('items-center gap-3 w-full no-wrap'):
                            with ui.column().classes('gap-0 grow'):
                                ui.label(dataset['name']).classes('font-semibold')
                                ui.label(f'{len(dataset["rows"])} fila(s) · {", ".join(dataset["columns"])}').classes('text-sm text-gray-500')

                            def view_sample(d=dataset):
                                with ui.dialog() as dialog, ui.card().classes('w-[700px] max-w-full'):
                                    ui.label(f'Muestra de «{d["name"]}»').classes('text-lg font-semibold')
                                    cols = [{'name': c, 'label': c, 'field': c, 'align': 'left'} for c in d['columns']]
                                    sample = [random.choice(d['rows'])] if d['rows'] else []
                                    ui.table(columns=cols, rows=sample, row_key=d['columns'][0]).classes('w-full').props('dense flat bordered')
                                    ui.label('Una fila elegida al azar cada vez que abrís esto — así se ve exactamente lo que {{random:…}} devolvería.') \
                                        .classes('text-xs text-gray-500')
                                    ui.button('Cerrar', on_click=dialog.close).props('flat')
                                dialog.open()
                            ui.button('Ver muestra', icon='casino', on_click=view_sample).props('outline dense')
                            ui.button(icon='edit', on_click=lambda _, d=dataset: edit_dataset(d['id'])).props('flat round dense').tooltip('Editar')

                            def remove(d=dataset):
                                core.delete('datasets', d['id'])
                                table_view.refresh()
                            ui.button(icon='delete', on_click=lambda _, d=dataset, r=remove: confirm(
                                f'¿Eliminar «{d["name"]}»? Cualquier {{{{random:{d["name"]}}}}} o Sorteo que lo use dejará de resolver.', r)) \
                                .props('flat round dense color=negative')

                        with ui.row().classes('items-center gap-1 flex-wrap mt-1'):
                            ui.label('Uso:').classes('text-xs text-gray-500')
                            if len(dataset['columns']) == 1:
                                ui.label('{{random:' + dataset['name'] + '}}').classes('text-xs font-mono bg-gray-100 px-1 rounded')
                            for column in dataset['columns'][:4]:
                                ui.label('{{random:' + dataset['name'] + '.' + column + '}}').classes('text-xs font-mono bg-gray-100 px-1 rounded')
            table_view()

        @ui.refreshable
        def content():
            if view['mode'] == 'edit':
                dataset_editor(view['id'])
            else:
                dataset_list()
        content()
