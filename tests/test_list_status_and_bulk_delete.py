"""UI de las listas de Casos API, Casos UI (Guardados), Flujos y Suites: estado de la última corrida junto al
nombre, y «Eliminar seleccionados»/«Eliminar seleccionadas» en Flujos y Suites (reusando la misma marca de
checkboxes que ya usa «Ejecutar seleccionados»)."""
import pytest
from nicegui import ui
from nicegui.testing import User
from app import core


def _setup():
    project = core.create_project('P')
    core.set_active_project(project['id'])
    env = core.save('environments', {'name': 'local', 'project_id': project['id'], 'base_url': 'http://x', 'auth': {'type': 'none'}, 'variables': {}})
    case = core.save('cases', {'name': 'Mi caso', 'type': 'api', 'project_id': project['id'], 'method': 'GET', 'path': '/health', 'assertions': []})
    return project, env, case


def _run(**extra):
    base = {'id': core.uid(), 'started_at': core.now(), 'status': 'passed'}
    base.update(extra)
    return core.save('runs', base)


async def test_case_list_shows_no_badge_without_a_run_and_the_status_once_it_ran(user: User):
    project, env, case = _setup()
    await user.open('/cases')
    await user.should_see('Mi caso')
    with pytest.raises(AssertionError):
        user.find('Falló')   # nunca corrió: sin estado que mostrar
    _run(type='api', case_id=case['id'], status='failed')
    await user.open('/cases')
    await user.should_see('Mi caso')
    await user.should_see('Falló')


async def test_ui_cases_saved_list_shows_the_last_run_status(user: User):
    project, env, case = _setup()
    ui_case = core.save('cases', {'name': 'Mi UI', 'type': 'ui', 'project_id': project['id'], 'steps': [{'action': 'navigate', 'url': '/'}]})
    _run(type='ui', case_id=ui_case['id'], status='passed')
    await user.open('/ui-cases')
    await user.should_see('Mi UI')
    await user.should_see('Pasó')


async def test_suite_list_shows_last_run_status_and_bulk_delete(user: User):
    project, env, case = _setup()
    suite = core.save_suite('Mi flujo', env['id'], [case['id']], project['id'])
    _run(type='suite', suite_id=suite['id'], status='failed')
    await user.open('/suites')
    await user.should_see('Mi flujo')
    await user.should_see('Falló')

    user.find('Eliminar seleccionados').click()
    await user.should_see('Marca al menos un flujo')

    user.find(kind=ui.checkbox).elements.pop().value = True
    user.find('Eliminar seleccionados').click()
    await user.should_see('¿Eliminar 1 flujo(s) seleccionados?')
    user.find(marker='confirm-dialog-accept').click()
    await user.should_see('No hay flujos')
    assert core.list_items('suites') == []


async def test_suite_group_list_shows_last_run_status_and_bulk_delete(user: User):
    project, env, case = _setup()
    group = core.save_suite_group('Mi suite', project['id'], [{'type': 'case', 'id': case['id']}], environment_id=env['id'])
    _run(type='suite_group', group_id=group['id'], status='passed')
    await user.open('/suite-groups')
    await user.should_see('Mi suite')
    await user.should_see('Pasó')

    user.find(kind=ui.checkbox).elements.pop().value = True
    user.find('Eliminar seleccionadas').click()
    await user.should_see('¿Eliminar 1 suite(s) seleccionadas?')
    user.find(marker='confirm-dialog-accept').click()
    await user.should_see('No hay suites')
    assert core.list_items('suite_groups') == []
