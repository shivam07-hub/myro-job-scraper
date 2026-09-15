"""Company × skill facts built from one completed source run."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any


def build_company_skill_facts(
    jobs: list[dict[str, Any]],
    *,
    skill_id_map: dict[str, int],
    source_run_id: str,
    company_id: str,
) -> list[dict[str, Any]]:
    aggregates: dict[int, dict[str, Any]] = {}
    for job in jobs:
        job_id = str(job.get("job_id") or "")
        if not job_id:
            continue
        role = str(job.get("role_domain") or "").strip()
        country = str(job.get("location_country") or "").strip()
        per_job = _job_skills(job, skill_id_map)
        for skill_id, level in per_job.items():
            bucket = aggregates.setdefault(
                skill_id,
                {
                    "job_ids": set(),
                    "levels": [],
                    "required_level_counts": Counter(),
                    "role_domain_counts": Counter(),
                    "location_country_counts": Counter(),
                },
            )
            bucket["job_ids"].add(job_id)
            bucket["levels"].append(level)
            bucket["required_level_counts"][str(level)] += 1
            if role:
                bucket["role_domain_counts"][role] += 1
            if country:
                bucket["location_country_counts"][country] += 1

    facts: list[dict[str, Any]] = []
    observed_at = datetime.now(timezone.utc).isoformat()
    for skill_id, bucket in sorted(aggregates.items()):
        levels = bucket["levels"]
        job_count = len(bucket["job_ids"])
        facts.append(
            {
                "source_run_id": source_run_id,
                "company_id": company_id,
                "skill_id": skill_id,
                "active_job_count": job_count,
                "primary_job_count": job_count,
                "average_required_level": round(sum(levels) / len(levels), 2),
                "required_level_counts": dict(bucket["required_level_counts"]),
                "role_domain_counts": dict(bucket["role_domain_counts"]),
                "location_counts": dict(bucket["location_country_counts"]),
                "observed_at": observed_at,
            }
        )
    return facts


def write_company_skill_facts(
    sb: Any,
    facts: list[dict[str, Any]],
    *,
    source_run_id: str,
    batch_size: int = 200,
) -> int:
    for start in range(0, len(facts), batch_size):
        sb.table("company_skill_run_facts").upsert(
            facts[start : start + batch_size],
            on_conflict="source_run_id,company_id,skill_id",
        ).execute()
    sb.rpc(
        "refresh_company_skill_profiles",
        {"p_source_run_id": source_run_id},
    ).execute()
    return len(facts)


def add_dormant_skill_facts(
    facts: list[dict[str, Any]],
    *,
    known_skill_ids: set[int],
    source_run_id: str,
    company_id: str,
) -> list[dict[str, Any]]:
    current_ids = {int(row["skill_id"]) for row in facts}
    observed_at = datetime.now(timezone.utc).isoformat()
    dormant = [
        {
            "source_run_id": source_run_id,
            "company_id": company_id,
            "skill_id": skill_id,
            "active_job_count": 0,
            "primary_job_count": 0,
            "average_required_level": None,
            "required_level_counts": {},
            "role_domain_counts": {},
            "location_counts": {},
            "observed_at": observed_at,
        }
        for skill_id in sorted(known_skill_ids - current_ids)
    ]
    return [*facts, *dormant]


def _job_skills(job: dict[str, Any], skill_id_map: dict[str, int]) -> dict[int, int]:
    raw = job.get("skills")
    entries = raw if isinstance(raw, list) and raw else [
        {"name": name, "required_level": 2}
        for name in (job.get("main_skills") or [])
    ]
    strongest: dict[int, int] = {}
    for entry in entries:
        if isinstance(entry, str):
            name, level = entry.strip(), 2
        elif isinstance(entry, dict):
            name = str(entry.get("name") or "").strip()
            try:
                level = int(entry.get("required_level") or 2)
            except (TypeError, ValueError):
                level = 2
        else:
            continue
        skill_id = skill_id_map.get(name)
        if not skill_id:
            continue
        level = min(4, max(1, level))
        strongest[skill_id] = max(level, strongest.get(skill_id, 0))
    return strongest
