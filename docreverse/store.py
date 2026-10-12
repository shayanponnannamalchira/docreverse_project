"""SQLite persistence + full-text search (FTS5 when available, plain scoring otherwise)."""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import Document, Extraction
from .textutil import STOPWORDS

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents(id INTEGER PRIMARY KEY, path TEXT UNIQUE, title TEXT, doc_type TEXT, doc_code TEXT,
    sha TEXT, mtime REAL, n_sections INTEGER, metadata TEXT);
CREATE TABLE IF NOT EXISTS sections(id INTEGER PRIMARY KEY, doc_id INTEGER, idx INTEGER, heading TEXT, level INTEGER, n_chars INTEGER);
CREATE TABLE IF NOT EXISTS mentions(id INTEGER PRIMARY KEY, doc_id INTEGER, name TEXT, kind TEXT, section TEXT, sentence TEXT);
CREATE TABLE IF NOT EXISTS relations(id INTEGER PRIMARY KEY, doc_id INTEGER, subject TEXT, subject_kind TEXT, predicate TEXT,
    object TEXT, object_kind TEXT, section TEXT, evidence TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS processes(id INTEGER PRIMARY KEY, doc_id INTEGER, name TEXT, section TEXT, owner TEXT, owner_source TEXT,
    trigger_text TEXT, steps TEXT, systems TEXT, roles TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS rules(id INTEGER PRIMARY KEY, doc_id INTEGER, section TEXT, modality TEXT, text TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY, doc_id INTEGER, section TEXT, value REAL, unit TEXT, raw TEXT, sentence TEXT);
CREATE TABLE IF NOT EXISTS refs(id INTEGER PRIMARY KEY, doc_id INTEGER, target TEXT, kind TEXT, evidence TEXT);
CREATE TABLE IF NOT EXISTS terms(id INTEGER PRIMARY KEY, doc_id INTEGER, term TEXT, definition TEXT);
CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, doc_id INTEGER, section TEXT, text TEXT);
CREATE INDEX IF NOT EXISTS ix_mentions_doc ON mentions(doc_id);
CREATE INDEX IF NOT EXISTS ix_rel_doc ON relations(doc_id);
"""
CHILD_TABLES = ["sections", "mentions", "relations", "processes", "rules", "facts", "refs", "terms"]


class Store:
    def __init__(self, path: str = ".docreverse/index.db"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = sqlite3.connect(path)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        self.fts = True
        try:
            self.con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(text, section UNINDEXED, doc_id UNINDEXED, tokenize='porter')")
        except sqlite3.OperationalError:
            self.fts = False
        self.con.commit()

    # ------------------------------------------------------------------ writes
    def document_sha(self, path: str) -> Optional[str]:
        row = self.con.execute("SELECT sha FROM documents WHERE path=?", (path,)).fetchone()
        return row["sha"] if row else None

    def remove_document(self, path: str) -> None:
        row = self.con.execute("SELECT id FROM documents WHERE path=?", (path,)).fetchone()
        if not row:
            return
        did = row["id"]
        for t in CHILD_TABLES:
            self.con.execute(f"DELETE FROM {t} WHERE doc_id=?", (did,))
        if self.fts:
            self.con.execute("DELETE FROM chunks_fts WHERE rowid IN (SELECT id FROM chunks WHERE doc_id=?)", (did,))
        self.con.execute("DELETE FROM chunks WHERE doc_id=?", (did,))
        self.con.execute("DELETE FROM documents WHERE id=?", (did,))
        self.con.commit()

    def save_document(self, doc: Document, ex: Extraction, chunks: List[Tuple[str, str]]) -> int:
        self.remove_document(doc.path)
        cur = self.con.execute(
            "INSERT INTO documents(path,title,doc_type,doc_code,sha,mtime,n_sections,metadata) VALUES(?,?,?,?,?,?,?,?)",
            (doc.path, doc.title, doc.doc_type, doc.doc_code, doc.sha, doc.mtime, len(doc.sections), json.dumps(doc.metadata)))
        did = cur.lastrowid
        c = self.con
        c.executemany("INSERT INTO sections(doc_id,idx,heading,level,n_chars) VALUES(?,?,?,?,?)",
                      [(did, s.index, s.heading, s.level, len(s.text)) for s in doc.sections])
        c.executemany("INSERT INTO mentions(doc_id,name,kind,section,sentence) VALUES(?,?,?,?,?)",
                      [(did, m.name, m.kind, m.section, m.sentence) for m in ex.mentions])
        c.executemany("INSERT INTO relations(doc_id,subject,subject_kind,predicate,object,object_kind,section,evidence,source) VALUES(?,?,?,?,?,?,?,?,?)",
                      [(did, r.subject, r.subject_kind, r.predicate, r.object, r.object_kind, r.section, r.evidence, r.source) for r in ex.relations])
        c.executemany("INSERT INTO processes(doc_id,name,section,owner,owner_source,trigger_text,steps,systems,roles,source) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      [(did, p.name, p.section, p.owner, p.owner_source, p.trigger, json.dumps([asdict(s) for s in p.steps]),
                        json.dumps(p.systems), json.dumps(p.roles), p.source) for p in ex.processes])
        c.executemany("INSERT INTO rules(doc_id,section,modality,text,source) VALUES(?,?,?,?,?)",
                      [(did, r.section, r.modality, r.text, r.source) for r in ex.rules])
        c.executemany("INSERT INTO facts(doc_id,section,value,unit,raw,sentence) VALUES(?,?,?,?,?,?)",
                      [(did, f.section, f.value, f.unit, f.raw, f.sentence) for f in ex.facts])
        c.executemany("INSERT INTO refs(doc_id,target,kind,evidence) VALUES(?,?,?,?)",
                      [(did, r.target, r.kind, r.evidence) for r in ex.references])
        c.executemany("INSERT INTO terms(doc_id,term,definition) VALUES(?,?,?)", [(did, t.term, t.definition) for t in ex.terms])
        for section, text in chunks:
            ck = c.execute("INSERT INTO chunks(doc_id,section,text) VALUES(?,?,?)", (did, section, text))
            if self.fts:
                c.execute("INSERT INTO chunks_fts(rowid,text,section,doc_id) VALUES(?,?,?,?)", (ck.lastrowid, text, section, did))
        c.commit()
        return did

    def prune_missing(self) -> List[str]:
        gone = [r["path"] for r in self.con.execute("SELECT path FROM documents") if not Path(r["path"]).exists()]
        for p in gone:
            self.remove_document(p)
        return gone

    # ------------------------------------------------------------------ reads
    def rows(self, table: str) -> List[Dict]:
        return [dict(r) for r in self.con.execute(f"SELECT * FROM {table}")]

    def count(self, table: str) -> int:
        return self.con.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]

    def search(self, query: str, k: int = 6) -> List[Dict]:
        words = [w for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]+", query.lower()) if w not in STOPWORDS]
        if not words:
            return []
        sql_base = ("SELECT c.id, c.doc_id, c.section, c.text, d.title, d.path FROM {src} "
                    "JOIN documents d ON d.id = c.doc_id")
        if self.fts:
            match = " OR ".join(f'"{w}"' for w in words)
            try:
                rows = self.con.execute(
                    "SELECT c.id, c.doc_id, c.section, c.text, d.title, d.path, bm25(chunks_fts) AS score "
                    "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid JOIN documents d ON d.id = c.doc_id "
                    "WHERE chunks_fts MATCH ? ORDER BY score LIMIT ?", (match, k)).fetchall()
                return [dict(r) for r in rows]
            except sqlite3.OperationalError:
                pass
        scored = []
        for r in self.con.execute(sql_base.format(src="chunks c")):
            low = r["text"].lower()
            score = sum(low.count(w) for w in words)
            if score:
                scored.append((score, dict(r)))
        scored.sort(key=lambda t: -t[0])
        return [d for _, d in scored[:k]]

    def close(self) -> None:
        self.con.close()
