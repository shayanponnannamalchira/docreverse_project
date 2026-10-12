"""CSV, PDF and e-mail loaders."""
from __future__ import annotations

import csv
import email
import io
import re
import shutil
import subprocess
from collections import Counter
from email import policy
from pathlib import Path
from typing import Dict, List, Tuple

from ..models import Block
from .html import parse_html
from .text import parse_plaintext


class LoaderError(Exception):
    pass


def load_csv(path: Path, max_rows: int = 1000) -> Tuple[List[Block], Dict[str, str]]:
    raw = path.read_bytes().decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = list(csv.reader(io.StringIO(raw), dialect))
    blocks = [Block("heading", path.stem.replace("_", " ").title(), 1)]
    if not rows:
        return blocks, {}
    header = [h.strip() or f"col{i+1}" for i, h in enumerate(rows[0])]
    blocks.append(Block("paragraph", "Columns: " + ", ".join(header)))
    for r in rows[1: max_rows + 1]:
        parts = [f"{h}: {v.strip()}" for h, v in zip(header, r) if v.strip()]
        if parts:
            blocks.append(Block("table_row", "; ".join(parts)))
    return blocks, {}


def _strip_repeated_lines(pages: List[str]) -> List[str]:
    """Remove running headers/footers: short lines that repeat on at least half of the pages."""
    if len(pages) < 3:
        return pages
    counts: Counter = Counter()
    for pg in pages:
        for line in {l.strip() for l in pg.splitlines() if 0 < len(l.strip()) < 80}:
            counts[re.sub(r"\d+", "#", line)] += 1
    noisy = {k for k, v in counts.items() if v >= len(pages) / 2}
    cleaned = []
    for pg in pages:
        cleaned.append("\n".join(l for l in pg.splitlines() if re.sub(r"\d+", "#", l.strip()) not in noisy))
    return cleaned


def load_pdf(path: Path) -> Tuple[List[Block], Dict[str, str]]:
    pages: List[str] = []
    try:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(str(path))
        pages = [(p.extract_text() or "") for p in reader.pages]
    except ImportError:
        exe = shutil.which("pdftotext")
        if not exe:
            raise LoaderError("PDF support needs either `pip install pypdf` or poppler's `pdftotext` on PATH.")
        out = subprocess.run([exe, "-layout", str(path), "-"], capture_output=True, text=True, check=True).stdout
        pages = out.split("\f")
    text = "\n\n".join(_strip_repeated_lines(pages))
    if not text.strip():
        raise LoaderError(f"{path.name}: no extractable text (scanned PDF?). OCR it first, e.g. with ocrmypdf.")
    return parse_plaintext(text), {}


def load_eml(path: Path) -> Tuple[List[Block], Dict[str, str]]:
    msg = email.message_from_bytes(path.read_bytes(), policy=policy.default)
    subject = str(msg.get("subject", "") or path.stem)
    meta = {k: str(msg.get(k, "")) for k in ("from", "to", "date") if msg.get(k)}
    blocks = [Block("heading", subject, 1)]
    for k, v in meta.items():
        blocks.append(Block("paragraph", f"{k.title()}: {v}"))
    body = msg.get_body(preferencelist=("plain", "html"))
    if body is not None:
        content = body.get_content()
        if body.get_content_type() == "text/html":
            inner, _ = parse_html(content)
            blocks.extend(b for b in inner if b.kind != "heading" or b.level > 1)
        else:
            content = "\n".join(l for l in content.splitlines() if not l.lstrip().startswith(">"))
            blocks.extend(b for b in parse_plaintext(content))
    return blocks, meta
