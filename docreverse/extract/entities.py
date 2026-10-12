"""Find roles, teams, systems and artifacts (forms, reports...) inside a sentence.

Entirely rule-based: capitalised phrases ending in a role/team head noun, lowercase phrases after a
determiner ("the line manager"), tool names after cue words ("using Concur"), plus an optional
user-supplied gazetteer for names the heuristics cannot guess.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from ..textutil import strip_leading


@dataclass
class Span:
    start: int
    end: int
    name: str
    kind: str     # role | team | system | artifact


@dataclass
class Gazetteer:
    """Optional company vocabulary: {"systems": [...], "roles": [...], "teams": [...], "aliases": {"SAP ERP": "SAP"}}"""
    systems: Set[str] = field(default_factory=set)
    roles: Set[str] = field(default_factory=set)
    teams: Set[str] = field(default_factory=set)
    aliases: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Optional[str]) -> "Gazetteer":
        if not path:
            return cls()
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(set(data.get("systems", [])), set(data.get("roles", [])), set(data.get("teams", [])),
                   dict(data.get("aliases", {})))

    def canonical(self, name: str) -> str:
        return self.aliases.get(name) or self.aliases.get(name.lower()) or name


_ROLE_HEADS = (
    "Manager|Director|Analyst|Engineer|Officer|Coordinator|Administrator|Supervisor|Lead|Specialist|Controller|"
    "Executive|Assistant|President|Owner|Approver|Reviewer|Auditor|Recruiter|Accountant|Architect|Developer|"
    "Technician|Representative|Advisor|Counsel|Agent|Commander|Employee|Customer|Vendor|Supplier|Requester|"
    "Requestor|Applicant|Contractor|Candidate|Staff"
)
_TEAM_HEADS = "Team|Department|Committee|Board|Desk|Group|Office|Division|Council|Unit|Function"
_ARTIFACT_HEADS = (
    "Form|Report|Request|Ticket|Invoice|Order|Receipt|Notice|Checklist|Template|Agreement|Contract|Statement|"
    "Record|Log|Memo|Claim|Voucher|Certificate|Proposal|Plan|Policy|Procedure|Runbook|Standard|Guideline|"
    "Handbook|Manual|Playbook|Charter|Scorecard|Questionnaire|Assessment"
)
_CAP = r"(?:[A-Z][A-Za-z&]*[ \-]){0,3}"
_CAP1 = r"(?:[A-Z][A-Za-z&]*[ \-]){1,3}"

ROLE_RE = re.compile(rf"\b({_CAP}(?:{_ROLE_HEADS})s?)\b")
SPECIAL_ROLE_RE = re.compile(r"\b(VP(?: of [A-Z][A-Za-z]+)?|Head of [A-Z][A-Za-z]+|Chief [A-Z][a-z]+ Officer)\b")
TEAM_RE = re.compile(rf"\b({_CAP}(?:{_TEAM_HEADS})s?)\b")
DEPT_RE = re.compile(
    r"\b(HR|IT|QA|PMO|SOC|NOC|R&D|Finance|Legal|Procurement|Payroll|Compliance|Facilities|Engineering|"
    r"Marketing|Sales|Operations)\b(?![ ]+[A-Z][a-z])")
ARTIFACT_RE = re.compile(rf"\b({_CAP1}(?:{_ARTIFACT_HEADS})s?)\b")

_LOW_ROLE = ("manager|director|analyst|engineer|officer|coordinator|administrator|supervisor|lead|specialist|controller|"
             "approver|reviewer|auditor|recruiter|accountant|architect|developer|technician|representative|advisor|"
             "employee|customer|vendor|supplier|requester|requestor|applicant|contractor|candidate|commander")
_LOW_TEAM = "team|department|committee|board|desk|group|division|council"
_LOW_ARTIFACT = ("form|report|request|ticket|invoice|order|receipt|notice|checklist|template|agreement|contract|"
                 "statement|memo|claim|voucher|certificate|proposal|scorecard|questionnaire")
LOW_ROLE_RE = re.compile(rf"\b(?:the|a|an|your|their|each|every|any|our|to|by)\s+((?:[a-z]+\s){{0,2}}(?:{_LOW_ROLE})s?)\b")
LOW_TEAM_RE = re.compile(rf"\b(?:the|our|your|to|by|with|from|a|an)\s+((?:[a-z]+\s){{1,2}}(?:{_LOW_TEAM}))\b")
LOW_ARTIFACT_RE = re.compile(
    rf"\b(?:the|a|an|your|their|each|every|any|this|that|completed|signed)\s+((?:[a-z]+\s){{1,2}}(?:{_LOW_ARTIFACT}))s?\b")
_NOISE_PREFIX = {"submitted", "the", "a", "an", "our", "your", "their", "to", "by", "following", "attached", "relevant", "approved", "same", "original", "new", "other", "applicable",
                 "responsible", "assigned", "designated", "such", "above", "below", "required", "necessary",
                 "completed", "signed", "relevant", "this", "that", "next", "previous", "first", "second", "final",
                 "initial", "separate", "single", "its", "his", "her", "own", "only", "whole", "entire", "main"}

SYS_NOUN_RE = re.compile(
    r"\b((?:[A-Z][A-Za-z0-9&.]*\s){0,2}[A-Z][A-Za-z0-9&.]*)\s+"
    r"(?:system|platform|tool|database|portal|application|software|module|dashboard|API|server|repository|"
    r"tracker|workspace|app|service)\b")
_CUES = (r"(?:using|use|uses|via|through|in|into|on|within|inside|open|opens|log(?:s|ged)? (?:in|into|on)|enter|enters|entered|"
         r"record|records|recorded|store|stores|stored|update|updates|updated|sync(?:s|ed)? (?:to|with)|"
         r"integrat(?:es|ed)? with|access|accesses|accessed)")
CUE_TOKEN_RE = re.compile(rf"\b{_CUES}\s+(?:the\s+)?([A-Z]{{2,}}[A-Za-z0-9]*|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+)\b")
CAP_CUE_RE = re.compile(
    r"\b(?:using|via|into|in|on|through|log(?:s|ged)? (?:in|into|on)|access(?:es)?)\s+(?:the\s+)?([A-Z][a-z0-9]{2,})\b(?!\s+[A-Z])")

TOKEN_STOP = set(
    """PDF USD EUR GBP CSV FAQ AM PM UTC OK ID US UK EU SLA KPI FYI CEO CFO CTO COO SOP NA TBD ASAP PO HTML URL JSON
    XML SMS RACI MFA NDA ROI OKR""".split())
CAP_STOP = set(
    """January February March April May June July August September October November December Monday Tuesday Wednesday
    Thursday Friday Saturday Sunday The This That Email Phone Mail Paper Hand Writing Person Default Writing
    Finance Legal Procurement Payroll Compliance Facilities Engineering Marketing Sales Operations Security
    Section Appendix Chapter Phase Step Table Figure Europe Asia America Africa Annex Schedule Exhibit Article
    Page Part Level Tier Stage Group Team Office Board Policy Procedure Project Program Process Case Cases
    Writing Order Line Total Draft Full Part""".split())

_PRIORITY = {"role": 0, "team": 1, "artifact": 2, "system": 3}


def _title(name: str) -> str:
    return " ".join(w.capitalize() if w.islower() else w for w in name.split())


def _clean_low(name: str, head_alone_ok: bool) -> str:
    words = [w for w in name.split() if w not in _NOISE_PREFIX]
    if len(words) == 1 and not head_alone_ok:
        return ""
    return _title(" ".join(words))


def _depluralize(name: str) -> str:
    if name.endswith("ies"):
        return name
    if name.endswith("s") and not name.endswith("ss"):
        return name[:-1]
    return name


def find_spans(text: str, gaz: Optional[Gazetteer] = None) -> List[Span]:
    gaz = gaz or Gazetteer()
    cands: List[Span] = []

    def add(m: "re.Match", group: int, kind: str, name: str) -> None:
        name = " ".join(name.split())
        if name:
            cands.append(Span(m.start(group), m.end(group), gaz.canonical(name), kind))

    for m in ROLE_RE.finditer(text):
        name = strip_leading(m.group(1))
        if name:
            add(m, 1, "role", _depluralize(name))
    for m in SPECIAL_ROLE_RE.finditer(text):
        add(m, 1, "role", m.group(1))
    for m in TEAM_RE.finditer(text):
        name = strip_leading(m.group(1))
        if len(name.split()) >= 2 or name.split()[-1:] and name.lower() not in {"team", "group", "board", "office", "unit"}:
            if name:
                add(m, 1, "team", _depluralize(name))
    for m in DEPT_RE.finditer(text):
        add(m, 1, "team", m.group(1))
    for m in ARTIFACT_RE.finditer(text):
        name = strip_leading(m.group(1))
        if len(name.split()) >= 2:
            add(m, 1, "artifact", _depluralize(name))
    for m in LOW_ROLE_RE.finditer(text):
        name = _clean_low(m.group(1), head_alone_ok=True)
        if name:
            add(m, 1, "role", _depluralize(name))
    for m in LOW_TEAM_RE.finditer(text):
        name = _clean_low(m.group(1), head_alone_ok=False)
        if name:
            add(m, 1, "team", name)
    for m in LOW_ARTIFACT_RE.finditer(text):
        name = _clean_low(m.group(1), head_alone_ok=False)
        if name:
            add(m, 1, "artifact", name)
    for m in SYS_NOUN_RE.finditer(text):
        name = strip_leading(m.group(1))
        if name and name.split()[-1] not in CAP_STOP and name not in TOKEN_STOP:
            add(m, 1, "system", name)
    for m in CUE_TOKEN_RE.finditer(text):
        tok = m.group(1)
        if tok not in TOKEN_STOP and not re.fullmatch(r"P\d|SEV\d?|HR|IT|QA", tok):
            add(m, 1, "system", tok)
    for m in CAP_CUE_RE.finditer(text):
        if m.group(1) not in CAP_STOP and m.group(1) not in TOKEN_STOP:
            add(m, 1, "system", m.group(1))

    for name in gaz.systems:
        for m in re.finditer(rf"\b{re.escape(name)}\b", text):
            cands.append(Span(m.start(), m.end(), gaz.canonical(name), "system"))
    for names, kind in ((gaz.roles, "role"), (gaz.teams, "team")):
        for name in names:
            for m in re.finditer(rf"\b{re.escape(name)}\b", text, re.I):
                cands.append(Span(m.start(), m.end(), gaz.canonical(_title(name)), kind))

    # resolve overlaps: earliest start wins, then longest, then kind priority
    cands.sort(key=lambda s: (s.start, -(s.end - s.start), _PRIORITY[s.kind]))
    out: List[Span] = []
    last_end = -1
    for s in cands:
        if s.start >= last_end:
            out.append(s)
            last_end = s.end
    return out
