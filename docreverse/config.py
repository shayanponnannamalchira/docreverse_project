"""Central configuration. Everything has a sensible default; override via CLI flags or env vars."""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DB = os.environ.get("DOCREVERSE_DB", ".docreverse/index.db")
DEFAULT_MODEL = os.environ.get("DOCREVERSE_MODEL", "claude-sonnet-5-5")

SUPPORTED_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst", ".log",
    ".html", ".htm", ".csv", ".docx", ".xlsx", ".pptx", ".pdf", ".eml",
}


@dataclass
class Config:
    db_path: str = DEFAULT_DB
    chunk_chars: int = 900          # target size of a search chunk
    chunk_overlap: int = 150        # max size of a block re-used as overlap between chunks
    llm_model: str = DEFAULT_MODEL
    redact_before_llm: bool = True  # strip emails/phones/IDs/secrets before any text leaves the machine
    stale_after_days: int = 365     # a document not reviewed for this long is flagged as stale
