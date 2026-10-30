"""Builds a clean distributable ZIP: no caches, databases, evidence, virtualenvs or credentials."""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXCLUDE_DIRS = {'__pycache__', '.pytest_cache', '.venv', 'venv', 'dist', 'build', '.git', 'evidence', 'logs', 'data', '.local_test_workspace'}
EXCLUDE_SUFFIX = {'.pyc', '.sqlite3', '.sqlite3-wal', '.sqlite3-shm', '.db', '.lock', '.log', '.env', '.pem', '.key'}


def included(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    if any(part in EXCLUDE_DIRS or part.endswith('.egg-info') for part in rel.parts):
        return False
    if path.suffix in EXCLUDE_SUFFIX or path.name.startswith('.env') or path.name.endswith('.zip'):
        return False
    return path.is_file()


def main(version):
    target = ROOT / 'dist' / f'local-test-workspace-{version}.zip'
    target.parent.mkdir(exist_ok=True)
    files = sorted(p for p in ROOT.rglob('*') if included(p))
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in files:
            z.write(path, Path('local-test-workspace') / path.relative_to(ROOT))
    print(f'{target} ({len(files)} archivos)')
    return target


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else '1.0.0')
