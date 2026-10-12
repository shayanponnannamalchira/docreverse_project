"""Numbers with units (deadlines, limits, thresholds, prices), cross-references and glossary terms."""
from __future__ import annotations

import re
from typing import List, Optional

from ..models import Document, Fact, Reference, Term
from ..textutil import shorten

_WORDNUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
            "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "sixty": 60, "ninety": 90}
_NUM = r"\d+(?:\.\d+)?|" + "|".join(_WORDNUM)

CURRENCY_RE = re.compile(r"(?P<cur>[$€£])\s?(?P<num>\d[\d,]*(?:\.\d+)?)(?:\s?(?P<mult>[kKmM])\b)?")
DURATION_RE = re.compile(
    rf"\b(?P<num>{_NUM})[\s-]?(?P<unit>business days?|working days?|calendar days?|minutes?|mins?|hours?|hrs?|days?|weeks?|months?|years?)\b",
    re.I)
PERCENT_RE = re.compile(r"(?P<num>\d+(?:\.\d+)?)\s?(?P<unit>%|percent)", re.I)
_SYM = {"$": "USD", "€": "EUR", "£": "GBP"}


def _to_float(token: str) -> float:
    t = token.lower()
    return float(_WORDNUM[t]) if t in _WORDNUM else float(t.replace(",", ""))


def _unit(u: str) -> str:
    u = u.lower().rstrip("s")
    if u.startswith(("business", "working")):
        return "business_day"
    if u.startswith("calendar"):
        return "day"
    return {"min": "minute", "hr": "hour", "percent": "%"}.get(u, u)


def extract_facts(sentence: str, section: str) -> List[Fact]:
    out: List[Fact] = []
    s = shorten(sentence, 260)
    for m in CURRENCY_RE.finditer(sentence):
        v = _to_float(m.group("num")) * {"k": 1e3, "m": 1e6}.get((m.group("mult") or "").lower(), 1)
        out.append(Fact(v, _SYM[m.group("cur")], m.group(0), s, section))
    for m in DURATION_RE.finditer(sentence):
        out.append(Fact(_to_float(m.group("num")), _unit(m.group("unit")), m.group(0), s, section))
    for m in PERCENT_RE.finditer(sentence):
        out.append(Fact(_to_float(m.group("num")), "%", m.group(0), s, section))
    return out


# ------------------------------------------------------------------ cross references
CODE_REF_RE = re.compile(r"\b([A-Z]{2,6}-\d{2,5})\b")
NAMED_REF_RE = re.compile(
    r"(?:see|refer to|per|in accordance with|as described in|defined in|according to|consult|outlined in|under)\s+"
    r"(?:the\s+)?((?:[A-Z][\w&\-]*\s+){0,5}(?:Policy|Procedure|Runbook|Standard|Guideline|Guidelines|Agreement|Handbook|Manual|Playbook|Charter|SOP|Plan))\b")


def extract_references(sentence: str, doc: Document) -> List[Reference]:
    out: List[Reference] = []
    for m in CODE_REF_RE.finditer(sentence):
        if m.group(1) != doc.doc_code:
            out.append(Reference(m.group(1), "code", shorten(sentence, 200)))
    for m in NAMED_REF_RE.finditer(sentence):
        out.append(Reference(" ".join(m.group(1).split()), "named", shorten(sentence, 200)))
    return out


# ------------------------------------------------------------------ glossary
_SMALL = {"of", "and", "the", "for", "to", "in", "on"}
ACRONYM_RE = re.compile(r"((?:[A-Za-z][\w&\-]*\s){1,7})\(([A-Z][A-Z0-9]{1,8})s?\)")
MEANS_RE = re.compile(r"\"?\b([A-Z][\w\- ]{1,40}?)\"?\s+(?:means|refers to|is defined as)\s+([^.]{10,200})\.")
GLOSSARY_HEAD = re.compile(r"glossar|definition|terminolog|abbreviation|acronym", re.I)
TERM_LINE_RE = re.compile(r"^([^:–—\-]{2,40}?)\s*[:–—-]\s+(.{8,})$")


def _acronym_def(phrase: str, acro: str) -> Optional[str]:
    words = phrase.split()
    for k in range(len(acro), min(len(acro) + 3, len(words)) + 1):
        cand = words[-k:]
        initials = "".join(w[0].upper() for w in cand if w.lower() not in _SMALL)
        if initials == acro:
            return " ".join(cand)
    return None


def extract_terms(doc: Document) -> List[Term]:
    terms: List[Term] = []
    seen = set()

    def add(term: str, definition: str) -> None:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            terms.append(Term(term.strip(), shorten(definition.strip(), 200)))

    for sec in doc.sections:
        in_glossary = bool(GLOSSARY_HEAD.search(sec.heading))
        for b in sec.blocks:
            if in_glossary and b.kind in ("list_item", "paragraph", "table_row"):
                m = TERM_LINE_RE.match(b.text)
                if m:
                    add(m.group(1), m.group(2))
            if b.kind in ("paragraph", "list_item", "table_row"):
                for m in ACRONYM_RE.finditer(b.text):
                    d = _acronym_def(m.group(1), m.group(2))
                    if d:
                        add(m.group(2), d)
                for m in MEANS_RE.finditer(b.text):
                    add(m.group(1), m.group(2))
    return terms
