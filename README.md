# DocReverse

Reverse-engineer a company's documents (policies, SOPs, runbooks, contracts, spreadsheets, decks, e-mails)
into a **queryable model of how the organisation actually works**: who does what, in which system, in what
order, under which rules, and where the documents contradict or fail to cover each other.

* Pure Python standard library at its core (3.9+). No server, no cloud, no API key required.
* Reads `.txt .md .rst .html .csv .docx .xlsx .pptx .eml .pdf`
* Optional LLM layer (Anthropic API) for written answers and deeper extraction, with automatic redaction.

## Quick start

```bash
python scripts/make_samples.py                 # (optional) create the docx/xlsx/pptx samples
python -m docreverse ingest sample_docs        # build the index  -> .docreverse/index.db
python -m docreverse status
python -m docreverse processes                 # every process found
python -m docreverse processes --show "Expense" --mermaid
python -m docreverse explain "Line Manager"    # how does this role / system / form work?
python -m docreverse impact Concur             # what breaks if Concur changes or fails?
python -m docreverse impact SAP --direction up # what does SAP depend on?
python -m docreverse gaps                      # missing owners, conflicts, broken refs, stale docs
python -m docreverse ask "who approves expense claims over 2500"
python -m docreverse report --out out/report.md
python -m docreverse graph --format mermaid --out out/graph.mmd
python -m unittest discover -s tests -t .      # run the tests
```

Point `ingest` at your own folders instead of `sample_docs`. Re-running is incremental (unchanged files are skipped).
Use `--gazetteer company.json` to teach it your system/role names (see `docs/PROJECT_GUIDE.md`).

Optional extras: `pip install pypdf` (PDF), `pip install anthropic` + `export ANTHROPIC_API_KEY=...` (LLM answers, `ingest --deep`).

Full explanation of the design and every module: **[docs/PROJECT_GUIDE.md](docs/PROJECT_GUIDE.md)**.
A generated example output is in `out/example_report.md`.
