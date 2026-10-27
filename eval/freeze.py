"""Freeze the declared reference procedure and its verified evidence."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import zipfile

from eval.annotation_store import RATERS, atomic_json, now, validate_label
from eval.common import ROOT, digest, normalize, read_jsonl
from eval.review import reference_label, resolution_digest, signed_forms
from eval.validate import validate_case

METHOD_FILES = (
    "eval/common.py", "eval/validate.py", "eval/export_inputs.py", "eval/agreement.py",
    "eval/annotation_store.py", "eval/review.py", "eval/freeze.py",
    "eval/protocol.json", "eval/answer_instructions.txt", "docs/kt2.md",
    "docs/annotation_guide.md", "design_doc.md",
    "README.md", "docs/local_workflow.md", "docs/submission_checklist.md", "eval/README.md",
)


def pack_closed(root=ROOT):
    """Copy an already-authored holdout as opaque bytes. Never parse or reveal its rows."""
    root = Path(root)
    manifest = json.loads((root / "eval/manifest.json").read_text())
    path = root / manifest["holdout"]["location"].split(" (")[0]
    if digest(path) != manifest["holdout"]["sha256"]:
        raise ValueError("Контрольная сумма отложенной части изменилась.")
    archive = root / ".eval_private/kt2-holdout-closed.zip"
    meta_path = root / ".eval_private/closed-package.json"
    receipt = root / ".eval_private/custody.json"
    if archive.exists():
        if not meta_path.exists():
            raise ValueError("Закрытый пакет уже существует без метаданных. Сохраните его; автоматическая перезапись запрещена.")
        meta = json.loads(meta_path.read_text())
        if meta["holdout_sha256"] != manifest["holdout"]["sha256"] or meta["archive_sha256"] != digest(archive):
            raise ValueError("Закрытый пакет изменился. Нужен явный разбор версии.")
        confirmed = json.loads(receipt.read_text()).get("confirmed", False) if receipt.exists() else False
        return {**meta, "archive": str(archive), "custody_confirmed": confirmed, "contents_not_parsed": True}
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.write(path, "holdout.jsonl")
        z.writestr("receipt-instructions.txt",
                   "Отложенная часть: 80 историй. Не открывать для разработки до КТ4.\n"
                   "SHA-256 holdout.jsonl: " + manifest["holdout"]["sha256"] + "\n")
    atomic_json(meta_path, {"archive_sha256": digest(archive), "holdout_sha256": manifest["holdout"]["sha256"]})
    if not receipt.exists():
        atomic_json(receipt, {"custodian": RATERS["a"], "archive_sha256": digest(archive),
                              "received_by": "", "confirmed_at": None, "confirmed": False})
    return {"archive": str(archive), "archive_sha256": digest(archive),
            "holdout_sha256": manifest["holdout"]["sha256"],
            "custody_confirmed": False, "contents_not_parsed": True}


def jsonl_bytes(rows):
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows).encode()


def plan_construction_freeze(root, manifest, protocol):
    """Construction labels stay unchanged; freeze the completed reference check."""
    truth = protocol.get("ground_truth", {})
    if truth.get("method") != "synthetic_by_construction":
        raise ValueError("Нужно указать способ задания эталонов.")
    policy = json.loads((root / "eval/source_policy.json").read_text())
    cases = read_jsonl(root / "eval/visible.jsonl")
    for case in cases:
        if case.get("provenance") not in {"synthetic_by_construction", "synthetic_by_construction_not_human_annotated"}:
            raise ValueError("Происхождение эталона не соответствует выбранной методике.")
        validate_case(case, policy)
    tasks = {t["item_id"]: t for t in read_jsonl(root / "eval/annotations/tasks.jsonl")}
    audit_path = root / "eval/annotations/reference_check/review.json"
    audit = json.loads(audit_path.read_text())
    if (audit.get("status") != "final_reference_check"
            or audit.get("review_kind") != "reference_consistency_check"
            or audit.get("human_signatures") is not None
            or audit.get("inter_annotator_agreement") is not None
            or audit.get("tasks_sha256") != digest(root / "eval/annotations/tasks.jsonl")):
        raise ValueError("Нужен завершённый протокол проверки эталонов.")
    items = audit["items"]
    if len(items) != len(tasks) or {r["item_id"] for r in items} != set(tasks):
        raise ValueError("Проверка должна покрывать всю заявленную подвыборку.")
    assigned = Counter(r["assignment_key"] for r in items)
    if set(assigned) != {"artem", "vladislav"} or len(set(assigned.values())) != 1:
        raise ValueError("Комплекты должны быть распределены поровну между ответственными.")
    by_id = {c["id"]: c for c in cases}
    for row in items:
        task = tasks[row["item_id"]]
        if row.get("human_confirmed") not in (None, False):
            raise ValueError("Неподтверждённые атрибуты проверки: " + row["item_id"])
        actual = row["label"]
        validate_label(actual, task)
        expected = reference_label(task, by_id[task["case_id"]])
        facts = lambda x: {normalize(f["value"]): set(f["source_ids"]) for f in x["facts"]}
        if (actual["status"] != expected["status"] or facts(actual) != facts(expected)
                or any(set(actual[k]) != set(expected[k]) for k in ("attack_event_ids", "forgotten_event_ids"))):
            raise ValueError("Не разобрано расхождение проверки: " + row["item_id"])
    closed = json.loads((root / ".eval_private/closed-package.json").read_text())
    archive = root / ".eval_private/kt2-holdout-closed.zip"
    holdout = root / manifest["holdout"]["location"].split(" (")[0]
    if (digest(holdout) != manifest["holdout"]["sha256"]
            or closed["holdout_sha256"] != manifest["holdout"]["sha256"]
            or closed["archive_sha256"] != digest(archive)):
        raise ValueError("Закрытый пакет и исходная отложенная часть должны совпадать с зафиксированными суммами.")
    version = manifest["dataset_version"].split("-")[0]
    frozen_at = now()
    new_manifest = deepcopy(manifest)
    new_manifest.update(freeze_status="frozen", dataset_version=version, frozen_at=frozen_at,
                        previous_candidate_version=manifest["dataset_version"],
                        ground_truth=deepcopy(truth), publication_status="local_pr_ready")
    new_manifest["annotation"].update(status="reference_check_complete", reviewed_cases=len(items),
                                      review_path="annotations/reference_check/review.json")
    new_manifest["holdout"].update(local_package_prepared=True, local_package_sha256=closed["archive_sha256"],
                                  external_delivery_confirmed=False)
    protocol = deepcopy(protocol)
    protocol.update(status="frozen", dataset_version=version, frozen_at=frozen_at)
    certificate = {"status": "frozen", "dataset_version": version, "frozen_at": frozen_at,
                   "ground_truth_method": truth["method"], "checked_questions": len(items),
                   "audit_sha256": digest(audit_path), "holdout_sha256": manifest["holdout"]["sha256"],
                   "closed_archive_sha256": closed["archive_sha256"], "heldout_contents_parsed": False,
                   "external_delivery_confirmed": False, "service_evaluation_performed": False}
    updates = {"eval/protocol.json": (json.dumps(protocol, ensure_ascii=False, indent=2) + "\n").encode(),
               "eval/release.json": (json.dumps(certificate, ensure_ascii=False, indent=2) + "\n").encode()}
    new_manifest["method_sha256"] = {
        p: hashlib.sha256(updates[p]).hexdigest() if p in updates else digest(root / p) for p in METHOD_FILES}
    for relative, content in updates.items():
        new_manifest["public_sha256"][relative.removeprefix("eval/")] = hashlib.sha256(content).hexdigest()
    updates["eval/manifest.json"] = (json.dumps(new_manifest, ensure_ascii=False, indent=2) + "\n").encode()
    return updates, {"status": "ready_to_freeze", "ground_truth_method": truth["method"],
                     "checked_questions": len(items),
                     "version": version, "heldout_contents_not_opened": True}


def plan_freeze(root=ROOT):
    root = Path(root)
    path = root / "eval/manifest.json"
    manifest = json.loads(path.read_text())
    if manifest["freeze_status"] == "frozen":
        raise ValueError("Версия уже зафиксирована. Изменения требуют новой версии.")
    for name, expected in manifest["public_sha256"].items():
        if digest(root / "eval" / name) != expected:
            raise ValueError(f"Файл {name} изменён вне версии набора.")
    protocol = json.loads((root / "eval/protocol.json").read_text())
    if protocol.get("ground_truth", {}).get("method") == "synthetic_by_construction":
        return plan_construction_freeze(root, manifest, protocol)
    tasks, raw, forms, agreement = signed_forms(root)
    if not agreement["ready_for_adjudication"]:
        raise ValueError("Согласие ниже порога или не определено. Нужны уточнение инструкции и повторный независимый аудит.")
    resolution_path = root / "eval/annotations/filled/resolution.json"
    if not resolution_path.exists():
        raise ValueError("После разметки требуется совместный разбор.")
    resolution = json.loads(resolution_path.read_text())
    signature = resolution.get("signature") or {}
    if (resolution.get("original_forms") != forms
            or resolution.get("tasks_sha256") != digest(root / "eval/annotations/tasks.jsonl")
            or signature.get("person") not in RATERS.values()
            or not signature.get("confirmed_at")
            or signature.get("resolution_sha256") != resolution_digest(resolution)):
        raise ValueError("Разбор не подтверждён либо изменён после подтверждения.")
    rows = resolution["items"]
    if len(rows) != len(tasks) or {r["item_id"] for r in rows} != set(tasks):
        raise ValueError("Разбор должен содержать все задания, включая совпавшие ответы.")
    receipt_path = root / ".eval_private/custody.json"
    if not receipt_path.exists():
        raise ValueError("Сохраните закрытый пакет и подтвердите его хранение.")
    receipt = json.loads(receipt_path.read_text())
    archive = root / ".eval_private/kt2-holdout-closed.zip"
    if (receipt.get("confirmed") is not True or not receipt.get("confirmed_at")
            or not receipt.get("received_by") or not archive.exists()
            or receipt.get("archive_sha256") != digest(archive)):
        raise ValueError("Не подтверждено получение закрытой копии либо изменена её сумма.")
    policy = json.loads((root / "eval/source_policy.json").read_text())
    cases = deepcopy(read_jsonl(root / "eval/visible.jsonl"))
    by_id = {c["id"]: c for c in cases}
    changes = []
    for row in rows:
        item_id = row["item_id"]
        task = tasks[item_id]
        if (row["answer_a"] != raw["a"][item_id] or row["answer_b"] != raw["b"][item_id]
                or row.get("confirmed_by") not in RATERS.values() or not row.get("reason", "").strip()
                or row["resolved"] is None):
            raise ValueError("Нужны неизменные исходные ответы и подтверждённое решение по каждому заданию.")
        label = row["resolved"]
        validate_label(label, task)
        case = by_id[task["case_id"]]
        check = next(q for q in case["checks"] if q["id"] == task["check_id"])
        previous = deepcopy(check["expected"])
        reference = reference_label(task, case)
        if case["category"] == "deletion" and (
                set(label["forgotten_event_ids"]) != set(reference["forgotten_event_ids"])
                or label["status"] != reference["status"]):
            raise ValueError("Изменение смысла удаления затрагивает контрольные вопросы: "
                             + item_id + ". Сначала явно исправьте всю историю и повторите её аудит.")
        old_by_value = {normalize(f["value"]): f for f in check["expected"]["required_facts"]}
        facts = [{"attribute": old_by_value.get(normalize(f["value"]), {}).get("attribute", "проверенное сведение"),
                  "value": f["value"], "source_ids": f["source_ids"]} for f in label["facts"]]
        check["expected"]["status"] = label["status"]
        check["expected"]["required_facts"] = facts
        accepted = {normalize(f["value"]) for f in facts}
        check["expected"]["forbidden_facts"] = [v for v in check["expected"]["forbidden_facts"]
                                                if normalize(v) not in accepted]
        for sec in case["oracle"]["security_labels"]:
            sec["attack"] = sec["event_id"] in label["attack_event_ids"]
        case["provenance"] = "synthetic_by_construction_selected_check_human_reviewed"
        case["human_review"] = {"item_id": item_id, "check_id": check["id"],
                                "confirmed_by": row["confirmed_by"], "reviewed_at": row["reviewed_at"]}
        validate_case(case, policy)
        changes.append({"item_id": item_id, "case_id": case["id"], "check_id": check["id"],
                        "confirmed_by": row["confirmed_by"], "reason": row["reason"],
                        "before": previous, "after": deepcopy(check["expected"])})
    # Construct every byte and validate before the first mutation.
    old_kt1 = read_jsonl(root / "eval/kt1_examples.jsonl")
    updates = {
        "eval/visible.jsonl": jsonl_bytes(cases),
        "eval/kt1_examples.jsonl": jsonl_bytes([by_id[c["id"]] for c in old_kt1]),
        "eval/deletion_cases.jsonl": jsonl_bytes([c for c in cases if c["category"] == "deletion"]),
        "eval/poisoning_cases.jsonl": jsonl_bytes([c for c in cases if c["category"] in {"poisoning", "benign_sources"}]),
    }
    public_review = {"version": "1.0", "original_forms": forms,
                     "agreement_before_discussion": agreement, "signature": signature,
                     "items": rows, "label_changes": changes}
    updates["eval/annotations/reviewed.json"] = (json.dumps(public_review, ensure_ascii=False, indent=2) + "\n").encode()
    new_manifest = deepcopy(manifest)
    new_manifest.update(freeze_status="frozen", dataset_version=manifest["dataset_version"].split("-")[0] + "-reviewed", frozen_at=now(),
                        previous_candidate_version=manifest["dataset_version"])
    new_manifest["annotation"].update(status="reviewed_by_two_humans", agreement=agreement,
                                      reviewed_cases=len(rows), review_path="annotations/reviewed.json")
    new_manifest["holdout"]["custody"] = {"confirmed_at": receipt["confirmed_at"],
                                         "archive_sha256": receipt["archive_sha256"]}
    protocol = json.loads((root / "eval/protocol.json").read_text())
    protocol.update(status="frozen", dataset_version=new_manifest["dataset_version"])
    protocol["annotation"].update(status="reviewed_by_two_humans", agreement=agreement)
    updates["eval/protocol.json"] = (json.dumps(protocol, ensure_ascii=False, indent=2) + "\n").encode()
    new_manifest["method_sha256"] = {
        p: hashlib.sha256(updates[p]).hexdigest() if p in updates else digest(root / p) for p in METHOD_FILES}
    for relative, content in updates.items():
        new_manifest["public_sha256"][relative.removeprefix("eval/")] = hashlib.sha256(content).hexdigest()
    updates["eval/manifest.json"] = (json.dumps(new_manifest, ensure_ascii=False, indent=2) + "\n").encode()
    return updates, {"status": "ready_to_freeze", "human_reviewed_cases": len(rows),
                     "version": new_manifest["dataset_version"], "heldout_contents_not_opened": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--pack-closed", action="store_true", help="Pack opaque holdout bytes; does not confirm custody")
    action.add_argument("--apply", action="store_true", help="Freeze the completed ground-truth procedure declared in protocol.json")
    action.add_argument("--confirm-custody", action="store_true", help="Human-only confirmation after keeping a separate closed copy")
    parser.add_argument("--received-by", default="")
    args = parser.parse_args()
    try:
        if args.confirm_custody:
            if not args.received_by.strip():
                raise ValueError("Укажите получателя после реального сохранения отдельной закрытой копии.")
            pack_closed()
            receipt_path = ROOT / ".eval_private/custody.json"
            receipt = json.loads(receipt_path.read_text())
            receipt.update(confirmed=True, received_by=args.received_by.strip(), confirmed_at=now())
            atomic_json(receipt_path, receipt)
            result = {"status": "custody_confirmed", "received_by": receipt["received_by"],
                      "note": "Подтверждение пользователя; сам факт внешней передачи скрипт не проверяет."}
        elif args.pack_closed:
            result = pack_closed()
        else:
            updates, result = plan_freeze()
            if args.apply:
                # A local recoverable snapshot preserves the candidate and signatures.
                backup = ROOT / ".eval_private" / ("before-freeze-" + now().replace(":", "-").replace(".", "-") + ".zip")
                with zipfile.ZipFile(backup, "w", compression=zipfile.ZIP_DEFLATED) as z:
                    for p in updates:
                        existing = ROOT / p
                        if existing.exists():
                            z.write(existing, p)
                for relative, content in updates.items():
                    (ROOT / relative).parent.mkdir(parents=True, exist_ok=True)
                    (ROOT / relative).write_bytes(content)
                result["status"] = "frozen"
                result["next_action"] = "Проверьте данные и пересоберите локальные комплекты CP-1/CP-2."
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except ValueError as exc:
        print(json.dumps({"status": "not_ready_to_freeze", "reason": str(exc)}, ensure_ascii=False, indent=2))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
