"""Export a verified, company-wise job archive before guarded retention purges.

The exporter is deliberately read-only.  It captures the full retention candidate
set plus its skill edges, identifies jobs that must stay because a user has
interacted with them, and writes a manifest with hashes/counts for later purge
verification.

Usage:
    python export_job_archive.py --cutoff 20260531 --output-dir ../outputs/job_archive_20260715
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from supabase import Client, create_client


HERE = Path(__file__).resolve().parent
from environment import load_environment

load_environment()

PAGE_SIZE = 500
IN_BATCH_SIZE = 100
ARCHIVE_JOB_FIELDS = [
    "job_id",
    "job_title",
    "job_description",
    "company_name",
    "industry",
    "location",
    "apply_url",
    "main_skills",
    "side_skills",
    "batch_date",
    "first_seen",
    "last_seen",
    "is_active",
    "change_fingerprint",
    "role_domain",
    "industry_group",
    "location_city",
    "report_count",
    "location_raw",
    "location_country",
    "location_mode",
    "location_quality",
    "locations",
    "job_summary",
    "date_posted",
    "seniority_level",
    "work_mode",
    "min_years_experience",
    "max_years_experience",
    "ingestion_source",
    "source_platform",
    "quality_status",
    "source_url",
    "listing_confidence",
    "last_verified_live_at",
    "last_verification_attempt_at",
    "consecutive_complete_misses",
    "confidence_reason",
    "quarantined_at",
    "quarantine_until",
    "deletion_eligible_at",
    "retired_at",
    "reactivated_at",
    "lifecycle_updated_at",
    "company_id",
    "last_source_run_id",
    "source_content_hash",
    "enriched_source_hash",
    "job_content_hash",
    "enrichment_status",
    "enrichment_model",
    "enrichment_version",
    "enrichment_queued_at",
    "enrichment_started_at",
    "enriched_at",
    "enrichment_last_error",
    "enrichment_priority_requested_at",
]
PROTECTION_TABLES = {
    "user_match": "user_job_matches",
    "application": "job_applications",
    "feedback": "job_feedback_events",
    "report": "job_reports",
}


def chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def client() -> Client:
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_KEY are required in scraper/.env")
    return create_client(url, key)


def fetch_all(query: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    page = 0
    while True:
        response = query.range(page * PAGE_SIZE, (page + 1) * PAGE_SIZE - 1).execute()
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
        page += 1


def fetch_candidates(sb: Client, cutoff: int) -> list[dict[str, Any]]:
    select_fields = ",".join(ARCHIVE_JOB_FIELDS)
    query = (
        sb.table("jobs")
        .select(select_fields)
        .or_(f"is_active.eq.false,last_seen.lt.{cutoff}")
        .order("job_id")
    )
    return fetch_all(query)


def fetch_protection_reasons(sb: Client, job_ids: list[str]) -> dict[str, set[str]]:
    reasons: dict[str, set[str]] = defaultdict(set)
    candidate_ids = set(job_ids)
    for reason, table in PROTECTION_TABLES.items():
        # These user-interaction tables are small. Reading just their job IDs once
        # avoids hundreds of OR-list queries and keeps this export both faster and
        # easier to audit.
        rows = fetch_all(sb.table(table).select("job_id").order("job_id"))
        for row in rows:
            job_id = str(row.get("job_id") or "")
            if job_id in candidate_ids:
                reasons[job_id].add(reason)
    return reasons


def fetch_skill_names(sb: Client) -> dict[int, str]:
    rows = fetch_all(sb.table("skills").select("id,taxonomy_key").order("id"))
    return {
        int(row["id"]): str(row["taxonomy_key"])
        for row in rows
        if row.get("id") is not None and row.get("taxonomy_key")
    }


def fetch_skill_edges(sb: Client, job_ids: list[str], skill_names: dict[int, str]) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    for index, job_id_batch in enumerate(chunks(job_ids, IN_BATCH_SIZE), start=1):
        query = (
            sb.table("job_skills")
            .select("job_id,skill_id,is_primary,required_level")
            .in_("job_id", job_id_batch)
            .order("id")
        )
        for edge in fetch_all(query):
            skill_id = edge.get("skill_id")
            if skill_id is not None:
                edge["skill_name"] = skill_names.get(int(skill_id))
            edges.append(edge)
        if index % 25 == 0:
            print(f"  fetched skill edges for {min(index * IN_BATCH_SIZE, len(job_ids)):,}/{len(job_ids):,} jobs")
    return edges


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def save_json(path: Path, data: Any) -> None:
    with path.open("w", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, separators=(",", ":"))


def archive(cutoff: int, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    sb = client()

    print("Fetching retention candidates (read-only) …")
    jobs = fetch_candidates(sb, cutoff)
    if not jobs:
        raise SystemExit("No jobs matched the retention selector; no archive created.")
    job_ids = [str(job["job_id"]) for job in jobs]
    if len(job_ids) != len(set(job_ids)):
        raise SystemExit("Candidate export contains duplicate job IDs; refusing to create archive.")

    print(f"Fetching user-history guards for {len(jobs):,} jobs …")
    protection = fetch_protection_reasons(sb, job_ids)
    for job in jobs:
        reasons = sorted(protection.get(str(job["job_id"]), set()))
        job["preservation_reasons"] = reasons
        job["purge_eligible"] = not reasons
        job["archive_reason"] = "user_history_protected" if reasons else (
            "already_inactive" if job.get("is_active") is False else f"active_stale_before_{cutoff}"
        )
        job["description_characters"] = len(job.get("job_description") or "")

    print("Fetching canonical skill names …")
    skill_names = fetch_skill_names(sb)
    print("Fetching candidate skill edges …")
    skill_edges = fetch_skill_edges(sb, job_ids, skill_names)

    jobs_path = output_dir / "archive_jobs.json"
    skills_path = output_dir / "archive_job_skills.json"
    save_json(jobs_path, jobs)
    save_json(skills_path, skill_edges)

    by_company: Counter[str] = Counter(str(job.get("company_name") or "Unknown") for job in jobs)
    disposition_counts = Counter(
        "preserve_user_history" if not job["purge_eligible"] else (
            "archive_then_delete_inactive" if job.get("is_active") is False else "delist_then_archive_delete"
        )
        for job in jobs
    )
    manifest = {
        "archive_format": "job_archive_v1",
        "project_ref": "gipvxuugajkugntwkeiz",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "retention_cutoff_last_seen": cutoff,
        "selector": f"is_active = false OR last_seen < {cutoff}",
        "jobs": {
            "count": len(jobs),
            "distinct_companies": len(by_company),
            "purge_eligible": sum(1 for job in jobs if job["purge_eligible"]),
            "preserved_for_user_history": sum(1 for job in jobs if not job["purge_eligible"]),
            "description_characters": sum(job["description_characters"] for job in jobs),
            "descriptions_over_excel_cell_limit": sum(
                1 for job in jobs if job["description_characters"] > 32767
            ),
            "dispositions": dict(sorted(disposition_counts.items())),
            "sha256": sha256_file(jobs_path),
        },
        "job_skills": {
            "count": len(skill_edges),
            "sha256": sha256_file(skills_path),
        },
    }
    save_json(output_dir / "archive_manifest.json", manifest)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only job archive export for guarded retention purges")
    parser.add_argument("--cutoff", type=int, required=True, help="YYYYMMDD last_seen cutoff")
    parser.add_argument("--output-dir", type=Path, required=True, help="Directory for archive JSON and manifest")
    args = parser.parse_args()

    manifest = archive(args.cutoff, args.output_dir)
    print(
        "Archive complete: "
        f"{manifest['jobs']['count']:,} jobs, "
        f"{manifest['job_skills']['count']:,} skill edges, "
        f"{manifest['jobs']['purge_eligible']:,} purge-eligible, "
        f"{manifest['jobs']['preserved_for_user_history']:,} preserved."
    )


if __name__ == "__main__":
    main()
