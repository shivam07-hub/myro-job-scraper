"""Batched Supabase writes for trusted job lifecycle transitions."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import time
from typing import Any, Iterable


_BATCH_SIZE = 200
# A jobs UPDATE that hits the statement timeout (57014) under contention is
# split until it fits; at this size it backs off and retries instead.
_MIN_SPLIT = 25
_RETRY_DELAYS = (5, 15, 45)
_sleep = time.sleep


def apply_seen(
    sb: Any,
    existing: list[dict[str, Any]],
    current_ids: set[str],
    *,
    company_id: str,
    source_run_id: str,
    now: datetime,
) -> None:
    if not current_ids:
        return
    timestamp = now.isoformat()
    payload = {
        "is_active": True,
        "company_id": company_id,
        "listing_confidence": "active",
        "last_verified_live_at": timestamp,
        "last_verification_attempt_at": timestamp,
        "consecutive_complete_misses": 0,
        "confidence_reason": "complete_source_seen",
        "last_source_run_id": source_run_id,
        "quarantined_at": None,
        "quarantine_until": None,
        "deletion_eligible_at": None,
        "retired_at": None,
        "lifecycle_updated_at": timestamp,
    }
    for chunk in _chunks(sorted(current_ids)):
        _update_jobs(sb, payload, chunk)

    reactivated = [
        str(row["job_id"])
        for row in existing
        if row.get("job_id") in current_ids
        and row.get("listing_confidence") != "active"
    ]
    for chunk in _chunks(reactivated):
        _update_jobs(sb, {"reactivated_at": timestamp}, chunk)
    # Live presence lives on jobs.last_verified_live_at. A seen_live row per
    # poll was the 230k-row diary; Ghost Index keeps the latest historical ping
    # plus a freeze at retire.


def apply_missing(
    sb: Any,
    existing: list[dict[str, Any]],
    current_ids: set[str],
    *,
    source_run_id: str,
    now: datetime,
) -> None:
    # Imported lazily to avoid a module cycle: policy orchestration imports writer.
    from trusted_job_lifecycle import missing_transition

    timestamp = now.isoformat()
    buckets: dict[tuple[Any, ...], list[str]] = defaultdict(list)
    observations: list[dict[str, Any]] = []
    for row in existing:
        job_id = str(row.get("job_id") or "")
        if not job_id or job_id in current_ids:
            continue
        transition = missing_transition(
            int(row.get("consecutive_complete_misses") or 0), now=now
        )
        quarantine = (
            transition.quarantine_until.isoformat()
            if transition.quarantine_until
            else None
        )
        key = (
            transition.consecutive_misses,
            transition.listing_confidence,
            transition.is_active,
            quarantine,
        )
        buckets[key].append(job_id)
        if transition.consecutive_misses == 1:
            observations.append(
                {
                    "job_id": job_id,
                    "source_run_id": source_run_id,
                    "observer": "scraper",
                    "result": "source_missing",
                    "strength": "medium",
                    "observed_at": timestamp,
                    "evidence": {
                        "consecutive_complete_misses": transition.consecutive_misses
                    },
                }
            )

    for (misses, confidence, is_active, quarantine), job_ids in buckets.items():
        payload = {
            "consecutive_complete_misses": misses,
            "listing_confidence": confidence,
            "is_active": is_active,
            "last_source_run_id": source_run_id,
            "last_verification_attempt_at": timestamp,
            "confidence_reason": f"complete_source_miss_{misses}",
            "lifecycle_updated_at": timestamp,
        }
        if quarantine:
            payload.update(
                {
                    "quarantined_at": timestamp,
                    "quarantine_until": quarantine,
                    "deletion_eligible_at": quarantine,
                    "retired_at": timestamp,
                }
            )
        for chunk in _chunks(job_ids):
            _update_jobs(sb, payload, chunk)
    _write_observations(sb, observations)


def _update_jobs(sb: Any, payload: dict[str, Any], job_ids: list[str], attempt: int = 0) -> None:
    """UPDATE jobs for these ids; the payload is idempotent, so retrying is safe."""
    try:
        sb.table("jobs").update(payload).in_("job_id", job_ids).execute()
    except Exception as exc:
        if not _is_statement_timeout(exc):
            raise
        if len(job_ids) > _MIN_SPLIT:
            middle = len(job_ids) // 2
            _update_jobs(sb, payload, job_ids[:middle])
            _update_jobs(sb, payload, job_ids[middle:])
            return
        if attempt >= len(_RETRY_DELAYS):
            raise
        _sleep(_RETRY_DELAYS[attempt])
        _update_jobs(sb, payload, job_ids, attempt + 1)


def _is_statement_timeout(exc: Exception) -> bool:
    return getattr(exc, "code", None) == "57014" or "statement timeout" in str(exc)


def _write_observations(sb: Any, rows: list[dict[str, Any]]) -> None:
    for start in range(0, len(rows), _BATCH_SIZE):
        sb.table("job_listing_observations").insert(
            rows[start : start + _BATCH_SIZE]
        ).execute()


def _chunks(values: Iterable[str]) -> Iterable[list[str]]:
    materialized = list(values)
    for start in range(0, len(materialized), _BATCH_SIZE):
        yield materialized[start : start + _BATCH_SIZE]
