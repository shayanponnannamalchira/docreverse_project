"""Render the whole analysis as one Markdown report (with Mermaid diagrams)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from .analyze import Analyzer
from .model import Model
from .textutil import shorten

PRED_TEXT = {"responsible_for": "owns / is responsible for", "approves": "approves", "reviews": "reviews/checks",
             "creates": "creates", "submits": "submits", "sends_to": "sends / escalates to", "triggers": "triggers"}


def _esc(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def process_mermaid(p: dict) -> str:
    lines = ["flowchart TD"]
    prev: Optional[str] = None
    for s in p["steps"]:
        nid = f"S{s['n']}"
        label = shorten(f"{s['n']}. {s['text']}", 80).replace('"', "'")
        if s.get("actor"):
            label += f" ({s['actor']})"
        lines.append(f'  {nid}{{"{label}"}}' if s.get("is_decision") else f'  {nid}["{label}"]')
        if prev:
            lines.append(f"  {prev} --> {nid}")
        prev = nid
    return "\n".join(lines)


def build_report(model: Model, analyzer: Optional[Analyzer] = None, today: Optional[datetime] = None) -> str:
    a = analyzer or Analyzer(model)
    ov = a.overview()
    out: List[str] = ["# How the organisation works - reverse-engineered from documents", "",
                      f"_Generated {datetime.now():%Y-%m-%d %H:%M} by DocReverse. Everything below was extracted automatically; "
                      "treat it as a map to verify, not as ground truth._", ""]

    out += ["## 1. Corpus overview", "",
            f"- **{ov['documents']} documents**, {ov['sections']} sections ({', '.join(f'{v} {k}' for k, v in ov['by_type'].items())})",
            f"- **{ov['processes']} processes**, {ov['relations']} relations, {ov['rules']} rules, {ov['glossary_terms']} glossary terms",
            f"- Knowledge graph: {sum(ov['graph_nodes'].values())} nodes ({', '.join(f'{v} {k}' for k, v in ov['graph_nodes'].items())}), {ov['graph_edges']} edges", ""]

    out += ["## 2. Document inventory", "", "| Code | Title | Type | Sections |", "|---|---|---|---|"]
    for d in sorted(model.docs.values(), key=lambda d: d["title"]):
        out.append(f"| {d['doc_code'] or ''} | {_esc(d['title'])} | {d['doc_type']} | {d['n_sections']} |")
    out.append("")

    out += ["## 3. Process catalogue", ""]
    if not model.processes:
        out += ["_No step-by-step processes were detected._", ""]
    for p in sorted(model.processes, key=lambda p: p["name"].lower()):
        owner = f"{p['owner']} ({p['owner_source']})" if p["owner"] else "**unknown**"
        out += [f"### {p['name']}", "",
                f"- Source: {model.doc_label(p['doc_id'])} > {p['section']}",
                f"- Owner: {owner}",
                f"- Systems: {', '.join(p['systems']) or '-'}",
                f"- Roles involved: {', '.join(p['roles']) or '-'}"]
        if p["trigger"]:
            out.append(f"- Trigger: {p['trigger']}")
        out += ["", "```mermaid", process_mermaid(p), "```", ""]
        for s in p["steps"]:
            tags = (f" - *{s['actor']}*" if s.get("actor") else "") + (f" [{', '.join(s['systems'])}]" if s.get("systems") else "")
            out.append(f"{s['n']}. {'**(decision)** ' if s.get('is_decision') else ''}{s['text']}{tags}")
        out.append("")

    out += ["## 4. Who is responsible for what", ""]
    table = a.ownership()
    if table:
        out += ["| Actor | Relationship | Object(s) |", "|---|---|---|"]
        for actor in sorted(table):
            for pred, objs in table[actor].items():
                out.append(f"| {_esc(actor)} | {PRED_TEXT.get(pred, pred)} | {_esc('; '.join(objs[:8]))} |")
    else:
        out.append("_No ownership relations detected._")
    out.append("")

    out += ["## 5. Systems map", ""]
    systems = a.systems_map()
    if systems:
        out += ["| System | Docs | Used by | Processes | Described? |", "|---|---|---|---|---|"]
        for s in systems:
            out.append(f"| {_esc(s['system'])} | {s['documents']} | {_esc(', '.join(s['used_by']) or '-')} | {_esc(', '.join(s['processes']) or '-')} | {'yes' if s['described'] else 'no'} |")
    else:
        out.append("_No systems detected (add names to a gazetteer file to help)._")
    out.append("")

    out += ["## 6. Critical dependencies (largest downstream impact)", ""]
    crit = a.critical_nodes()
    out += [f"- **{c['name']}** ({c['kind']}): affects {c['downstream']} downstream items, {c['processes']} of them processes" for c in crit] or ["_Not enough relations to rank._"]
    out.append("")

    out += ["## 7. Rules digest", ""]
    for modality in ("prohibition", "obligation", "recommendation", "permission"):
        rules = [r for r in model.rules if r["modality"] == modality]
        if rules:
            out += [f"**{modality.title()}s ({len(rules)})**", ""]
            out += [f"- {r['text']}  _({model.doc_label(r['doc_id'])})_" for r in rules[:15]]
            out.append("")

    out += ["## 8. Glossary", ""]
    seen = set()
    for t in sorted(model.terms, key=lambda t: t["term"].lower()):
        if t["term"].lower() not in seen:
            seen.add(t["term"].lower())
            out.append(f"- **{t['term']}** - {t['definition']}")
    if not seen:
        out.append("_No definitions found._")
    out.append("")

    out += ["## 9. Gaps, inconsistencies and risks", ""]
    findings = a.gaps(today=today)
    if findings:
        for f in findings:
            out.append(f"- **[{f.severity.upper()}] {f.kind}** - {f.message}")
            for ev in f.evidence[:3]:
                out.append(f"  - _{shorten(ev, 220)}_")
    else:
        out.append("_No issues detected._")
    out.append("")

    out += ["## 10. Knowledge graph (top nodes)", "", "```mermaid", model.graph.to_mermaid(), "```", ""]
    return "\n".join(out)
