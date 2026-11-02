"""Shared file and normalization helpers; no network or model calls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = (
    "recall", "update", "temporal", "conflict", "unknown", "long_context",
    "deletion", "poisoning", "benign_sources", "isolation_retry",
)
STATUSES = {"found", "unknown", "conflict", "needs_clarification", "denied"}


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{number}: {exc.msg}") from exc
    return rows


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    return re.sub(r"\s+", " ", value).strip(" \t\r\n.,;:!?\"'«»")


def system_input(case: dict) -> dict:
    """Whitelist only transport events and timed queries; never export labels."""
    event_fields = {"delivery_id", "id", "op", "at", "channel", "scope", "text", "expires_at"}
    query_fields = {"scope", "now", "text", "token_budget"}
    def clean(value, allowed):
        result = {key: value[key] for key in allowed if key in value}
        if "scope" in result:
            result["scope"] = {key: result["scope"][key] for key in ("tenant", "subject", "namespace")}
        return result
    return {
        "events": [clean(e, event_fields) for e in case["events"]],
        "queries": [{"after_event": c["after_event"], "input": clean(c["input"], query_fields)}
                    for c in case["checks"]],
    }
