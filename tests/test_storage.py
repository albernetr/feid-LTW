import sqlite3
import sys
from pathlib import Path
from app import core


def test_default_storage_is_inside_the_package(monkeypatch, tmp_path):
    monkeypatch.delenv('TEST_WORKSPACE_HOME', raising=False)
    assert core.default_root() == core.app_dir() / 'data'
    assert core.app_dir() == Path(core.__file__).resolve().parent.parent
    # frozen build: next to the executable
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'LocalTestWorkspace.exe'))
    assert core.default_root() == tmp_path.resolve() / 'data'
    # explicit override wins
    monkeypatch.setenv('TEST_WORKSPACE_HOME', str(tmp_path / 'custom'))
    assert core.default_root() == tmp_path / 'custom'


def test_read_only_package_falls_back_to_user_profile(monkeypatch, tmp_path):
    monkeypatch.delenv('TEST_WORKSPACE_HOME', raising=False)
    monkeypatch.setattr(core.os, 'access', lambda *a, **k: False)
    assert core.default_root() == core.LEGACY_ROOT


def test_database_file_is_created_in_the_data_folder():
    core.initialize()
    assert core.DB.parent == core.ROOT and core.DB.exists()
    with sqlite3.connect(core.DB) as con:
        tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    assert {'projects', 'cases', 'suites', 'runs', 'settings'} <= tables


def test_legacy_workspace_is_copied_once_and_not_deleted(monkeypatch, tmp_path):
    legacy = tmp_path / 'legacy'
    monkeypatch.setattr(core, 'LEGACY_ROOT', legacy)
    # build a legacy DB (with an evidence file) using the same schema
    monkeypatch.setattr(core, 'ROOT', legacy)
    monkeypatch.setattr(core, 'DB', legacy / 'workspace.sqlite3')
    monkeypatch.setattr(core, 'ARTIFACTS', legacy / 'evidence')
    project = core.create_project('Heredado')
    (core.ARTIFACTS / 'old.png').write_bytes(b'png')
    # new package location
    package = tmp_path / 'package' / 'data'
    monkeypatch.setattr(core, 'ROOT', package)
    monkeypatch.setattr(core, 'DB', package / 'workspace.sqlite3')
    monkeypatch.setattr(core, 'ARTIFACTS', package / 'evidence')
    monkeypatch.delenv('TEST_WORKSPACE_HOME', raising=False)
    assert core.migrate_legacy_data() is True
    assert core.get('projects', project['id'])['name'] == 'Heredado'
    assert (package / 'evidence' / 'old.png').exists()
    assert (legacy / 'workspace.sqlite3').exists()          # original untouched
    core.save('projects', {'id': project['id'], 'name': 'Cambiado'})
    assert core.migrate_legacy_data() is False              # never overwrites
    assert core.get('projects', project['id'])['name'] == 'Cambiado'
