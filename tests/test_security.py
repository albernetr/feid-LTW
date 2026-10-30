import io
import json
import zipfile
import pytest
from app import core, logs, recorder


def make_zip(path, entries, manifest=None):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json', json.dumps(manifest or {'format': 'local-test-workspace', 'schema_version': 1}))
        for name, content in entries.items():
            z.writestr(name, content if isinstance(content, (str, bytes)) else json.dumps(content))
    return path


ID1 = '11111111-1111-4111-8111-111111111111'
ID2 = '22222222-2222-4222-8222-222222222222'


def test_zip_path_traversal_and_bad_names_rejected(tmp_path):
    for name in ('../evil.json', 'cases/../../evil.json', '/abs.json', 'cases\\x.json', 'other/' + ID1 + '.json', 'cases/sub/' + ID1 + '.json'):
        p = make_zip(tmp_path / 'z.zip', {name: {'id': ID1}})
        with pytest.raises(ValueError):
            core.import_workspace(p)


def test_zip_symlink_and_duplicates_and_zip_bomb_rejected(tmp_path):
    p = tmp_path / 'link.zip'
    with zipfile.ZipFile(p, 'w') as z:
        z.writestr('manifest.json', json.dumps({'format': 'local-test-workspace', 'schema_version': 1}))
        info = zipfile.ZipInfo(f'cases/{ID1}.json')
        info.external_attr = (0o120777 << 16)
        z.writestr(info, '{"id": "%s"}' % ID1)
    with pytest.raises(ValueError, match='enlace'):
        core.import_workspace(p)

    bomb = tmp_path / 'bomb.zip'
    with zipfile.ZipFile(bomb, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('manifest.json', json.dumps({'format': 'local-test-workspace', 'schema_version': 1}))
        z.writestr(f'cases/{ID1}.json', '{"id": "%s", "pad": "%s"}' % (ID1, 'A' * 5_000_000))
    with pytest.raises(ValueError, match='sospechosa'):
        core.import_workspace(bomb)

    with pytest.raises(ValueError):
        core.import_workspace(tmp_path / 'nonzip.zip' if (tmp_path / 'nonzip.zip').write_bytes(b'hello') else None)


def test_invalid_manifest_and_records(tmp_path):
    with pytest.raises(ValueError, match='incompatible'):
        core.import_workspace(make_zip(tmp_path / 'a.zip', {}, {'format': 'x', 'schema_version': 1}))
    with pytest.raises(ValueError, match='inválido'):
        core.import_workspace(make_zip(tmp_path / 'b.zip', {f'cases/{ID1}.json': {'id': ID1, 'name': 123}}))
    with pytest.raises(ValueError, match='id'):
        core.import_workspace(make_zip(tmp_path / 'c.zip', {f'cases/{ID1}.json': {'id': ID2}}))


def test_failed_import_rolls_back_completely(tmp_path, monkeypatch):
    p = make_zip(tmp_path / 'ok.zip', {f'cases/{ID1}.json': {'id': ID1, 'name': 'a'}, f'cases/{ID2}.json': {'id': ID2, 'name': 'b'}})
    original = core.save_in
    calls = {'n': 0}

    def failing(con, table, item):
        calls['n'] += 1
        if calls['n'] == 2:
            raise RuntimeError('disk full')
        return original(con, table, item)

    monkeypatch.setattr(core, 'save_in', failing)
    with pytest.raises(RuntimeError):
        core.import_workspace(p, 'replace')
    assert core.list_items('cases') == []
    monkeypatch.setattr(core, 'save_in', original)
    assert core.import_workspace(p, 'replace')['cases'] == 2


def test_preview_does_not_write_and_reports_conflicts_and_warnings(tmp_path):
    project = core.create_project('P')
    case = core.save('cases', {'name': 'c', 'project_id': project['id'], 'headers': {'Authorization': 'Bearer xyz', 'X-A': '1'}})
    core.save('schedules', {'suite_id': 'x', 'enabled': True, 'name': 'daily'})
    path = core.export_workspace(tmp_path / 'e.zip')
    before = {t: len(core.list_items(t)) for t in core.TABLES}
    preview = core.preview_import(path, 'merge')
    assert preview['summary']['cases'] == {'total': 1, 'new': 0, 'existing': 1}
    assert any('desactivada' in w for w in preview['warnings'])
    assert preview['items'][0]['action'] in ('omitir', 'crear')
    assert {t: len(core.list_items(t)) for t in core.TABLES} == before
    with zipfile.ZipFile(path) as z:
        exported = json.loads(z.read(f'cases/{case["id"]}.json'))
    assert 'Authorization' not in exported['headers'] and exported['headers']['X-A'] == '1'


def test_export_scopes_include_dependencies_only(tmp_path):
    a = core.create_project('A'); b = core.create_project('B')
    mod = core.save('modules', {'name': 'm', 'project_id': a['id'], 'operations': []})
    env = core.save('environments', {'name': 'e', 'project_id': a['id'], 'base_url': 'http://x', 'variables': {'api_token': 'S', 'region': 'eu'}})
    case = core.save('cases', {'name': 'c', 'project_id': a['id'], 'module_id': mod['id']})
    core.save('cases', {'name': 'other', 'project_id': b['id']})
    suite = core.save_suite('s', env['id'], [case['id']], a['id'])

    def read(path):
        with zipfile.ZipFile(path) as z:
            return {n: z.read(n).decode() for n in z.namelist() if n != 'manifest.json'}

    listed = read(core.export_workspace(tmp_path / 'p.zip', project_id=a['id']))
    assert len(listed) == 5 and not any('other' in body for body in listed.values())
    listed = read(core.export_workspace(tmp_path / 's.zip', suite_ids=[suite['id']]))
    assert {n.split('/')[0] for n in listed} == {'projects', 'modules', 'environments', 'cases', 'suites'}
    assert json.loads(listed[f'environments/{env["id"]}.json'])['variables'] == {'region': 'eu'}
    case_zip = core.export_workspace(tmp_path / 'c.zip', case_ids=[case['id']])
    assert {n.split('/')[0] for n in read(case_zip)} == {'projects', 'modules', 'cases'}
    # round trip into a clean workspace as a new copy
    counts = core.import_workspace(case_zip, 'new')
    assert counts['cases'] == 1 and counts['modules'] == 1


def test_secrets_use_os_store_and_never_reach_runs_or_exports(sample_app, tmp_path):
    core.secret_set('qa-token', 'tok-abc123')
    assert 'qa-token' in core.secret_names()
    assert core.secret_get('qa-token') == 'tok-abc123'
    env = core.save('environments', {'name': 'e', 'base_url': sample_app.url, 'auth': {'type': 'bearer', 'secret': 'qa-token'}})
    case = core.save('cases', {'name': 'items', 'method': 'GET', 'path': '/api/items', 'assertions': [{'type': 'status', 'expected': 200}],
                               'headers': {'X-Debug': '{{secret:qa-token}}'}})
    run = core.execute_api(case, env)
    assert run['status'] == 'passed'
    dumped = json.dumps(core.list_items('runs'))
    assert 'tok-abc123' not in dumped
    path = core.export_workspace(tmp_path / 'x.zip', include_runs=True)
    with zipfile.ZipFile(path) as z:
        assert all(b'tok-abc123' not in z.read(n) for n in z.namelist())
    core.secret_delete('qa-token')
    assert core.secret_names() == []
    with pytest.raises(ValueError):
        core.secret_set('bad name!', 'x')


def test_unresolved_variables_block_execution_without_sending(sample_app):
    env = core.save('environments', {'name': 'e', 'base_url': sample_app.url, 'auth': {'type': 'none'}, 'variables': {}})
    case = core.save('cases', {'name': 'c', 'method': 'GET', 'path': '/api/items/{{item_id}}', 'assertions': [{'type': 'status', 'expected': 200}]})
    run = core.execute_api(case, env)
    assert run['status'] == 'error' and 'item_id' in run['error']
    assert 'request' not in run
    assert core.find_unresolved({'a': ['{{x}}', 'ok'], 'b': '{{ y.z }}'}) == ['x', 'y.z']


def test_logs_are_structured_and_redacted(tmp_path):
    logs.event('test.event', password='hunter2', note='Authorization: Bearer abcdef123456', nested={'api_key': 'k', 'ok': 1})
    text = (core.ROOT / 'logs' / 'workspace.log').read_text(encoding='utf-8')
    record = json.loads(text.splitlines()[-1])
    assert record['password'] == '[REDACTED]' and record['nested']['api_key'] == '[REDACTED]'
    assert 'abcdef123456' not in text and record['event'] == 'test.event'
    core.save('environments', {'name': 'e', 'base_url': 'http://x', 'auth': {'type': 'bearer', 'secret': 'n'}, 'secrets': {'t': 'S3CRET'}})
    bundle = logs.diagnostic_package(tmp_path / 'diag.zip')
    with zipfile.ZipFile(bundle) as z:
        blob = b''.join(z.read(n) for n in z.namelist())
    assert b'S3CRET' not in blob and b'hunter2' not in blob and b'abcdef123456' not in blob
    assert b'"counts"' in blob


def test_retention_and_safe_evidence_download():
    old = core.save('runs', {'id': '33333333-3333-4333-8333-333333333333', 'started_at': '2020-01-01T00:00:00+00:00', 'status': 'passed', 'screenshot': '33333333-3333-4333-8333-333333333333.png'})
    fresh = core.save('runs', {'id': '44444444-4444-4444-8444-444444444444', 'started_at': core.now(), 'status': 'passed', 'screenshot': '44444444-4444-4444-8444-444444444444.png'})
    (core.ARTIFACTS / old['screenshot']).write_bytes(b'png')
    (core.ARTIFACTS / fresh['screenshot']).write_bytes(b'png')
    assert core.evidence_path(fresh['id'], fresh['screenshot']).name == fresh['screenshot']
    for bad in ('../workspace.sqlite3', '..\\x', 'other.png'):
        with pytest.raises((ValueError, FileNotFoundError)):
            core.evidence_path(fresh['id'], bad)
    with pytest.raises(ValueError):
        core.evidence_path('../../etc', 'x')
    assert core.purge_evidence(max_age_days=30) == {'runs': 1, 'files': 1}
    assert core.get('runs', old['id']) is None and core.get('runs', fresh['id'])
    assert not (core.ARTIFACTS / old['screenshot']).exists()


SCRIPT = '''
import re
import os
from playwright.sync_api import Playwright, sync_playwright, expect

def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("http://127.0.0.1:8765/login")
    page.get_by_label("Usuario").fill("qa")
    page.get_by_label("Contraseña").fill("qa-pass")
    page.get_by_role("button", name="Entrar").click()
    expect(page.get_by_test_id("msg")).to_contain_text("Bienvenido qa")
    page.locator("#raw").click()
    page.get_by_role("link", name="x").first.click()
    os.system("calc.exe")
    page.evaluate("alert(1)")
    context.close()
    browser.close()

with sync_playwright() as playwright:
    run(playwright)
'''


def test_recorder_imports_subset_and_reports_the_rest_without_executing(tmp_path):
    marker = tmp_path / 'executed'
    result = recorder.import_codegen(SCRIPT.replace('calc.exe', 'echo x > executed_marker.txt'))
    assert [s['action'] for s in result['steps']] == ['navigate', 'fill', 'fill', 'click', 'assert_text', 'click']
    assert result['steps'][5]['locator'] == {'by': 'role', 'role': 'link', 'name': 'x', 'first': True}
    assert result['steps'][3]['locator'] == {'by': 'role', 'role': 'button', 'name': 'Entrar'}
    assert result['steps'][4] == {'action': 'assert_text', 'locator': {'by': 'testid', 'value': 'msg'}, 'expected': 'Bienvenido qa'}
    reasons = ' | '.join(u['reason'] for u in result['unsupported'])
    assert 'locator no soportado' in reasons and 'first' not in reasons and 'system()' in reasons and 'evaluate()' in reasons and 'import «os»' in reasons
    assert not marker.exists() and not __import__('pathlib').Path('executed_marker.txt').exists()
    with pytest.raises(ValueError, match='Python válido'):
        recorder.import_codegen('def (:')
    with pytest.raises(ValueError):
        recorder.launch_codegen('file:///etc/passwd')


def test_navigation_failures_are_surfaced_not_swallowed(monkeypatch):
    """A wrong protocol or an unreachable target makes Playwright's CLI close the window and exit immediately;
    without this, that was completely silent - the browser just vanished with nothing shown on screen."""
    import subprocess as sp

    class FakeResult:
        def __init__(self, returncode, stderr='', stdout=''):
            self.returncode, self.stderr, self.stdout = returncode, stderr, stdout

    def fake_ssl_error(*a, **kw):
        return FakeResult(1, stderr='Error: net::ERR_SSL_PROTOCOL_ERROR at https://localhost:4200/auth/login\nCall log:\n  - navigating...\n')
    monkeypatch.setattr(sp, 'run', fake_ssl_error)
    with pytest.raises(ValueError, match='ERR_SSL_PROTOCOL_ERROR'):
        recorder.open_browser('https://localhost:4200/auth/login')

    monkeypatch.setattr(sp, 'run', lambda *a, **kw: FakeResult(1))
    with pytest.raises(ValueError, match='código 1'):
        recorder.open_browser('http://localhost:9/x')

    monkeypatch.setattr(sp, 'run', lambda *a, **kw: FakeResult(0))
    recorder.open_browser('http://localhost:9/x')                       # clean exit: the person closed the window themselves, no error

    def fake_codegen_nav_error(cmd, *a, **kw):
        return FakeResult(1, stderr='Error: net::ERR_CONNECTION_REFUSED at http://localhost:9/x\n')
    monkeypatch.setattr(sp, 'run', fake_codegen_nav_error)
    with pytest.raises(ValueError, match='ERR_CONNECTION_REFUSED'):
        recorder.launch_codegen('http://localhost:9/x')

    def fake_codegen_clean_close(cmd, *a, **kw):
        return FakeResult(0)                                             # closed cleanly with nothing recorded: not a navigation failure
    monkeypatch.setattr(sp, 'run', fake_codegen_clean_close)
    assert recorder.launch_codegen('http://localhost:9/x') == ''
