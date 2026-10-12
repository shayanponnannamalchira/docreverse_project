"""A small knowledge graph (no external dependency) with impact analysis and diagram export."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from .textutil import norm_key, shorten

# How a predicate propagates impact:  FLOW  = "if src fails, dst is affected"
#                                     DEP   = "if dst fails, src is affected"
FLOW = {"sends_to", "triggers", "creates", "submits", "approves", "reviews", "responsible_for", "involved_in", "owns"}
DEP = {"uses", "depends_on", "reports_to", "stored_in", "references"}


@dataclass
class Node:
    id: str
    kind: str
    labels: Counter = field(default_factory=Counter)
    docs: Set[int] = field(default_factory=set)
    attrs: Dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return self.labels.most_common(1)[0][0] if self.labels else self.id


@dataclass
class Edge:
    src: str
    dst: str
    rel: str
    weight: int = 0
    evidence: List[str] = field(default_factory=list)
    docs: Set[int] = field(default_factory=set)


def node_id(kind: str, name: str) -> str:
    return f"{kind}:{norm_key(name)}"


class KnowledgeGraph:
    def __init__(self) -> None:
        self.nodes: Dict[str, Node] = {}
        self.edges: Dict[Tuple[str, str, str], Edge] = {}

    # ---------------------------------------------------------------- building
    def add_node(self, kind: str, label: str, doc: Optional[int] = None, **attrs) -> str:
        nid = node_id(kind, label)
        n = self.nodes.setdefault(nid, Node(nid, kind))
        n.labels[label.strip()] += 1
        if doc is not None:
            n.docs.add(doc)
        n.attrs.update(attrs)
        return nid

    def add_edge(self, src: str, dst: str, rel: str, evidence: str = "", doc: Optional[int] = None) -> None:
        if src == dst:
            return
        e = self.edges.setdefault((src, dst, rel), Edge(src, dst, rel))
        e.weight += 1
        if evidence and len(e.evidence) < 3 and evidence not in e.evidence:
            e.evidence.append(evidence)
        if doc is not None:
            e.docs.add(doc)

    # ---------------------------------------------------------------- queries
    def out_edges(self, nid: str) -> List[Edge]:
        return [e for (s, _, _), e in self.edges.items() if s == nid]

    def in_edges(self, nid: str) -> List[Edge]:
        return [e for (_, d, _), e in self.edges.items() if d == nid]

    def degree(self, nid: str) -> int:
        return sum(e.weight for (s, d, _), e in self.edges.items() if nid in (s, d))

    def find(self, query: str, kinds: Optional[Iterable[str]] = None) -> List[str]:
        q = norm_key(query)
        qtokens = set(re.findall(r"\w+", q))
        ranked = []
        for nid, n in self.nodes.items():
            if kinds and n.kind not in kinds:
                continue
            labels = [norm_key(l) for l in n.labels]
            if q in labels:
                rank = 0
            elif any(l.startswith(q) for l in labels):
                rank = 1
            elif any(q in l for l in labels):
                rank = 2
            elif qtokens and any(qtokens <= set(re.findall(r"\w+", l)) for l in labels):
                rank = 3
            else:
                continue
            ranked.append((rank, -self.degree(nid), nid))
        return [nid for _, _, nid in sorted(ranked)]

    def _impact_adjacency(self) -> Dict[str, List[Tuple[str, Edge]]]:
        adj: Dict[str, List[Tuple[str, Edge]]] = defaultdict(list)
        for e in self.edges.values():
            if e.rel in FLOW:
                adj[e.src].append((e.dst, e))
            elif e.rel in DEP:
                adj[e.dst].append((e.src, e))
        return adj

    def impact(self, nid: str, direction: str = "down", depth: int = 3) -> List[Tuple[str, int, Edge]]:
        """direction='down': what is affected if `nid` changes/fails. 'up': what `nid` depends on."""
        adj = self._impact_adjacency()
        if direction == "up":
            rev: Dict[str, List[Tuple[str, Edge]]] = defaultdict(list)
            for src, lst in adj.items():
                for dst, e in lst:
                    rev[dst].append((src, e))
            adj = rev
        seen = {nid}
        out: List[Tuple[str, int, Edge]] = []
        q = deque([(nid, 0)])
        while q:
            cur, d = q.popleft()
            if d >= depth:
                continue
            if cur != nid and self.nodes[cur].kind in ("role", "team"):
                continue          # people/teams are affected, but we don't chain through them
            for nxt, e in adj.get(cur, []):
                if nxt not in seen:
                    seen.add(nxt)
                    out.append((nxt, d + 1, e))
                    q.append((nxt, d + 1))
        return out

    def shortest_path(self, a: str, b: str) -> Optional[List[str]]:
        nbrs: Dict[str, Set[str]] = defaultdict(set)
        for (s, d, _) in self.edges:
            nbrs[s].add(d)
            nbrs[d].add(s)
        prev = {a: None}
        q = deque([a])
        while q:
            cur = q.popleft()
            if cur == b:
                path = []
                while cur is not None:
                    path.append(cur)
                    cur = prev[cur]
                return path[::-1]
            for n in nbrs[cur]:
                if n not in prev:
                    prev[n] = cur
                    q.append(n)
        return None

    def top_nodes(self, n: int = 10, kinds: Optional[Iterable[str]] = None) -> List[Tuple[Node, int]]:
        scored = [(node, self.degree(nid)) for nid, node in self.nodes.items() if not kinds or node.kind in kinds]
        return sorted(scored, key=lambda t: -t[1])[:n]

    # ---------------------------------------------------------------- export
    def to_json(self) -> str:
        return json.dumps({
            "nodes": [{"id": n.id, "label": n.label, "kind": n.kind, "docs": sorted(n.docs), **n.attrs} for n in self.nodes.values()],
            "edges": [{"source": e.src, "target": e.dst, "relation": e.rel, "weight": e.weight, "evidence": e.evidence}
                      for e in self.edges.values()],
        }, indent=2)

    def _subgraph(self, max_nodes: int, kinds: Optional[Set[str]]) -> Set[str]:
        keep = [n.id for n, _ in self.top_nodes(max_nodes * 3, kinds) if self.degree(n.id) > 0][:max_nodes]
        return set(keep)

    def to_mermaid(self, max_nodes: int = 35, kinds: Optional[Set[str]] = None) -> str:
        keep = self._subgraph(max_nodes, kinds)
        ids = {nid: f"n{i}" for i, nid in enumerate(sorted(keep))}
        shapes = {"role": ("([", "])"), "team": ("([", "])"), "system": ("[[", "]]"), "process": ("{{", "}}"),
                  "artifact": ("[", "]"), "document": ("[(", ")]")}
        lines = ["flowchart LR"]
        for nid, mid in ids.items():
            n = self.nodes[nid]
            l, r = shapes.get(n.kind, ("[", "]"))
            lines.append(f'  {mid}{l}"{shorten(n.label, 38).replace(chr(34), chr(39))}"{r}')
        for e in self.edges.values():
            if e.src in ids and e.dst in ids:
                lines.append(f"  {ids[e.src]} -->|{e.rel}| {ids[e.dst]}")
        return "\n".join(lines)

    def to_dot(self, max_nodes: int = 60) -> str:
        keep = self._subgraph(max_nodes, None)
        ids = {nid: f"n{i}" for i, nid in enumerate(sorted(keep))}
        lines = ["digraph G {", "  rankdir=LR;", "  node [fontname=Helvetica];"]
        for nid, mid in ids.items():
            n = self.nodes[nid]
            lines.append(f'  {mid} [label="{shorten(n.label, 40)}\\n({n.kind})"];')
        for e in self.edges.values():
            if e.src in ids and e.dst in ids:
                lines.append(f'  {ids[e.src]} -> {ids[e.dst]} [label="{e.rel}"];')
        lines.append("}")
        return "\n".join(lines)
