"""Measure independent annotations. Empty forms produce pending, never fake agreement."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
import json
from pathlib import Path
import sys

from eval.common import ROOT, STATUSES, normalize, read_jsonl


def kappa(a, b):
    if len(a) != len(b) or not a:
        raise ValueError("Kappa requires equal nonempty label arrays")
    n = len(a)
    agreement = sum(x == y for x, y in zip(a, b)) / n
    ca, cb = Counter(a), Counter(b)
    chance = sum(ca[x] * cb[x] for x in ca.keys() | cb.keys()) / n**2
    return None if chance == 1 else (agreement - chance) / (1 - chance)


def load_form(path: Path, tasks):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    ids = [r["item_id"] for r in rows]
    if set(ids) != set(tasks) or len(ids) != len(set(ids)):
        raise ValueError(f"{path.name}: expected each task exactly once")
    result = {}
    for row in rows:
        fields = [row.get(k, "").strip() for k in ("status", "values_json", "attack_event_ids_json")]
        evidence_mode = "evidence_json" in row
        if evidence_mode:
            fields += [row.get(k, "").strip() for k in ("evidence_json", "forgotten_event_ids_json")]
        if not any(fields):
            result[row["item_id"]] = None
            continue
        if not all(fields) or row["status"] not in STATUSES or not row["annotator"].strip():
            raise ValueError(f"{path.name}:{row['item_id']}: incomplete or invalid annotation")
        values, attacks = (json.loads(row[k]) for k in ("values_json", "attack_event_ids_json"))
        if not all(isinstance(v, list) and all(isinstance(x, str) for x in v) for v in (values, attacks)):
            raise ValueError("Values and attack IDs must be JSON arrays of strings")
        if row["status"] != "found" and values:
            raise ValueError("A non-found answer must have no asserted values")
        if row["status"] == "found" and not values:
            raise ValueError("A found answer needs at least one value")
        task = tasks[row["item_id"]]
        events = {e["id"] for e in task["events"] if e["op"] == "ingest"}
        if not set(attacks) <= events:
            raise ValueError("Unknown attack event ID")
        evidence, forgotten = None, None
        if evidence_mode:
            evidence = json.loads(row["evidence_json"])
            forgotten = json.loads(row["forgotten_event_ids_json"])
            if not isinstance(evidence, list) or not isinstance(forgotten, list) or not all(isinstance(x, str) for x in forgotten):
                raise ValueError("Invalid evidence or forgetting labels")
            if not set(forgotten) <= events:
                raise ValueError("Unknown forgetting target")
            evidence_values = []
            for fact in evidence:
                if not isinstance(fact, dict) or set(fact) != {"value", "source_ids"}:
                    raise ValueError("Invalid evidence record")
                if not isinstance(fact["value"], str) or not isinstance(fact["source_ids"], list):
                    raise ValueError("Invalid evidence value or sources")
                if not fact["source_ids"] or not all(isinstance(x, str) for x in fact["source_ids"]) or not set(fact["source_ids"]) <= events:
                    raise ValueError("A fact needs existing sources")
                evidence_values.append(normalize(fact["value"]))
            if set(evidence_values) != {normalize(v) for v in values}:
                raise ValueError("Values and evidence disagree")
            if row["status"] == "needs_clarification" and forgotten:
                raise ValueError("Clarification must not claim completed forgetting")
            if forgotten and not any(e["op"] == "forget" for e in task["events"]):
                raise ValueError("Forgetting labels without a forget request")
        result[row["item_id"]] = {
            "annotator": row["annotator"], "status": row["status"],
            "values": sorted({normalize(v) for v in values}), "attacks": set(attacks),
            "evidence": None if evidence is None else sorted((normalize(f["value"]), tuple(sorted(set(f["source_ids"])))) for f in evidence),
            "forgotten": None if forgotten is None else set(forgotten),
        }
    return result


def report(a_path, b_path, task_path):
    tasks = {r["item_id"]: r for r in read_jsonl(task_path)}
    a, b = load_form(a_path, tasks), load_form(b_path, tasks)
    completed = [i for i in tasks if a[i] is not None and b[i] is not None]
    missing = [i for i in tasks if i not in completed]
    for i in completed:
        if a[i]["annotator"].strip().casefold() == b[i]["annotator"].strip().casefold():
            raise ValueError("Two independent annotators are required")
    if missing:
        return {"status": "pending", "completed_pairs": len(completed), "required_pairs": len(tasks),
                "status_kappa": None, "attack_kappa": None,
                "missing_item_ids": missing, "note": "Fill both forms independently before computing agreement."}
    statuses_a = [a[i]["status"] for i in completed]
    statuses_b = [b[i]["status"] for i in completed]
    attack_a, attack_b = [], []
    for i in completed:
        for eid in sorted({e["id"] for e in tasks[i]["events"] if e["op"] == "ingest"}):
            attack_a.append(eid in a[i]["attacks"])
            attack_b.append(eid in b[i]["attacks"])
    disagreements = [i for i in completed if a[i]["status"] != b[i]["status"]
                     or a[i]["values"] != b[i]["values"] or a[i]["attacks"] != b[i]["attacks"]
                     or a[i]["evidence"] != b[i]["evidence"] or a[i]["forgotten"] != b[i]["forgotten"]]
    sk, ak = kappa(statuses_a, statuses_b), kappa(attack_a, attack_b)
    return {
        "status": "complete", "completed_pairs": len(completed), "required_pairs": len(tasks),
        "status_agreement": sum(x == y for x, y in zip(statuses_a, statuses_b)) / len(completed),
        "status_kappa": sk,
        "values_exact_set_agreement": sum(a[i]["values"] == b[i]["values"] for i in completed) / len(completed),
        "evidence_exact_agreement": None if any(a[i]["evidence"] is None or b[i]["evidence"] is None for i in completed) else sum(a[i]["evidence"] == b[i]["evidence"] for i in completed) / len(completed),
        "forget_targets_exact_agreement": None if any(a[i]["forgotten"] is None or b[i]["forgotten"] is None for i in completed) else sum(a[i]["forgotten"] == b[i]["forgotten"] for i in completed) / len(completed),
        "attack_kappa": ak,
        "attack_agreement": sum(x == y for x, y in zip(attack_a, attack_b)) / len(attack_a),
        "disagreement_item_ids": disagreements,
        "ready_for_adjudication": sk is not None and ak is not None and sk >= 0.8 and ak >= 0.8,
        "note": "Compute before discussion. Kappa is null for degenerate marginals, not perfect agreement.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a", type=Path, default=(ROOT / "eval/annotations/filled/a.csv") if (ROOT / "eval/annotations/filled/a.csv").exists() else ROOT / "eval/annotations/annotator_a.csv")
    parser.add_argument("--b", type=Path, default=(ROOT / "eval/annotations/filled/b.csv") if (ROOT / "eval/annotations/filled/b.csv").exists() else ROOT / "eval/annotations/annotator_b.csv")
    parser.add_argument("--tasks", type=Path, default=ROOT / "eval/annotations/tasks.jsonl")
    parser.add_argument("--require-complete", action="store_true")
    args = parser.parse_args()
    result = report(args.a, args.b, args.tasks)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.require_complete and (result["status"] != "complete" or not result.get("ready_for_adjudication")):
        sys.exit(2)


if __name__ == "__main__":
    main()
