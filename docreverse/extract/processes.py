"""Recover step-by-step processes (who does what, in which system, in what order)."""
from __future__ import annotations

import re
from collections import Counter
from typing import List, Optional, Tuple

from ..models import Block, Document, Process, Relation, Section, Step
from ..structure import parent_index
from ..textutil import shorten, split_sentences
from .entities import Gazetteer, find_spans

HEAD_CUE = re.compile(
    r"procedure|process|workflow|steps?\b|how to|instructions?|onboarding|offboarding|runbook|playbook|escalation|"
    r"checklist|lifecycle|response|reimbursement|approval|provisioning|resolution|recovery|handling", re.I)
HEAD_EXCLUDE = re.compile(r"purpose|scope|responsibilit|definition|glossary|revision|history|references?\b|background|contacts?", re.I)
GENERIC = {"steps", "step", "procedure", "procedures", "process", "instructions", "workflow", "overview", "details",
           "policy", "summary", "checklist"}
SEQ_CUE = re.compile(r"^(first|second|third|then|next|after that|afterwards|finally|lastly|once)\b", re.I)
DECISION = re.compile(r"^(if|when|where|in case|unless)\b|\botherwise\b|\bif not\b", re.I)
OWNER_FIELD = re.compile(r"^(?:process owner|owner|document owner)\s*[:\-–]\s*(.+)$", re.I)
OWNED_BY = re.compile(r"\b(?:owned|maintained|managed) by\s+(?:the\s+)?([A-Z][\w&\- ]{2,40}?)(?:[.,;]|$)")
TRIGGER = re.compile(r"\b(when|upon|whenever|if|in the event|following)\b", re.I)


def _clean_heading(h: str) -> str:
    h = re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", h).strip()
    h = re.sub(r"^(?:procedure|process|workflow)\s*[:\-–]\s*", "", h, flags=re.I)
    return h.strip(" :")


def _is_generic(h: str) -> bool:
    return _clean_heading(h).lower() in GENERIC


def _step_from(n: int, text: str, gaz: Optional[Gazetteer]) -> Step:
    spans = find_spans(text, gaz)
    actor = next((s.name for s in spans if s.kind in ("role", "team")), None)
    systems = sorted({s.name for s in spans if s.kind == "system"})
    first = re.sub(r"^(?:then|next|finally|first|once|also)[,\s]+", "", text, flags=re.I).split(" ")[0].lower().strip(",.:")
    return Step(n, shorten(text, 300), actor, systems, bool(DECISION.search(text)), first)


def _collect_steps(sec: Section, cue: bool, gaz: Optional[Gazetteer]) -> List[Step]:
    items = [b for b in sec.blocks if b.kind == "list_item" and b.level == 0]
    ordered = [b for b in items if b.ordered]
    chosen: List[Block] = ordered if len(ordered) >= 2 else (items if cue else [])
    if chosen:
        steps: List[Step] = []
        # fold nested sub-items into their parent step
        parent_idx = -1
        buckets = {}
        for b in sec.blocks:
            if b.kind == "list_item" and b.level == 0 and b in chosen:
                parent_idx = chosen.index(b)
                buckets[parent_idx] = []
            elif b.kind == "list_item" and b.level > 0 and parent_idx >= 0:
                buckets[parent_idx].append(b.text)
        for i, b in enumerate(chosen):
            text = b.text + (" (" + "; ".join(buckets.get(i, [])) + ")" if buckets.get(i) else "")
            steps.append(_step_from(i + 1, text, gaz))
        return steps
    if cue:
        sents = [s for b in sec.blocks if b.kind == "paragraph" for s in split_sentences(b.text)]
        idx = [i for i, s in enumerate(sents) if SEQ_CUE.match(s)]
        if len(idx) >= 3:
            return [_step_from(n + 1, s, gaz) for n, s in enumerate(sents[idx[0]: idx[-1] + 1])]
    return []


def extract_processes(doc: Document, gaz: Optional[Gazetteer], relations: List[Relation]) -> List[Process]:
    procs: List[Process] = []
    doc_owner = doc.metadata.get("process owner") or doc.metadata.get("owner") or doc.metadata.get("document owner")

    for i, sec in enumerate(doc.sections):
        cue = bool(HEAD_CUE.search(sec.heading))
        if HEAD_EXCLUDE.search(sec.heading) and not cue:
            continue
        steps = _collect_steps(sec, cue, gaz)
        minimum = 2 if cue else 3
        if len(steps) < minimum:
            continue

        name = _clean_heading(sec.heading)
        if _is_generic(sec.heading):
            pi = parent_index(doc.sections, i)
            name = _clean_heading(doc.sections[pi].heading) if pi is not None and not _is_generic(doc.sections[pi].heading) else doc.title
        if not name:
            name = doc.title

        spans_all = [s for b in sec.blocks if b.kind != "code" for s in find_spans(b.text, gaz)]
        systems = sorted({s.name for s in spans_all if s.kind == "system"})
        roles = sorted({s.name for s in spans_all if s.kind in ("role", "team")})

        owner, owner_source = None, ""
        for b in sec.blocks:
            m = OWNER_FIELD.match(b.text)
            if m:
                owner, owner_source = m.group(1).strip().rstrip("."), "stated"
                break
        if not owner:
            for b in sec.blocks:
                m = OWNED_BY.search(b.text)
                if m:
                    owner, owner_source = m.group(1).strip(), "stated"
                    break
        if not owner:
            words = {w.lower() for w in re.findall(r"[A-Za-z]{4,}", name)}
            for r in relations:
                if r.predicate == "responsible_for" and r.subject_kind in ("role", "team") and words & {w.lower() for w in re.findall(r"[A-Za-z]{4,}", r.object)}:
                    owner, owner_source = r.subject, "stated"
                    break
        if not owner and doc_owner:
            owner, owner_source = doc_owner, "stated"
        if not owner:
            actors = Counter(s.actor for s in steps if s.actor)
            if actors:
                top, n = actors.most_common(1)[0]
                if n >= max(2, len([s for s in steps if s.actor]) // 2 + 1):
                    owner, owner_source = top, "inferred"

        trigger = None
        for b in sec.blocks:
            if b.kind == "paragraph":
                for s in split_sentences(b.text):
                    if TRIGGER.search(s) and not SEQ_CUE.match(s):
                        trigger = shorten(s, 200)
                        break
            if trigger:
                break

        procs.append(Process(name, sec.heading, steps, owner, owner_source, trigger, systems, roles))
    return procs
