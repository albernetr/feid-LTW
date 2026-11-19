"""app/assistant/: componente de Asistente reutilizable y portable (sin ningún import de app.core ni de
app.pages), verificado de forma aislada vía la ruta de demo en app/pages/assistant_demo.py — con
InMemoryAdapter, no un adaptador real. Migrar las páginas reales para que lo usen queda para los próximos
pasos (ver el plan)."""
from nicegui.testing import User


async def _reset(user: User):
    await user.open('/assistant/demo-reset')
    await user.should_see(marker='demo-assistant-reset-done')


async def test_empty_hint_shows_before_any_message(user: User):
    await _reset(user)
    await user.open('/assistant/demo')
    await user.should_see('Escribí algo para empezar.')


async def test_matching_intent_runs_its_handler(user: User):
    await _reset(user)
    await user.open('/assistant/demo')
    user.find(marker='demo-assistant-input').type('eco esto')
    user.find(marker='demo-assistant-send').click()
    await user.should_see('Dijiste: eco esto')


async def test_unmatched_text_goes_to_fallback(user: User):
    await _reset(user)
    await user.open('/assistant/demo')
    user.find(marker='demo-assistant-input').type('cualquier otra cosa')
    user.find(marker='demo-assistant-send').click()
    await user.should_see('No reconocí ningún intent ahí')


async def test_memory_persists_across_reloads_when_enabled(user: User):
    await _reset(user)
    await user.open('/assistant/demo')
    user.find(marker='demo-assistant-input').type('eco persistente')
    user.find(marker='demo-assistant-send').click()
    await user.should_see('Dijiste: eco persistente')

    await user.open('/assistant/demo')   # recarga la página — mismo thread_key, memoria habilitada por defecto
    await user.should_see('Dijiste: eco persistente')


async def test_disabling_memory_stops_new_turns_from_being_saved(user: User):
    await _reset(user)
    await user.open('/assistant/demo')
    user.find(marker='demo-assistant-menu').click()
    user.find(marker='assistant-memory-toggle').click()   # apaga "Recordar esta conversación"

    user.find(marker='demo-assistant-input').type('eco no debería quedar guardado')
    user.find(marker='demo-assistant-send').click()
    await user.should_see('Dijiste: eco no debería quedar guardado')   # se ve en esta sesión...

    await user.open('/assistant/demo')
    await user.should_not_see('no debería quedar guardado')   # ...pero no sobrevive a la recarga


async def test_compact_keeps_only_recent_turns():
    from app.assistant import InMemoryAdapter
    memory = InMemoryAdapter()
    for i in range(30):
        memory.append('t', {'who': 'user', 'text': str(i)})
    memory.compact('t', keep_last=5)
    assert len(memory.load('t')) == 5


async def test_clear_from_the_menu_empties_the_thread(user: User):
    await _reset(user)
    await user.open('/assistant/demo')
    user.find(marker='demo-assistant-input').type('eco esto se va a borrar')
    user.find(marker='demo-assistant-send').click()
    await user.should_see('Dijiste: eco esto se va a borrar')

    user.find(marker='demo-assistant-menu').click()
    user.find(marker='assistant-memory-clear').click()
    await user.should_not_see('Dijiste: eco esto se va a borrar')
    await user.should_see('Escribí algo para empezar.')
