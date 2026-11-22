"""Un unico motor de render para toda la reporteria (HTML/Markdown/PDF/DOCX), sobre el arbol de bloques
genericos de report_doc.py -- antes `reporting.py`, `spec_report.py` y `evidence_report.py` reimplementaban
cada uno su propio HTML/CSS/Markdown/DOCX por separado; esto es el unico lugar de verdad de ahi en mas.
`render_pdf_from_html` es el mismo Chromium/Playwright que ya usaba `reporting.render_pdf` (sin cambios de
comportamiento, solo movido aca); `reporting.render_pdf` queda como alias para no romper a quien ya lo llama."""
import html
import io
import json
from pathlib import Path

HTML_CSS = '''
:root{color-scheme:light}*{box-sizing:border-box}body{font-family:Segoe UI,Calibri,Arial,sans-serif;color:#111827;margin:0;background:#f3f4f6}
main{max-width:980px;margin:0 auto;padding:24px 20px 48px}h1{font-size:24px;margin:0 0 2px}h2{font-size:16px;margin:26px 0 8px;border-bottom:1px solid #e5e7eb;padding-bottom:4px}
h3{font-size:14px;margin:16px 0 6px}.meta{color:#6b7280;font-size:13px}.banner{border-radius:10px;padding:16px 20px;color:#fff;margin:16px 0}
.banner b{font-size:22px;letter-spacing:.5px}.banner ul{margin:8px 0 0 18px;padding:0}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:14px 0}
.card{background:#fff;border-radius:8px;padding:10px 14px;border:1px solid #e5e7eb}.card .v{font-size:22px;font-weight:700}.card .l{font-size:12px;color:#6b7280}
table{width:100%;border-collapse:collapse;background:#fff;font-size:13px;margin:8px 0}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #e5e7eb;vertical-align:top}th{background:#f9fafb;color:#374151}
.pill{display:inline-block;padding:1px 10px;border-radius:10px;color:#fff;font-size:12px;font-weight:600}
.group{background:#fff;border:1px solid #e5e7eb;border-radius:8px;padding:12px 14px;margin:10px 0}
.group.indent{margin-left:18px;border-left:2px solid #e5e7eb;border-radius:0;background:none;border-top:none;border-right:none;border-bottom:none}
pre{background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:8px 10px;font-size:12px;overflow:auto;white-space:pre-wrap;word-break:break-word}
.check{display:flex;gap:6px;align-items:flex-start;font-size:13px;margin:2px 0}.ok{color:#16a34a}.bad{color:#dc2626}
.foot{color:#6b7280;font-size:12px;margin-top:24px}
@media print{body{background:#fff}main{padding:0}.card,.group,table{break-inside:avoid}h2{break-after:avoid}}
'''


# --------------------------------------------------------------------------- HTML

def _block_html(block, e=html.escape):
    kind = block['kind']
    if kind == 'heading':
        level = min(max(block.get('level', 2), 1), 4) + 1   # h1 es el titulo del doc; las secciones arrancan en h2
        return f'<h{level}>{e(block["text"])}</h{level}>'
    if kind == 'text':
        return f'<p>{e(block["text"])}</p>'
    if kind == 'kv':
        rows = ''.join(f'<tr><th>{e(str(k))}</th><td>{e(str(v) if v is not None else "—")}</td></tr>' for k, v in block['rows'])
        return f'<table>{rows}</table>'
    if kind == 'table':
        head = ''.join(f'<th>{e(str(c))}</th>' for c in block['columns'])
        body = ''.join('<tr>' + ''.join(f'<td>{e(str(c) if c is not None else "—")}</td>' for c in row) + '</tr>' for row in block['rows'])
        return f'<table><tr>{head}</tr>{body}</table>'
    if kind == 'list':
        tag = 'ol' if block.get('ordered') else 'ul'
        return f'<{tag}>' + ''.join(f'<li>{e(str(i))}</li>' for i in block['items']) + f'</{tag}>'
    if kind == 'checks':
        rows = []
        for item in block['items']:
            icon = '✓' if item.get('ok') else '✗'
            detail = f' → {e(str(item["detail"])[:300])}' if item.get('detail') and not item['ok'] else ''
            note = f'<div style="margin-left:18px;color:#4b5563">{e(str(item["note"]))}</div>' if item.get('note') else ''
            rows.append(f'<div class="check {"ok" if item.get("ok") else "bad"}">{icon} {e(item.get("label", ""))}{detail}</div>{note}')
        return ''.join(rows)
    if kind == 'file':
        note = f' {e(block["note"])}' if block.get('note') else ''
        return f'<img src="{e(block["url"])}" alt="{e(block["label"])}" style="max-width:100%;border-radius:8px">{note}' if block.get('image') \
            else f'<p><a href="{e(block["url"])}">{e(block["label"])}</a>{note}</p>'
    if kind == 'badge':
        return f'<span class="pill" style="background:{e(block["color"])}">{e(block["label"])}</span>'
    if kind == 'cards':
        return '<div class="cards">' + ''.join(f'<div class="card"><div class="v">{e(str(i["value"]))}</div><div class="l">{e(i["label"])}</div></div>' for i in block['items']) + '</div>'
    if kind == 'banner':
        lines = ''.join(f'<li>{e(l)}</li>' for l in block['lines'])
        return f'<div class="banner" style="background:{e(block["color"])}"><b>{e(block["title"])}</b>' + (f'<ul>{lines}</ul>' if lines else '') + '</div>'
    if kind == 'svg':
        return block['markup']
    if kind == 'code':
        return f'<pre>{e(block["text"])}</pre>'
    if kind == 'group':
        inner = ''.join(_block_html(c, e) for c in block['children'])
        cls = 'group indent' if block.get('indent') else 'group'
        return f'<div class="{cls}">{inner}</div>'
    raise ValueError(f'Bloque desconocido: {kind}')


def render_html(doc):
    e = html.escape
    body = [f'<h1>{e(doc["title"])}</h1>']
    if doc.get('meta'):
        body.append(f'<div class="meta">{e(doc["meta"])}</div>')
    body += [_block_html(b, e) for b in doc['blocks']]
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{e(doc["title"])}</title><style>{HTML_CSS}</style></head><body><main>{"".join(body)}</main></body></html>')


# --------------------------------------------------------------------------- Markdown

def _block_markdown(block, level=2):
    kind = block['kind']
    if kind == 'heading':
        return [f'{"#" * min(max(block.get("level", level), 1), 6)} {block["text"]}', '']
    if kind == 'text':
        return [block['text'], '']
    if kind == 'kv':
        lines = ['| Campo | Valor |', '|---|---|']
        lines += [f'| {k} | {v if v is not None else "—"} |' for k, v in block['rows']]
        return lines + ['']
    if kind == 'table':
        lines = ['| ' + ' | '.join(str(c) for c in block['columns']) + ' |', '|' + '---|' * len(block['columns'])]
        lines += ['| ' + ' | '.join(str(c) if c is not None else '—' for c in row).replace('\n', ' ') + ' |' for row in block['rows']]
        return lines + ['']
    if kind == 'list':
        if block.get('ordered'):
            return [f'{i}. {item}' for i, item in enumerate(block['items'], 1)] + ['']
        return [f'- {i}' for i in block['items']] + ['']
    if kind == 'checks':
        lines = []
        for item in block['items']:
            mark = '✓' if item.get('ok') else '✗'
            detail = f' → {str(item["detail"])[:300]}' if item.get('detail') and not item['ok'] else ''
            lines.append(f'- {mark} {item.get("label", "")}{detail}')
            if item.get('note'):
                lines.append(f'  {item["note"]}')
        return lines + ['']
    if kind == 'badge':
        return [f'**{block["label"]}**', '']
    if kind == 'cards':
        return [f'- **{i["value"]}** {i["label"]}' for i in block['items']] + ['']
    if kind == 'banner':
        lines = [f'> **{block["title"]}**']
        lines += [f'> - {l}' for l in block['lines']]
        return lines + ['']
    if kind == 'svg':
        return []   # sin equivalente textual, se omite (el PDF/HTML sí lo muestran)
    if kind == 'file':
        link = f'![{block["label"]}]({block["url"]})' if block.get('image') else f'[{block["label"]}]({block["url"]})'
        return [link + (f' {block["note"]}' if block.get('note') else ''), '']
    if kind == 'code':
        lang = block.get('language') or ''
        return [f'```{lang}', block['text'], '```', '']
    if kind == 'group':
        lines = []
        for child in block['children']:
            lines += _block_markdown(child, level + 1)
        return lines
    raise ValueError(f'Bloque desconocido: {kind}')


def render_markdown(doc):
    lines = [f'# {doc["title"]}', '']
    if doc.get('meta'):
        lines += [doc['meta'], '']
    for block in doc['blocks']:
        lines += _block_markdown(block)
    return '\n'.join(lines) + '\n'


# --------------------------------------------------------------------------- DOCX

def _block_docx(doc, block, level=2):
    from docx.shared import Pt
    kind = block['kind']
    if kind == 'heading':
        doc.add_heading(block['text'], level=min(max(block.get('level', level), 1), 4))
    elif kind == 'text':
        doc.add_paragraph(block['text'])
    elif kind == 'kv':
        for k, v in block['rows']:
            doc.add_paragraph(f'{k}: {v if v is not None else "—"}')
    elif kind == 'table':
        table = doc.add_table(rows=1, cols=len(block['columns']))
        table.style = 'Light Grid Accent 1'
        for cell, col in zip(table.rows[0].cells, block['columns']):
            cell.text = str(col)
        for row in block['rows']:
            cells = table.add_row().cells
            for cell, value in zip(cells, row):
                cell.text = str(value) if value is not None else '—'
    elif kind == 'list':
        style = 'List Number' if block.get('ordered') else 'List Bullet'
        for item in block['items']:
            doc.add_paragraph(str(item), style=style)
    elif kind == 'checks':
        for item in block['items']:
            mark = '✓ ' if item.get('ok') else '✗ '
            detail = f' → {str(item["detail"])[:300]}' if item.get('detail') and not item['ok'] else ''
            doc.add_paragraph(mark + item.get('label', '') + detail)
            if item.get('note'):
                doc.add_paragraph(str(item['note']))
    elif kind == 'file':
        if block.get('image') and block.get('path') and Path(block['path']).is_file():
            try:
                from docx.shared import Inches
                doc.add_picture(block['path'], width=Inches(4))
            except Exception:
                doc.add_paragraph(f'[imagen no disponible: {block["label"]}]')
        elif block.get('image'):
            doc.add_paragraph(f'[imagen: {block["label"]} — ver la versión HTML]')
        else:
            doc.add_paragraph(f'Adjunto: {block["label"]}' + (f' {block["note"]}' if block.get('note') else ''))
    elif kind == 'badge':
        doc.add_paragraph(block['label'])
    elif kind == 'cards':
        doc.add_paragraph(' · '.join(f'{i["value"]} {i["label"]}' for i in block['items']))
    elif kind == 'banner':
        doc.add_heading(block['title'], level=2)
        for line in block['lines']:
            doc.add_paragraph(line, style='List Bullet')
    elif kind == 'svg':
        pass   # sin equivalente en DOCX, se omite (el PDF/HTML sí lo muestran)
    elif kind == 'code':
        p = doc.add_paragraph(block['text'])
        for run_ in p.runs:
            run_.font.name = 'Consolas'
            run_.font.size = Pt(9)
    elif kind == 'group':
        for child in block['children']:
            _block_docx(doc, child, level + 1)
    else:
        raise ValueError(f'Bloque desconocido: {kind}')


def render_docx(doc):
    from docx import Document
    document = Document()
    document.add_heading(doc['title'], level=1)
    if doc.get('meta'):
        document.add_paragraph(doc['meta'])
    for block in doc['blocks']:
        _block_docx(document, block)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# --------------------------------------------------------------------------- PDF (Chromium/Playwright) y despacho

def render_pdf_from_html(html_text, destination):
    """Chromium (ya lo requiere la UI de Casos UI) imprime el HTML del reporte -- igual que antes vivía en
    reporting.render_pdf; movido acá para que sea el único lugar, con un alias en reporting.py."""
    from playwright.sync_api import sync_playwright
    destination = Path(destination)
    source = destination.with_suffix('.tmp.html')
    source.write_text(html_text, encoding='utf-8')
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(source.as_uri(), wait_until='load')
            page.emulate_media(media='print')
            page.pdf(path=str(destination), format='A4', print_background=True, margin={'top': '14mm', 'bottom': '14mm', 'left': '12mm', 'right': '12mm'})
            browser.close()
    finally:
        source.unlink(missing_ok=True)
    return destination


def render(doc, kind):
    """Despacho genérico: 'html' | 'md'/'markdown' | 'docx' | 'json' (el doc crudo, para depurar/integrar)."""
    if kind == 'html':
        return render_html(doc).encode('utf-8')
    if kind in ('md', 'markdown'):
        return render_markdown(doc).encode('utf-8')
    if kind == 'docx':
        return render_docx(doc)
    if kind == 'json':
        return json.dumps(doc, indent=2, ensure_ascii=False).encode('utf-8')
    raise ValueError('Formato no reconocido (html, md, docx o json; pdf se genera desde el HTML, ver render_pdf_from_html)')
