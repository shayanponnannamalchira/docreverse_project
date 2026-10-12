"""File loaders. `load_document(path)` picks the right one from the file extension."""
from __future__ import annotations

from pathlib import Path

from ..models import Document
from ..structure import build_document
from .html import load_html
from .office import load_docx, load_pptx, load_xlsx
from .other import LoaderError, load_csv, load_eml, load_pdf
from .text import load_text

LOADERS = {
    ".txt": load_text, ".md": load_text, ".markdown": load_text, ".rst": load_text, ".log": load_text,
    ".html": load_html, ".htm": load_html,
    ".csv": load_csv,
    ".docx": load_docx, ".pptx": load_pptx, ".xlsx": load_xlsx,
    ".pdf": load_pdf, ".eml": load_eml,
}


def load_document(path) -> Document:
    p = Path(path)
    loader = LOADERS.get(p.suffix.lower())
    if loader is None:
        raise LoaderError(f"Unsupported file type: {p.suffix or '(none)'}")
    blocks, meta = loader(p)
    return build_document(p, blocks, meta)


__all__ = ["load_document", "LoaderError", "LOADERS"]
