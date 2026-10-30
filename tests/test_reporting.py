"""Executive summary and status report: traffic light, trends, failing-since, exports and command line."""
import datetime as dt
import json
import pytest
from app import core, reporting, observer

NOW = dt.datetime(2026, 10, 29, 12, 0, tzinfo=dt.timezone.utc)


def ago(days=0, hours=0):
    return (NOW - dt.timedelta(days=days, hours=hours)).isoformat()


@pytest.fixture
def world():
    project = core.create_project('Tienda')
    cases = {n: core.save('cases', {'name': n, 'method': 'GET', 'path': f'/{n}', 'project_id': project['id'], 'headers': {}, 'query': {}, 'body': None,
                                    'assertions': [], 'variables': {}, 'extract': [], 'timeout': 10}) for n in ('login', 'items', 'pago')}
    suite = core.save('suites', {'name': 'compra', 'project_id': project['id'], 'steps': [{'case_id': cases['login']['id'], 'alias': 'login'}, {'case_id': cases['items']['id'], 'alias': 'items'}]})
    return project, cases, suite


def case_run(project, case, status, when, ms=100, error='', assertions=None):
    return core.save('runs', {'type': 'api', 'case_id': case['id'], 'case_name': case['name'], 'project_id': project['id'], 'status': status, 'started_at': when,
                              'duration_ms': ms, 'error': error, 'assertions': assertions or []})


def suite_run(project, suite, status, when, finished=None):
    return core.save('runs', {'type': 'suite', 'suite_id': suite['id'], 'suite_name': suite['name'], 'project_id': project['id'], 'status': status, 'started_at': when,
                              'finished_at': finished, 'case_runs': []})


def test_without_runs_it_says_so_instead_of_inventing_a_color(world):
    project, _, _ = world
    report = reporting.collect(project['id'], 14, now=NOW)
    assert report['rag']['level'] == 'grey' and report['kpis']['success_rate'] is None and 'Aún no hay ejecuciones' in report['headline']
    assert report['kpis']['cases']['never'] == 3 and len(report['trend']) == 14


def test_all_green(world):
    project, cases, suite = world
    for case in cases.values():
        case_run(project, case, 'passed', ago(1))
    suite_run(project, suite, 'passed', ago(1))
    report = reporting.collect(project['id'], 14, now=NOW)
    assert report['rag']['level'] == 'green' and report['kpis']['success_rate'] == 100.0 and report['kpis']['suites_healthy'] == 1
    assert report['failing'] == [] and 'tasa de éxito 100.0%' in report['headline']


def test_failing_case_is_amber_with_since_and_streak(world):
    project, cases, _ = world
    case_run(project, cases['pago'], 'passed', ago(6))
    for days in (3, 2, 1):
        case_run(project, cases['pago'], 'failed', ago(days), assertions=[{'rule': {'type': 'status', 'expected': 200}, 'passed': False, 'actual': 500}])
    for case in (cases['login'], cases['items']):
        for days in range(1, 7):
            case_run(project, case, 'passed', ago(days))
    report = reporting.collect(project['id'], 14, now=NOW)
    failing = report['failing']
    assert report['rag']['level'] == 'amber' and len(failing) == 1
    assert failing[0]['name'] == 'pago' and failing[0]['consecutive_failures'] == 3 and failing[0]['since'] == ago(3) and 'status' in failing[0]['detail'] and '500' in failing[0]['detail']
    assert any('fallan en su última ejecución' in r for r in report['rag']['reasons'])


def test_a_failing_suite_makes_it_red(world):
    project, cases, suite = world
    for case in cases.values():
        case_run(project, case, 'passed', ago(1))
    suite_run(project, suite, 'failed', ago(1), finished=ago(1, hours=-0))
    report = reporting.collect(project['id'], 14, now=NOW)
    assert report['rag']['level'] == 'red' and report['suites'][0]['status'] == 'failed' and report['kpis']['suites_failing'] == 1


def test_low_success_rate_is_red_and_delta_compares_with_previous_period(world):
    project, cases, _ = world
    for i in range(4):
        case_run(project, cases['login'], 'passed' if i == 0 else 'failed', ago(2 + i))          # 25% now
    for i in range(4):
        case_run(project, cases['login'], 'passed', ago(10 + i))                                    # 100% before (7-day window)
    report = reporting.collect(project['id'], 7, now=NOW)
    assert report['kpis']['success_rate'] == 25.0 and report['kpis']['success_rate_previous'] == 100.0 and report['kpis']['delta'] == -75.0
    assert report['rag']['level'] == 'red' and '25.0%' in ' '.join(report['rag']['reasons'])
    assert '-75.0 puntos' in report['headline'] and not report['headline'].startswith('Estado')


def test_cancelled_runs_do_not_count(world):
    project, cases, _ = world
    case_run(project, cases['login'], 'passed', ago(1))
    case_run(project, cases['login'], 'cancelled', ago(0, hours=2))
    assert reporting.collect(project['id'], 14, now=NOW)['kpis']['executions'] == 1


def test_unstable_slow_and_trend(world):
    project, cases, _ = world
    for i, status in enumerate(['passed', 'failed', 'passed', 'failed', 'passed']):
        case_run(project, cases['items'], status, ago(5 - i), ms=300 + i)
    case_run(project, cases['login'], 'passed', ago(1), ms=40)
    report = reporting.collect(project['id'], 7, now=NOW)
    assert report['unstable'][0]['name'] == 'items' and report['unstable'][0]['flips'] == 4
    assert report['slow'][0]['name'] == 'items' and report['slow'][0]['max_ms'] == 304
    assert sum(d['runs'] for d in report['trend']) == 6 and sum(d['failed'] for d in report['trend']) == 2


def test_observer_changes_and_overdue_schedules_raise_amber(world):
    project, cases, suite = world
    for case in cases.values():
        case_run(project, case, 'passed', ago(1))
    for i in (1, 2, 3):
        doc = observer.record('Usuarios', project['id'], 'GET', f'/api/users/{i}', '', '', 200, json.dumps({'id': i, 'name': 'a'}), 4.0, origin='http://h:1')
    observer.set_baseline(doc['id'])
    observer.record('Usuarios', project['id'], 'GET', '/api/users/9', '', '', 200, json.dumps({'id': 9, 'name': 'a', 'extra': True}), 4.0, origin='http://h:1')
    core.save('schedules', {'name': 's', 'project_id': project['id'], 'suite_id': suite['id'], 'enabled': True, 'next_run_at': ago(1)})
    report = reporting.collect(project['id'], 14, now=NOW)
    assert report['rag']['level'] == 'amber'
    reasons = ' '.join(report['rag']['reasons'])
    assert 'sin aviso' in reasons and 'vencidas' in reasons and report['observer']['with_changes'] == 1 and report['schedules']['overdue'] == 1


def test_other_projects_do_not_leak_into_the_report(world):
    project, cases, _ = world
    other = core.create_project('Otro')
    case_run(other, cases['login'], 'failed', ago(1))
    assert reporting.collect(project['id'], 14, now=NOW)['kpis']['executions'] == 0


def test_exports_say_the_same_and_escape_html(world):
    project, cases, suite = world
    evil = core.save('cases', {'name': '<script>alert(1)</script>', 'method': 'GET', 'path': '/x', 'project_id': project['id'], 'headers': {}, 'query': {}, 'body': None,
                               'assertions': [], 'variables': {}, 'extract': [], 'timeout': 5})
    case_run(project, evil, 'failed', ago(1), error='boom <b>')
    case_run(project, cases['login'], 'passed', ago(1))
    suite_run(project, suite, 'failed', ago(1))
    report = reporting.collect(project['id'], 14, now=NOW, notes='Riesgo: <i>pago</i> inestable')
    page = reporting.render_html(report)
    assert '<script>alert(1)</script>' not in page and '&lt;script&gt;' in page and '&lt;i&gt;pago&lt;/i&gt;' in page
    assert 'ROJO' in page and '<svg' in page and 'Qué está fallando' in page and page.startswith('<!doctype html>')
    markdown = reporting.render_markdown(report)
    assert '## Estado general: ROJO' in markdown and '| compra | Falló |' in markdown and 'Riesgo: <i>pago</i> inestable' in markdown
    assert json.loads(reporting.render(report, 'json'))['format'] == 'ltw.status/1'
    text = reporting.summary_text(report)
    assert 'Estado ROJO' in text and 'Falla:' in text and text.startswith('Reporte de estatus de pruebas — Tienda')
    with pytest.raises(ValueError):
        reporting.render(report, 'docx')


def test_pdf_export(world, tmp_path):
    project, cases, _ = world
    case_run(project, cases['login'], 'passed', ago(1))
    target = reporting.render_pdf(reporting.render_html(reporting.collect(project['id'], 14, now=NOW)), tmp_path / 'r.pdf')
    assert target.read_bytes()[:4] == b'%PDF' and target.stat().st_size > 5_000


def test_command_line(world, tmp_path, capsys):
    project, cases, suite = world
    case_run(project, cases['login'], 'passed', ago(0, hours=1))
    assert reporting.cli(['--status-report', str(tmp_path / 'a.html'), '--project', 'tienda', '--days', '7']) == 0
    assert (tmp_path / 'a.html').read_text(encoding='utf-8').count('<svg') >= 1
    case_run(project, cases['items'], 'failed', ago(0, hours=1))
    suite_run(project, suite, 'failed', ago(0, hours=1))
    assert reporting.cli(['--status-report', str(tmp_path / 'b.md'), '--notes', 'revisar']) == 1                  # attention needed -> exit 1 for CI
    assert 'revisar' in (tmp_path / 'b.md').read_text(encoding='utf-8')
    assert reporting.cli(['--status-report', str(tmp_path / 'c.json')]) == 1 and json.loads((tmp_path / 'c.json').read_text(encoding='utf-8'))['rag']['level'] == 'red'
    for bad in (['--status-report', str(tmp_path / 'x.html'), '--project', 'no existe'], ['--status-report', str(tmp_path / 'x.html'), '--days', '0'],
                ['--status-report', str(tmp_path / 'x.docx')], ['--status-report']):
        assert reporting.cli(bad) == 2
    assert 'Disponibles: Tienda' in capsys.readouterr().err


async def test_summary_page_shows_the_banner_and_failures(user, world):
    project, cases, suite = world
    core.set_active_project(project['id'])
    case_run(project, cases['pago'], 'failed', ago(0, hours=3), error='HTTP 500 inesperado')
    case_run(project, cases['login'], 'passed', ago(0, hours=3))
    suite_run(project, suite, 'failed', ago(0, hours=3))
    await user.open('/resumen')
    await user.should_see('Estado general: ROJO')
    await user.should_see('Qué está fallando y desde cuándo')
    await user.should_see('HTTP 500 inesperado')
    await user.should_see('Reporte de estatus')
    await user.should_see('Copiar resumen')
    user.find('30 días').click()
    await user.should_see('Estado general: ROJO')
