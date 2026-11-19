"""Demo de app/assistant/ — sin nada de app.core (usa InMemoryAdapter, no un adaptador real), solo para
ejercitarlo y verlo en vivo, y para que tests/test_assistant_panel.py tenga una ruta fija y real contra la
que probar. No está en NAV/NAV_GROUPS a propósito: es documentación viva, no una pantalla real de LTW."""
from nicegui import ui
from ..assistant import AssistantIntent, AssistantProfile, InMemoryAdapter, assistant_header, assistant_memory_menu_items, assistant_panel

# Un solo adaptador para todo el proceso de demo — mismo espíritu que el ASSISTANT_THREADS de hoy en
# user_stories.py/test_case_specs.py (se pierde al reiniciar el servidor; los adaptadores reales persisten
# de verdad, ver app/assistant_memory.py).
_MEMORY = InMemoryAdapter()


async def _handle_eco(text):
    return f'Dijiste: {text}'


async def _fallback(text, history):
    return f'No reconocí ningún intent ahí — probá "eco: algo". ({len(history)} turno(s) antes de este)'


_PROFILE = AssistantProfile(
    name='demo',
    placeholder='Escribí "eco algo" para probar un intent, cualquier otra cosa va al fallback',
    empty_hint='Escribí algo para empezar.',
    tooltip='Demo aislada del Asistente reutilizable — memoria en InMemoryAdapter, se pierde al reiniciar.',
    intents=[AssistantIntent(keywords=('eco',), handler=_handle_eco)],
    fallback=_fallback,
)


@ui.page('/assistant/demo')
def assistant_demo():
    thread_key = 'demo:main'
    thread = _MEMORY.load(thread_key)

    @ui.refreshable
    def assistant_mount():
        assistant_header('Asistente de IA', _PROFILE.tooltip)
        assistant_panel(_PROFILE, thread=thread, memory=_MEMORY, thread_key=thread_key)

    def on_memory_change():
        # Mismo patrón que van a seguir las páginas reales (ver assistant_right_mount/assistant_bottom_mount
        # en user_stories.py): resincronizar `thread` con lo que diga la memoria, y refrescar el mount — no
        # alcanza con mutar `thread` solo, `history_view` vive adentro de assistant_panel() y no tiene forma
        # de enterarse sin volver a llamarlo.
        thread[:] = _MEMORY.load(thread_key)
        assistant_mount.refresh()

    with ui.column().classes('w-full p-4 gap-4').style('max-width:640px'):
        with ui.row().classes('items-center justify-between w-full'):
            ui.label('Demo de Asistente').classes('text-2xl font-semibold')
            with ui.button(icon='more_vert').props('flat round dense').mark('demo-assistant-menu'):
                with ui.menu():
                    assistant_memory_menu_items(_MEMORY, thread_key, on_change=on_memory_change)
        with ui.card().classes('w-full'):
            assistant_mount()


@ui.page('/assistant/demo-reset')
def assistant_demo_reset():
    """Ruta fija para que un test pueda dejar la memoria de la demo limpia entre corridas, sin depender del
    orden de ejecución de otros tests que también usan /assistant/demo."""
    _MEMORY.clear_all()
    ui.label('Memoria de la demo reiniciada').mark('demo-assistant-reset-done')
