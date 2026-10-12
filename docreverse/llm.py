"""Optional LLM layer (Anthropic API). The whole project works without it; it only *adds*:
   - natural-language answers grounded in retrieved passages (`ask`)
   - "deep" extraction that catches processes/relations the rules miss (`ingest --deep`)
Text is redacted first (see redact.py) unless you turn that off."""
from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Optional

from .config import Config
from .models import Document, Extraction, Process, Relation, Rule, Step, Term
from .redact import redact


class LLM:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.client = None
        if os.environ.get("ANTHROPIC_API_KEY"):
            try:
                import anthropic  # type: ignore
                self.client = anthropic.Anthropic()
            except ImportError:
                self.client = None

    @property
    def available(self) -> bool:
        return self.client is not None

    def complete(self, system: str, user: str, max_tokens: int = 1500) -> str:
        if not self.client:
            raise RuntimeError("LLM not available: set ANTHROPIC_API_KEY and `pip install anthropic`.")
        if self.cfg.redact_before_llm:
            user = redact(user)
        resp = self.client.messages.create(model=self.cfg.llm_model, max_tokens=max_tokens, system=system,
                                           messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


ANSWER_SYSTEM = (
    "You explain how a company operates, using ONLY the excerpts and extracted facts provided. "
    "Cite sources inline as [Document title > Section]. If the material is insufficient or contradictory, say so "
    "plainly and say what is missing. Never invent names, numbers or steps."
)

EXTRACT_SYSTEM = (
    "You analyse one section of a company document. Return ONLY JSON with keys: "
    '"processes" (list of {"name","owner","steps":[{"text","actor"}]}), '
    '"relations" (list of {"subject","predicate","object"}; predicate one of approves, reviews, responsible_for, '
    "reports_to, sends_to, uses, depends_on, triggers, creates), "
    '"rules" (list of {"modality","text"}; modality one of obligation, prohibition, recommendation, permission), '
    '"terms" (list of {"term","definition"}). Include only what the text explicitly states.'
)


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0)) if m else {}


def deep_enrich(doc: Document, ex: Extraction, llm: LLM, max_sections: int = 25) -> int:
    """Ask the LLM to extract structure per section and merge it into `ex` (marked source='llm'). Returns items added."""
    added = 0
    known_rel = {(r.subject.lower(), r.predicate, r.object.lower()) for r in ex.relations}
    known_proc = {p.name.lower() for p in ex.processes}
    sections = [s for s in doc.sections if len(s.text) > 300][:max_sections]
    for sec in sections:
        try:
            data = _parse_json(llm.complete(EXTRACT_SYSTEM, f"Document: {doc.title}\nSection: {sec.heading}\n\n{sec.text[:6000]}", 1800))
        except Exception:
            continue
        for p in data.get("processes", []):
            steps = [Step(i + 1, s.get("text", ""), s.get("actor")) for i, s in enumerate(p.get("steps", [])) if s.get("text")]
            if p.get("name") and len(steps) >= 2 and p["name"].lower() not in known_proc:
                ex.processes.append(Process(p["name"], sec.heading, steps, p.get("owner"), "stated" if p.get("owner") else "", source="llm"))
                known_proc.add(p["name"].lower())
                added += 1
        for r in data.get("relations", []):
            key = (str(r.get("subject", "")).lower(), r.get("predicate"), str(r.get("object", "")).lower())
            if all(key) and key not in known_rel:
                ex.relations.append(Relation(r["subject"], "role", r["predicate"], r["object"], "artifact", sec.heading, sec.heading, "llm"))
                known_rel.add(key)
                added += 1
        for r in data.get("rules", []):
            if r.get("text"):
                ex.rules.append(Rule(r.get("modality", "obligation"), r["text"], sec.heading, "llm"))
                added += 1
        for t in data.get("terms", []):
            if t.get("term") and t.get("definition"):
                ex.terms.append(Term(t["term"], t["definition"]))
                added += 1
    return added
