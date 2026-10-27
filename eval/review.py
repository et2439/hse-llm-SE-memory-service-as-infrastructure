"""Human adjudication after two signed independent forms. No automatic consensus."""
from __future__ import annotations

from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
from threading import RLock

from eval.agreement import load_form, report
from eval.annotation_store import RATERS, ConflictError, atomic_json, now, row_to_label, validate_label
from eval.common import ROOT, digest, normalize, read_jsonl


def signed_forms(root=ROOT):
    root = Path(root)
    tasks_path = root / "eval/annotations/tasks.jsonl"
    tasks = {t["item_id"]: t for t in read_jsonl(tasks_path)}
    folder = root / "eval/annotations/filled"
    evidence = {}
    raw = {}
    for reviewer, person in RATERS.items():
        path, meta_path = folder / f"{reviewer}.csv", folder / f"{reviewer}.meta.json"
        if not path.exists() or not meta_path.exists():
            raise ValueError("Сначала оба участника должны завершить и подтвердить свои бланки.")
        meta = json.loads(meta_path.read_text())
        signature = meta.get("signature") or {}
        if (meta.get("person") != person or meta.get("tasks_sha256") != digest(tasks_path)
                or signature.get("independent") is not True or signature.get("person") != person
                or not signature.get("completed_at") or signature.get("form_sha256") != digest(path)):
            raise ValueError("Один из бланков не подтверждён либо изменён после подтверждения.")
        labels = load_form(path, tasks)
        if any(v is None or v["evidence"] is None or v["forgotten"] is None for v in labels.values()):
            raise ValueError("Нужна полная разметка значений, источников и целей удаления.")
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if any(r["annotator"] != person for r in rows):
            raise ValueError("Имя в строках бланка не совпадает с подтверждением.")
        raw[reviewer] = {r["item_id"]: row_to_label(r) for r in rows}
        evidence[reviewer] = {"csv_sha256": digest(path), "metadata_sha256": digest(meta_path),
                              "person": person, "completed_at": signature["completed_at"]}
    agreement = report(folder / "a.csv", folder / "b.csv", tasks_path)
    return tasks, raw, evidence, agreement


def reference_label(task, case):
    q = next(c for c in case["checks"] if c["id"] == task["check_id"])
    operations = {op["delivery_id"]: op["status"] for op in case["oracle"]["operations"]}
    confirmed_forget = any(e["op"] == "forget" and e["scope"] == task["question"]["scope"]
                           and operations.get(e["delivery_id"]) == "accepted" for e in task["events"])
    values = [normalize(v) for v in q["expected"]["sensitive_values"]] if confirmed_forget else []
    forgotten = sorted({e["id"] for e in task["events"] if e["op"] == "ingest"
                        and e["scope"] == task["question"]["scope"]
                        and any(v in normalize(e["text"]) for v in values)})
    available = {e["id"] for e in task["events"] if e["op"] == "ingest"}
    return {"status": q["expected"]["status"],
            "facts": [{"value": f["value"], "source_ids": f["source_ids"]} for f in q["expected"]["required_facts"]],
            "attack_event_ids": sorted(x["event_id"] for x in case["oracle"]["security_labels"]
                                       if x["attack"] and x["event_id"] in available),
            "forgotten_event_ids": forgotten, "comment": ""}


def resolution_digest(document):
    value = deepcopy(document)
    value["signature"] = None
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


class ReviewStore:
    def __init__(self, *, root=ROOT):
        self.root = Path(root)
        self.directory = self.root / "eval/annotations/filled"
        self.path = self.directory / "resolution.json"
        self.lock = RLock()
        self.tasks, self.raw, self.evidence, self.agreement = signed_forms(self.root)
        self.cases = {c["id"]: c for c in read_jsonl(self.root / "eval/visible.jsonl")}
        if not self.path.exists():
            document = {"version": "1.0", "created_at": now(),
                        "tasks_sha256": digest(self.root / "eval/annotations/tasks.jsonl"),
                        "original_forms": self.evidence, "agreement_before_discussion": self.agreement,
                        "signature": None,
                        "items": [{"item_id": i, "case_id": t["case_id"], "check_id": t["check_id"],
                                   "answer_a": self.raw["a"][i], "answer_b": self.raw["b"][i],
                                   "resolved": None, "confirmed_by": "", "reason": "", "reviewed_at": None}
                                  for i, t in self.tasks.items()]}
            atomic_json(self.path, document)
        self._read()

    def frozen(self):
        return json.loads((self.root / "eval/manifest.json").read_text())["freeze_status"] == "frozen"

    def _read(self):
        document = json.loads(self.path.read_text())
        if (document["tasks_sha256"] != digest(self.root / "eval/annotations/tasks.jsonl")
                or document["original_forms"] != self.evidence):
            raise ValueError("Исходные бланки или задания изменились. Старый разбор сохранён.")
        if {r["item_id"] for r in document["items"]} != set(self.tasks) or len(document["items"]) != len(self.tasks):
            raise ValueError("Неполный список заданий разбора.")
        for r in document["items"]:
            if r["answer_a"] != self.raw["a"][r["item_id"]] or r["answer_b"] != self.raw["b"][r["item_id"]]:
                raise ValueError("Первоначальные ответы изменены в протоколе разбора.")
        return document

    def revision(self):
        return digest(self.path)

    def state(self):
        with self.lock:
            d = self._read()
            return {
                "mode": "review", "person": "Совместный разбор", "revision": self.revision(),
                "signed": d["signature"] is not None, "locked": self.frozen(),
                "completed": [r["item_id"] for r in d["items"] if r["resolved"] is not None],
                "agreement": self.agreement, "people": list(RATERS.values()),
                "items": [{"item_id": r["item_id"], "events": self.tasks[r["item_id"]]["events"],
                           "question": self.tasks[r["item_id"]]["question"],
                           "answer": r["resolved"], "draft": None,
                           "answer_a": r["answer_a"], "answer_b": r["answer_b"],
                           "reference": reference_label(self.tasks[r["item_id"]], self.cases[r["case_id"]]),
                           "confirmed_by": r["confirmed_by"], "reason": r["reason"]}
                          for r in d["items"]],
            }

    def mutate(self, payload):
        with self.lock:
            if self.frozen():
                raise ValueError("КТ2 зафиксирована. Разбор доступен для чтения.")
            if payload.get("revision") != self.revision():
                raise ConflictError("Разбор изменён в другой вкладке. Обновите страницу.")
            d = self._read()
            action = payload.get("action")
            if d["signature"] is not None:
                raise ValueError("Разбор уже подтверждён. Для изменений нужна новая версия.")
            if action == "complete":
                item_id = payload.get("item_id")
                if item_id not in self.tasks:
                    raise ValueError("Неизвестное задание.")
                validate_label(payload.get("label"), self.tasks[item_id])
                if payload.get("confirmed_by") not in RATERS.values() or len(payload.get("reason", "").strip()) < 5:
                    raise ValueError("Укажите проверившего участника и основание решения.")
                for row in d["items"]:
                    if row["item_id"] == item_id:
                        row.update(resolved=payload["label"], confirmed_by=payload["confirmed_by"],
                                   reason=payload["reason"].strip(), reviewed_at=now())
            elif action == "sign":
                if any(r["resolved"] is None for r in d["items"]):
                    raise ValueError("Проверьте все задания, включая совпавшие ответы.")
                if payload.get("person") not in RATERS.values() or payload.get("checked_all") is not True:
                    raise ValueError("Подтвердите проверку и укажите своё имя.")
                d["signature"] = {"person": payload["person"], "confirmed_at": now(),
                                  "resolution_sha256": resolution_digest(d)}
            else:
                raise ValueError("В режиме разбора сохраните итоговый ответ или подтвердите всю проверку.")
            atomic_json(self.path, d)
            return self.state()

    def export(self):
        return self.path.read_bytes()
