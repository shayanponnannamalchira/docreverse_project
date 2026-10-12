"""Load everything the store holds into memory and assemble the knowledge graph."""
from __future__ import annotations

import json
from typing import Dict, List, Optional

from .graph import KnowledgeGraph, node_id
from .store import Store
from .textutil import norm_key


class Model:
    def __init__(self, store: Store):
        self.store = store
        self.docs: Dict[int, dict] = {}
        for d in store.rows("documents"):
            d["metadata"] = json.loads(d.get("metadata") or "{}")
            self.docs[d["id"]] = d
        self.sections = store.rows("sections")
        self.mentions = store.rows("mentions")
        self.relations = store.rows("relations")
        self.rules = store.rows("rules")
        self.facts = store.rows("facts")
        self.refs = store.rows("refs")
        self.terms = store.rows("terms")
        self.processes = store.rows("processes")
        for p in self.processes:
            p["trigger"] = p.get("trigger_text")
            p["steps"] = json.loads(p["steps"] or "[]")
            p["systems"] = json.loads(p["systems"] or "[]")
            p["roles"] = json.loads(p["roles"] or "[]")
        self.graph = self._build_graph()

    # ------------------------------------------------------------------ helpers
    def doc_label(self, doc_id: int) -> str:
        d = self.docs.get(doc_id)
        return (d["doc_code"] + " " if d and d.get("doc_code") else "") + (d["title"] if d else "?")

    def _kind_of(self, name: str, default: str = "role") -> str:
        key = norm_key(name)
        for m in self.mentions:
            if norm_key(m["name"]) == key:
                return m["kind"]
        return default

    # ------------------------------------------------------------------ graph assembly
    def _build_graph(self) -> KnowledgeGraph:
        g = KnowledgeGraph()
        for m in self.mentions:
            g.add_node(m["kind"], m["name"], m["doc_id"])
        for r in self.relations:
            s = g.add_node(r["subject_kind"], r["subject"], r["doc_id"])
            o = g.add_node(r["object_kind"], r["object"], r["doc_id"])
            g.add_edge(s, o, r["predicate"], r["evidence"], r["doc_id"])
        for p in self.processes:
            pid = g.add_node("process", p["name"], p["doc_id"], owner=p["owner"])
            if p["owner"]:
                o = g.add_node(self._kind_of(p["owner"]), p["owner"], p["doc_id"])
                g.add_edge(o, pid, "responsible_for", f"Owner of '{p['name']}' ({p['owner_source']})", p["doc_id"])
            for role in p["roles"]:
                if not p["owner"] or norm_key(role) != norm_key(p["owner"]):
                    g.add_edge(g.add_node(self._kind_of(role), role, p["doc_id"]), pid, "involved_in", "", p["doc_id"])
            for system in p["systems"]:
                g.add_edge(pid, g.add_node("system", system, p["doc_id"]), "uses", "", p["doc_id"])
        by_code = {d["doc_code"]: d for d in self.docs.values() if d.get("doc_code")}
        by_title = {norm_key(d["title"]): d for d in self.docs.values()}
        for ref in self.refs:
            src = self.docs[ref["doc_id"]]
            sid = g.add_node("document", src["title"], ref["doc_id"])
            target = None
            if ref["kind"] == "code":
                target = by_code.get(ref["target"])
            else:
                key = norm_key(ref["target"])
                target = by_title.get(key) or next((d for t, d in by_title.items() if key in t or t in key), None)
            if target:
                tid = g.add_node("document", target["title"], target["id"])
            else:
                tid = g.add_node("document", ref["target"], None, missing=True)
            g.add_edge(sid, tid, "references", ref["evidence"], ref["doc_id"])
        return g
