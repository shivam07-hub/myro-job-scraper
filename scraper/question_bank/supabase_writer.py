from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import requests

from question_bank.models import SkillRef


_REQUIRED_COLUMNS = {
    "skill_id",
    "skill_key",
    "level",
    "question_text",
    "options",
    "correct_index",
    "explanation",
    "source_url",
    "dedupe_hash",
    "status",
}
_DB_FIELDS = (
    "skill_id",
    "skill_key",
    "level",
    "question_text",
    "options",
    "correct_index",
    "explanation",
    "source_url",
    "dedupe_hash",
    "status",
)
_BATCH_SIZE = 100


@dataclass(frozen=True)
class PublishResult:
    planned: int
    written: int
    skipped: int


def _row_key(row: dict) -> tuple[int, int, str]:
    return (
        int(row["skill_id"]),
        int(row["level"]),
        str(row["dedupe_hash"]),
    )


def plan_upserts(incoming_rows: Iterable[dict], existing_rows: Iterable[dict]) -> list[dict]:
    existing = {_row_key(row): row for row in existing_rows}
    planned: dict[tuple[int, int, str], dict] = {}
    for row in incoming_rows:
        key = _row_key(row)
        current = existing.get(key)
        if current and current.get("status") == "active":
            continue
        if current and current.get("status") == "review" and row.get("status") != "active":
            continue
        planned[key] = row
    return list(planned.values())


class QuestionBankSupabase:
    def __init__(self, base_url: str, service_key: str, *, session=None) -> None:
        if not base_url or not service_key:
            raise ValueError("Supabase URL and service key are required")
        self.base_url = base_url.rstrip("/")
        self.service_key = service_key
        self.session = session or requests.Session()
        self.headers = {
            "apikey": service_key,
            "Authorization": f"Bearer {service_key}",
        }

    def preflight(self) -> None:
        response = self.session.get(
            f"{self.base_url}/rest/v1/",
            headers={**self.headers, "Accept": "application/openapi+json"},
            timeout=30,
        )
        response.raise_for_status()
        spec = response.json()
        schemas = spec.get("definitions") or spec.get("components", {}).get("schemas") or {}
        table = schemas.get("skill_questions") or schemas.get("public.skill_questions") or {}
        columns = set((table.get("properties") or {}).keys())
        missing = sorted(_REQUIRED_COLUMNS - columns)
        if missing:
            raise RuntimeError(
                "skill_questions is missing required columns: " + ", ".join(missing)
            )

    def resolve_skills(self, skill_keys: Iterable[str]) -> dict[str, SkillRef]:
        requested = tuple(dict.fromkeys(skill_keys))
        encoded = ",".join(f'"{key.replace(chr(34), chr(92) + chr(34))}"' for key in requested)
        response = self.session.get(
            f"{self.base_url}/rest/v1/skills",
            params={
                "select": "id,taxonomy_key,description",
                "taxonomy_key": f"in.({encoded})",
            },
            headers=self.headers,
            timeout=30,
        )
        response.raise_for_status()
        rows = response.json() or []
        result = {
            row["taxonomy_key"]: SkillRef(
                skill_id=int(row["id"]),
                skill_key=row["taxonomy_key"],
                description=str(row.get("description") or ""),
            )
            for row in rows
            if row.get("id") is not None and row.get("taxonomy_key")
        }
        missing = [key for key in requested if key not in result]
        if missing:
            raise RuntimeError("skills.taxonomy_key did not resolve: " + ", ".join(missing))
        return result

    def load_existing(self, skill_ids: Iterable[int]) -> list[dict]:
        ids = tuple(dict.fromkeys(int(value) for value in skill_ids))
        if not ids:
            return []
        rows: list[dict] = []
        start = 0
        page_size = 1000
        while True:
            response = self.session.get(
                f"{self.base_url}/rest/v1/skill_questions",
                params={
                    "select": ",".join(_DB_FIELDS),
                    "skill_id": f"in.({','.join(str(value) for value in ids)})",
                },
                headers={
                    **self.headers,
                    "Range": f"{start}-{start + page_size - 1}",
                },
                timeout=30,
            )
            response.raise_for_status()
            batch = response.json() or []
            rows.extend(batch)
            if len(batch) < page_size:
                break
            start += page_size
        return rows

    def publish(
        self,
        rows: Iterable[dict],
        *,
        existing_rows: Iterable[dict],
        dry_run: bool,
    ) -> PublishResult:
        incoming = list(rows)
        planned = plan_upserts(incoming, existing_rows)
        if dry_run or not planned:
            return PublishResult(
                planned=len(planned),
                written=0,
                skipped=len(incoming) - len(planned),
            )

        db_rows = [
            {field: row.get(field) for field in _DB_FIELDS}
            for row in planned
        ]
        for index in range(0, len(db_rows), _BATCH_SIZE):
            response = self.session.post(
                f"{self.base_url}/rest/v1/skill_questions",
                params={"on_conflict": "skill_id,level,dedupe_hash"},
                headers={
                    **self.headers,
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates,return=minimal",
                },
                json=db_rows[index:index + _BATCH_SIZE],
                timeout=60,
            )
            response.raise_for_status()

        return PublishResult(
            planned=len(planned),
            written=len(planned),
            skipped=len(incoming) - len(planned),
        )

