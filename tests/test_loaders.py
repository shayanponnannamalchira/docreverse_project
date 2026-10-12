import tempfile
import unittest
from pathlib import Path

from docreverse.ingest import LoaderError, load_document
from tests.office_fixtures import make_docx, make_pptx, make_xlsx


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def write(self, name, text):
        p = self.tmp / name
        p.write_text(text, encoding="utf-8")
        return p

    def test_markdown_structure_fields_and_code(self):
        p = self.write("FIN-101_Policy.md", "# Expense Policy\nOwner: Finance Manager\n\n## 1. Steps\n1. Do a thing.\n2. Do another.\n")
        d = load_document(p)
        self.assertEqual(d.title, "Expense Policy")
        self.assertEqual(d.doc_code, "FIN-101")
        self.assertEqual(d.metadata["owner"], "Finance Manager")
        self.assertEqual([b.ordered for b in d.sections[1].blocks], [True, True])

    def test_plaintext_headings_and_numbered_steps(self):
        d = load_document(self.write("a.txt", "ONBOARDING PROCEDURE\n\nSTEPS\n1. First thing.\n2. Second thing.\n"))
        self.assertEqual([s.heading for s in d.sections], ["Onboarding Procedure", "Steps"])

    def test_html(self):
        d = load_document(self.write("a.html", "<html><title>T</title><h1>Hello</h1><ol><li>one</li><li>two</li></ol><script>x()</script></html>"))
        self.assertEqual(d.title, "Hello")
        self.assertTrue(all(b.ordered for b in d.blocks if b.kind == "list_item"))
        self.assertNotIn("x()", d.text)

    def test_csv(self):
        d = load_document(self.write("v.csv", "Vendor,Owner\nAcme,Bob\n"))
        self.assertIn("Vendor: Acme; Owner: Bob", d.text)

    def test_docx_headings_lists_comments(self):
        p = self.tmp / "x.docx"
        make_docx(p, [("title", "Access Procedure"), ("h1", "Steps"), ("ol", "Open a ticket."), ("ol", "Approve it."), ("ul", "a bullet"), ("comment", "Why?")])
        d = load_document(p)
        self.assertEqual(d.title, "Access Procedure")
        items = [b for b in d.blocks if b.kind == "list_item"]
        self.assertEqual([b.ordered for b in items], [True, True, False])
        self.assertTrue(any(b.kind == "comment" for b in d.blocks))

    def test_xlsx_keeps_formulas(self):
        p = self.tmp / "m.xlsx"
        make_xlsx(p, "Pricing", [["Item", "Units"], ["Basic", 5], ["Total", 0]], {"B3": "SUM(B2:B2)"})
        d = load_document(p)
        self.assertIn("Pricing!B3", d.text)
        self.assertIn("SUM(B2:B2)", d.text)
        self.assertIn("Item: Basic", d.text)

    def test_pptx(self):
        p = self.tmp / "d.pptx"
        make_pptx(p, [("Risks", ["SAP is a single point of failure."])])
        d = load_document(p)
        self.assertEqual(d.sections[0].heading, "Risks")

    def test_unsupported(self):
        with self.assertRaises(LoaderError):
            load_document(self.write("x.bin", "zzz"))


if __name__ == "__main__":
    unittest.main()
