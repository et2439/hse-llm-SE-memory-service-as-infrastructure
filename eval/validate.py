"""Validate the first 20 evaluation histories and their expected outcomes."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
import json
import re
from urllib.parse import unquote

from eval.common import CATEGORIES, ROOT, STATUSES, digest, read_jsonl, system_input


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



def main():
    manifest = json.loads((ROOT / "eval/manifest.json").read_text())
    for name, expected in manifest["public_sha256"].items():
        require(digest(ROOT / "eval" / name) == expected, "Changed file: " + name)
    cases = read_jsonl(ROOT / "eval/kt1_examples.jsonl")
    require(len(cases) == 20 and len({c["id"] for c in cases}) == 20, "Expected 20 stories")
    require(Counter(c["category"] for c in cases) == {c: 2 for c in CATEGORIES}, "Category counts")
    require(sum(len(c["checks"]) for c in cases) == 24, "Expected 24 questions")
    policy = json.loads((ROOT / "eval/source_policy.json").read_text())
    for case in cases:
        validate_case(case, policy)
    documents = [ROOT / "README.md", ROOT / "design_doc.md", ROOT / "eval/README.md"]
    documents += list((ROOT / "docs").rglob("*.md"))
    for path in documents:
        text = path.read_text()
        require(text.count(chr(96) * 3) % 2 == 0, "Unclosed code fence: " + str(path))
        for link in re.findall(r"\]\(([^)]+)\)", text):
            if "://" not in link and not link.startswith("#"):
                target = unquote(link.split("#")[0])
                require((path.parent / target).exists(), "Broken local link: " + link)
    print(json.dumps({"checkpoint": "CP-1", "stories": 20, "questions": 24,
                      "status": "valid_data_not_service_results"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
