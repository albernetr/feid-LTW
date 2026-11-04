"""Variables y secuencias: lo que {{now_date}}/{{uuid}}/{{seq}} resuelven ahora mismo (de referencia, no se
guardan) y los consecutivos que sí viven en la base — el global {{seq}} y cada {{seq:nombre}} — para verlos y
ajustarlos a mano sin tener que abrir la base de datos directamente."""
import datetime as dt
from nicegui import ui
from .. import core
from .common import frame, guard, confirm
from .widgets import DYNAMIC_VAR_HINTS


@ui.page('/sequences')
def sequences_page():
    with frame('Variables y secuencias', '/sequences'):
        with ui.card().classes('w-full'):
            ui.label('Variables integradas').classes('text-lg font-semibold')
            ui.label('Se calculan solas en cada envío; no hace falta declararlas en ningún caso. Esto es lo que resolverían ahora mismo.').classes('text-sm text-gray-500')
            stamp = dt.datetime.now(dt.timezone.utc)
            preview = {'now_date': stamp.strftime('%Y-%m-%d'), 'now_time': stamp.strftime('%H:%M:%S'), 'now_iso': stamp.isoformat(),
                       'now_epoch': str(int(stamp.timestamp())), 'uuid': '2f1a9c…(nuevo en cada envío)', 'seq': str(core.current_sequence() + 1)}
            with ui.row().classes('w-full gap-2 flex-wrap mt-2'):
                for name, hint in DYNAMIC_VAR_HINTS:
                    token = '{{' + name + '}}'
                    with ui.row().classes('items-center gap-1 border rounded px-2 py-1'):
                        ui.label(token).classes('font-mono text-sm')
                        ui.label('· ' + preview[name]).classes('text-xs text-gray-500')
                        ui.button(icon='content_copy', on_click=lambda _, t=token: (ui.clipboard.write(t), ui.notify('Copiado', type='positive'))) \
                            .props('flat round dense size=sm').tooltip(hint)

        with ui.card().classes('w-full mt-3'):
            ui.label('Consecutivo global {{seq}}').classes('text-lg font-semibold')
            ui.label('Compartido por toda la app; nunca se reinicia solo. Cada envío que lo usa lo avanza en uno (sea en un caso suelto, un flujo sin consecutivo propio, o un caso de Chat).').classes('text-sm text-gray-500')
            with ui.row().classes('items-center gap-3 mt-1'):
                value = ui.number('Próximo valor', value=core.current_sequence() + 1, precision=0, min=0).props('outlined dense').classes('w-48') \
                    .tooltip('El siguiente envío que use {{seq}} va a recibir este número')

                def save_global():
                    core.set_sequence(int(value.value or 0) - 1)
                    ui.notify('Consecutivo global actualizado', type='positive')
                ui.button('Guardar', icon='save', on_click=guard(save_global)).props('outline')

        with ui.card().classes('w-full mt-3'):
            ui.label('Consecutivos con nombre {{seq:nombre}}').classes('text-lg font-semibold')
            ui.label('Cada nombre persiste por su cuenta y retoma donde quedó, sea en un caso suelto, dentro de un flujo, o en cualquier combinación de los dos.').classes('text-sm text-gray-500')

            @ui.refreshable
            def rows():
                items = core.list_named_sequences()
                if not items:
                    ui.label('Ninguno usado todavía. Aparece acá la primera vez que un caso use {{seq:nombre}}.').classes('text-gray-500 text-sm mt-1')
                for item in items:
                    with ui.row().classes('items-center gap-3 w-full no-wrap mt-1'):
                        ui.label('{{seq:' + item['name'] + '}}').classes('font-mono grow')
                        ui.label('próximo:').classes('text-xs text-gray-500')
                        field = ui.number(value=item['value'] + 1, precision=0, min=0).props('outlined dense').classes('w-32')

                        def save_one(name=item['name'], f=field):
                            core.reset_named_sequence(name, int(f.value or 0) - 1)
                            ui.notify(f'«{name}» actualizado', type='positive')
                            rows.refresh()
                        ui.button(icon='save', on_click=lambda _, s=save_one: s()).props('flat round dense').tooltip('Guardar')

                        def remove(name=item['name']):
                            core.delete('sequences', name)
                            ui.notify(f'«{name}» eliminado', type='positive')
                            rows.refresh()
                        ui.button(icon='delete', on_click=lambda _, n=item['name'], r=remove: confirm(
                            f'¿Eliminar el consecutivo «{n}»? Si algún caso lo vuelve a usar, arranca de nuevo en 1.', r)).props('flat round dense color=negative')
            rows()
