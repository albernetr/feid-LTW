import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import make_release  # noqa: E402


def test_release_zip_has_no_caches_databases_or_private_data(tmp_path, monkeypatch):
    (ROOT / 'evidence').mkdir(exist_ok=True)
    (ROOT / 'evidence' / 'secret.png').write_bytes(b'x')
    (ROOT / 'personal.sqlite3').write_bytes(b'x')
    try:
        target = make_release.main('test')
        with zipfile.ZipFile(target) as z:
            names = z.namelist()
        assert any(n.endswith('run.py') for n in names) and any(n.endswith('app/core.py') for n in names)
        bad = [n for n in names if any(t in n for t in ('__pycache__', '.pytest_cache', 'evidence/', '.sqlite3', '.pyc', '.venv', '.lock', '.env', 'dist/'))]
        assert bad == []
    finally:
        (ROOT / 'evidence' / 'secret.png').unlink()
        (ROOT / 'evidence').rmdir()
        (ROOT / 'personal.sqlite3').unlink()
        (ROOT / 'dist' / 'local-test-workspace-test.zip').unlink(missing_ok=True)
