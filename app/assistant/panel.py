"""Chrome de UI del Asistente — historial + input + (opcional) contenido extra, y el menú de memoria para
insertar en un `ui.menu()` ya abierto por la página anfitriona. Sin ningún import de `app.core` ni de
`app.pages`: la página decide memoria, perfil y dónde montar esto (típicamente como el `render` de un
`Panel` más dentro de `workspace_layout`)."""
from nicegui import ui

from ._types import MemoryAdapter, AssistantProfile


def assistant_header(title: str, tooltip: str = '') -> None:
    with ui.row().classes('items-center gap-2'):
        ui.icon('smart_toy', color='primary')
        ui.label(title).classes('font-semibold')
        if tooltip:
            ui.icon('info', size='xs', color='grey').classes('cursor-help').tooltip(tooltip)


def assistant_panel(profile: AssistantProfile, *, thread: list, memory: MemoryAdapter, thread_key: str,
                     candidates=None) -> None:
    """Llamable más de una vez en la misma página (una por mount físico — lateral/centro/abajo), siempre que
    `thread`/`memory`/`thread_key` sean los mismos objetos en cada mount, para que no diverjan.

    - `candidates`: callable opcional que renderiza contenido propio de la página entre el historial y el
      input (p. ej. una tarjeta de "elegí cuál de estos crear") — `assistant_panel` no sabe qué es, solo lo
      llama en el lugar correcto."""

    @ui.refreshable
    def history_view():
        if not thread:
            ui.label(profile.empty_hint).classes('text-sm text-gray-400')
        for turn in thread:
            with ui.chat_message(name='Vos' if turn['who'] == 'user' else 'Asistente', sent=turn['who'] == 'user').classes('w-full'):
                ui.label(turn['text']).style('white-space:pre-wrap')
    history_view()
    if candidates:
        candidates()

    async def send(box):
        text = (box.value or '').strip()
        if not text:
            return
        box.value = ''
        thread.append({'who': 'user', 'text': text})
        if memory.is_enabled(thread_key):
            memory.append(thread_key, thread[-1])
        history_view.refresh()
        lowered = text.lower()
        try:
            intent = next((i for i in profile.intents
                           if any(k in lowered for k in i.keywords) or (i.also_match and i.also_match(text))), None)
            if intent:
                reply = await intent.handler(text)
            elif profile.fallback:
                reply = await profile.fallback(text, thread[:-1])
            else:
                reply = 'No tengo nada configurado para responder a esto todavía.'
        except profile.catch as exc:
            reply = f'No pude: {exc}'
        thread.append({'who': 'assistant', 'text': reply})
        if memory.is_enabled(thread_key):
            memory.append(thread_key, thread[-1])
        history_view.refresh()

    with ui.row().classes('w-full items-center gap-2'):
        box = ui.input(placeholder=profile.placeholder).props('outlined dense').classes('grow').mark(f'{profile.name}-assistant-input')
        box.on('keydown.enter', lambda: send(box))
        ui.button(icon='send', on_click=lambda: send(box)).props('round dense color=primary').mark(f'{profile.name}-assistant-send')


def assistant_memory_menu_items(memory: MemoryAdapter, thread_key: str, on_change, *, default_enabled: bool = True) -> None:
    """Para insertar DENTRO de un `with ui.menu():` ya abierto por la página — un switch ("Recordar esta
    conversación") más "Compactar"/"Limpiar", todo sobre ESTE hilo puntual. `on_change` es responsabilidad de
    la página anfitriona: debe resincronizar su `thread` local (p. ej. `thread[:] = memory.load(thread_key)`)
    y refrescar lo que haga falta — este helper no conoce esas vistas."""
    with ui.row().classes('items-center gap-2 w-full no-wrap px-4 py-2'):
        ui.label('Recordar esta conversación').classes('text-sm grow')

        def on_toggle(e):
            # No llama a on_change(): habilitar/deshabilitar no cambia el contenido del hilo, así que no hay
            # nada que resincronizar ni refrescar — y refrescar acá innecesariamente deja elementos del
            # input/botón obsoletos si el usuario ya estaba escribiendo (visto en tests/test_assistant_panel.py).
            memory.set_enabled(thread_key, e.value)
        ui.switch(value=memory.is_enabled(thread_key, default_enabled), on_change=on_toggle).props('dense color=primary').mark('assistant-memory-toggle')

    with ui.row().classes('gap-1 px-4 pb-2'):
        def do_compact():
            memory.compact(thread_key)
            on_change()

        def do_clear():
            memory.clear(thread_key)
            on_change()
        ui.button('Compactar', icon='compress', on_click=do_compact).props('flat dense size=sm no-caps').mark('assistant-memory-compact') \
            .tooltip('Recorta este hilo a los últimos turnos')
        ui.button('Limpiar', icon='delete_sweep', on_click=do_clear).props('flat dense size=sm no-caps color=negative').mark('assistant-memory-clear') \
            .tooltip('Borra todo el historial de este hilo')
