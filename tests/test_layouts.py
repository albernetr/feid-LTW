"""app/layouts/: Nivel 0 (app_shell) y Nivel 1 (workspace_layout) — primitivas reutilizables y portables
(sin ningún import de app.core ni de app.pages), verificadas de forma aislada vía las rutas de demo en
app/pages/layouts_demo.py. Migrar una página real para que las use queda para una ronda futura."""
from nicegui.testing import User


async def test_layouts_demo_renders_shell_and_both_panel_areas(user: User):
    await user.open('/layouts/demo')
    await user.should_see('Demo de layouts')
    await user.should_see('(demo — sin selector de proyecto ni usuario)')
    await user.should_see('Sin navegación real en esta demo')
    await user.should_see(marker='layouts_demo-rail-general')
    await user.should_see(marker='layouts_demo-rail-detalles')
    await user.should_see('Documento')   # center_anchor, visible desde el arranque


async def test_center_anchors_never_appear_in_the_rail(user: User):
    """Regresión: 'document' es un center_anchor — nunca debe tener una pestaña propia en el riel lateral."""
    await user.open('/layouts/demo')
    await user.should_not_see(marker='layouts_demo-rail-document')


async def test_clicking_a_rail_tab_switches_the_visible_side_panel(user: User):
    await user.open('/layouts/demo')
    await user.should_see('Campos de ejemplo')   # 'general' es la pestaña activa por defecto
    user.find(marker='layouts_demo-rail-detalles').click()
    await user.should_see('Otro grupo')


def _split_value(user: User, prefix: str):
    return user.find(marker=f'{prefix}-main-split').elements.pop()._props['model-value']


async def test_clicking_the_active_rail_tab_collapses_and_restores_the_split(user: User):
    await user.open('/layouts/demo')
    before = _split_value(user, 'layouts_demo')
    assert before != 95
    user.find(marker='layouts_demo-rail-general').click()   # ya estaba activa -> colapsa
    assert _split_value(user, 'layouts_demo') == 95
    user.find(marker='layouts_demo-rail-general').click()   # vuelve a hacer clic en la misma -> restaura
    assert _split_value(user, 'layouts_demo') == before


async def test_add_to_center_and_remove_from_center_via_the_handle(user: User):
    await user.open('/layouts/demo-handle-test')
    await user.should_not_see(marker='handle_test-center-a')
    user.find(marker='btn-add-a').click()
    await user.should_see(marker='handle_test-center-a')
    user.find(marker='btn-remove-a').click()
    await user.should_not_see(marker='handle_test-center-a')


async def test_toggle_center_mode_switches_between_tabs_and_split(user: User):
    await user.open('/layouts/demo-handle-test')
    user.find(marker='btn-add-a').click()
    await user.should_see(marker='handle_test-center-a')
    user.find(marker='btn-toggle-mode').click()
    await user.should_see(marker='handle_test-center-document')
    await user.should_see(marker='handle_test-center-a')


async def test_side_extra_renders_and_fill_height_false_does_not_crash(user: User):
    """side_extra: contenido siempre visible, fuera de las pestañas del riel. fill_height=False: estilos sin
    el height:100% que colapsaba todo a 0px cuando no hay una altura definida alrededor (ver test_case_specs.py)."""
    await user.open('/layouts/demo-extra-test')
    await user.should_see(marker='extra-always-visible')
    await user.should_see('doc')


async def test_center_panel_cap_rejects_a_fourth_panel(user: User):
    await user.open('/layouts/demo-cap-test')
    for key in ('a', 'b', 'c'):
        user.find(marker=f'btn-add-{key}').click()
    # document + a + b = 3 = max_center_panels -> el intento de agregar 'c' se rechaza
    await user.should_see('Ya tenés 3 paneles abiertos en el centro')
    await user.should_not_see(marker='cap_test-center-c')
