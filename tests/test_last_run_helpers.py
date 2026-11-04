"""last_run_for_case/last_run_for_suite_group: el último run decisivo (no cancelado/omitido) de un caso (API o
UI) o de una suite (grupo) — mismo criterio que ya usa last_run_for_suite, para mostrar el estado junto al
nombre en las listas de Casos/Flujos/Suites."""
from app import core


def _run(**extra):
    base = {'id': core.uid(), 'started_at': core.now(), 'status': 'passed'}
    base.update(extra)
    return core.save('runs', base)


def test_last_run_for_case_ignores_other_cases_and_non_decisive_statuses():
    assert core.last_run_for_case('c1') is None
    _run(type='api', case_id='c1', status='cancelled')
    assert core.last_run_for_case('c1') is None   # cancelado no cuenta
    _run(type='api', case_id='other', status='passed')
    assert core.last_run_for_case('c1') is None   # de otro caso


def test_last_run_for_case_picks_the_most_recent_and_covers_both_api_and_ui():
    _run(type='api', case_id='c1', status='failed', started_at='2026-01-01T00:00:00')
    latest = _run(type='ui', case_id='c1', status='passed', started_at='2026-01-02T00:00:00')
    found = core.last_run_for_case('c1')
    assert found['id'] == latest['id'] and found['status'] == 'passed'


def test_last_run_for_suite_group_ignores_suites_and_other_groups():
    _run(type='suite', suite_id='g1', status='passed')   # un flujo, no una suite (grupo)
    assert core.last_run_for_suite_group('g1') is None
    _run(type='suite_group', group_id='other', status='passed')
    assert core.last_run_for_suite_group('g1') is None


def test_last_run_for_suite_group_picks_the_most_recent():
    _run(type='suite_group', group_id='g1', status='failed', started_at='2026-01-01T00:00:00')
    latest = _run(type='suite_group', group_id='g1', status='passed', started_at='2026-01-02T00:00:00')
    found = core.last_run_for_suite_group('g1')
    assert found['id'] == latest['id']
