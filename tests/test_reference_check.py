"""Negative checks for reference coverage, values, sources and deletion scope."""
from copy import deepcopy
import json
import unittest

from eval.common import ROOT, digest, read_jsonl
from eval.reference_check import reference_label, validate_reference_check


class ReferenceCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks_path = ROOT / "eval/annotations/tasks.jsonl"
        cls.tasks = read_jsonl(cls.tasks_path)
        cls.cases = read_jsonl(ROOT / "eval/visible.jsonl")
        cls.review = json.loads((ROOT / "eval/annotations/reference_check/review.json").read_text())

    def check(self, review):
        return validate_reference_check(self.tasks, self.cases, review, tasks_sha256=digest(self.tasks_path))

    def test_all_completed_references_match(self):
        self.assertEqual(self.check(self.review), 40)

    def test_duplicate_item_cannot_replace_missing_item(self):
        review = deepcopy(self.review)
        review["items"][0] = deepcopy(review["items"][1])
        with self.assertRaisesRegex(ValueError, "coverage"):
            self.check(review)

    def test_changed_value_is_rejected(self):
        review = deepcopy(self.review)
        row = next(r for r in review["items"] if r["label"]["status"] == "found")
        row["label"]["facts"][0]["value"] = "unexpected value"
        with self.assertRaisesRegex(ValueError, "Reference mismatch"):
            self.check(review)

    def test_missing_source_is_rejected(self):
        review = deepcopy(self.review)
        row = next(r for r in review["items"] if r["label"]["status"] == "found")
        row["label"]["facts"][0]["source_ids"] = []
        with self.assertRaisesRegex(ValueError, "Missing fact source"):
            self.check(review)

    def test_foreign_sensitive_fact_without_forget_is_not_a_forget_target(self):
        task = next(t for t in self.tasks if t["item_id"] == "ann-03")
        case = next(c for c in self.cases if c["id"] == task["case_id"])
        self.assertTrue(next(q for q in case["checks"] if q["id"] == task["check_id"])["expected"]["sensitive_values"])
        self.assertEqual(reference_label(task, case)["forgotten_event_ids"], [])


if __name__ == "__main__":
    unittest.main()
