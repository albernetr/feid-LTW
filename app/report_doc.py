"""Modelo de documento comun para toda la reporteria (resumen ejecutivo, Especificacion, evidencia de una
corrida, Suite, Caso con historial): un arbol de BLOQUES genericos que cada constructor de datos arma sin
saber nada de HTML/Markdown/PDF/DOCX -- eso lo resuelve un unico renderer (ver report_render.py). Nunca se
instancia a mano salvo con estos helpers: mantienen la forma de cada "kind" en un solo lugar."""

# kinds soportados, cada uno una funcion de fabrica mas abajo:
#   heading, text, kv, table, list, checks, badge, cards, banner, svg, code, group


def doc(title, blocks, meta=''):
    """El documento completo: titulo, una linea de metadatos (proyecto/periodo/corrida) y sus bloques."""
    return {'title': title, 'meta': meta, 'blocks': list(blocks)}


def heading(text, level=2):
    return {'kind': 'heading', 'text': text, 'level': level}


def text(value):
    return {'kind': 'text', 'text': value}


def kv(rows):
    """`rows`: lista de (etiqueta, valor) -- valor ya como texto, el renderer no sabe formatear dominio."""
    return {'kind': 'kv', 'rows': list(rows)}


def table(columns, rows):
    """`rows`: lista de listas, ya en el mismo orden que `columns` (celdas como texto)."""
    return {'kind': 'table', 'columns': list(columns), 'rows': [list(r) for r in rows]}


def bullet_list(items, ordered=False):
    return {'kind': 'list', 'items': list(items), 'ordered': ordered}


def checks(items):
    """Lista de aserciones/criterios con pasa/no pasa: cada item {'label', 'ok', 'detail'(opcional, solo se
    muestra si `ok` es falso — p. ej. el valor obtenido de una aserción), 'note'(opcional, se muestra siempre,
    independiente de `ok` — p. ej. el Dado/Cuando/Entonces de un criterio)}."""
    return {'kind': 'checks', 'items': list(items)}


def file(url, label, image=False, path=None, note=''):
    """Una imagen o un adjunto (los 2 tipos de campo custom que apuntan a un archivo guardado). `path`:
    ruta real en disco (solo para una imagen, para poder incrustarla en el DOCX) -- `url` es siempre la web.
    `note`: texto aparte tras el enlace/imagen (p. ej. el tamaño del adjunto)."""
    return {'kind': 'file', 'url': url, 'label': label, 'image': image, 'path': path, 'note': note}


def badge(label, color):
    """Color ya resuelto por quien arma el dato (el renderer no conoce la paleta de estados de dominio)."""
    return {'kind': 'badge', 'label': label, 'color': color}


def cards(items):
    """Grilla de metricas: cada item {'value', 'label'}."""
    return {'kind': 'cards', 'items': list(items)}


def banner(color, title, lines=()):
    return {'kind': 'banner', 'color': color, 'title': title, 'lines': list(lines)}


def svg(markup):
    """SVG ya armado (p. ej. reporting.trend_svg/spark_svg) -- pasa tal cual en HTML, se omite en MD/DOCX."""
    return {'kind': 'svg', 'markup': markup}


def code(value, language=''):
    return {'kind': 'code', 'text': value, 'language': language}


def group(children, indent=False, background=None, border=False):
    """Anidamiento: un step con sus sub-bloques, o una seccion con sub-secciones. `background`/`border`
    (diseñador visual, Reportería): solo tienen efecto en HTML -- DOCX/Markdown los ignoran (mismo criterio
    de degradar sin equivalente directo que ya usan `svg`/`file` con imagen)."""
    return {'kind': 'group', 'children': list(children), 'indent': indent, 'background': background, 'border': border}


def row(cells, background=None, border=False, gap=16):
    """Fila de una grilla de 12 columnas (Fase 2: diseñador visual) -- `cells`: lista de
    {'span': 1-12, 'children': [bloque, ...]}. HTML/DOCX honran las columnas reales; Markdown (sin noción de
    columnas) concatena los bloques de cada celda en secuencia, igual que ya hace `group`. `background`/
    `border` (diseñador visual, Reportería): solo tienen efecto en HTML, igual que en `group`."""
    return {'kind': 'row', 'cells': [{'span': c['span'], 'children': list(c['children'])} for c in cells],
           'background': background, 'border': border, 'gap': gap}


def divider(orientation='horizontal', thickness=1, color='#d1d5db'):
    """Línea separadora (diseñador visual, Reportería): `orientation` 'horizontal'|'vertical'. En Markdown se
    degrada a `---` (vertical no tiene equivalente, se omite, mismo criterio que `svg`)."""
    return {'kind': 'divider', 'orientation': orientation, 'thickness': thickness, 'color': color}
