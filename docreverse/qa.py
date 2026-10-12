"""Question answering: retrieve passages (BM25) + graph facts, then answer with an LLM or extractively."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from .analyze import Analyzer
from .llm import ANSWER_SYSTEM, LLM
from .model import Model
from .textutil import content_words, norm_key, shorten

VERB_HINTS = {"approv": "approves", "review": "reviews", "own": "responsible_for", "responsib": "responsible_for",
              "escalat": "sends_to", "notif": "sends_to", "send": "sends_to", "report": "reports_to", "use": "uses",
              "trigger": "triggers", "depend": "depends_on", "creat": "creates", "submit": "submits"}


@dataclass
class Answer:
    text: str
    mode: str                                   # llm | extractive
    sources: List[str] = field(default_factory=list)
    facts: List[str] = field(default_factory=list)


def _graph_facts(model: Model, question: str, limit: int = 14) -> List[str]:
    q = norm_key(question)
    facts: List[str] = []
    seen = set()
    for nid, n in model.graph.nodes.items():
        if n.kind in ("document",) or norm_key(n.label) not in q or len(n.label) < 3:
            continue
        for e in model.graph.out_edges(nid):
            line = f"{n.label} {e.rel.replace('_', ' ')} {model.graph.nodes[e.dst].label}"
            if line not in seen:
                seen.add(line)
                facts.append(line)
        for e in model.graph.in_edges(nid):
            line = f"{model.graph.nodes[e.src].label} {e.rel.replace('_', ' ')} {n.label}"
            if line not in seen:
                seen.add(line)
                facts.append(line)
    wanted = {pred for stem, pred in VERB_HINTS.items() if stem in q}
    if wanted:
        qwords = content_words(question)
        scored = []
        for e in model.graph.edges.values():
            if e.rel in wanted:
                text = f"{model.graph.nodes[e.src].label} {model.graph.nodes[e.dst].label} {' '.join(e.evidence)}"
                overlap = len(qwords & content_words(text))
                if overlap:
                    scored.append((overlap, f"{model.graph.nodes[e.src].label} {e.rel.replace('_', ' ')} {model.graph.nodes[e.dst].label}"))
        for _, line in sorted(scored, key=lambda t: -t[0])[:6]:
            if line not in seen:
                seen.add(line)
                facts.append(line)
    for p in model.processes:
        if norm_key(p["name"]) in q:
            facts.append(f"Process '{p['name']}': owner={p['owner'] or 'unknown'}; systems={', '.join(p['systems']) or 'none found'}; "
                         f"{len(p['steps'])} steps")
    return facts[:limit]


def ask(model: Model, question: str, llm: LLM | None = None, k: int = 6) -> Answer:
    passages = model.store.search(question, k)
    facts = _graph_facts(model, question)
    sources = [f"{p['title']} > {p['section']}" for p in passages]
    if not passages and not facts:
        return Answer("I could not find anything in the ingested documents that relates to that question.", "extractive")

    if llm is not None and llm.available:
        excerpts = "\n\n".join(f"[{p['title']} > {p['section']}]\n{p['text']}" for p in passages)
        user = f"EXTRACTED FACTS:\n" + "\n".join(f"- {f}" for f in facts) + f"\n\nEXCERPTS:\n{excerpts}\n\nQUESTION: {question}"
        return Answer(llm.complete(ANSWER_SYSTEM, user, 1200), "llm", sources, facts)

    lines = ["(No LLM configured - showing the most relevant passages. Set ANTHROPIC_API_KEY for a written answer.)", ""]
    for p in passages[:4]:
        lines.append(f"* {p['title']} > {p['section']}\n  {shorten(p['text'], 420)}")
    return Answer("\n".join(lines), "extractive", sources, facts)
