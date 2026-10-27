"""Checks for evaluation integrity; no service-quality results are fabricated."""
from copy import deepcopy
import csv
import json
from pathlib import Path
import tempfile
import unittest

from eval.agreement import kappa, report
from eval.budget import calculate
from eval.common import ROOT, read_jsonl, system_input
from eval.validate import validate_case, validate_dataset


class IntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = read_jsonl(ROOT / "eval/visible.jsonl")
        cls.policy = json.loads((ROOT / "eval/source_policy.json").read_text())

    def test_public_snapshot_and_controls(self):
        result = validate_dataset()
        self.assertEqual(result["holdout_check"], "not_opened")
        self.assertEqual(result["visible"], 120)

    def test_export_never_forwards_gold_metadata(self):
        case = deepcopy(self.cases[0])
        case["future_internal_field"] = {"gold": "MUST_NOT_LEAK"}
        case["checks"][0]["expected"]["future_internal_field"] = "MUST_NOT_LEAK"
        case["events"][0]["future_internal_field"] = "MUST_NOT_LEAK"
        case["checks"][0]["input"]["future_internal_field"] = "MUST_NOT_LEAK"
        exported = system_input(case)
        self.assertEqual(set(exported), {"events", "queries"})
        self.assertEqual(set(exported["queries"][0]), {"after_event", "input"})
        self.assertNotIn("MUST_NOT_LEAK", json.dumps(exported))

    def test_cross_scope_reference_is_rejected(self):
        case = deepcopy(self.cases[0])
        case["checks"][0]["input"]["scope"]["subject"] = "different-person"
        with self.assertRaisesRegex(ValueError, "cross-scope"):
            validate_case(case, self.policy)

    def test_future_evidence_is_rejected(self):
        case = deepcopy(self.cases[0])
        case["checks"][0]["input"]["now"] = "2026-09-01T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "future event"):
            validate_case(case, self.policy)

    def test_deletion_without_retained_control_is_rejected(self):
        case = deepcopy(next(c for c in self.cases if c["category"] == "deletion"))
        case["checks"] = [q for q in case["checks"] if q["purpose"] != "retained_control"]
        with self.assertRaisesRegex(ValueError, "deletion controls"):
            validate_case(case, self.policy)

    def test_source_only_attack_rule_fails_in_both_directions(self):
        mistakes = {False: 0, True: 0}
        for case in self.cases:
            sources = {e["id"]: e["channel"] for e in case["events"] if e["op"] == "ingest"}
            for label in case["oracle"]["security_labels"]:
                prediction = sources[label["event_id"]] != "user"
                if prediction != label["attack"]:
                    mistakes[label["attack"]] += 1
        self.assertGreater(mistakes[False], 0)
        self.assertGreater(mistakes[True], 0)

    def test_always_unknown_and_erase_everything_are_caught(self):
        self.assertTrue(any(q["expected"]["status"] == "found" for c in self.cases for q in c["checks"]))
        for case in self.cases:
            if case["category"] == "deletion":
                retained = next(q for q in case["checks"] if q["purpose"] == "retained_control")
                self.assertEqual(retained["expected"]["status"], "found")
                self.assertTrue(retained["expected"]["required_facts"])


class AgreementTests(unittest.TestCase):
    def test_known_kappa(self):
        self.assertAlmostEqual(kappa(["a", "a", "b", "b"], ["a", "b", "b", "b"]), 0.5)
        self.assertAlmostEqual(kappa(["a", "b"], ["a", "b"]), 1.0)

    def test_degenerate_kappa_is_not_perfect_agreement(self):
        self.assertIsNone(kappa(["a", "a"], ["a", "a"]))

    def test_blank_real_forms_stay_pending(self):
        value = report(ROOT / "eval/annotations/annotator_a.csv",
                       ROOT / "eval/annotations/annotator_b.csv",
                       ROOT / "eval/annotations/tasks.jsonl")
        self.assertEqual(value["status"], "pending")
        self.assertEqual(value["completed_pairs"], 0)
        self.assertIsNone(value["status_kappa"])

    def test_completed_synthetic_forms_have_explicit_agreement(self):
        # These two artificial labels test the formula, not human or service performance.
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            tasks = folder / "tasks.jsonl"
            tasks.write_text('\n'.join(json.dumps({"item_id": f"x{i}", "events": [{"op": "ingest", "id": "e1"}]})
                                       for i in range(2)) + '\n')
            fields = ["item_id", "annotator", "status", "values_json", "attack_event_ids_json", "comment"]
            for person in ("a", "b"):
                with (folder / f"{person}.csv").open("w", newline="") as stream:
                    writer = csv.DictWriter(stream, fields)
                    writer.writeheader()
                    writer.writerow(dict(item_id="x0", annotator=person, status="found",
                                         values_json='["value"]', attack_event_ids_json='["e1"]'))
                    writer.writerow(dict(item_id="x1", annotator=person, status="unknown",
                                         values_json="[]", attack_event_ids_json="[]"))
            value = report(folder / "a.csv", folder / "b.csv", tasks)
            self.assertEqual(value["status"], "complete")
            self.assertEqual(value["status_kappa"], 1)
            self.assertEqual(value["attack_kappa"], 1)


class BudgetTests(unittest.TestCase):
    def test_cost_and_operation_counts_reconcile(self):
        inputs = json.loads((ROOT / "eval/budget_inputs.json").read_text())
        result = calculate(inputs)
        self.assertEqual(result["writes"] + result["reads"] + result["forgets"], result["monthly_operations"])
        self.assertEqual(result["reads"], 207000)
        self.assertEqual(result["memory_service_with_reserve_usd"], 104.11)
        self.assertEqual(result["memory_total_with_agent_usd"], 197.70)
        self.assertFalse(calculate(dict(inputs, operations_per_day=20000))["memory_service_within_cap"])


if __name__ == "__main__":
    unittest.main()
