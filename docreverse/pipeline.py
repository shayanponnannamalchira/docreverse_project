"""Orchestration: load -> analyse -> store."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

from .config import SUPPORTED_EXTENSIONS, Config
from .extract.entities import Gazetteer, find_spans
from .extract.facts import extract_facts, extract_references, extract_terms
from .extract.processes import extract_processes
from .extract.relations import extract_relations
from .extract.rules import extract_rule
from .ingest import LoaderError, load_document
from .models import Block, Document, Extraction, Mention
from .store import Store
from .textutil import split_sentences

ANALYSED_KINDS = {"paragraph", "list_item", "table_row", "field", "comment"}


def analyse_document(doc: Document, gaz: Optional[Gazetteer] = None) -> Extraction:
    ex = Extraction()
    for sec in doc.sections:
        for blk in sec.blocks:
            if blk.kind not in ANALYSED_KINDS:
                continue
            for sent in split_sentences(blk.text):
                spans = find_spans(sent, gaz)
                for sp in spans:
                    ex.mentions.append(Mention(sp.name, sp.kind, sec.heading, sent[:240]))
                ex.relations.extend(extract_relations(sent, spans, sec.heading))
                if blk.kind != "field":
                    rule = extract_rule(sent, sec.heading)
                    if rule:
                        ex.rules.append(rule)
                ex.facts.extend(extract_facts(sent, sec.heading))
                ex.references.extend(extract_references(sent, doc))
    ex.terms = extract_terms(doc)
    ex.processes = extract_processes(doc, gaz, ex.relations)
    return ex


def make_chunks(doc: Document, size: int, overlap: int) -> List[Tuple[str, str]]:
    """Split each section into search chunks of roughly `size` characters."""
    chunks: List[Tuple[str, str]] = []
    for sec in doc.sections:
        buf: List[str] = []
        length = 0
        for b in sec.blocks:
            if b.kind == "heading":
                continue
            text = ("- " if b.kind == "list_item" else "") + b.text
            if length + len(text) > size and buf:
                chunks.append((sec.heading, "\n".join(buf)))
                keep = buf[-1] if len(buf[-1]) <= overlap else None
                buf, length = ([keep] if keep else []), (len(keep) if keep else 0)
            buf.append(text)
            length += len(text)
        if buf:
            chunks.append((sec.heading, "\n".join(buf)))
    return chunks


def discover(paths: Iterable[str]) -> List[Path]:
    files: List[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_file():
            files.append(path)
        else:
            for root, dirs, names in os.walk(path):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("__pycache__", "node_modules")]
                for n in sorted(names):
                    if not n.startswith(".") and not n.startswith("~$") and Path(n).suffix.lower() in SUPPORTED_EXTENSIONS:
                        files.append(Path(root) / n)
    return sorted(files)


def ingest(paths: Iterable[str], store: Store, cfg: Config, gaz: Optional[Gazetteer] = None, force: bool = False,
           log: Callable[[str], None] = print) -> dict:
    stats = {"added": 0, "updated": 0, "unchanged": 0, "failed": 0}
    for f in discover(paths):
        try:
            doc = load_document(f)
        except (LoaderError, OSError, Exception) as e:   # one bad file must never stop the batch
            stats["failed"] += 1
            log(f"  ! {f}: {e}")
            continue
        existing = store.document_sha(doc.path)
        if existing == doc.sha and not force:
            stats["unchanged"] += 1
            continue
        ex = analyse_document(doc, gaz)
        store.save_document(doc, ex, make_chunks(doc, cfg.chunk_chars, cfg.chunk_overlap))
        stats["updated" if existing else "added"] += 1
        log(f"  + {f}  [{doc.doc_type}] {len(doc.sections)} sections, {len(ex.processes)} processes, "
            f"{len(ex.relations)} relations, {len(ex.rules)} rules")
    return stats
