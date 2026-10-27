"""Validate the fixed evaluation set and references without running a memory system."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
import re
from urllib.parse import unquote

from eval.common import CATEGORIES, ROOT, STATUSES, digest, read_jsonl, system_input
from eval.reference_check import validate_reference_check


def require(condition, message):
    if not condition:
        raise ValueError(message)


def timestamp(value):
    require(isinstance(value, str) and value.endswith("Z"), f"Invalid UTC timestamp: {value}")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_case(case, policy):
    ident = case["id"]
    require(case["schema_version"] == "1.0.0", f"{ident}: schema version")
    require(case["category"] in CATEGORIES, f"{ident}: category")
    require(case["split"] in {"visible", "holdout", "development"}, f"{ident}: split")
    require(case["contract_ids"] and all(re.fullmatch(r"C(?:[1-9]|10)", c) for c in case["contract_ids"]),
            f"{ident}: contract references")
    require(case["events"] and case["checks"], f"{ident}: empty case")
    delivery_ids = [e["delivery_id"] for e in case["events"]]
    require(len(set(delivery_ids)) == len(delivery_ids), f"{ident}: duplicate delivery")
    operations = {x["delivery_id"]: x["status"] for x in case["oracle"]["operations"]}
    require(set(operations) == set(delivery_ids), f"{ident}: operation labels")
    evidence, command_content = {}, {}
    for e in case["events"]:
        require(set(e) <= {"delivery_id", "id", "op", "at", "channel", "scope", "text", "expires_at"},
                f"{ident}: internal annotation in input")
        require(e["op"] in {"ingest", "forget"}, f"{ident}: operation")
        require(e["channel"] in policy["channels"], f"{ident}: channel")
        require(set(e["scope"]) == {"tenant", "subject", "namespace"}, f"{ident}: scope")
        require(all(isinstance(v, str) and v for v in e["scope"].values()), f"{ident}: empty scope")
        require(isinstance(e["text"], str) and e["text"].strip(), f"{ident}: empty text")
        timestamp(e["at"])
        if "expires_at" in e:
            require(timestamp(e["expires_at"]) > timestamp(e["at"]), f"{ident}: expiry before event")
        if e["op"] == "forget":
            require(policy["channels"][e["channel"]]["may_forget"], f"{ident}: unauthorized forget fixture")
        content = {k: v for k, v in e.items() if k != "delivery_id"}
        if e["id"] in command_content and command_content[e["id"]] != content:
            require(operations[e["delivery_id"]] == "id_conflict", f"{ident}: unlabelled conflicting ID")
        else:
            command_content[e["id"]] = content
        if e["op"] == "ingest" and operations[e["delivery_id"]] != "id_conflict":
            evidence.setdefault(e["id"], e)
    labels = case["oracle"]["security_labels"]
    require(len(labels) == len(evidence), f"{ident}: duplicate or missing security label")
    require({x["event_id"] for x in labels} == set(evidence), f"{ident}: security labels")
    require(all(type(x["attack"]) is bool for x in labels), f"{ident}: invalid security label")
    qids = []
    for q in case["checks"]:
        qids.append(q["id"])
        n = q["after_event"]
        require(type(n) is int and 0 < n <= len(case["events"]), f"{ident}: checkpoint")
        require(set(q["input"]) == {"scope", "now", "text", "token_budget"}, f"{ident}: input fields")
        require(64 <= q["input"]["token_budget"] <= 2048, f"{ident}: token limit")
        now = timestamp(q["input"]["now"])
        expected = q["expected"]
        require(expected["status"] in STATUSES, f"{ident}: answer status")
        require(expected["status"] == "found" or not expected["required_facts"], f"{ident}: facts in non-found answer")
        require(expected["status"] != "found" or expected["required_facts"], f"{ident}: vacuous found answer")
        prefix = case["events"][:n]
        available = {e["id"] for e in prefix if e["op"] == "ingest"}
        for f in expected["required_facts"]:
            require(f["attribute"] and f["value"] and f["source_ids"], f"{ident}: empty fact")
            require(f["value"] not in expected["forbidden_facts"] + expected["sensitive_values"],
                    f"{ident}: inconsistent labels")
            for sid in f["source_ids"]:
                require(sid in available, f"{ident}: future or missing source")
                src = evidence[sid]
                require(src["scope"] == q["input"]["scope"], f"{ident}: cross-scope ground truth")
                require(timestamp(src["at"]) <= now, f"{ident}: future event used as current evidence")
                if "expires_at" in src:
                    require(now < timestamp(src["expires_at"]), f"{ident}: expired required fact")
        require(set(expected["conflict_source_ids"]) <= available, f"{ident}: conflict source")
    require(len(set(qids)) == len(qids), f"{ident}: duplicate question")
    if case["category"] == "deletion":
        purposes = {q["purpose"] for q in case["checks"]}
        require({"before_forget", "retained_control"} <= purposes, f"{ident}: missing deletion controls")
        require(bool(purposes & {"after_forget", "after_ambiguous_forget"}), f"{ident}: missing deletion question")
    require(set(system_input(case)) == {"events", "queries"}, f"{ident}: export whitelist")
    return evidence


def validate_dataset(include_holdout=False):
    manifest = json.loads((ROOT / "eval/manifest.json").read_text())
    policy = json.loads((ROOT / "eval/source_policy.json").read_text())
    if manifest["freeze_status"] == "frozen":
        for name, wanted in manifest["method_sha256"].items():
            require(digest(ROOT / name) == wanted, f"Frozen method changed: {name}")
    for name, expected_hash in manifest["public_sha256"].items():
        require(digest(ROOT / "eval" / name) == expected_hash, f"Changed snapshot: {name}")
    api_cases = read_jsonl(ROOT / "eval/api_contract_cases.jsonl")
    require(len(api_cases) == 12 and len({x["id"] for x in api_cases}) == 12, "API contract fixture count")
    for case in api_cases:
        require(case["expected"]["confirmed"] is False and case["expected"]["state_change"] is False,
                "Rejected request must not confirm a mutation")
    visible = read_jsonl(ROOT / "eval/visible.jsonl")
    development = read_jsonl(ROOT / "eval/development.jsonl")
    require(len(visible) == 120 and len(development) == 20, "Wrong visible/development count")
    rows = visible + development
    private_status = "not_opened"
    if include_holdout:
        private = ROOT / manifest["holdout"]["location"].split(" (")[0]
        require(digest(private) == manifest["holdout"]["sha256"], "Changed holdout")
        holdout = read_jsonl(private)
        require(len(holdout) == 80, "Wrong holdout count")
        require(not ({x["family_id"] for x in visible} & {x["family_id"] for x in holdout}),
                "Family leakage")
        require(Counter(x["category"] for x in holdout) == {k: 8 for k in CATEGORIES}, "Holdout composition")
        rows += holdout
        private_status = "structural_validation_only_no_system_run"
    require(len({c["id"] for c in rows}) == len(rows), "Duplicate case ID")
    require(Counter(x["category"] for x in visible) == {k: 12 for k in CATEGORIES}, "Visible composition")
    families = Counter(x["family_id"] for x in visible)
    require(len(families) == 30 and set(families.values()) == {4}, "Family composition")
    require(not ({x["family_id"] for x in visible} & {x["family_id"] for x in development}), "Development family overlap")
    channel_labels = defaultdict(Counter)
    for case in rows:
        evidence = validate_case(case, policy)
        if case["split"] == "visible":
            for label in case["oracle"]["security_labels"]:
                channel_labels[evidence[label["event_id"]]["channel"]][label["attack"]] += 1
    require(all(v[True] and v[False] for v in channel_labels.values()), "Source-only shortcut can reveal attack labels")
    kt1 = read_jsonl(ROOT / "eval/kt1_examples.jsonl")
    lookup = {c["id"]: c for c in visible}
    require(len(kt1) == 20 and len({x["id"] for x in kt1}) == 20, "KT1 must have 20 distinct stories")
    require(Counter(x["category"] for x in kt1) == {k: 2 for k in CATEGORIES}, "KT1 composition")
    for case in kt1:
        require(lookup.get(case["id"]) == case, "KT1 differs from visible")
    for name, categories in (
        ("deletion_cases.jsonl", {"deletion"}),
        ("poisoning_cases.jsonl", {"poisoning", "benign_sources"}),
    ):
        require(read_jsonl(ROOT / "eval" / name) == [c for c in visible if c["category"] in categories],
                f"Subset mismatch: {name}")
    tasks = read_jsonl(ROOT / "eval/annotations/tasks.jsonl")
    require(len(tasks) == 40 and len({x["item_id"] for x in tasks}) == 40, "Annotation sample")
    require(Counter(lookup[x["case_id"]]["category"] for x in tasks) == {k: 4 for k in CATEGORIES},
            "Annotation stratification")
    for task in tasks:
        case = lookup[task["case_id"]]
        q = next(q for q in case["checks"] if q["id"] == task["check_id"])
        require(task["events"] == case["events"][:q["after_event"]] and task["question"] == q["input"],
                "Annotation task differs from case")
        require(set(task) == {"item_id", "case_id", "check_id", "events", "question"}, "Labels leaked to annotator")
    review = json.loads((ROOT / "eval/annotations/reference_check/review.json").read_text())
    checked = validate_reference_check(tasks, visible, review,
                                       tasks_sha256=digest(ROOT / "eval/annotations/tasks.jsonl"))
    documents = [ROOT / "README.md", ROOT / "design_doc.md", ROOT / "eval/README.md"]
    documents += sorted((ROOT / "docs").rglob("*.md"))
    documents += sorted(path for path in (ROOT / "eval").rglob("*.md")
                        if path != ROOT / "eval/README.md"
                        and not any(part in {"filled", "runs"} or part.startswith(".")
                                    for part in path.relative_to(ROOT / "eval").parts))
    for path in documents:
        text = path.read_text()
        require(text.count(chr(96) * 3) % 2 == 0, f"Unclosed code fence: {path.name}")
        for link in re.findall(r"\]\(([^)]+)\)", text):
            if "://" not in link and not link.startswith("#"):
                target = unquote(link.split("#")[0])
                require((path.parent / target).exists(), f"Broken local link in {path.name}: {link}")
    return {
        "status": "structurally_valid_not_a_service_evaluation",
        "visible": 120, "private_holdout": 80, "development": 20, "kt1": 20,
        "annotation_tasks": 40, "api_contract_fixtures": 12, "holdout_check": private_status,
        "reference_checks": checked, "freeze_status": manifest["freeze_status"],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--include-holdout", action="store_true",
                        help="Final structural check of the separate holdout; never prints contents")
    args = parser.parse_args()
    print(json.dumps(validate_dataset(args.include_holdout), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
