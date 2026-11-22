"""Catálogo de tipos de reporte para la sección "Reportes" (/reports): una lista declarativa, no una entidad
persistida — sumar un reporte nuevo (custom, o uno que hoy se pasa por alto) es agregar una entrada a
REPORT_TYPES con sus funciones, sin tocar la página ni el modelo de datos. Cada entrada reusa el builder de
datos y el constructor de `doc` (report_doc.py) que ya existe para ese reporte individual (spec_report.py,
reporting.py, evidence_report.py) — acá solo se decide CÓMO combinar varios en un solo documento cuando el
alcance es "varios"/"todos"."""
from dataclasses import dataclass
from typing import Callable, Optional
from . import core, evidence_report, reporting, spec_report, report_doc as rd

EVIDENCE_RUN_TYPES = ('api', 'ui')
EVIDENCE_LIST_LIMIT = 50   # corridas hoja más recientes a ofrecer en el selector — no todo el historial


@dataclass
class ReportType:
    key: str
    label: str
    icon: str
    slug: str                        # tramo de su ruta propia, /reports/<slug> (ver app/pages/reports.py)
    scope: str                       # 'items' (selección múltiple) | 'project' (siempre todo, sin selección)
    uses_template: bool               # True -> ofrece el selector de spec_templates (kind='output', applies_to='report')
    list_fn: Optional[Callable] = None        # (project_id) -> [item]
    label_fn: Optional[Callable] = None       # (item) -> texto de la fila
    single_doc_fn: Optional[Callable] = None  # (item, template=None) -> doc
    batch_doc_fn: Optional[Callable] = None   # (items, template=None) -> doc combinado
    project_doc_fn: Optional[Callable] = None  # (project_id, template=None) -> doc   [solo scope='project']


def _concat_docs(title, items, label_fn, single_doc_fn):
    """Un reporte "de varios" es, para cualquier tipo basado en secciones/tarjetas, el mismo documento
    individual de cada item concatenado bajo un heading propio — nunca un ZIP ni N descargas sueltas."""
    blocks = []
    for item in items:
        blocks.append(rd.heading(label_fn(item), level=1))
        blocks += single_doc_fn(item)['blocks']
    return rd.doc(title, blocks, meta=f'{len(items)} ítem(s) combinados')


# --------------------------------------------------------------------------- Historias de usuario

def _story_label(story):
    return story.get('title', '')


def _story_single_doc(story, template=None):
    return spec_report._spec_doc(spec_report.build_story_report_data(story, template))


def _story_batch_doc(stories, template=None):
    return _concat_docs('Historias de usuario', stories, _story_label, lambda s: _story_single_doc(s, template))


# --------------------------------------------------------------------------- Casos de prueba (TC)

def _test_case_label(spec):
    return spec.get('title', '')


def _test_case_single_doc(spec, template=None):
    return spec_report._spec_doc(spec_report.build_test_case_report_data(spec, template))


def _test_case_batch_doc(specs, template=None):
    return _concat_docs('Casos de prueba', specs, _test_case_label, lambda s: _test_case_single_doc(s, template))


# --------------------------------------------------------------------------- Casos ejecutables (API/UI)

def _case_label(case):
    return case.get('name', '')


def _case_single_doc(case, template=None):
    return reporting._case_doc(reporting.build_case_report_data(case['id'], template=template))


def _case_batch_doc(cases, template=None):
    return _concat_docs('Casos ejecutables', cases, _case_label, _case_single_doc)


# --------------------------------------------------------------------------- Suites

def _suite_group_label(group):
    return group.get('name', '')


def _suite_group_single_doc(group, template=None):
    return reporting._suite_group_doc(reporting.build_suite_group_report_data(group['id'], template=template))


def _suite_group_batch_doc(groups, template=None):
    return _concat_docs('Suites', groups, _suite_group_label, _suite_group_single_doc)


# --------------------------------------------------------------------------- Evidencias de ejecución

def _list_evidence_runs(project_id):
    """Corridas hoja (api/ui) más recientes — las de suite/suite_group ya tienen su propio reporte histórico
    (tipo 'suite_group' acá arriba); mezclarlas en Evidencias no aporta y build_multi_report_data espera la
    forma request/response de una corrida hoja, no la de una corrida compuesta."""
    runs = [r for r in core.list_items('runs') if r.get('type') in EVIDENCE_RUN_TYPES
            and (not project_id or r.get('project_id') in (project_id, None))]
    runs.sort(key=lambda r: r.get('started_at') or '', reverse=True)
    return runs[:EVIDENCE_LIST_LIMIT]


def _evidence_label(run):
    return run.get('case_name') or (run.get('id') or '')[:8]


def _evidence_single_doc(run, template=None):
    return evidence_report._to_doc(evidence_report.build_report_data(run, template=template))


def _evidence_batch_doc(runs, template=None):
    return evidence_report._to_doc(evidence_report.build_multi_report_data(f'Evidencias ({len(runs)} corridas)', runs, template=template))


# --------------------------------------------------------------------------- Matriz de trazabilidad

def _matrix_project_doc(project_id, template=None):
    return spec_report._spec_doc(spec_report.build_test_matrix_report_data(project_id, template))


REPORT_TYPES = [
    ReportType(key='user_story', label='Historias de usuario', icon='auto_stories', slug='user-story', scope='items', uses_template=True,
               list_fn=lambda pid: core.list_project_items('user_stories', pid), label_fn=_story_label,
               single_doc_fn=_story_single_doc, batch_doc_fn=_story_batch_doc),
    ReportType(key='test_case', label='Casos de prueba', icon='checklist', slug='test-case', scope='items', uses_template=True,
               list_fn=lambda pid: core.list_project_items('test_case_specs', pid), label_fn=_test_case_label,
               single_doc_fn=_test_case_single_doc, batch_doc_fn=_test_case_batch_doc),
    ReportType(key='case', label='Casos ejecutables (API/UI)', icon='science', slug='case', scope='items', uses_template=True,
               list_fn=lambda pid: core.list_project_items('cases', pid), label_fn=_case_label,
               single_doc_fn=_case_single_doc, batch_doc_fn=_case_batch_doc),
    ReportType(key='suite_group', label='Suites', icon='folder_special', slug='suite-group', scope='items', uses_template=True,
               list_fn=lambda pid: core.list_project_items('suite_groups', pid), label_fn=_suite_group_label,
               single_doc_fn=_suite_group_single_doc, batch_doc_fn=_suite_group_batch_doc),
    ReportType(key='evidence', label='Evidencias de ejecución', icon='history', slug='evidence', scope='items', uses_template=True,
               list_fn=_list_evidence_runs, label_fn=_evidence_label,
               single_doc_fn=_evidence_single_doc, batch_doc_fn=_evidence_batch_doc),
    ReportType(key='matrix', label='Matriz de trazabilidad', icon='alt_route', slug='matrix', scope='project', uses_template=True,
               project_doc_fn=_matrix_project_doc),
]
