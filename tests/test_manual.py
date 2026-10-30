"""The user manual must not drift from the product: links, images and the lists that come from the code."""
import re
import sys
from pathlib import Path
import pytest
from app import core, automation, observer, llm
from app.pages.common import NAV

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import build_manual  # noqa: E402

SRC_TEXT = '\n'.join(p.read_text(encoding='utf-8') for p in sorted((ROOT / 'docs' / 'manual' / 'src').glob('*.md')))


def test_every_image_referenced_exists_and_every_image_is_used():
    referenced = set(re.findall(r'\]\(img/([^)]+)\)', SRC_TEXT))
    existing = {p.name for p in (ROOT / 'docs' / 'manual' / 'img').glob('*.png')}
    assert referenced and not (referenced - existing), f'imágenes citadas que no existen: {referenced - existing}'
    assert not (existing - referenced), f'imágenes sin usar en el manual: {existing - referenced}'
    for name in referenced:
        assert (ROOT / 'docs' / 'manual' / 'img' / name).stat().st_size > 5_000


def test_internal_links_resolve_to_anchors():
    body, toc = build_manual.prepare(SRC_TEXT)
    anchors = set(re.findall(r'<a id="([^"]+)"></a>', body))
    assert len([t for t in toc if t[0] == 'ch']) == 20
    for target in re.findall(r'\]\(#([^)]+)\)', body):
        assert target in anchors, f'enlace roto: #{target}'
    chapters = [int(c) for c in re.findall(r'^# (\d+)\. ', SRC_TEXT, flags=re.M)]
    assert chapters == list(range(1, 21))                                           # no chapter missing or duplicated


def test_generated_manual_files_are_current():
    body, toc = build_manual.prepare(SRC_TEXT)
    md = (ROOT / 'MANUAL_DE_USUARIO.md').read_text(encoding='utf-8')
    assert md.endswith(build_manual.build_markdown(body, toc, re.search(r'\*\*Fecha:\*\* (\d{4}-\d{2}-\d{2})', md).group(1))), \
        'MANUAL_DE_USUARIO.md no corresponde a docs/manual/src: ejecuta python scripts/build_manual.py'
    html = (ROOT / 'docs' / 'manual' / 'MANUAL_DE_USUARIO.html').read_text(encoding='utf-8')
    assert html.count('<figure>') == len(re.findall(r'\]\(img/', SRC_TEXT))
    assert (ROOT / 'docs' / 'manual' / 'MANUAL_DE_USUARIO.pdf').stat().st_size > 500_000


@pytest.mark.parametrize('kind', sorted(core.ASSERTION_TYPES))
def test_every_assertion_type_is_documented(kind):
    assert f'`{kind}`' in SRC_TEXT, f'el tipo de aserción «{kind}» no está en el manual (capítulo 20)'
    assert core.ASSERTION_TYPES[kind]['label'].split(' (')[0] in SRC_TEXT or kind.startswith('numeric_'), f'falta la etiqueta de «{kind}»'


def test_ui_actions_locators_and_navigation_are_documented():
    for action, spec in automation.STEP_ACTIONS.items():
        label = spec['label'].replace(' / ', ' ').split(' ')[0]
        assert label in SRC_TEXT, f'acción UI «{action}» ({spec["label"]}) sin documentar'
    for label in ('Etiqueta (label)', 'Texto', 'Rol ARIA', 'data-testid', 'Placeholder'):
        assert label in SRC_TEXT
    for label, _, _ in NAV:
        assert f'**{label}**' in SRC_TEXT, f'la opción de menú «{label}» no aparece en el manual'
    for label in core.ENRICH_ACTIONS.values():
        assert label.split(' ')[0] in SRC_TEXT
    for label in list(core.ENRICH_TARGETS.values()) + list(core.SOURCE_TYPES.values()):
        assert label in SRC_TEXT, f'«{label}» (enriquecimiento) sin documentar'
    for label in list(automation.FREQUENCIES.values()) + list(automation.MISSED_POLICIES.values()):
        assert label in SRC_TEXT, f'«{label}» (programaciones) sin documentar'


def test_environment_variables_limits_and_commands_match_the_code():
    for variable in ('LTW_PORT', 'TEST_WORKSPACE_HOME', 'LTW_AGENT_TOKEN', 'LTW_STORAGE_SECRET', llm.KEY_SECRET):
        assert variable in SRC_TEXT
    # numbers quoted in the manual come from the code
    from app import workspace as ws
    for number in (f'{ws.MAX_HISTORY}', '100 000', '10 080', '50 000', '200 000'):
        assert number in SRC_TEXT
    assert observer.MAX_SAMPLES == 5 and '5 muestras' in SRC_TEXT and '5 MB' in SRC_TEXT
    assert core.MAX_ENTRIES == 5000 and '5000 entradas' in SRC_TEXT and core.MAX_ENTRY_BYTES == 10_000_000
    for command in ('scripts\\install.bat', 'scripts\\run.bat', 'scripts\\scheduler.bat', '--only-failed', '--validate', '--schema', '--junit', '--persist', '--status-report'):
        assert command in SRC_TEXT
    for path in ('scripts/install.bat', 'scripts/run.bat', 'scripts/scheduler.bat', 'scripts/test.bat', 'scripts/build_exe.bat'):
        assert (ROOT / path).exists()


def test_manual_does_not_leak_personal_paths():
    for text in (SRC_TEXT, (ROOT / 'MANUAL_DE_USUARIO.md').read_text(encoding='utf-8')):
        assert 'niu81' not in text and 'AppData' not in text


def test_assistant_providers_are_documented():
    for preset in llm.PRESETS.values():
        if preset['label'] != 'Personalizado':
            assert preset['label'].split(' (')[0].split(' /')[0] in SRC_TEXT, f'proveedor «{preset["label"]}» sin documentar'
    assert 'Permitir enviar datos fuera de esta máquina' in SRC_TEXT and 'Probar conexión' in SRC_TEXT


def test_contract_url_import_is_documented():
    for text in ('Swagger UI', 'Redoc', 'github.com/…/blob/', 'Crear ambiente con esta URL', 'Servidor declarado', f'{__import__("app.core", fromlist=["x"]).MAX_SPEC_FETCHES} direcciones'):
        assert text in SRC_TEXT, text


def test_status_report_is_documented_and_matches_the_thresholds():
    from app import reporting
    for text in ('Reporte de estatus', 'Copiar resumen', 'ltw.status/1', 'Comentarios para el reporte', f'{int(reporting.GREEN_RATE * 100)} %', f'{int(reporting.AMBER_RATE * 100)} %'):
        assert text in SRC_TEXT, text
    for days in reporting.RANGES[:-1]:
        assert str(days) in SRC_TEXT
    for color in reporting.RAG.values():
        assert f'**{color}**' in SRC_TEXT
