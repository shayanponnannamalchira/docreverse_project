"""Plain-text / Markdown / reStructuredText parsing into blocks (also reused by PDF, EML)."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

from ..models import Block

MD_HEAD = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
NUM_HEAD = re.compile(r"^(\d+(?:\.\d+)+)\.?\s+(\S.{1,100})$")             # "2.1 Scope"  (needs an inner dot)
SECTION_HEAD = re.compile(r"^(?:section|article|chapter|part|appendix)\s+[\w.]+[:.\-]?\s*.*$", re.I)
LIST_ITEM = re.compile(r"^(\s*)([-*•–]|\d+[.)]|[a-z]\))\s+(.*)$")
RULE_LINE = re.compile(r"^(?:-{3,}|\*{3,}|_{3,}|={3,})$")
TABLE_SEP = re.compile(r"^\|?[\s:\-|]+\|?$")
FIELD_LINE = re.compile(
    r"^(owner|process owner|document owner|version|effective date|last reviewed|review date|next review|approved by|"
    r"department|author|status|document id|document code|doc id|revision|date|classification)\s*:\s*(.+)$", re.I)


def _cells(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def parse_plaintext(text: str) -> List[Block]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: List[Block] = []
    para: List[str] = []

    def flush() -> None:
        if para:
            blocks.append(Block("paragraph", " ".join(s.strip() for s in para)))
            para.clear()

    i, in_code = 0, False
    while i < len(lines):
        line = lines[i].rstrip()
        s = line.strip()

        if s.startswith("```"):
            flush()
            in_code = not in_code
            i += 1
            continue
        if in_code:
            blocks.append(Block("code", line))
            i += 1
            continue
        if not s:
            flush()
            i += 1
            continue
        if RULE_LINE.match(s):
            flush()
            i += 1
            continue

        m = MD_HEAD.match(s)
        if m:
            flush()
            blocks.append(Block("heading", m.group(2).strip(), len(m.group(1))))
            i += 1
            continue

        # setext headings:  Title\n=====   /  Title\n-----
        if not para and i + 1 < len(lines) and len(s) < 100 and not LIST_ITEM.match(line) \
                and re.fullmatch(r"=+|-{3,}", lines[i + 1].strip() or "x"):
            blocks.append(Block("heading", s, 1 if lines[i + 1].strip().startswith("=") else 2))
            i += 2
            continue

        # markdown tables
        if s.startswith("|") and s.count("|") >= 2:
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not TABLE_SEP.match(lines[i].strip()):
                    rows.append(_cells(lines[i]))
                i += 1
            if rows:
                header, body = rows[0], rows[1:]
                for r in body:
                    if len(r) == len(header):
                        blocks.append(Block("table_row", "; ".join(f"{h}: {v}" for h, v in zip(header, r) if v)))
                    else:
                        blocks.append(Block("table_row", " | ".join(r)))
                if not body:
                    blocks.append(Block("table_row", " | ".join(header)))
            continue

        m = NUM_HEAD.match(s)
        if m and not s.endswith(".") and len(m.group(2).split()) <= 10:
            flush()
            blocks.append(Block("heading", f"{m.group(1)} {m.group(2)}", m.group(1).count(".") + 1))
            i += 1
            continue
        if SECTION_HEAD.match(s) and len(s) < 80:
            flush()
            blocks.append(Block("heading", s, 1))
            i += 1
            continue
        if s.isupper() and 3 <= len(s) <= 80 and re.search(r"[A-Z]{3}", s) and not LIST_ITEM.match(line) \
                and not s.endswith((".", ":")):
            flush()
            blocks.append(Block("heading", s.title(), 1))
            i += 1
            continue

        m = LIST_ITEM.match(line)
        if m:
            flush()
            indent = len(m.group(1).replace("\t", "    "))
            marker = m.group(2)
            item = [m.group(3).strip()]
            i += 1
            # continuation lines: indented deeper than the marker, not themselves list items / headings
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip():
                    break
                nindent = len(nxt) - len(nxt.lstrip())
                if nindent > indent and not LIST_ITEM.match(nxt) and not MD_HEAD.match(nxt.strip()):
                    item.append(nxt.strip())
                    i += 1
                else:
                    break
            blocks.append(Block("list_item", " ".join(item), indent // 2, marker[0].isdigit() or marker.endswith(")") and marker[0].isalpha()))
            continue

        m = FIELD_LINE.match(s)
        if m and not para:
            blocks.append(Block("field", f"{m.group(1).strip().title()}: {m.group(2).strip()}"))
            i += 1
            continue

        para.append(s)
        i += 1
    flush()
    return blocks


def load_text(path: Path) -> Tuple[List[Block], Dict[str, str]]:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return parse_plaintext(raw.decode(enc)), {}
        except UnicodeDecodeError:
            continue
    return [], {}
