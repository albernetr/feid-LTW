"""Conjuntos de datos: sube un .txt/.csv/.json con valores de referencia (nombres, RFCs, situación laboral, rangos
de sueldo…) para usarlos como {{random:nombre}} / {{random:nombre.columna}} en cualquier caso — cada aparición
sortea una fila al azar del conjunto, de nuevo en cada envío. Para que varios campos de la misma conversación
compartan la fila sorteada (la misma persona en todo el flujo), una Suite declara un «Sorteo» con este conjunto
(ver /suites/edit) en vez de referenciarlo directo como {{random:...}}."""
import random
from nicegui import ui
from .. import core
from .common import frame, guard, confirm, empty_state, require_project, read_upload


@ui.page('/datasets')
def datasets_page():
    with frame('Conjuntos de datos', '/datasets'):
        if not require_project():
            return
        pid = core.get_active_project_id()

        with ui.card().classes('w-full'):
            ui.label('Nuevo conjunto de datos').classes('text-lg font-semibold')
            ui.label('Un .txt (un valor por línea), un .csv (primera fila = columnas) o un .json '
                      '(lista de objetos, o lista de valores sueltos).').classes('text-sm text-gray-500')
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

        @ui.refreshable
        def table_view():
            items = core.list_project_items('datasets', pid)
            if not items:
                empty_state('No hay conjuntos de datos todavía. Subí uno arriba.')
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
