#!/usr/bin/python3
"""Debian side of make-docx, make-xlsx, make-pptx, make-pdf and read-doc.

  office.py docx OUT.docx [IN.md]          Markdown or plain text to a Word file
  office.py xlsx OUT.xlsx [IN.csv|IN.json]...  CSV or JSON to a spreadsheet; several inputs or a JSON object give several sheets
  office.py pptx OUT.pptx [IN.md]          an outline to slides
  office.py pdf  OUT.pdf  [IN.md]          Markdown with headings, lists and tables to a PDF (weasyprint)
  office.py read FILE                      the text of a .docx, .xlsx, .pptx or .pdf file
With no IN, the text comes from stdin. Each maker prints the path and the size in bytes.
The libraries are the pinned ones from makers-install.sh.
"""
import csv
import html
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import makers_common as common  # noqa: E402
from makers_common import MakerError  # noqa: E402

USAGE = {
    'docx': 'usage: make-docx OUT.docx [IN.md]   (or pipe Markdown or text in)',
    'xlsx': 'usage: make-xlsx OUT.xlsx [IN.csv|IN.json]... [--sheet NAME]   (or pipe CSV or JSON in)',
    'pptx': 'usage: make-pptx OUT.pptx [IN.md]   (or pipe the outline in: "# Slide title" lines, "- point" lines under them)',
    'pdf': 'usage: make-pdf OUT.pdf [IN.md]   (or pipe Markdown in)',
    'read': 'usage: read-doc FILE   (.docx .xlsx .pptx .pdf)',
}


def markdown_tokens(text):
    md = common.need('markdown_it').MarkdownIt('commonmark').enable('table').enable('strikethrough')
    return md.parse(text)


# ---------- Word

def add_inline(paragraph, token):
    """Bold, italic, code and links inside one paragraph, as Word runs."""
    bold = italic = strike = False
    link = None
    for child in token.children or []:
        kind = child.type
        if kind == 'strong_open': bold = True
        elif kind == 'strong_close': bold = False
        elif kind == 'em_open': italic = True
        elif kind == 'em_close': italic = False
        elif kind == 's_open': strike = True
        elif kind == 's_close': strike = False
        elif kind == 'link_open': link = child.attrs.get('href')
        elif kind == 'link_close':
            if link:
                paragraph.add_run(f' ({link})')
            link = None
        elif kind in ('softbreak', 'hardbreak'):
            paragraph.add_run().add_break()
        elif kind in ('text', 'code_inline', 'html_inline'):
            run = paragraph.add_run(child.content)
            run.bold, run.italic, run.font.strike = bold, italic, strike
            if kind == 'code_inline':
                run.font.name = 'Courier New'
        elif kind == 'image':
            paragraph.add_run(child.content or child.attrs.get('alt', ''))


def make_docx(text, out):
    docx = common.need('docx')
    document = docx.Document()
    tokens = markdown_tokens(text)
    lists = []  # stack of 'bullet' / 'number'
    table_rows, in_table = [], False
    i = 0
    while i < len(tokens):
        token = tokens[i]
        kind = token.type
        if kind == 'heading_open':
            level = int(token.tag[1])
            paragraph = document.add_heading('', level=0 if level == 1 and not document.paragraphs else level)
            add_inline(paragraph, tokens[i + 1])
            i += 3
            continue
        if kind == 'bullet_list_open': lists.append('bullet')
        elif kind == 'ordered_list_open': lists.append('number')
        elif kind in ('bullet_list_close', 'ordered_list_close'): lists.pop()
        elif kind == 'table_open': in_table, table_rows = True, []
        elif kind == 'tr_open': table_rows.append([])
        elif kind == 'inline' and in_table:
            table_rows[-1].append(token)
        elif kind == 'table_close':
            in_table = False
            width = max(len(row) for row in table_rows)
            table = document.add_table(rows=len(table_rows), cols=width)
            table.style = 'Table Grid'
            for r, row in enumerate(table_rows):
                for c, cell in enumerate(row):
                    paragraph = table.cell(r, c).paragraphs[0]
                    add_inline(paragraph, cell)
                    if r == 0:
                        for run in paragraph.runs:
                            run.bold = True
        elif kind == 'inline':
            if lists:
                depth = min(len(lists), 3)
                style = ('List Bullet' if lists[-1] == 'bullet' else 'List Number') + ('' if depth == 1 else f' {depth}')
                paragraph = document.add_paragraph(style=style)
            else:
                paragraph = document.add_paragraph()
            add_inline(paragraph, token)
        elif kind in ('fence', 'code_block'):
            paragraph = document.add_paragraph()
            run = paragraph.add_run(token.content.rstrip('\n'))
            run.font.name = 'Courier New'
        elif kind == 'hr':
            document.add_paragraph('_' * 40)
        i += 1
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


# ---------- Excel

SHEET_BAD = re.compile(r'[\[\]:*?/\\]')


def sheet_name(name, taken):
    name = SHEET_BAD.sub('-', name).strip("'") or 'Sheet'
    name = name[:31]
    base, n = name, 2
    while name.lower() in taken:
        suffix = f' ({n})'
        name = base[:31 - len(suffix)] + suffix
        n += 1
    taken.add(name.lower())
    return name


def cell_value(value):
    """Numbers stay numbers: '12' -> 12, '3.5' -> 3.5. Everything else is kept as text."""
    if isinstance(value, str):
        stripped = value.strip()
        if re.fullmatch(r'-?(0|[1-9][0-9]{0,14})', stripped):
            return int(stripped)
        if re.fullmatch(r'-?(0|[1-9][0-9]*)\.[0-9]+', stripped):
            return float(stripped)
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def rows_from_json(data):
    """A list of lists, or a list of objects (the keys become the header row)."""
    if isinstance(data, list) and all(isinstance(row, dict) for row in data) and data:
        header = []
        for row in data:
            header.extend(key for key in row if key not in header)
        return [header] + [[row.get(key) for key in header] for row in data]
    if isinstance(data, list) and all(isinstance(row, list) for row in data):
        return data
    if isinstance(data, list):
        return [[item] for item in data]
    raise MakerError('A JSON sheet must be a list of rows or a list of objects.')


def sheets_from_text(text, name):
    stripped = text.strip()
    if not stripped:
        raise MakerError('The input is empty.')
    if stripped[0] in '[{':
        try:
            data = json.loads(stripped)
        except ValueError as exc:
            raise MakerError(f'{name}: the JSON does not parse ({exc}).') from exc
        if isinstance(data, dict):
            return [(key, rows_from_json(value)) for key, value in data.items()]
        return [(name, rows_from_json(data))]
    try:
        dialect = csv.Sniffer().sniff(stripped.splitlines()[0], delimiters=',;\t|')
    except csv.Error:
        dialect = csv.excel
    return [(name, list(csv.reader(io.StringIO(text), dialect)))]


def make_xlsx(sheets, out):
    openpyxl = common.need('openpyxl')
    from openpyxl.styles import Font
    from openpyxl.utils import get_column_letter
    if not sheets:
        raise MakerError('The input has no sheets.')
    book = openpyxl.Workbook()
    book.remove(book.active)
    taken = set()
    for name, rows in sheets:
        sheet = book.create_sheet(sheet_name(str(name), taken))
        widths = {}
        for row in rows:
            sheet.append([cell_value(value) for value in row])
            for c, value in enumerate(row, 1):
                widths[c] = max(widths.get(c, 0), len(str(value if value is not None else '')))
        if rows:
            for cell in sheet[1]:
                cell.font = Font(bold=True)
            sheet.freeze_panes = 'A2'
        for c, width in widths.items():
            sheet.column_dimensions[get_column_letter(c)].width = min(max(width + 2, 8), 60)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


# ---------- PowerPoint

def outline(text):
    """[(title, [(level, words)], notes)] from '# Title' lines and '- point' lines. '>' lines are speaker notes."""
    slides = []
    for raw in text.splitlines():
        if not raw.strip():
            continue
        heading = re.match(r'^\s*#{1,6}\s+(.*)$', raw)
        if heading:
            slides.append([heading.group(1).strip(), [], []])
            continue
        if not slides:
            slides.append(['', [], []])
        note = re.match(r'^\s*>\s?(.*)$', raw)
        if note:
            slides[-1][2].append(note.group(1))
            continue
        point = re.match(r'^(\s*)(?:[-*+]|[0-9]+[.)])\s+(.*)$', raw)
        indent = len(raw) - len(raw.lstrip(' \t').expandtabs(2)) if not point else len(point.group(1).expandtabs(2))
        words = point.group(2) if point else raw.strip()
        slides[-1][1].append((min(indent // 2, 4), words.strip()))
    return [(title, points, ' '.join(notes)) for title, points, notes in slides]


def make_pptx(text, out):
    pptx = common.need('pptx')
    from pptx.util import Inches
    deck = pptx.Presentation()
    deck.slide_width, deck.slide_height = Inches(13.333), Inches(7.5)
    slides = outline(text)
    if not slides:
        raise MakerError('The outline is empty.')
    for number, (title, points, notes) in enumerate(slides):
        title_only = number == 0 and len(points) <= 1 and all(level == 0 for level, _ in points)
        slide = deck.slides.add_slide(deck.slide_layouts[0 if title_only else 1])
        slide.shapes.title.text = title
        body = slide.placeholders[1]
        if title_only:
            body.text = points[0][1] if points else ''
        else:
            frame = body.text_frame
            for n, (level, words) in enumerate(points):
                paragraph = frame.paragraphs[0] if n == 0 else frame.add_paragraph()
                paragraph.text, paragraph.level = words, level
        if notes:
            slide.notes_slide.notes_text_frame.text = notes
    buffer = io.BytesIO()
    deck.save(buffer)
    return buffer.getvalue()


# ---------- PDF

PDF_STYLE = ('@page{size:Letter;margin:1in}body{font-family:DejaVu Sans,sans-serif;font-size:11pt;line-height:1.4}'
             'h1{font-size:20pt}h2{font-size:15pt}h3{font-size:12.5pt}table{border-collapse:collapse;margin:8pt 0}'
             'th,td{border:1px solid #888;padding:3pt 6pt;text-align:left;vertical-align:top}th{background:#eee}'
             'code,pre{font-family:DejaVu Sans Mono,monospace;font-size:9.5pt}pre{background:#f4f4f4;padding:6pt;white-space:pre-wrap}'
             'a{color:#1a4fa0;word-break:break-all}blockquote{border-left:3px solid #bbb;margin-left:0;padding-left:10pt;color:#333}')


def markdown_html(text):
    md = common.need('markdown_it').MarkdownIt('commonmark', {'linkify': False}).enable('table').enable('strikethrough')
    return ('<!doctype html><html><head><meta charset="utf-8"><style>' + PDF_STYLE + '</style></head><body>'
            + md.render(text) + '</body></html>')


def make_pdf(text, out, run=subprocess.run):
    with tempfile.TemporaryDirectory(prefix='make-pdf-') as folder:
        page = Path(folder) / 'page.html'
        target = Path(folder) / 'page.pdf'
        page.write_text(markdown_html(text), encoding='utf-8')
        common.need('weasyprint')
        done = run([str(common.VENV / 'bin/python'), '-m', 'weasyprint', '-q', str(page), str(target)],
                   capture_output=True, text=True, stdin=subprocess.DEVNULL)
        if done.returncode != 0 or not target.is_file():
            raise MakerError('weasyprint: ' + ((done.stderr or done.stdout or 'failed').strip()[-600:]))
        return target.read_bytes()


# ---------- read

def read_docx(path):
    docx = common.need('docx')
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    document = docx.Document(str(path))
    lines = []
    for block in document.element.body.iterchildren():
        tag = block.tag.rsplit('}', 1)[-1]
        if tag == 'p':
            paragraph = Paragraph(block, document)
            style = paragraph.style.name if paragraph.style is not None else ''
            prefix = '#' * int(style.split()[-1]) + ' ' if style.startswith('Heading ') and style.split()[-1].isdigit() \
                else '# ' if style == 'Title' else '- ' if style.startswith('List') else ''
            if paragraph.text.strip():
                lines.append(prefix + paragraph.text)
        elif tag == 'tbl':
            for row in Table(block, document).rows:
                lines.append('\t'.join(cell.text for cell in row.cells))
    return '\n'.join(lines)


def read_xlsx(path):
    openpyxl = common.need('openpyxl')
    book = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    lines = []
    for sheet in book.worksheets:
        lines.append(f'== sheet: {sheet.title}')
        for row in sheet.iter_rows(values_only=True):
            if any(value is not None for value in row):
                lines.append('\t'.join('' if value is None else str(value) for value in row))
    return '\n'.join(lines)


def read_pptx(path):
    pptx = common.need('pptx')
    deck = pptx.Presentation(str(path))
    lines = []
    for number, slide in enumerate(deck.slides, 1):
        lines.append(f'== slide {number}')
        for shape in slide.shapes:
            if shape.has_text_frame:
                for paragraph in shape.text_frame.paragraphs:
                    words = ''.join(run.text for run in paragraph.runs)
                    if words.strip():
                        lines.append('  ' * paragraph.level + words)
            if getattr(shape, 'has_table', False) and shape.has_table:
                for row in shape.table.rows:
                    lines.append('\t'.join(cell.text for cell in row.cells))
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame.text.strip():
            lines.append('notes: ' + slide.notes_slide.notes_text_frame.text)
    return '\n'.join(lines)


def read_pdf(path):
    pypdf = common.need('pypdf')
    reader = pypdf.PdfReader(str(path))
    lines = []
    for number, page in enumerate(reader.pages, 1):
        lines.append(f'== page {number}')
        lines.append((page.extract_text() or '').rstrip())
    return '\n'.join(lines)


READERS = {'docx': read_docx, 'xlsx': read_xlsx, 'pptx': read_pptx, 'pdf': read_pdf}


def file_kind(path):
    """By the file's first bytes, then the name inside the zip: docx, xlsx, pptx or pdf."""
    try:
        with open(path, 'rb') as handle:
            head = handle.read(8)
    except OSError as exc:
        raise MakerError(f'Cannot read {path}: {exc.__class__.__name__}.') from exc
    if head.startswith(b'%PDF-'):
        return 'pdf'
    if head.startswith(b'PK\x03\x04'):
        import zipfile
        try:
            names = zipfile.ZipFile(path).namelist()
        except zipfile.BadZipFile as exc:
            raise MakerError(f'{path} is a damaged zip file.') from exc
        for prefix, kind in (('word/', 'docx'), ('xl/', 'xlsx'), ('ppt/', 'pptx')):
            if any(name.startswith(prefix) for name in names):
                return kind
    raise MakerError(f'{path} is not a Word, Excel, PowerPoint or PDF file.')


# ---------- main

def main(argv, stdin=None):
    if not argv or argv[0] not in USAGE:
        print('usage: office.py docx|xlsx|pptx|pdf|read ...', file=sys.stderr)
        return 2
    what, rest = argv[0], argv[1:]
    try:
        if what == 'read':
            if len(rest) != 1:
                raise MakerError(USAGE['read'])
            path = os.path.abspath(os.path.expanduser(rest[0]))
            text = READERS[file_kind(path)](path)
            print(text)
            return 0
        sheet = None
        if what == 'xlsx' and '--sheet' in rest:
            at = rest.index('--sheet')
            if at + 1 >= len(rest):
                raise MakerError(USAGE['xlsx'])
            sheet = rest[at + 1]
            rest = rest[:at] + rest[at + 2:]
        if not rest or (what != 'xlsx' and len(rest) > 2) or any(arg.startswith('--') for arg in rest):
            raise MakerError(USAGE[what])
        out = common.out_path(rest[0], ['.' + what])
        if what == 'xlsx':
            sheets = []
            for source in rest[1:] or [None]:
                name = sheet or (Path(source).stem if source else 'Sheet1')
                text = common.read_input(source) if source or stdin is None else stdin.read()
                sheets.extend(sheets_from_text(text, name))
            data = make_xlsx(sheets, out)
        else:
            source = rest[1] if len(rest) > 1 else None
            text = common.read_input(source) if source or stdin is None else stdin.read()
            if not text.strip():
                raise MakerError('The input is empty.')
            data = {'docx': make_docx, 'pptx': make_pptx, 'pdf': make_pdf}[what](text, out)
        common.write_whole(out, data)
    except MakerError as exc:
        message = str(exc)
        print(message, file=sys.stderr)
        return 2 if message.startswith('usage:') or 'must end in' in message or 'does not exist' in message \
            or message.startswith(('No input', 'The input is empty', 'Cannot read')) else 1
    print(f'{out}  {len(data)} bytes')
    return 0


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
