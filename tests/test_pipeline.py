import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from docreverse.analyze import Analyzer
from docreverse.config import Config
from docreverse.model import Model
from docreverse.pipeline import ingest
from docreverse.qa import ask
from docreverse.redact import redact
from docreverse.report import build_report
from docreverse.store import Store

SAMPLES = Path(__file__).resolve().parents[1] / "sample_docs"


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = Store(":memory:")
        cls.stats = ingest([str(SAMPLES)], cls.store, Config(), log=lambda *_: None)
        cls.model = Model(cls.store)
        cls.an = Analyzer(cls.model)

    def test_everything_ingested(self):
        self.assertEqual(self.stats["failed"], 0)
        self.assertGreaterEqual(self.stats["added"], 8)

    def test_processes_found_with_owner_and_systems(self):
        procs = {p["name"]: p for p in self.model.processes}
        sop = procs["Expense Reimbursement SOP"]
        self.assertEqual(sop["owner"], "Accounts Payable Supervisor")
        self.assertIn("Concur", sop["systems"])
        self.assertEqual(len(sop["steps"]), 7)
        self.assertTrue(sop["steps"][3]["is_decision"])
        self.assertIn("Severity 1 Response", procs)
        self.assertIn("Access Request Procedure", procs)      # from .docx

    def test_conflicting_numbers_detected(self):
        msgs = [f.message for f in self.an.gaps(today=datetime(2025, 1, 1)) if f.kind == "conflicting_numbers"]
        self.assertTrue(any("3 business days" in m and "5 business days" in m for m in msgs))

    def test_broken_reference_and_stale(self):
        kinds = {(f.kind) for f in self.an.gaps(today=datetime(2026, 1, 1))}
        self.assertIn("broken_reference", kinds)     # HR-204 is not in the corpus
        self.assertIn("stale_document", kinds)

    def test_glossary_and_acronyms(self):
        terms = {t["term"] for t in self.model.terms}
        self.assertIn("SLA", terms)

    def test_impact_goes_through_processes(self):
        res = self.an.impact("SAP", "down")
        self.assertIsNotNone(res)
        self.assertTrue(any(n.kind == "process" for n, _, _ in res["affected"]))

    def test_explain_and_search(self):
        info = self.an.explain("Line Manager")
        self.assertTrue(any(rel == "approves" for rel, _, _ in info["outgoing"]))
        self.assertTrue(self.store.search("postmortem confluence"))

    def test_ask_without_llm_returns_passages_and_facts(self):
        ans = ask(self.model, "who approves expense claims over 2500", llm=None)
        self.assertEqual(ans.mode, "extractive")
        self.assertTrue(any("Finance Manager approves" in f for f in ans.facts))

    def test_report_has_all_sections_and_mermaid(self):
        text = build_report(self.model, today=datetime(2026, 1, 1))
        for heading in ("Process catalogue", "Systems map", "Gaps, inconsistencies"):
            self.assertIn(heading, text)
        self.assertIn("flowchart TD", text)

    def test_incremental_ingest_skips_unchanged(self):
        stats = ingest([str(SAMPLES)], self.store, Config(), log=lambda *_: None)
        self.assertEqual(stats["added"] + stats["updated"], 0)

    def test_redaction(self):
        out = redact("Mail bob@acme.com or call 415-555-0134; card 4111 1111 1111 1111; SSN 123-45-6789")
        for token in ("bob@acme.com", "4111", "123-45-6789"):
            self.assertNotIn(token, out)


if __name__ == "__main__":
    unittest.main()
