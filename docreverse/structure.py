"""Turn a flat list of blocks into a Document: sections, title, type, code and header fields."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional

from .models import Block, Document, Section

FIELD_KEYS = {
    "owner", "process owner", "document owner", "version", "effective date", "last reviewed", "review date",
    "next review", "approved by", "department", "author", "status", "document id", "document code", "doc id",
    "revision", "date", "classification",
}
FIELD_RE = re.compile(r"^([A-Za-z][A-Za-z ]{1,25}):\s*(.+)$")
CODE_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{2,5}-\d{2,5})(?![A-Za-z0-9])")

TYPE_HINTS = [
    ("runbook", r"runbook|playbook|on-call|incident response"),
    ("sop", r"\bsop\b|standard operating|procedure|work instruction|\bprocess\b"),
    ("policy", r"policy|code of conduct|guideline|\bstandard\b"),
    ("contract", r"agreement|contract|terms and conditions|\bnda\b"),
    ("meeting_minutes", r"minutes|agenda|action items"),
    ("spec", r"specification|requirements|architecture|design doc"),
    ("report", r"report|analysis|summary|quarterly"),
]
EXT_TYPES = {".pptx": "presentation", ".xlsx": "spreadsheet", ".csv": "spreadsheet", ".eml": "email"}


def extract_fields(blocks: List[Block]) -> Dict[str, str]:
    """Pick up 'Owner: ...', 'Version: ...' style header lines."""
    out: Dict[str, str] = {}
    for b in blocks:
        if b.kind in ("field", "paragraph", "list_item"):
            m = FIELD_RE.match(b.text.strip())
            if m and m.group(1).strip().lower() in FIELD_KEYS:
                out.setdefault(m.group(1).strip().lower(), m.group(2).strip())
    return out


def build_sections(blocks: List[Block]) -> List[Section]:
    sections: List[Section] = []
    cur: Optional[Section] = None
    for b in blocks:
        if b.kind == "heading":
            cur = Section(len(sections), b.text, b.level or 1, [])
            sections.append(cur)
        else:
            if cur is None:
                cur = Section(0, "Introduction", 1, [])
                sections.append(cur)
            cur.blocks.append(b)
    return sections


def parent_index(sections: List[Section], i: int) -> Optional[int]:
    """Index of the nearest preceding section with a smaller heading level."""
    for j in range(i - 1, -1, -1):
        if sections[j].level < sections[i].level:
            return j
    return None


def _prettify(stem: str) -> str:
    stem = CODE_RE.sub("", stem, count=1)
    stem = re.sub(r"[_\-]+", " ", stem).strip()
    return stem.title() if stem.islower() else stem


def _classify(path: Path, title: str, blocks: List[Block]) -> str:
    if path.suffix.lower() in EXT_TYPES:
        return EXT_TYPES[path.suffix.lower()]
    head = (title + " " + path.stem).lower()
    body = " ".join(b.text for b in blocks[:25]).lower()[:1500]
    for haystack in (head, body):
        for name, pattern in TYPE_HINTS:
            if re.search(pattern, haystack):
                return name
    return "document"


def build_document(path: Path, blocks: List[Block], meta: Dict[str, str]) -> Document:
    meta = dict(meta)
    for k, v in extract_fields(blocks).items():
        meta.setdefault(k, v)

    title = None
    for b in blocks:
        if b.kind == "heading" and b.level == 1:
            title = b.text
            break
    title = title or meta.get("title") or next((b.text for b in blocks if b.kind == "heading"), None) or _prettify(path.stem)

    code = None
    for source in (path.stem, meta.get("document id", ""), meta.get("document code", ""), meta.get("doc id", ""),
                   " ".join(b.text for b in blocks[:8])):
        m = CODE_RE.search(source or "")
        if m:
            code = m.group(1)
            break

    return Document(
        path=str(path),
        title=title.strip(),
        doc_type=_classify(path, title, blocks),
        doc_code=code,
        sha=hashlib.sha256(path.read_bytes()).hexdigest(),
        mtime=path.stat().st_mtime,
        blocks=blocks,
        sections=build_sections(blocks),
        metadata=meta,
    )
