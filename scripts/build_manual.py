"""Builds the user manual from docs/manual/src/*.md.

Outputs
  MANUAL_DE_USUARIO.md                  Markdown (images referenced from docs/manual/img/)
  docs/manual/MANUAL_DE_USUARIO.html    single self-contained HTML (images embedded), with table of contents
  docs/manual/MANUAL_DE_USUARIO.pdf     A4 PDF rendered from the HTML with Chromium (needs Playwright)

Usage: python scripts/build_manual.py [--no-pdf]
"""
import base64
import datetime as dt
import html
import re
import sys
from pathlib import Path

import markdown2

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / 'docs' / 'manual' / 'src'
IMG = ROOT / 'docs' / 'manual' / 'img'
VERSION = '1.0.0'
TITLE = 'Manual de usuario'
SUBTITLE = 'Local Test Workspace'

CSS = """
:root{--ink:#1f2937;--muted:#6b7280;--line:#e5e7eb;--brand:#2563eb;--soft:#f3f4f6}
*{box-sizing:border-box}
body{font:15px/1.6 'Segoe UI',system-ui,-apple-system,Roboto,Arial,sans-serif;color:var(--ink);margin:0;background:#fff}
main{max-width:980px;margin:0 auto;padding:0 28px 80px}
h1{font-size:28px;margin:64px 0 12px;padding-top:24px;border-top:3px solid var(--brand);color:#111827}
h2{font-size:21px;margin:40px 0 10px;color:#111827}
h3{font-size:17px;margin:28px 0 8px;color:#111827}
h4{font-size:15px;margin:20px 0 6px}
p,li{max-width:80ch}
a{color:var(--brand);text-decoration:none} a:hover{text-decoration:underline}
code{font:13px/1.4 Consolas,'Cascadia Mono',monospace;background:var(--soft);padding:1px 5px;border-radius:4px}
pre{background:#0f172a;color:#e2e8f0;padding:14px 16px;border-radius:8px;overflow:auto;font-size:13px;line-height:1.5}
pre code{background:none;color:inherit;padding:0}
table{border-collapse:collapse;width:100%;margin:14px 0 20px;font-size:14px}
th,td{border:1px solid var(--line);padding:7px 10px;vertical-align:top;text-align:left}
th{background:var(--soft);font-weight:600}
tr:nth-child(even) td{background:#fafafa}
blockquote{margin:16px 0;padding:10px 16px;border-left:4px solid var(--brand);background:#eff6ff;border-radius:0 8px 8px 0}
blockquote p{margin:6px 0}
blockquote.warn{border-color:#d97706;background:#fffbeb}
blockquote.tip{border-color:#059669;background:#ecfdf5}
figure{margin:18px 0 26px;text-align:center}
figure img{max-width:100%;border:1px solid var(--line);border-radius:8px;box-shadow:0 2px 10px rgba(0,0,0,.08)}
figcaption{font-size:13px;color:var(--muted);margin-top:6px}
hr{border:0;border-top:1px solid var(--line);margin:40px 0}
.cover{min-height:92vh;display:flex;flex-direction:column;justify-content:center;padding:0 8px}
.cover .brand{color:var(--brand);font-weight:700;letter-spacing:.14em;text-transform:uppercase;font-size:13px}
.cover h1{font-size:52px;line-height:1.1;border:0;margin:10px 0 6px;padding:0}
.cover .sub{font-size:24px;color:var(--muted);margin-bottom:34px}
.cover dl{display:grid;grid-template-columns:140px 1fr;gap:6px 14px;font-size:15px;max-width:640px}
.cover dt{color:var(--muted)}
.toc{page-break-before:always;page-break-after:always}
.toc h2{margin-top:0}
.toc ol{list-style:none;padding-left:0;columns:1}
.toc .ch{font-weight:600;margin-top:10px}
.toc .sec{margin-left:22px;font-size:14px;color:#374151}
@page{size:A4;margin:18mm 16mm 20mm 16mm}
@media print{
  main{max-width:none;padding:0}
  h1{page-break-before:always;margin-top:0}
  .cover h1,.toc h2{page-break-before:auto}
  .cover{page-break-after:always}
  figure,pre,blockquote{page-break-inside:avoid}
  table{page-break-inside:auto} tr{page-break-inside:avoid} thead{display:table-header-group}
  h1,h2,h3{page-break-after:avoid}
  a{color:inherit}
  figure img{box-shadow:none}
  .cover{min-height:240mm}
}
"""


def load_parts():
    parts = []
    for path in sorted(SRC.glob('*.md')):
        parts.append(path.read_text(encoding='utf-8').strip())
    return '\n\n'.join(parts) + '\n'


def clean(label):
    """Headings may carry Markdown emphasis/code: the table of contents shows plain text."""
    return re.sub(r'[*`]', '', label)


def prepare(text):
    """Adds stable anchors (chapters: cap-N, sections: s-N-M), fixes descriptive links, and returns (text, toc entries)."""
    text = re.sub(r'\(#(\d+)-[^)]*\)', r'(#cap-\1)', text)
    out, toc, chapter, section = [], [], 0, 0
    for line in text.splitlines():
        m1 = re.match(r'^# (\d+)\. (.+)$', line)
        m2 = re.match(r'^## (\d+(?:\.\d+)?) (.+)$', line)
        if m1:
            chapter, section = int(m1.group(1)), 0
            toc.append(('ch', f'cap-{chapter}', clean(f'{chapter}. {m1.group(2)}')))
            out.append(f'<a id="cap-{chapter}"></a>')
            out.append('')
        elif m2:
            section += 1
            anchor = f's-{chapter}-{section}'
            toc.append(('sec', anchor, clean(f'{m2.group(1)} {m2.group(2)}')))
            out.append(f'<a id="{anchor}"></a>')
            out.append('')
        out.append(line)
    return '\n'.join(out) + '\n', toc


def cover_md(today):
    return (f'# {TITLE}\n\n## {SUBTITLE} · versión {VERSION}\n\n'
            f'**Fecha:** {today} · **Plataforma:** Windows · **Requisito:** Python 3.11 o superior\n\n'
            '**Para:** desarrolladores, testers, product owners, responsables de integración y quienes trabajen con agentes.\n\n')


def toc_md(toc):
    lines = ['## Contenido', '']
    for kind, anchor, label in toc:
        lines.append(f'- **[{label}](#{anchor})**' if kind == 'ch' else f'  - [{label}](#{anchor})')
    return '\n'.join(lines) + '\n\n---\n\n'


def build_markdown(body, toc, today):
    text = cover_md(today) + toc_md(toc) + body
    return text.replace('](img/', '](docs/manual/img/')


def embed_images(html_text):
    def repl(match):
        name = match.group(1)
        path = IMG / name
        if not path.exists():
            raise SystemExit(f'Falta la imagen {name}')
        data = base64.b64encode(path.read_bytes()).decode()
        return f'src="data:image/png;base64,{data}"'
    return re.sub(r'src="img/([^"]+)"', repl, html_text)


def figures(html_text):
    def repl(match):
        attrs = match.group(1)
        alt = re.search(r'alt="([^"]*)"', attrs)
        caption = f'<figcaption>{alt.group(1)}</figcaption>' if alt and alt.group(1) else ''
        return f'<figure><img {attrs}>{caption}</figure>'
    return re.sub(r'<p><img ([^>]*?)\s*/?></p>', repl, html_text)


def callouts(html_text):
    def repl(match):
        inner = match.group(1)
        kind = ''
        if re.search(r'<strong>(Importante|Cuidado|Atención)', inner):
            kind = ' class="warn"'
        elif re.search(r'<strong>(Consejo|Truco)', inner):
            kind = ' class="tip"'
        return f'<blockquote{kind}>{inner}</blockquote>'
    return re.sub(r'<blockquote>(.*?)</blockquote>', repl, html_text, flags=re.S)


def number_headings(rendered, toc):
    """Gives every chapter/section heading the same id the table of contents links to (raw HTML anchors do not survive markdown2)."""
    ids = [anchor for _, anchor, _ in toc]
    position = {'i': 0}

    def repl(match):
        level, inner = match.group(1), match.group(2)
        if position['i'] >= len(ids):
            raise SystemExit('Hay más títulos en el HTML que entradas en el índice')
        anchor = ids[position['i']]
        position['i'] += 1
        return f'<h{level} id="{anchor}">{inner}</h{level}>'
    rendered = re.sub(r'<h([12])>(.*?)</h\1>', repl, rendered, flags=re.S)
    if position['i'] != len(ids):
        raise SystemExit(f'El HTML tiene {position["i"]} títulos numerados y el índice {len(ids)}')
    return rendered


def build_html(body, toc, today):
    body = re.sub(r'<a id="[^"]+"></a>\n\n', '', body)            # anchors are for the Markdown version only
    rendered = markdown2.markdown(body, extras=['tables', 'fenced-code-blocks', 'cuddled-lists', 'strike', 'target-blank-links'])
    # relative links to sibling documents work from docs/manual/
    rendered = re.sub(r'href="(AGENTS|KNOWN_LIMITATIONS|ARCHITECTURE|DEVELOPER_GUIDE|TEST_REPORT|CHANGELOG)\.md"', r'href="../../\1.md"', rendered)
    rendered = re.sub(r'href="docs/agent/', 'href="../agent/', rendered)
    rendered = number_headings(rendered, toc)
    rendered = embed_images(rendered)
    rendered = figures(rendered)
    rendered = callouts(rendered)
    toc_html = ['<nav class="toc"><h2>Contenido</h2><ol>']
    for kind, anchor, label in toc:
        toc_html.append(f'<li class="{"ch" if kind == "ch" else "sec"}"><a href="#{anchor}">{html.escape(label)}</a></li>')
    toc_html.append('</ol></nav>')
    cover = (f'<section class="cover"><div class="brand">{SUBTITLE}</div><h1>{TITLE}</h1><div class="sub">Guía completa de uso · versión {VERSION}</div>'
             f'<dl><dt>Fecha</dt><dd>{today}</dd><dt>Plataforma</dt><dd>Windows</dd><dt>Requisito</dt><dd>Python 3.11 o superior</dd>'
             '<dt>Para</dt><dd>Desarrolladores, testers, product owners, responsables de integración y quienes trabajen con agentes</dd></dl></section>')
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{TITLE} · {SUBTITLE}</title><style>{CSS}</style></head><body><main>{cover}{"".join(toc_html)}{rendered}</main></body></html>')


def build_pdf(html_path, pdf_path):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(html_path.as_uri(), wait_until='load')
        page.emulate_media(media='print')
        header = '<div style="font-size:8px;color:#6b7280;width:100%;padding:0 16mm;text-align:right">Local Test Workspace · Manual de usuario</div>'
        footer = '<div style="font-size:8px;color:#6b7280;width:100%;padding:0 16mm;text-align:center">Página <span class="pageNumber"></span> de <span class="totalPages"></span></div>'
        page.pdf(path=str(pdf_path), format='A4', print_background=True, display_header_footer=True, header_template=header, footer_template=footer,
                 margin={'top': '18mm', 'bottom': '20mm', 'left': '16mm', 'right': '16mm'})
        browser.close()


def main(argv):
    today = dt.date.today().isoformat()
    body, toc = prepare(load_parts())
    (ROOT / 'MANUAL_DE_USUARIO.md').write_text(build_markdown(body, toc, today), encoding='utf-8')
    out_dir = ROOT / 'docs' / 'manual'
    html_path = out_dir / 'MANUAL_DE_USUARIO.html'
    html_path.write_text(build_html(body, toc, today), encoding='utf-8')
    print('MANUAL_DE_USUARIO.md y docs/manual/MANUAL_DE_USUARIO.html generados;', len([t for t in toc if t[0] == 'ch']), 'capítulos')
    if '--no-pdf' not in argv:
        pdf_path = out_dir / 'MANUAL_DE_USUARIO.pdf'
        build_pdf(html_path, pdf_path)
        print('PDF:', pdf_path, f'({pdf_path.stat().st_size // 1024} KB)')


if __name__ == '__main__':
    main(sys.argv[1:])
