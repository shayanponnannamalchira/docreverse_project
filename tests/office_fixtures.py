"""Build tiny but valid DOCX / XLSX / PPTX files with only the standard library (used by tests and sample generation)."""
from __future__ import annotations

import zipfile
from xml.sax.saxutils import escape

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_docx(path, items):
    """items: list of (kind, text) with kind in title|h1|h2|p|ol|ul|comment|table(list of rows)"""
    body = []
    for kind, text in items:
        if kind == "table":
            rows = "".join("<w:tr>" + "".join(f"<w:tc><w:p><w:r><w:t>{escape(c)}</w:t></w:r></w:p></w:tc>" for c in row) + "</w:tr>" for row in text)
            body.append(f"<w:tbl>{rows}</w:tbl>")
            continue
        if kind == "comment":
            continue
        style = {"title": "Title", "h1": "Heading1", "h2": "Heading2"}.get(kind)
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        if kind in ("ol", "ul"):
            ppr = f'<w:pPr><w:numPr><w:ilvl w:val="0"/><w:numId w:val="{1 if kind == "ol" else 2}"/></w:numPr></w:pPr>'
        body.append(f"<w:p>{ppr}<w:r><w:t>{escape(text)}</w:t></w:r></w:p>")
    document = f'<?xml version="1.0"?><w:document xmlns:w="{W_NS}"><w:body>{"".join(body)}</w:body></w:document>'
    styles = (f'<?xml version="1.0"?><w:styles xmlns:w="{W_NS}">'
              '<w:style w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>'
              '<w:style w:styleId="Heading2"><w:name w:val="heading 2"/></w:style>'
              '<w:style w:styleId="Title"><w:name w:val="Title"/></w:style></w:styles>')
    numbering = (f'<?xml version="1.0"?><w:numbering xmlns:w="{W_NS}">'
                 '<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="decimal"/></w:lvl></w:abstractNum>'
                 '<w:abstractNum w:abstractNumId="1"><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/></w:lvl></w:abstractNum>'
                 '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num><w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num></w:numbering>')
    comments = [t for k, t in items if k == "comment"]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", styles)
        z.writestr("word/numbering.xml", numbering)
        if comments:
            cx = "".join(f'<w:comment w:author="Reviewer"><w:p><w:r><w:t>{escape(c)}</w:t></w:r></w:p></w:comment>' for c in comments)
            z.writestr("word/comments.xml", f'<?xml version="1.0"?><w:comments xmlns:w="{W_NS}">{cx}</w:comments>')


def make_xlsx(path, sheet_name, rows, formulas):
    """rows: list of lists (strings/numbers). formulas: {'C2': 'A2*B2'} added as formula cells."""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    shared, index = [], {}

    def sidx(text):
        if text not in index:
            index[text] = len(shared)
            shared.append(text)
        return index[text]

    xml_rows = []
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, val in enumerate(row):
            ref = f"{chr(65 + c)}{r}"
            if ref in formulas:
                cells.append(f'<c r="{ref}"><f>{escape(formulas[ref])}</f><v>0</v></c>')
            elif isinstance(val, str):
                cells.append(f'<c r="{ref}" t="s"><v>{sidx(val)}</v></c>')
            else:
                cells.append(f'<c r="{ref}"><v>{val}</v></c>')
        xml_rows.append(f'<row r="{r}">{"".join(cells)}</row>')
    sheet = f'<?xml version="1.0"?><worksheet xmlns="{ns}"><sheetData>{"".join(xml_rows)}</sheetData></worksheet>'
    sst = f'<?xml version="1.0"?><sst xmlns="{ns}">' + "".join(f"<si><t>{escape(s)}</t></si>" for s in shared) + "</sst>"
    wb = (f'<?xml version="1.0"?><workbook xmlns="{ns}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
          f'<sheets><sheet name="{escape(sheet_name)}" sheetId="1" r:id="rId1"/></sheets></workbook>')
    rels = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", wb)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/sharedStrings.xml", sst)


def make_pptx(path, slides):
    """slides: list of (title, [bullets])"""
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    p = "http://schemas.openxmlformats.org/presentationml/2006/main"
    with zipfile.ZipFile(path, "w") as z:
        for i, (title, bullets) in enumerate(slides, start=1):
            paras = "".join(f"<a:p><a:r><a:t>{escape(b)}</a:t></a:r></a:p>" for b in bullets)
            xml = (f'<?xml version="1.0"?><p:sld xmlns:a="{a}" xmlns:p="{p}"><p:cSld><p:spTree>'
                   f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="title"/></p:nvPr></p:nvSpPr><p:txBody><a:p><a:r><a:t>{escape(title)}</a:t></a:r></a:p></p:txBody></p:sp>'
                   f'<p:sp><p:nvSpPr><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr><p:txBody>{paras}</p:txBody></p:sp>'
                   f'</p:spTree></p:cSld></p:sld>')
            z.writestr(f"ppt/slides/slide{i}.xml", xml)
