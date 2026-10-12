"""DOCX / PPTX / XLSX loaders.

These formats are zipped XML, so we parse them with the standard library only - no python-docx,
python-pptx or openpyxl needed. Spreadsheet *formulas* are kept: they are often the only
place where a company's real calculation logic is written down.
"""
from __future__ import annotations

import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Tuple

from ..models import Block

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _read_xml(z: zipfile.ZipFile, name: str):
    try:
        return ET.fromstring(z.read(name))
    except KeyError:
        return None


def _core_properties(z: zipfile.ZipFile) -> Dict[str, str]:
    root = _read_xml(z, "docProps/core.xml")
    meta: Dict[str, str] = {}
    if root is not None:
        for el in root:
            local = el.tag.split("}")[-1]
            if el.text and local in ("title", "creator", "modified", "created", "lastModifiedBy"):
                meta[{"creator": "author"}.get(local, local)] = el.text.strip()
    return meta


# ------------------------------------------------------------------------- DOCX
def _docx_numbering(z: zipfile.ZipFile) -> Dict[str, Dict[int, str]]:
    root = _read_xml(z, "word/numbering.xml")
    if root is None:
        return {}
    abstract: Dict[str, Dict[int, str]] = {}
    for an in root.findall(W + "abstractNum"):
        levels = {}
        for lvl in an.findall(W + "lvl"):
            fmt = lvl.find(W + "numFmt")
            levels[int(lvl.get(W + "ilvl", "0"))] = fmt.get(W + "val") if fmt is not None else "decimal"
        abstract[an.get(W + "abstractNumId")] = levels
    nums = {}
    for n in root.findall(W + "num"):
        a = n.find(W + "abstractNumId")
        nums[n.get(W + "numId")] = abstract.get(a.get(W + "val") if a is not None else "", {})
    return nums


def _docx_styles(z: zipfile.ZipFile) -> Dict[str, str]:
    root = _read_xml(z, "word/styles.xml")
    out: Dict[str, str] = {}
    if root is not None:
        for st in root.findall(W + "style"):
            name = st.find(W + "name")
            if name is not None:
                out[st.get(W + "styleId", "")] = name.get(W + "val", "").lower()
    return out


def _para_text(p) -> str:
    parts = []
    for el in p.iter():
        if el.tag == W + "t" and el.text:
            parts.append(el.text)
        elif el.tag == W + "tab":
            parts.append(" ")
        elif el.tag == W + "br":
            parts.append(" ")
    return " ".join("".join(parts).split())


def load_docx(path: Path) -> Tuple[List[Block], Dict[str, str]]:
    blocks: List[Block] = []
    with zipfile.ZipFile(path) as z:
        root = _read_xml(z, "word/document.xml")
        if root is None:
            return [], {}
        styles, numbering = _docx_styles(z), _docx_numbering(z)
        body = root.find(W + "body")
        for child in (body if body is not None else []):
            if child.tag == W + "p":
                text = _para_text(child)
                if not text:
                    continue
                ppr = child.find(W + "pPr")
                style_id = ""
                num_id, ilvl = None, 0
                if ppr is not None:
                    ps = ppr.find(W + "pStyle")
                    style_id = ps.get(W + "val", "") if ps is not None else ""
                    numpr = ppr.find(W + "numPr")
                    if numpr is not None:
                        n, l = numpr.find(W + "numId"), numpr.find(W + "ilvl")
                        num_id = n.get(W + "val") if n is not None else None
                        ilvl = int(l.get(W + "val", "0")) if l is not None else 0
                style = styles.get(style_id, style_id).lower()
                m = re.match(r"heading\s*(\d)", style)
                if m:
                    blocks.append(Block("heading", text, int(m.group(1))))
                elif style == "title":
                    blocks.append(Block("heading", text, 1))
                elif num_id not in (None, "0") or style.startswith("list"):
                    fmt = numbering.get(num_id or "", {}).get(ilvl, "bullet" if "bullet" in style else "decimal")
                    ordered = fmt not in ("bullet", "none") and "bullet" not in style
                    blocks.append(Block("list_item", text, ilvl, ordered))
                else:
                    blocks.append(Block("paragraph", text))
            elif child.tag == W + "tbl":
                header: List[str] = []
                for ri, tr in enumerate(child.iter(W + "tr")):
                    cells = [" ".join(_para_text(p) for p in tc.iter(W + "p")).strip() for tc in tr.findall(W + "tc")]
                    if ri == 0:
                        header = cells
                    elif len(cells) == len(header):
                        blocks.append(Block("table_row", "; ".join(f"{h}: {c}" for h, c in zip(header, cells) if c)))
                    else:
                        blocks.append(Block("table_row", " | ".join(cells)))
        comments = _read_xml(z, "word/comments.xml")
        if comments is not None:      # reviewers' comments often hold the real rationale
            for c in comments.findall(W + "comment"):
                text = " ".join(_para_text(p) for p in c.iter(W + "p")).strip()
                if text:
                    blocks.append(Block("comment", f"[comment by {c.get(W + 'author', 'unknown')}] {text}"))
        meta = _core_properties(z)
    return blocks, meta


# ------------------------------------------------------------------------- PPTX
def _slide_number(name: str) -> int:
    m = re.search(r"(\d+)\.xml$", name)
    return int(m.group(1)) if m else 0


def _pptx_paragraphs(shape_root) -> List[Tuple[str, int, bool]]:
    out = []
    for p in shape_root.iter(A + "p"):
        text = " ".join("".join(t.text or "" for t in p.iter(A + "t")).split())
        if text:
            ppr = p.find(A + "pPr")
            lvl = int(ppr.get("lvl", "0")) if ppr is not None else 0
            numbered = ppr is not None and ppr.find(A + "buAutoNum") is not None
            out.append((text, lvl, numbered))
    return out


def load_pptx(path: Path) -> Tuple[List[Block], Dict[str, str]]:
    blocks: List[Block] = []
    with zipfile.ZipFile(path) as z:
        slides = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml$", n)), key=_slide_number)
        for name in slides:
            root = _read_xml(z, name)
            n = _slide_number(name)
            title, body = None, []
            for sp in root.iter(P + "sp"):
                ph = sp.find(f".//{P}ph")
                paras = _pptx_paragraphs(sp)
                if ph is not None and ph.get("type") in ("title", "ctrTitle") and paras:
                    title = " ".join(t for t, _, _ in paras)
                else:
                    body.extend(paras)
            for tbl in root.iter(A + "tbl"):
                for tr in tbl.iter(A + "tr"):
                    cells = [" ".join("".join(t.text or "" for t in tc.iter(A + "t")).split()) for tc in tr.iter(A + "tc")]
                    if any(cells):
                        body.append((" | ".join(cells), 0, False))
            blocks.append(Block("heading", title or f"Slide {n}", 2))
            for text, lvl, numbered in body:
                blocks.append(Block("list_item", text, lvl, numbered))
            # speaker notes (linked via the slide's relationships)
            rels = _read_xml(z, f"ppt/slides/_rels/slide{n}.xml.rels")
            if rels is not None:
                for rel in rels.findall(PKG_REL + "Relationship"):
                    if "notesSlide" in rel.get("Target", ""):
                        target = posixpath.normpath(posixpath.join("ppt/slides", rel.get("Target")))
                        notes = _read_xml(z, target)
                        if notes is not None:
                            txt = " ".join(t for t, _, _ in _pptx_paragraphs(notes) if not t.isdigit())
                            if txt:
                                blocks.append(Block("paragraph", f"Speaker notes: {txt}"))
        meta = _core_properties(z)
    return blocks, meta


# ------------------------------------------------------------------------- XLSX
def _col_row(ref: str) -> Tuple[str, int]:
    m = re.match(r"([A-Z]+)(\d+)", ref)
    return (m.group(1), int(m.group(2))) if m else ("", 0)


def load_xlsx(path: Path, max_rows: int = 500, max_formulas: int = 300) -> Tuple[List[Block], Dict[str, str]]:
    blocks: List[Block] = []
    with zipfile.ZipFile(path) as z:
        shared: List[str] = []
        sst = _read_xml(z, "xl/sharedStrings.xml")
        if sst is not None:
            for si in sst.findall(M + "si"):
                shared.append("".join(t.text or "" for t in si.iter(M + "t")))
        wb = _read_xml(z, "xl/workbook.xml")
        rels = _read_xml(z, "xl/_rels/workbook.xml.rels")
        targets = {}
        if rels is not None:
            for rel in rels.findall(PKG_REL + "Relationship"):
                t = rel.get("Target", "")
                targets[rel.get("Id")] = t.lstrip("/") if t.startswith("/") else posixpath.normpath(posixpath.join("xl", t))
        sheets = []
        if wb is not None:
            for sh in wb.iter(M + "sheet"):
                sheets.append((sh.get("name", "Sheet"), targets.get(sh.get(R + "id"), "")))
        for sheet_name, target in sheets:
            root = _read_xml(z, target)
            if root is None:
                continue
            grid: Dict[str, str] = {}
            formulas: List[Tuple[str, str]] = []
            for c in root.iter(M + "c"):
                ref, ctype = c.get("r", ""), c.get("t", "n")
                v, f = c.find(M + "v"), c.find(M + "f")
                if ctype == "s" and v is not None and v.text is not None:
                    val = shared[int(v.text)] if int(v.text) < len(shared) else ""
                elif ctype == "inlineStr":
                    val = "".join(t.text or "" for t in c.iter(M + "t"))
                else:
                    val = v.text if v is not None and v.text is not None else ""
                if val != "":
                    grid[ref] = val
                if f is not None and f.text:
                    formulas.append((ref, f.text))
            blocks.append(Block("heading", f"Sheet: {sheet_name}", 2))
            rows: Dict[int, Dict[str, str]] = {}
            for ref, val in grid.items():
                col, row = _col_row(ref)
                rows.setdefault(row, {})[col] = val
            ordered_rows = sorted(rows)
            if ordered_rows:
                header_row = rows[ordered_rows[0]]
                cols = sorted(header_row, key=lambda c: (len(c), c))
                for r in ordered_rows[1: max_rows + 1]:
                    cells = rows[r]
                    parts = [f"{header_row.get(c, c)}: {cells[c]}" for c in sorted(cells, key=lambda c: (len(c), c)) if cells[c]]
                    if parts:
                        blocks.append(Block("table_row", "; ".join(parts)))
            col_header = {c: v for c, v in (rows[ordered_rows[0]].items() if ordered_rows else [])}
            for ref, formula in formulas[:max_formulas]:
                col, row = _col_row(ref)
                label = rows.get(row, {}).get("A", "")
                hdr = col_header.get(col, "")
                tag = " / ".join(x for x in (label, hdr) if x)
                blocks.append(Block("formula", f"{sheet_name}!{ref}{f' ({tag})' if tag else ''} = {formula}"))
        meta = _core_properties(z)
    return blocks, meta
