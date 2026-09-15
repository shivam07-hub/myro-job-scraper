from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_SENSITIVE_KEYS = {
    "candidate_text",
    "raw_text",
    "source_text",
    "source_prose",
}


def _assert_copyright_safe(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).casefold() in _SENSITIVE_KEYS:
                raise ValueError(f"copyright-sensitive field cannot be persisted: {key}")
            _assert_copyright_safe(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            _assert_copyright_safe(child)


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _append_jsonl_atomic(path: Path, row: dict) -> None:
    _assert_copyright_safe(row)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = _read_jsonl(path)
    rows.append(row)
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in rows)
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


class RunState:
    def __init__(self, base_dir: Path, run_id: str) -> None:
        if not run_id or "/" in run_id or "\\" in run_id:
            raise ValueError("run_id must be a simple non-empty name")
        self.run_id = run_id
        self.run_dir = base_dir / run_id
        self.run_dir.mkdir(parents=True, exist_ok=True)

    @property
    def normalized_path(self) -> Path:
        return self.run_dir / "normalized.jsonl"

    @property
    def verified_path(self) -> Path:
        return self.run_dir / "verified.jsonl"

    @property
    def rejected_path(self) -> Path:
        return self.run_dir / "rejected.jsonl"

    def append_normalized(self, row: dict) -> None:
        _append_jsonl_atomic(self.normalized_path, row)

    def append_verified(self, row: dict) -> None:
        _append_jsonl_atomic(self.verified_path, row)

    def append_rejected(self, row: dict) -> None:
        _append_jsonl_atomic(self.rejected_path, row)

    def normalized_by_hash(self) -> dict[str, dict]:
        return {
            row["raw_hash"]: row
            for row in _read_jsonl(self.normalized_path)
            if row.get("raw_hash")
        }

    def completed_raw_hashes(self) -> set[str]:
        rows = _read_jsonl(self.verified_path) + _read_jsonl(self.rejected_path)
        return {row["raw_hash"] for row in rows if row.get("raw_hash")}

    def verified_rows(self) -> list[dict]:
        return _read_jsonl(self.verified_path)

    def rejected_rows(self) -> list[dict]:
        return _read_jsonl(self.rejected_path)

    def write_summary(self, summary: dict) -> Path:
        _assert_copyright_safe(summary)
        path = self.run_dir / "summary.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(summary, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
        return path

