"""Evidence-gated listing lifecycle policy for completed company source runs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import logging
from pathlib import Path
from typing import Any

from company_skill_rollup import (
    add_dormant_skill_facts,
    build_company_skill_facts,
    write_company_skill_facts,
)
from lifecycle_writer import apply_missing as _apply_missing
from lifecycle_writer import apply_seen as _apply_seen


MIN_SAFE_COVERAGE = 0.25
QUARANTINE_AFTER_CLOSE = timedelta(hours=1)
AGE_STALE_DAYS = 30
_BATCH_SIZE = 200
_PAGE_SIZE = 1000
log = logging.getLogger("trusted_job_lifecycle")


@dataclass(frozen=True)
class SourceRunAssessment:
    status: str
    coverage_ratio: float | None
    failure_reason: str | None = None


@dataclass(frozen=True)
class MissingTransition:
    consecutive_misses: int
    listing_confidence: str
    is_active: bool
    quarantine_until: datetime | None = None


def assess_source_run(
    *, current_count: int, prior_good_count: int | None
) -> SourceRunAssessment:
    if current_count <= 0:
        return SourceRunAssessment("failed", 0.0, "source returned zero jobs")
    if not prior_good_count:
        return SourceRunAssessment("complete", None)
    raw_coverage = current_count / prior_good_count
    # The database stores coverage as a bounded ratio.  A growing source can
    # legitimately return more jobs than the previous complete run; that is a
    # healthy expansion, not a value above the column's 1.0 upper bound.
    coverage = min(1.0, raw_coverage)
    if raw_coverage < MIN_SAFE_COVERAGE:
        return SourceRunAssessment(
            "partial",
            round(coverage, 6),
            f"coverage {raw_coverage:.1%} below {MIN_SAFE_COVERAGE:.0%} safety floor",
        )
    return SourceRunAssessment("complete", round(coverage, 6))


def missing_transition(
    previous_misses: int,
    *,
    now: datetime | None = None,
) -> MissingTransition:
    """One complete miss closes the listing. Later misses do not move the clock."""
    misses = max(0, previous_misses) + 1
    timestamp = now or datetime.now(timezone.utc)
    if misses == 1:
        return MissingTransition(
            misses, "closed", False, timestamp + QUARANTINE_AFTER_CLOSE
        )
    return MissingTransition(misses, "closed", False, None)


def stale_last_seen_cutoff(*, days: int = AGE_STALE_DAYS, today: datetime | None = None) -> int:
    """Integer YYYYMMDD: last_seen values older than this are ghost listings."""
    day = (today or datetime.now(timezone.utc)).date()
    return int((day - timedelta(days=days)).strftime("%Y%m%d"))


def delist_stale_jobs(
    sb: Any,
    *,
    days: int = AGE_STALE_DAYS,
    dry_run: bool = False,
    today: datetime | None = None,
) -> dict[str, int]:
    """Age backstop: hide jobs not seen in ``days`` (25–30 max; default 30).

    Presence-based close (one complete miss) is the primary clock for
    companies in this run. This catches companies that never appeared in a
    later folder — the ghost-job path. Rows with NULL last_seen are left
    alone; those are extension/saved-job entries, not scraper inventory.
    """
    cutoff = stale_last_seen_cutoff(days=days, today=today)
    ids = _fetch_stale_active_ids(sb, cutoff)
    result = {"cutoff": cutoff, "candidates": len(ids), "changed": 0}
    if dry_run or not ids:
        return result
    moment = today or datetime.now(timezone.utc)
    timestamp = moment.isoformat()
    eligible_at = (moment + QUARANTINE_AFTER_CLOSE).isoformat()
    payload = {
        "is_active": False,
        "listing_confidence": "closed",
        "confidence_reason": f"last_seen_older_than_{days}_days",
        "lifecycle_updated_at": timestamp,
        "quarantined_at": timestamp,
        "quarantine_until": eligible_at,
        "deletion_eligible_at": eligible_at,
        "retired_at": timestamp,
    }
    changed = 0
    for i in range(0, len(ids), _BATCH_SIZE):
        chunk = ids[i:i + _BATCH_SIZE]
        sb.table("jobs").update(payload).in_("job_id", chunk).execute()
        changed += len(chunk)
    result["changed"] = changed
    log.info(
        "Age delist: last_seen < %s → %s inactive",
        cutoff,
        changed,
    )
    return result


def _fetch_stale_active_ids(sb: Any, cutoff: int) -> list[str]:
    ids: list[str] = []
    page = 0
    while True:
        batch = (
            sb.table("jobs")
            .select("job_id")
            .eq("is_active", True)
            .not_.is_("last_seen", "null")
            .lt("last_seen", cutoff)
            .range(page * _PAGE_SIZE, (page + 1) * _PAGE_SIZE - 1)
            .execute()
        ).data or []
        for row in batch:
            job_id = str(row.get("job_id") or "")
            if job_id:
                ids.append(job_id)
        if len(batch) < _PAGE_SIZE:
            break
        page += 1
    return ids


def sync_import_run(
    sb: Any,
    *,
    feed_run_id: str,
    json_files: list[Path],
    skill_id_map: dict[str, int],
    eligible_companies: set[str],
    quality_status: str,
    dry_run: bool,
    write_skill_facts: bool = True,
    eligible_job_ids: dict[str, set[str]] | None = None,
) -> dict[str, int]:
    grouped = _load_company_jobs(
        json_files,
        eligible_companies,
        eligible_job_ids=eligible_job_ids,
    )
    summary = {"complete": 0, "partial": 0, "failed": 0}
    for company, jobs in sorted(grouped.items()):
        result = sync_company_run(
            sb,
            feed_run_id=feed_run_id,
            company=company,
            jobs=jobs,
            skill_id_map=skill_id_map,
            quality_status=quality_status,
            dry_run=dry_run,
            write_skill_facts=write_skill_facts,
        )
        summary[result.status] += 1
    return summary


def sync_company_run(
    sb: Any,
    *,
    feed_run_id: str,
    company: str,
    jobs: list[dict[str, Any]],
    skill_id_map: dict[str, int],
    quality_status: str,
    dry_run: bool,
    write_skill_facts: bool = True,
) -> SourceRunAssessment:
    current_ids = {str(job.get("job_id")) for job in jobs if job.get("job_id")}
    if dry_run:
        return assess_source_run(current_count=len(current_ids), prior_good_count=None)

    company_id = _resolve_company(sb, company)
    existing = _fetch_company_jobs(sb, company_id)
    prior_good = _prior_good_count(sb, company_id)
    assessment = assess_source_run(
        current_count=len(current_ids), prior_good_count=prior_good
    )
    if quality_status != "ok" and assessment.status == "complete":
        assessment = SourceRunAssessment(
            "partial", assessment.coverage_ratio, "global import quality gate blocked"
        )
    now = datetime.now(timezone.utc)
    source_key = _source_key(jobs)
    source_run_id = _write_source_run(
        sb,
        feed_run_id=feed_run_id,
        company=company,
        company_id=company_id,
        source_key=source_key,
        current_count=len(current_ids),
        prior_good_count=prior_good,
        assessment=assessment,
        jobs=jobs,
        now=now,
    )
    if assessment.status == "complete" and write_skill_facts:
        facts = build_company_skill_facts(
            jobs,
            skill_id_map=skill_id_map,
            source_run_id=source_run_id,
            company_id=company_id,
        )
        facts = add_dormant_skill_facts(
            facts,
            known_skill_ids=_known_company_skill_ids(sb, company_id),
            source_run_id=source_run_id,
            company_id=company_id,
        )
        write_company_skill_facts(
            sb, facts, source_run_id=source_run_id, batch_size=_BATCH_SIZE
        )
    _apply_seen(
        sb,
        existing,
        current_ids,
        company_id=company_id,
        source_run_id=source_run_id,
        now=now,
    )
    if assessment.status == "complete":
        _apply_missing(
            sb, existing, current_ids, source_run_id=source_run_id, now=now
        )
    log.info(
        "Lifecycle %s: %s (%s current, %s prior good)",
        company, assessment.status, len(current_ids), prior_good or 0,
    )
    return assessment


def _load_company_jobs(
    json_files: list[Path],
    eligible_companies: set[str],
    *,
    eligible_job_ids: dict[str, set[str]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for path in json_files:
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(rows, list):
            continue
        fallback = path.parent.parent.parent.name
        company = str((rows[0].get("company_name") if rows else fallback) or fallback)
        if company not in eligible_companies:
            continue
        allowed = eligible_job_ids.get(company) if eligible_job_ids is not None else None
        grouped.setdefault(company, []).extend(
            row
            for row in rows
            if isinstance(row, dict)
            and (allowed is None or str(row.get("job_id") or "") in allowed)
        )
    return grouped


def _resolve_company(sb: Any, company: str) -> str:
    data = sb.rpc("resolve_company_entity", {"p_company_name": company}).execute().data
    if isinstance(data, list):
        data = data[0] if data else None
    if isinstance(data, dict):
        data = data.get("resolve_company_entity") or data.get("id")
    if not data:
        raise RuntimeError(f"Could not resolve company entity for {company}")
    return str(data)


def _fetch_company_jobs(sb: Any, company_id: str) -> list[dict[str, Any]]:
    return sb.table("jobs").select(
        "job_id,is_active,listing_confidence,consecutive_complete_misses"
    ).eq("company_id", company_id).execute().data or []


def _prior_good_count(sb: Any, company_id: str) -> int | None:
    rows = sb.table("job_source_runs").select("observed_count").eq(
        "company_id", company_id
    ).eq("status", "complete").order("completed_at", desc=True).limit(1).execute().data or []
    return int(rows[0]["observed_count"]) if rows else None


def _known_company_skill_ids(sb: Any, company_id: str) -> set[int]:
    rows = sb.table("company_skill_profiles").select("skill_id").eq(
        "company_id", company_id
    ).execute().data or []
    return {int(row["skill_id"]) for row in rows if row.get("skill_id") is not None}


def _write_source_run(
    sb: Any,
    *,
    feed_run_id: str,
    company: str,
    company_id: str,
    source_key: str,
    current_count: int,
    prior_good_count: int | None,
    assessment: SourceRunAssessment,
    jobs: list[dict[str, Any]],
    now: datetime,
) -> str:
    marker = max((int(job.get("batch_date") or 0) for job in jobs), default=0) or None
    payload = {
        "feed_run_id": feed_run_id,
        "company_name": company,
        "company_id": company_id,
        "source_key": source_key,
        "provider": source_key,
        "started_at": now.isoformat(),
        "completed_at": now.isoformat(),
        "status": assessment.status,
        "observed_count": current_count,
        "prior_good_count": prior_good_count,
        "coverage_ratio": assessment.coverage_ratio,
        "run_marker": marker,
        "failure_reason": assessment.failure_reason,
        "metadata": {"pipeline": "csv_importer"},
    }
    rows = sb.table("job_source_runs").upsert(
        payload, on_conflict="feed_run_id,company_name,source_key"
    ).execute().data or []
    if not rows:
        rows = sb.table("job_source_runs").select("id").eq(
            "feed_run_id", feed_run_id
        ).eq("company_name", company).eq("source_key", source_key).execute().data or []
    if not rows:
        raise RuntimeError(f"Source run write returned no id for {company}")
    return str(rows[0]["id"])


def _source_key(jobs: list[dict[str, Any]]) -> str:
    first = jobs[0] if jobs else {}
    return str(
        first.get("source_platform") or first.get("ats") or "unknown"
    ).strip().lower() or "unknown"
