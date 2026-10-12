# DocReverse - Project Guide

## 1. What the project does

Companies describe how they work in scattered documents. Nobody holds the whole picture: which process is owned by whom,
which systems it touches, which policy says 3 days while the SOP says 5, which referenced document no longer exists.

DocReverse **reads those documents and reverse-engineers the operating model** behind them:

| You ask | DocReverse answers from |
|---|---|
| "What processes exist and what are the steps?" | numbered lists / sequence wording under process-like headings |
| "Who owns / approves / reviews what?" | sentence analysis -> (subject, verb, object) triples |
| "Which systems are used, by whom?" | tool-name detection + `uses` relations |
| "What breaks if SAP changes?" | graph traversal (impact analysis) |
| "What is inconsistent or missing?" | gap detectors (ownerless processes, conflicting numbers, broken references, stale documents) |
| "How does X work?" / free questions | full-text retrieval + graph facts (+ optional LLM) |

Everything is **local and deterministic by default**; the LLM is an optional add-on.

## 2. Architecture

```
files --> ingest/ loaders --> structure.py --> extract/* --> store.py (SQLite+FTS5)
 .md .docx .xlsx .pptx         blocks ->        entities,         |
 .pdf .html .csv .eml          sections,        relations,        v
                               title, code,     processes,     model.py --> graph.py
                               type, fields     rules, facts,     |
                                                refs, terms       +--> analyze.py  (gaps, impact, explain)
                                                                  +--> qa.py       (ask)
                                                                  +--> report.py   (Markdown + Mermaid)
                                                                  +--> cli.py      (all commands)
                                         llm.py + redact.py: optional deep extraction / written answers
```

Data flow in one sentence: **every file becomes a flat list of `Block`s -> grouped into `Section`s -> each sentence is scanned
for entities and relations -> sections with ordered steps become `Process`es -> everything is stored in SQLite -> the
`Model` loads it back and builds a `KnowledgeGraph` that the analyses query.**

## 3. Directory layout

```
docreverse/
  cli.py            argparse commands (ingest, status, processes, explain, impact, gaps, ask, search, graph, report)
  config.py         defaults (DB path, chunk size, model name, supported extensions)
  models.py         dataclasses: Block, Section, Document, Mention, Relation, Step, Process, Rule, Fact, Reference, Term
  textutil.py       sentence splitter, stop-words, light stemmer, helpers
  structure.py      blocks -> sections, title, doc code (FIN-102), doc type, header fields (Owner:, Version:)
  ingest/           one loader per format (text, html, office, other) + registry in __init__.py
  extract/          entities, relations, processes, rules, facts (numbers, references, glossary)
  pipeline.py       analyse_document(), chunking, folder discovery, incremental ingest
  store.py          SQLite schema, FTS5 search (with a pure-Python fallback)
  model.py          loads the store into memory and assembles the graph
  graph.py          KnowledgeGraph: find, impact, shortest_path, Mermaid/DOT/JSON export
  analyze.py        overview, ownership, systems map, gaps, conflicts, critical nodes, explain
  qa.py             retrieval + graph facts -> answer
  llm.py / redact.py optional LLM calls; PII/secret redaction before anything leaves the machine
tests/              32 unit/integration tests (stdlib unittest) + Office-file builders
sample_docs/        fictional company corpus with deliberately planted problems
scripts/make_samples.py   writes the .docx/.xlsx/.pptx samples
```

## 4. Walk-through of the code

### 4.1 Loaders (`ingest/`)
Each loader returns `(blocks, metadata)`. A **Block** has a `kind` (`heading`, `paragraph`, `list_item`, `table_row`,
`field`, `code`, `comment`, `formula`), text, a level and an `ordered` flag. Keeping one neutral representation means the
rest of the pipeline never cares about the file format.

* `text.py` - `parse_plaintext()` recognises Markdown headings, setext headings, `2.1 Numbered headings`, ALL-CAPS headings,
  bullets vs numbered items (with wrapped continuation lines), Markdown tables, code fences and `Owner: x` header lines.
  PDF and e-mail reuse it.
* `html.py` - `html.parser` based; keeps headings, paragraphs, ordered/unordered lists and tables; drops scripts/styles.
* `office.py` - DOCX/PPTX/XLSX are zipped XML, parsed with the standard library. DOCX: heading styles, real list numbering
  (decimal vs bullet), tables and **reviewer comments**. PPTX: slide titles, bullets, tables, speaker notes.
  XLSX: sheets as tables **plus every formula** with a human label (`Pricing!D4 (Total / Revenue) = SUM(D2:D3)`),
  because spreadsheet formulas are often the only written record of business logic.
* `other.py` - CSV (delimiter sniffing), PDF (`pypdf` or `pdftotext`; removes running headers/footers; clear error for scans),
  EML (headers + body, quoted replies stripped).

### 4.2 Structure (`structure.py`)
Groups blocks into sections under headings, picks the title, finds a document code (`FIN-102`), classifies the document
type (policy, sop, runbook, contract, ...) and collects header fields (`owner`, `version`, `last reviewed`...).

### 4.3 Extraction (`extract/`)
Rule-based and fully inspectable.

* **entities.py** - four entity kinds: *role* (Finance Manager), *team* (IT Service Desk), *system* (Concur), *artifact*
  (Expense Report). Techniques: capitalised phrases ending in a head noun; lowercase phrases after a determiner
  ("the line manager"); tool names after cue words ("log into Concur"); CamelCase/ALL-CAPS tokens; optional **gazetteer**
  and aliases. Overlaps are resolved longest-first.
* **relations.py** - for each pair of neighbouring entities, the text *between* them (the "gap") is classified by a verb
  lexicon into predicates: `approves, reviews, responsible_for, reports_to, sends_to, submits, creates, triggers,
  depends_on, uses, stored_in`. Handles passive voice (reverses direction), conjunction carry-over ("logs into Concur **and**
  approves the report" -> same subject), "X submits Y to Z", and free-text objects ("approves expenses over $5,000").
* **processes.py** - a section becomes a process when it has >= 2 ordered steps under a process-like heading (or >= 3 anywhere),
  or enough "First / Then / Finally" sentences. Each step gets an actor, systems and a decision flag. The owner comes from
  `Owner:` fields, "owned by", `responsible_for` relations, or (clearly marked *inferred*) the dominant actor.
* **rules.py** - sentences with must/shall/must not/should/may become obligations, prohibitions, recommendations, permissions.
* **facts.py** - numbers with units (money, durations incl. "five business days", percentages), cross-references
  (`HR-204`, "see the Expense Policy") and glossary terms (acronym definitions, "X means Y", glossary sections).

### 4.4 Storage (`store.py`)
One SQLite file. Tables: documents, sections, mentions, relations, processes, rules, facts, refs, terms, chunks (+ an FTS5
index with BM25 ranking; falls back to simple term counting if FTS5 is missing). Ingest is **incremental**: a SHA-256 per
file decides whether to re-analyse.

### 4.5 Graph and analyses
* `graph.py` - nodes (role/team/system/artifact/process/document) and typed edges with evidence sentences.
  **Impact analysis** normalises predicate direction: *flow* edges (sends_to, approves, triggers...) propagate src -> dst,
  *dependency* edges (uses, depends_on, references...) propagate dst -> src. People/teams are treated as "who is affected" leaves,
  so impact does not chain through a person into unrelated work.
* `analyze.py` - the detectors behind `gaps`:
  `ownerless_process`, `inferred_owner`, `thin_process`, `broken_reference` (doc code not in corpus), `missing_document`,
  `undocumented_system`, `undefined_acronym`, `stale_document`, `duplicate_process` (same process in two docs, different owners),
  `conflicting_numbers` (same unit, different value, similar sentences - Jaccard on stemmed content words).
* `qa.py` - BM25 passages + graph facts (entities named in the question, and edges matching verbs like "approves").
  With an LLM the answer is written and cited; without one you get the passages and facts.
* `report.py` - one Markdown report: overview, inventory, per-process Mermaid flowcharts, responsibility table, systems map,
  critical dependencies, rules digest, glossary, gaps, knowledge graph.

### 4.6 Optional LLM (`llm.py`, `redact.py`)
`ask` uses the model named in `DOCREVERSE_MODEL` (default `claude-sonnet-5-5`). `ingest --deep` asks the LLM to extract
processes/relations/rules/terms per section as JSON and merges them marked `source='llm'`. Before any text is sent,
`redact()` removes e-mails, phone numbers, SSNs, Luhn-valid card numbers, IBANs and key-like secrets.

## 5. Using it on real documents

1. `python -m docreverse ingest /path/to/docs` (re-run any time; only changed files are re-read; `--prune` removes deleted ones).
2. Run `status` and `gaps` first - they show how well extraction fits your document style.
3. Improve recall with a gazetteer: `--gazetteer company.json`
   ```json
   {"systems": ["Workday"], "roles": ["Incident Commander"], "teams": ["Security Team"], "aliases": {"SAP ERP": "SAP"}}
   ```
4. `report` for a shareable overview; `explain`, `impact` and `ask` for investigation.

## 6. Extending

* **New file format**: write `load_xxx(path) -> (blocks, meta)` and register it in `ingest/__init__.py` and `config.SUPPORTED_EXTENSIONS`.
* **New relation verb**: add a regex to `ACTIVE` (or `PASSIVE`) in `extract/relations.py`; add the predicate to `FLOW`/`DEP` in `graph.py`.
* **New gap check**: add a block to `Analyzer.gaps()` returning `Finding`s.
* **Other languages**: the lexicons are English; replace the verb/role lists.

## 7. Honest limitations

* Heuristics, not understanding: expect missed relations and some wrong ones. Every relation keeps its **evidence sentence** so you can verify.
* Lowercase roles/systems are only recognised after determiners or via the gazetteer; place names after "in" can be mistaken for systems (add stop-words).
* Processes written as free prose without step markers or sequence words are missed (use `--deep`).
* `conflicting_numbers` is a similarity heuristic: review its evidence; it can produce false positives and miss differently-worded conflicts.
* Spreadsheet formulas are indexed and searchable but not yet modelled as a dependency graph. Scanned PDFs need OCR first.
* Dates in "last reviewed" fields are parsed from a handful of common formats.
* Extracted structure describes what documents *say*, not what people *do*; treat gaps as questions to ask, not verdicts.

## 8. Privacy and safety

Default operation never leaves your machine. LLM features are opt-in (API key + library) and redact first, but redaction is
best-effort - do not send documents you are not permitted to share. Add `.docreverse/` to version-control ignores (done in `.gitignore`).

## 9. Roadmap ideas

OCR for scans; spreadsheet formula dependency graph; embeddings for semantic search; document diffing across versions;
RACI matrix export; a small web UI over the Markdown/Mermaid outputs.
