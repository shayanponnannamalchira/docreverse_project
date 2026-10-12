"""Turn sentences into (subject, predicate, object) triples.

Method: find entity spans in the sentence, look at the text *between* neighbouring spans (the "gap"),
and classify that gap with a small verb lexicon. Passive voice ("X is approved by Y") reverses direction.
Conjunction carry-over handles "Manager logs into Concur and approves the Expense Report".
"""
from __future__ import annotations

import re
from typing import List, Optional, Tuple

from ..models import Relation
from ..textutil import shorten, strip_leading
from .entities import Span

_MODALS = (r"(?:(?:must|shall|will|should|can|may|could|would|need(?:s)? to|has to|have to|is to|are to|also|then|first|"
           r"next|finally|promptly|immediately|always|subsequently|typically|usually|normally|automatically|only|"
           r"directly|manually|electronically)\s+)*")
_PREFIX = rf"^\s*(?:(?:and then|and|then|or|but)\s+)?{_MODALS}"

# --- passive voice: (regex, predicate, reverse?)  reverse => the span AFTER the gap is the subject
_P = r"^\s*(?:is|are|was|were|be|been|being)\s+(?:\w+\s+)?"
PASSIVE = [
    (re.compile(_P + r"(?:approved|authori[sz]ed|signed off)\s+by\b", re.I), "approves", True),
    (re.compile(_P + r"(?:reviewed|verified|validated|checked|audited|inspected)\s+by\b", re.I), "reviews", True),
    (re.compile(_P + r"(?:owned|maintained|managed|handled|administered|overseen)\s+by\b", re.I), "responsible_for", True),
    (re.compile(_P + r"(?:created|opened|raised|filed|generated|issued|prepared|logged|recorded|completed)\s+by\b", re.I), "creates", True),
    (re.compile(_P + r"(?:triggered|initiated|started|caused)\s+by\b", re.I), "triggers", True),
    (re.compile(_P + r"(?:sent|forwarded|submitted|escalated|routed|assigned|delivered|reported|directed)\s+to\b", re.I), "sends_to", False),
    (re.compile(_P + r"(?:stored|recorded|logged|tracked|kept|saved)\s+in\b", re.I), "stored_in", False),
]


def _active(verbs: str) -> "re.Pattern":
    return re.compile(rf"{_PREFIX}(?:{verbs})\b\s*(.*)$", re.I)


# order matters: first match wins
ACTIVE = [
    ("approves", _active(r"approv\w*|sign\w* off(?: on)?|authori[sz]\w*")),
    ("responsible_for", _active(r"(?:is|are)\s+(?:responsible|accountable)\s+for|is in charge of|take(?:s)? ownership of|"
                                r"own(?:s)?|manag(?:es|e|ing)|maintain(?:s|ing)?|oversee(?:s)?|handl(?:es|e|ing)|administer(?:s)?|runs?")),
    ("reviews", _active(r"review\w*|audit\w*|verif\w*|validat\w*|inspect\w*|check\w*")),
    ("reports_to", _active(r"reports?\s+(?:directly\s+)?to|report(?:ing)?\s+to")),
    ("triggers", _active(r"trigger\w*|initiat\w*|kick\w* off|start\w*|cause\w*|result\w* in|lead\w* to")),
    ("depends_on", _active(r"depend\w*\s+(?:on|upon)|rel(?:y|ies|ying)\s+on|require\w*|integrat\w*\s+with|sync\w*\s+(?:with|to)|feed\w*|connect\w*\s+to")),
    ("uses", _active(r"use(?:s|d)?|using|log(?:s|ged)?\s+(?:in|into|on)|access(?:es|ed)?|enter(?:s|ed)?|record(?:s|ed)?|"
                     r"stor(?:es|e|ed)|track(?:s|ed)?|updat(?:es|e|ed)|upload(?:s|ed)?|post(?:s|ed)?")),
    ("sends_to", _active(r"send(?:s)?|sent|forward\w*|submit\w*|escalat\w*|rout(?:es|e|ed)|assign\w*|notif(?:ies|y|ied)|"
                         r"email\w*|inform\w*|alert\w*|contact\w*|page[sd]?|hand\w*\s+over|deliver\w*")),
    ("creates", _active(r"creat\w*|open(?:s|ed)?|rais(?:es|e|ed)|fil(?:es|e|ed)|generat\w*|produc\w*|issu(?:es|e|ed)|"
                        r"prepar\w*|complet\w*|fill\w*\s+out|draft\w*|writ\w*|log(?:s|ged)?")),
]
LOCATIVE_END = re.compile(r"\b(?:in|into|on|via|using|through|within)\s*$", re.I)
CONJ = re.compile(r"^\s*(?:and then|and|then|or|but)\b", re.I)
FREE_TEXT_PREDICATES = {"approves", "responsible_for", "reviews", "triggers", "creates", "depends_on"}
_OBJ_CUT = re.compile(r"[;]|,(?!\d)|\.(?!\d)|\b(?:when|if|before|after|within|once|so that|because|unless|until|and then|and|or|which|that)\b", re.I)


def classify_gap(gap: str, a_kind: str, b_kind: str) -> Optional[Tuple[str, bool, bool]]:
    """Return (predicate, reverse, conjunction) for the text between two entity spans, or None."""
    if len(gap) > 90 or "," in gap or ";" in gap or ":" in gap:
        return None
    if len(gap.split()) > 7:
        return None
    conj = bool(CONJ.match(gap))
    for rx, pred, rev in PASSIVE:
        if rx.match(re.sub(_PREFIX, "", gap, count=1, flags=re.I) if conj else gap):
            return pred, rev, conj
    if b_kind == "system" and a_kind != "system" and LOCATIVE_END.search(gap):
        return "uses", False, conj
    for pred, rx in ACTIVE:
        if rx.match(gap):
            if pred == "uses" and b_kind != "system":
                continue
            if pred == "sends_to" and b_kind == "artifact" and not re.search(r"\bto\s*$", gap, re.I):
                pred = "submits"
            return pred, False, conj
    if b_kind == "system" and LOCATIVE_END.search(gap) and not CONJ.match(gap):
        return "uses", False, conj
    return None


def _free_object(rest: str) -> Optional[Tuple[str, str, str]]:
    """Match a verb at the start of `rest`; return (predicate, object_text, kind)."""
    for pred, rx in ACTIVE:
        if pred not in FREE_TEXT_PREDICATES:
            continue
        m = rx.match(rest)
        if m:
            obj = _OBJ_CUT.split(m.group(1), maxsplit=1)[0].strip()
            obj = strip_leading(obj)
            words = obj.split()
            if not words or len(obj) < 3:
                return None
            return pred, " ".join(words[:7]), "artifact"
    return None


def extract_relations(sentence: str, spans: List[Span], section: str) -> List[Relation]:
    rels: List[Relation] = []
    seen = set()
    evidence = shorten(sentence, 240)

    def emit(subj: Span, pred: str, obj_name: str, obj_kind: str) -> None:
        if subj.name.lower() == obj_name.lower():
            return
        key = (subj.name.lower(), pred, obj_name.lower())
        if key in seen:
            return
        seen.add(key)
        rels.append(Relation(subj.name, subj.kind, pred, obj_name, obj_kind, section, evidence))

    subject_idx = set()
    last_subject: Optional[Span] = None
    prev_pair: Optional[Tuple[int, str, Span]] = None   # (index of pair start, predicate, subject)

    for i in range(len(spans) - 1):
        a, b = spans[i], spans[i + 1]
        gap = sentence[a.end:b.start]
        cls = classify_gap(gap, a.kind, b.kind)
        if cls is None:
            # "X submits Y to Z": the (Y, Z) gap is just "to"
            if gap.strip().lower() in ("to", "into") and prev_pair and prev_pair[0] == i - 1 and prev_pair[1] in ("sends_to", "creates", "submits"):
                emit(prev_pair[2], "sends_to", b.name, b.kind)
            continue
        pred, reverse, conj = cls
        if reverse:
            subj, obj = b, a
        else:
            subj, obj = (last_subject if conj and last_subject else a), b
            if pred == "uses" and subj.kind == "artifact":
                # "Employee creates the Expense Report in Concur": the *person* uses Concur, not the report
                actor = next((spans[j] for j in range(i - 1, -1, -1) if spans[j].kind in ("role", "team")), None)
                if actor:
                    subj = actor
                else:
                    pred = "stored_in"
        emit(subj, pred, obj.name, obj.kind)
        subject_idx.add(i + 1 if reverse else i)
        last_subject = subj
        prev_pair = (i, pred, subj)

    # free-text objects: "Finance Manager approves expenses over $5,000."
    for i, s in enumerate(spans):
        if i in subject_idx or s.kind not in ("role", "team", "system"):
            continue
        rest = sentence[s.end:]
        hit = _free_object(rest)
        if not hit:
            continue
        pred, obj_text, kind = hit
        nxt = spans[i + 1] if i + 1 < len(spans) else None
        if nxt is not None and nxt.start - s.end < len(rest) and obj_text.lower() in sentence[nxt.start:].lower():
            continue
        if nxt is not None and sentence[s.end:nxt.start].count(" ") <= len(obj_text.split()) + 4 and pred in ("sends_to",):
            continue
        emit(s, pred, obj_text, kind)
    return rels
