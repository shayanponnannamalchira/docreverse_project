"""Analyses over the Model: overview, ownership, systems, gaps, conflicts, impact, explanations."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from .model import Model
from .textutil import content_words, jaccard, norm_key

DATE_FORMATS = ["%Y-%m-%d", "%B %d, %Y", "%d %B %Y", "%b %d, %Y", "%d %b %Y", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%B %Y"]
ACRONYM_STOP = set(
    """PDF USD EUR GBP CSV FAQ AM PM UTC OK ID US UK EU FYI CEO CFO CTO COO HR IT QA PMO SOC NOC HTML URL JSON XML SMS NA TBD
    ASAP CC BCC RE FW AND OR NOT THE ALL ANY NO YES API""".split())


@dataclass
class Finding:
    severity: str            # warn | info
    kind: str
    message: str
    evidence: List[str] = field(default_factory=list)


def parse_date(text: str) -> Optional[datetime]:
    text = (text or "").strip().split(" (")[0]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


class Analyzer:
    def __init__(self, model: Model):
        self.m = model
        self.g = model.graph

    # ------------------------------------------------------------------ overview
    def overview(self) -> dict:
        kinds = Counter(n.kind for n in self.g.nodes.values())
        return {
            "documents": len(self.m.docs),
            "by_type": dict(Counter(d["doc_type"] for d in self.m.docs.values())),
            "sections": len(self.m.sections),
            "processes": len(self.m.processes),
            "relations": len(self.m.relations),
            "rules": len(self.m.rules),
            "glossary_terms": len({norm_key(t["term"]) for t in self.m.terms}),
            "graph_nodes": dict(kinds),
            "graph_edges": len(self.g.edges),
        }

    # ------------------------------------------------------------------ ownership & systems
    def ownership(self) -> Dict[str, Dict[str, List[str]]]:
        """role/team -> predicate -> objects (what each actor owns, approves, reviews, sends...)."""
        table: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
        for e in self.g.edges.values():
            src = self.g.nodes[e.src]
            if src.kind in ("role", "team") and e.rel in ("responsible_for", "approves", "reviews", "creates", "submits", "sends_to", "triggers"):
                dst = self.g.nodes[e.dst].label
                if dst not in table[src.label][e.rel]:
                    table[src.label][e.rel].append(dst)
        return table

    def systems_map(self) -> List[dict]:
        headings = [norm_key(s["heading"]) for s in self.m.sections] + [norm_key(d["title"]) for d in self.m.docs.values()]
        defined = {norm_key(t["term"]) for t in self.m.terms}
        rows = []
        for nid, n in self.g.nodes.items():
            if n.kind != "system":
                continue
            users = sorted({self.g.nodes[e.src].label for e in self.g.in_edges(nid) if e.rel == "uses" and self.g.nodes[e.src].kind in ("role", "team")})
            procs = sorted({self.g.nodes[e.src].label for e in self.g.in_edges(nid) if e.rel == "uses" and self.g.nodes[e.src].kind == "process"})
            key = norm_key(n.label)
            rows.append({"system": n.label, "documents": len(n.docs), "used_by": users, "processes": procs,
                         "described": any(key in h for h in headings) or key in defined})
        return sorted(rows, key=lambda r: (-r["documents"], r["system"]))

    # ------------------------------------------------------------------ gaps
    def gaps(self, today: Optional[datetime] = None, stale_days: int = 365) -> List[Finding]:
        today = today or datetime.now()
        out: List[Finding] = []

        for p in self.m.processes:
            doc = self.m.doc_label(p["doc_id"])
            if not p["owner"]:
                out.append(Finding("warn", "ownerless_process", f"Process '{p['name']}' has no stated owner.", [doc]))
            elif p["owner_source"] == "inferred":
                out.append(Finding("info", "inferred_owner", f"Owner of '{p['name']}' is only inferred ({p['owner']}) - confirm it.", [doc]))
            if len(p["steps"]) < 3:
                out.append(Finding("info", "thin_process", f"Process '{p['name']}' has only {len(p['steps'])} step(s); detail may be missing.", [doc]))

        by_code = {d["doc_code"] for d in self.m.docs.values() if d.get("doc_code")}
        titles = [norm_key(d["title"]) for d in self.m.docs.values()]
        seen = set()
        for r in self.m.refs:
            key = (r["doc_id"], r["target"])
            if key in seen:
                continue
            seen.add(key)
            if r["kind"] == "code" and r["target"] not in by_code:
                out.append(Finding("warn", "broken_reference", f"{self.m.doc_label(r['doc_id'])} references {r['target']}, which is not in the corpus.", [r["evidence"]]))
            elif r["kind"] == "named":
                k = norm_key(r["target"])
                if not any(k in t or t in k for t in titles):
                    out.append(Finding("info", "missing_document", f"{self.m.doc_label(r['doc_id'])} cites '{r['target']}', which was not found among the ingested documents.", [r["evidence"]]))

        for row in self.systems_map():
            if row["documents"] >= 2 and not row["described"]:
                out.append(Finding("info", "undocumented_system", f"System '{row['system']}' appears in {row['documents']} documents but no document or section describes it."))

        defined = {norm_key(t["term"]) for t in self.m.terms}
        code_prefixes = {d["doc_code"].split("-")[0] for d in self.m.docs.values() if d.get("doc_code")}
        counts: Counter = Counter()
        for row in self.m.store.con.execute("SELECT text FROM chunks"):
            counts.update(re.findall(r"\b[A-Z]{2,6}\b", row["text"]))
        for tok, n in counts.most_common():
            if n >= 3 and tok not in ACRONYM_STOP and tok not in code_prefixes and norm_key(tok) not in defined \
                    and not any(norm_key(tok) == norm_key(nd.label) for nd in self.g.nodes.values() if nd.kind == "system"):
                out.append(Finding("info", "undefined_acronym", f"Acronym '{tok}' is used {n} times but never defined."))

        for d in self.m.docs.values():
            meta = d["metadata"]
            when = parse_date(meta.get("last reviewed") or meta.get("review date") or meta.get("effective date") or meta.get("date") or "")
            if when and (today - when).days > stale_days:
                out.append(Finding("warn", "stale_document", f"{self.m.doc_label(d['id'])} was last reviewed/dated {when:%Y-%m-%d} ({(today - when).days} days ago).", []))

        groups: Dict[str, list] = defaultdict(list)
        for p in self.m.processes:
            groups[norm_key(p["name"])].append(p)
        for name, plist in groups.items():
            if len({p["doc_id"] for p in plist}) > 1:
                owners = {norm_key(p["owner"]) for p in plist if p["owner"]}
                sev = "warn" if len(owners) > 1 else "info"
                out.append(Finding(sev, "duplicate_process", f"Process '{plist[0]['name']}' is defined in {len({p['doc_id'] for p in plist})} documents"
                                   + (" with different owners." if len(owners) > 1 else "; check they agree."),
                                   [self.m.doc_label(p["doc_id"]) for p in plist]))
        out.extend(self.conflicts())
        order = {"warn": 0, "info": 1}
        return sorted(out, key=lambda f: (order[f.severity], f.kind))

    # ------------------------------------------------------------------ conflicting numbers
    def conflicts(self, min_similarity: float = 0.4, cap: int = 800) -> List[Finding]:
        by_unit: Dict[str, list] = defaultdict(list)
        for f in self.m.facts:
            by_unit[f["unit"]].append(f)
        out: List[Finding] = []
        seen = set()
        for unit, facts in by_unit.items():
            facts = facts[:cap]
            words = [content_words(f["sentence"]) for f in facts]
            for i in range(len(facts)):
                for j in range(i + 1, len(facts)):
                    a, b = facts[i], facts[j]
                    if a["value"] == b["value"] or a["sentence"] == b["sentence"]:
                        continue
                    if len(words[i] & words[j]) < 3 or jaccard(words[i], words[j]) < min_similarity:
                        continue
                    key = tuple(sorted((a["sentence"], b["sentence"])))
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append(Finding("warn", "conflicting_numbers",
                                       f"Possible conflict ({unit}): {a['raw']} vs {b['raw']} for similar statements.",
                                       [f"{self.m.doc_label(a['doc_id'])}: {a['sentence']}", f"{self.m.doc_label(b['doc_id'])}: {b['sentence']}"]))
        return out

    # ------------------------------------------------------------------ impact & criticality
    def impact(self, topic: str, direction: str = "down", depth: int = 3) -> Optional[dict]:
        hits = self.g.find(topic)
        if not hits:
            return None
        nid = hits[0]
        reach = self.g.impact(nid, direction, depth)
        return {"node": self.g.nodes[nid], "direction": direction,
                "affected": [(self.g.nodes[n], d, e) for n, d, e in reach]}

    def critical_nodes(self, top: int = 8) -> List[dict]:
        rows = []
        for nid, n in self.g.nodes.items():
            if n.kind in ("role", "team", "system"):
                reach = self.g.impact(nid, "down", 3)
                if reach:
                    rows.append({"name": n.label, "kind": n.kind, "downstream": len(reach),
                                 "processes": len([1 for r in reach if self.g.nodes[r[0]].kind == "process"])})
        return sorted(rows, key=lambda r: (-r["downstream"], r["name"]))[:top]

    # ------------------------------------------------------------------ "how does X work?"
    def explain(self, topic: str) -> Optional[dict]:
        hits = self.g.find(topic)
        t = norm_key(topic)
        procs = [p for p in self.m.processes if t in norm_key(p["name"]) or t in [norm_key(s) for s in p["systems"]]
                 or (p["owner"] and t in norm_key(p["owner"])) or t in [norm_key(r) for r in p["roles"]]
                 or any(t in norm_key(s["text"]) for s in p["steps"])]
        if not hits and not procs:
            return None
        info: dict = {"topic": topic, "node": None, "outgoing": [], "incoming": [], "processes": procs,
                      "rules": [], "documents": [], "terms": []}
        if hits:
            nid = hits[0]
            info["node"] = self.g.nodes[nid]
            info["outgoing"] = [(e.rel, self.g.nodes[e.dst].label, e.evidence[:1]) for e in self.g.out_edges(nid)]
            info["incoming"] = [(self.g.nodes[e.src].label, e.rel, e.evidence[:1]) for e in self.g.in_edges(nid)]
            info["documents"] = [self.m.doc_label(d) for d in sorted(self.g.nodes[nid].docs)]
        info["rules"] = [r for r in self.m.rules if t in norm_key(r["text"])][:12]
        info["terms"] = [x for x in self.m.terms if t in norm_key(x["term"]) or t == norm_key(x["term"])][:3]
        return info
