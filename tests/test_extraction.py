import unittest

from docreverse.extract.entities import Gazetteer, find_spans
from docreverse.extract.facts import extract_facts, extract_terms
from docreverse.extract.relations import extract_relations
from docreverse.extract.rules import extract_rule
from docreverse.textutil import split_sentences


def rels(sentence):
    return {(r.subject, r.predicate, r.object) for r in extract_relations(sentence, find_spans(sentence), "s")}


class EntityTests(unittest.TestCase):
    def test_roles_teams_systems_artifacts(self):
        spans = {(s.name, s.kind) for s in find_spans("The Finance Manager sends the Expense Report to the IT Service Desk using Concur.")}
        self.assertIn(("Finance Manager", "role"), spans)
        self.assertIn(("Expense Report", "artifact"), spans)
        self.assertIn(("IT Service Desk", "team"), spans)
        self.assertIn(("Concur", "system"), spans)

    def test_lowercase_phrases_after_determiner(self):
        spans = {(s.name, s.kind) for s in find_spans("Ask the line manager or the finance team.")}
        self.assertIn(("Line Manager", "role"), spans)
        self.assertIn(("Finance Team", "team"), spans)

    def test_gazetteer_and_aliases(self):
        gaz = Gazetteer(systems={"Zorp"}, aliases={"Zorp": "ZorpCRM"})
        self.assertIn(("ZorpCRM", "system"), {(s.name, s.kind) for s in find_spans("Log the call in Zorp.", gaz)})

    def test_no_false_system_for_months(self):
        self.assertFalse([s for s in find_spans("The report is due in March.") if s.kind == "system"])


class RelationTests(unittest.TestCase):
    def test_active_and_free_text_object(self):
        self.assertIn(("Finance Manager", "approves", "expenses over $5,000"), rels("Finance Manager approves expenses over $5,000."))

    def test_passive_reverses_direction(self):
        self.assertIn(("Line Manager", "approves", "Expense Report"), rels("The Expense Report is approved by the Line Manager."))

    def test_submit_to(self):
        r = rels("Employee submits Expense Report to Line Manager.")
        self.assertIn(("Employee", "submits", "Expense Report"), r)
        self.assertIn(("Employee", "sends_to", "Line Manager"), r)

    def test_conjunction_carries_subject(self):
        r = rels("The Finance Manager logs into Concur and approves the Expense Report.")
        self.assertIn(("Finance Manager", "uses", "Concur"), r)
        self.assertIn(("Finance Manager", "approves", "Expense Report"), r)

    def test_system_location_is_usage_by_the_person(self):
        r = rels("Employee creates the Expense Report in Concur and attaches all receipts.")
        self.assertIn(("Employee", "uses", "Concur"), r)
        self.assertNotIn(("Expense Report", "uses", "Concur"), r)

    def test_system_does_not_use_system(self):
        self.assertFalse([x for x in rels("Claims are recorded in Concur and archived in SharePoint.") if x[0] == "Concur"])


class FactTests(unittest.TestCase):
    def test_numbers_and_units(self):
        facts = {(f.value, f.unit) for f in extract_facts("Approve within five business days; claims over $2.5k or 10% fee.", "s")}
        self.assertIn((5.0, "business_day"), facts)
        self.assertIn((2500.0, "USD"), facts)
        self.assertIn((10.0, "%"), facts)

    def test_rules(self):
        self.assertEqual(extract_rule("Employees must not claim personal travel.", "s").modality, "prohibition")
        self.assertEqual(extract_rule("Receipts are mandatory for any expense over $25.", "s").modality, "obligation")
        self.assertEqual(extract_rule("Reports should be reviewed by the manager.", "s").modality, "recommendation")
        self.assertIsNone(extract_rule("Is this a rule at all here?", "s"))

    def test_sentence_split_keeps_decimals_and_abbreviations(self):
        self.assertEqual(len(split_sentences("The fee is 3.5% e.g. for Dr. Smith. Next step.")), 2)


if __name__ == "__main__":
    unittest.main()
