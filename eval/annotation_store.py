"""Local per-person drafts and signed forms. This module never reads gold labels."""
from __future__ import annotations

import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import random
import tempfile
import zipfile
from threading import RLock

from eval.agreement import load_form
from eval.common import ROOT, digest, read_jsonl, system_input

RATERS = {"a": "Жбанов Артём Игоревич", "b": "Савченко Владислав Евгеньевич"}
FIELDS = ["item_id", "annotator", "status", "values_json", "evidence_json",
          "attack_event_ids_json", "forgotten_event_ids_json", "comment"]


def now():
    return datetime.now(timezone.utc).isoformat()


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(text)
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def csv_text(rows):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def blank_row(item_id, person):
    return {key: item_id if key == "item_id" else person if key == "annotator" else "" for key in FIELDS}


def row_to_label(row):
    if not row["status"]:
        return {"status": "", "facts": [], "attack_event_ids": [], "forgotten_event_ids": [], "comment": ""}
    return {"status": row["status"], "facts": json.loads(row.get("evidence_json") or "[]"),
            "attack_event_ids": json.loads(row["attack_event_ids_json"]),
            "forgotten_event_ids": json.loads(row.get("forgotten_event_ids_json") or "[]"),
            "comment": row.get("comment", "")}


def label_to_row(item_id, person, label):
    return {"item_id": item_id, "annotator": person, "status": label["status"],
            "values_json": json.dumps([f["value"] for f in label["facts"]], ensure_ascii=False),
            "evidence_json": json.dumps(label["facts"], ensure_ascii=False),
            "attack_event_ids_json": json.dumps(label["attack_event_ids"], ensure_ascii=False),
            "forgotten_event_ids_json": json.dumps(label["forgotten_event_ids"], ensure_ascii=False),
            "comment": label["comment"]}


def validate_label(label, task, *, complete=True):
    keys = {"status", "facts", "attack_event_ids", "forgotten_event_ids", "comment"}
    if not isinstance(label, dict) or set(label) != keys:
        raise ValueError("Неверный формат ответа.")
    if label["status"] not in {"", "found", "unknown", "conflict", "needs_clarification", "denied"}:
        raise ValueError("Выберите статус из списка.")
    if not isinstance(label["comment"], str) or len(label["comment"]) > 10000:
        raise ValueError("Комментарий слишком длинный.")
    events = {e["id"] for e in task["events"] if e["op"] == "ingest"}
    for key in ("facts", "attack_event_ids", "forgotten_event_ids"):
        if not isinstance(label[key], list) or len(label[key]) > 200:
            raise ValueError("Неверный список в ответе.")
    for key in ("attack_event_ids", "forgotten_event_ids"):
        values = label[key]
        if not all(isinstance(x, str) for x in values) or not set(values) <= events:
            raise ValueError("Выбрано неизвестное событие.")
        if len(set(values)) != len(values):
            raise ValueError("Событие выбрано дважды.")
    for fact in label["facts"]:
        if not isinstance(fact, dict) or set(fact) != {"value", "source_ids"}:
            raise ValueError("У сведения должны быть значение и источники.")
        if not isinstance(fact["value"], str) or len(fact["value"]) > 2000:
            raise ValueError("Неверное значение сведения.")
        if not isinstance(fact["source_ids"], list) or not all(isinstance(x, str) for x in fact["source_ids"]):
            raise ValueError("Неверные ссылки на источники.")
        if not set(fact["source_ids"]) <= events:
            raise ValueError("Источник не существует в показанной истории.")
        if complete and (not fact["value"].strip() or not fact["source_ids"]):
            raise ValueError("Для каждого сведения укажите значение и хотя бы один источник.")
    if not any(e["op"] == "forget" for e in task["events"]) and label["forgotten_event_ids"]:
        raise ValueError("В этой истории нет отдельной просьбы забыть сведения.")
    if complete:
        if not label["status"]:
            raise ValueError("Сначала выберите статус.")
        if label["status"] == "found" and not label["facts"]:
            raise ValueError("Укажите хотя бы одно найденное сведение.")
        if label["status"] != "found" and label["facts"]:
            raise ValueError("При этом статусе список утверждённых фактов должен быть пуст.")
        if label["status"] == "needs_clarification" and label["forgotten_event_ids"]:
            raise ValueError("При уточнении удаление ещё не подтверждено.")


class ConflictError(ValueError):
    pass


class AnnotationStore:
    def __init__(self, reviewer, *, tasks_path=None, directory=None, manifest_path=None):
        if reviewer not in RATERS:
            raise ValueError("Неизвестный участник.")
        self.reviewer, self.person = reviewer, RATERS[reviewer]
        self.tasks_path = Path(tasks_path or ROOT / "eval/annotations/tasks.jsonl")
        self.directory = Path(directory or ROOT / "eval/annotations/filled")
        self.manifest_path = Path(manifest_path or ROOT / "eval/manifest.json")
        self.path = self.directory / f"{reviewer}.csv"
        self.meta_path = self.directory / f"{reviewer}.meta.json"
        self.drafts_path = self.directory / f"{reviewer}.drafts.json"
        self.tasks = {t["item_id"]: t for t in read_jsonl(self.tasks_path)}
        self.lock = RLock()
        self.directory.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            atomic_text(self.path, csv_text([blank_row(i, self.person) for i in self.tasks]))
        if not self.meta_path.exists():
            atomic_json(self.meta_path, {"reviewer": reviewer, "person": self.person,
                                        "tasks_sha256": digest(self.tasks_path), "signature": None})
        self._read()

    def frozen(self):
        return self.manifest_path.exists() and json.loads(self.manifest_path.read_text())["freeze_status"] == "frozen"

    def revision(self):
        return hashlib.sha256(b"\0".join(p.read_bytes() if p.exists() else b""
                                       for p in (self.path, self.meta_path, self.drafts_path))).hexdigest()

    def _read(self):
        meta = json.loads(self.meta_path.read_text())
        if meta["person"] != self.person or meta["reviewer"] != self.reviewer:
            raise ValueError("Бланк принадлежит другому участнику.")
        if meta["tasks_sha256"] != digest(self.tasks_path):
            raise ValueError("Задания изменились. Старый бланк сохранён; требуется новая версия разметки.")
        if meta.get("signature") and meta["signature"].get("form_sha256") != digest(self.path):
            raise ValueError("Подтверждённый бланк изменён вручную. Исходная версия остаётся в originals.")
        with self.path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        # Validate completeness/IDs, but never compare a response with an oracle.
        completed = load_form(self.path, self.tasks)
        if any(row["annotator"] != self.person for row in rows):
            raise ValueError("В бланке изменено имя участника.")
        drafts = json.loads(self.drafts_path.read_text()) if self.drafts_path.exists() else {}
        return rows, meta, drafts, completed

    def state(self):
        with self.lock:
            rows, meta, drafts, completed = self._read()
            answers = {r["item_id"]: row_to_label(r) for r in rows}
            order = list(self.tasks)
            random.Random("memory-annotations-" + self.reviewer).shuffle(order)
            return {
                "mode": "annotation", "reviewer": self.reviewer, "person": self.person,
                "revision": self.revision(), "completed": [i for i, x in completed.items() if x is not None],
                "signed": meta["signature"] is not None, "locked": self.frozen(),
                "items": [{"item_id": i,
                           "events": system_input({"events": self.tasks[i]["events"], "checks": []})["events"],
                           "question": system_input({"events": [], "checks": [{"after_event": 0, "input": self.tasks[i]["question"]}]})["queries"][0]["input"],
                           "answer": answers[i],
                           "draft": drafts.get(i)} for i in order],
            }

    def mutate(self, payload):
        with self.lock:
            if self.frozen():
                raise ValueError("КТ2 зафиксирована. Изменения требуют новой версии.")
            if payload.get("revision") != self.revision():
                raise ConflictError("Бланк изменён в другой вкладке. Обновите страницу; сохранённые ответы не потеряны.")
            rows, meta, drafts, completed = self._read()
            action = payload.get("action")
            if action == "reopen":
                if not meta["signature"]:
                    raise ValueError("Бланк ещё не подписан.")
                meta["signature"] = None
                atomic_json(self.meta_path, meta)
                return self.state()
            if meta["signature"]:
                raise ValueError("Бланк подписан. Для правки сначала возобновите работу.")
            if action in {"draft", "complete"}:
                item_id, label = payload.get("item_id"), payload.get("label")
                if item_id not in self.tasks:
                    raise ValueError("Неизвестное задание.")
                validate_label(label, self.tasks[item_id], complete=action == "complete")
                if action == "draft":
                    drafts[item_id] = label
                else:
                    rows = [label_to_row(item_id, self.person, label) if r["item_id"] == item_id else r for r in rows]
                    atomic_text(self.path, csv_text(rows))
                    drafts.pop(item_id, None)
                atomic_json(self.drafts_path, drafts)
            elif action == "sign":
                if any(x is None for x in completed.values()) or drafts:
                    raise ValueError("Сначала сохраните все ответы и завершите черновики.")
                if payload.get("independent") is not True:
                    raise ValueError("Подтвердите независимую работу.")
                meta["signature"] = {"person": self.person, "completed_at": now(),
                                     "independent": True, "form_sha256": digest(self.path)}
                atomic_json(self.meta_path, meta)
                stamp = meta["signature"]["completed_at"].replace(":", "-").replace(".", "-")
                archive = self.directory / "originals" / f"{self.reviewer}-{stamp}"
                atomic_text(archive.with_suffix(".csv"), self.path.read_text())
                atomic_json(archive.with_suffix(".json"), meta)
            else:
                raise ValueError("Неизвестное действие.")
            return self.state()

    def export(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(self.path, self.path.name)
            archive.write(self.meta_path, self.meta_path.name)
            if self.drafts_path.exists():
                archive.write(self.drafts_path, self.drafts_path.name)
        return stream.getvalue()
