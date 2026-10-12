"""Command-line interface:  python -m docreverse <command> ..."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .analyze import Analyzer
from .config import DEFAULT_DB, Config
from .extract.entities import Gazetteer
from .llm import LLM, deep_enrich
from .model import Model
from .pipeline import analyse_document, discover, ingest, make_chunks
from .qa import ask
from .report import build_report, process_mermaid
from .store import Store
from .textutil import shorten


def _open(args) -> Store:
    return Store(args.db)


def cmd_ingest(args) -> int:
    cfg = Config(db_path=args.db)
    store = Store(cfg.db_path)
    gaz = Gazetteer.load(args.gazetteer)
    print(f"Ingesting into {cfg.db_path}")
    if args.deep:
        llm = LLM(cfg)
        if not llm.available:
            print("--deep needs ANTHROPIC_API_KEY and `pip install anthropic`", file=sys.stderr)
            return 2
        from .ingest import load_document
        total = 0
        for f in discover(args.paths):
            try:
                doc = load_document(f)
            except Exception as e:
                print(f"  ! {f}: {e}")
                continue
            ex = analyse_document(doc, gaz)
            added = deep_enrich(doc, ex, llm)
            store.save_document(doc, ex, make_chunks(doc, cfg.chunk_chars, cfg.chunk_overlap))
            total += added
            print(f"  + {f}  (+{added} items from LLM)")
        stats = {"deep_items": total}
    else:
        stats = ingest(args.paths, store, cfg, gaz, force=args.force)
    if args.prune:
        gone = store.prune_missing()
        stats["pruned"] = len(gone)
    print("Done:", ", ".join(f"{k}={v}" for k, v in stats.items()))
    return 0


def cmd_status(args) -> int:
    ov = Analyzer(Model(_open(args))).overview()
    for k, v in ov.items():
        print(f"{k:>16}: {v}")
    return 0


def cmd_processes(args) -> int:
    model = Model(_open(args))
    procs = sorted(model.processes, key=lambda p: p["name"].lower())
    if args.show:
        hit = [p for p in procs if args.show.lower() in p["name"].lower()]
        if not hit:
            print("No such process.")
            return 1
        for p in hit:
            print(f"\n# {p['name']}   ({model.doc_label(p['doc_id'])})")
            print(f"Owner: {p['owner'] or 'unknown'} ({p['owner_source'] or '-'})   Systems: {', '.join(p['systems']) or '-'}")
            if p["trigger"]:
                print(f"Trigger: {p['trigger']}")
            for s in p["steps"]:
                print(f"  {s['n']:>2}. {'[decision] ' if s['is_decision'] else ''}{s['text']}" + (f"  <{s['actor']}>" if s["actor"] else ""))
            if args.mermaid:
                print("\n" + process_mermaid(p))
        return 0
    for p in procs:
        print(f"- {p['name']}  | owner: {p['owner'] or '?'} | {len(p['steps'])} steps | {model.doc_label(p['doc_id'])}")
    return 0


def cmd_explain(args) -> int:
    a = Analyzer(Model(_open(args)))
    info = a.explain(args.topic)
    if not info:
        print(f"Nothing found for '{args.topic}'.")
        return 1
    n = info["node"]
    print(f"# {n.label if n else args.topic}" + (f"  [{n.kind}]" if n else ""))
    if info["terms"]:
        for t in info["terms"]:
            print(f"Definition: {t['term']} = {t['definition']}")
    if info["outgoing"]:
        print("\nWhat it does / uses:")
        for rel, obj, ev in info["outgoing"][:15]:
            print(f"  - {rel.replace('_', ' ')} -> {obj}")
    if info["incoming"]:
        print("\nWho acts on it:")
        for subj, rel, ev in info["incoming"][:15]:
            print(f"  - {subj} {rel.replace('_', ' ')} it")
    if info["processes"]:
        print("\nProcesses involved:")
        for p in info["processes"][:10]:
            print(f"  - {p['name']} ({len(p['steps'])} steps, owner: {p['owner'] or '?'})")
    if info["rules"]:
        print("\nRules that mention it:")
        for r in info["rules"][:8]:
            print(f"  - [{r['modality']}] {shorten(r['text'], 200)}")
    if info["documents"]:
        print("\nDocuments:", "; ".join(info["documents"][:8]))
    return 0


def cmd_impact(args) -> int:
    res = Analyzer(Model(_open(args))).impact(args.topic, args.direction, args.depth)
    if not res:
        print(f"'{args.topic}' not found in the graph.")
        return 1
    node = res["node"]
    word = "is affected if it changes or fails" if args.direction == "down" else "it depends on"
    print(f"{node.label} [{node.kind}] - what {word}:")
    if not res["affected"]:
        print("  (nothing found)")
    for n, depth, e in res["affected"]:
        print(f"  {'  ' * (depth - 1)}- {n.label} [{n.kind}]  via '{e.rel}'")
    return 0


def cmd_gaps(args) -> int:
    findings = Analyzer(Model(_open(args))).gaps(stale_days=args.stale_days)
    if not findings:
        print("No issues detected.")
    for f in findings:
        print(f"[{f.severity.upper():4}] {f.kind}: {f.message}")
        for ev in f.evidence[:3]:
            print(f"        {shorten(ev, 200)}")
    return 0


def cmd_ask(args) -> int:
    store = _open(args)
    model = Model(store)
    llm = None if args.no_llm else LLM(Config(db_path=args.db))
    ans = ask(model, " ".join(args.question), llm)
    print(ans.text)
    if ans.facts:
        print("\nRelated facts from the graph:")
        for f in ans.facts[:8]:
            print(f"  - {f}")
    if ans.sources:
        print("\nSources:")
        for s in dict.fromkeys(ans.sources):
            print(f"  - {s}")
    return 0


def cmd_search(args) -> int:
    for r in _open(args).search(" ".join(args.query), args.k):
        print(f"* {r['title']} > {r['section']}\n  {shorten(r['text'], 300)}\n")
    return 0


def cmd_graph(args) -> int:
    g = Model(_open(args)).graph
    text = {"mermaid": lambda: g.to_mermaid(args.max_nodes), "dot": lambda: g.to_dot(args.max_nodes), "json": g.to_json}[args.format]()
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(text)
    return 0


def cmd_report(args) -> int:
    text = build_report(Model(_open(args)))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    print(f"Wrote {args.out} ({len(text.splitlines())} lines)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="docreverse", description="Reverse-engineer company documents into a queryable model.")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--db", default=DEFAULT_DB, help=f"index database (default {DEFAULT_DB})")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest", help="read documents and build the index")
    s.add_argument("paths", nargs="+")
    s.add_argument("--gazetteer", help="JSON file with known systems/roles/teams/aliases")
    s.add_argument("--force", action="store_true", help="re-analyse unchanged files")
    s.add_argument("--prune", action="store_true", help="drop documents whose files no longer exist")
    s.add_argument("--deep", action="store_true", help="LLM-assisted extraction (needs ANTHROPIC_API_KEY)")
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("status", help="corpus statistics"); s.set_defaults(fn=cmd_status)

    s = sub.add_parser("processes", help="list processes or show one")
    s.add_argument("--show", help="name (substring) of a process to print in full")
    s.add_argument("--mermaid", action="store_true", help="with --show: also print a flowchart")
    s.set_defaults(fn=cmd_processes)

    s = sub.add_parser("explain", help="how does <role|system|process|form> work?")
    s.add_argument("topic"); s.set_defaults(fn=cmd_explain)

    s = sub.add_parser("impact", help="what is affected if <thing> changes or fails?")
    s.add_argument("topic")
    s.add_argument("--direction", choices=["down", "up"], default="down", help="down=what it affects, up=what it depends on")
    s.add_argument("--depth", type=int, default=3)
    s.set_defaults(fn=cmd_impact)

    s = sub.add_parser("gaps", help="missing owners, broken references, conflicting numbers, stale docs...")
    s.add_argument("--stale-days", type=int, default=365); s.set_defaults(fn=cmd_gaps)

    s = sub.add_parser("ask", help="ask a question about the documents")
    s.add_argument("question", nargs="+")
    s.add_argument("--no-llm", action="store_true", help="never call an LLM; show passages only")
    s.set_defaults(fn=cmd_ask)

    s = sub.add_parser("search", help="full-text search")
    s.add_argument("query", nargs="+"); s.add_argument("-k", type=int, default=6); s.set_defaults(fn=cmd_search)

    s = sub.add_parser("graph", help="export the knowledge graph")
    s.add_argument("--format", choices=["mermaid", "dot", "json"], default="mermaid")
    s.add_argument("--max-nodes", type=int, default=40)
    s.add_argument("--out"); s.set_defaults(fn=cmd_graph)

    s = sub.add_parser("report", help="write the full Markdown report")
    s.add_argument("--out", default="out/report.md"); s.set_defaults(fn=cmd_report)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
