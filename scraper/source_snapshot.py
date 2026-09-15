"""Source snapshot writer — source-owned jobs writes and feed close.

Callers pass sparse source rows. This module owns PostgREST's uniform-keys
invariant (an omitted key in a mixed batch becomes NULL on conflict). Feed
close records presence and age-delists ghosts; physical unload is True_Yodha's
archive-then-delete after a one-hour quarantine.
"""
from __future__ import annotations

import logging
from typing import Any

from postgrest.exceptions import APIError

from job_summary import extractive_job_summary
from schema import MIN_JOB_DESCRIPTION_LEN
from trusted_job_lifecycle import AGE_STALE_DAYS, delist_stale_jobs, sync_import_run

log = logging.getLogger("source_snapshot")


def is_statement_timeout(exc: Exception) -> bool:
    return isinstance(exc, APIError) and getattr(exc, "code", None) == "57014"


def upsert_rows(
    sb: Any,
    table_name: str,
    rows: list[dict],
    *,
    on_conflict: str,
    ignore_duplicates: bool = False,
) -> None:
    """Upsert rows without letting omitted keys NULL out siblings.

    Groups by key-set so each PostgREST request is homogeneous, then
    timeout-splits each group.
    """
    if not rows:
        return
    groups: dict[frozenset[str], list[dict]] = {}
    order: list[frozenset[str]] = []
    for row in rows:
        key = frozenset(row.keys())
        if key not in groups:
            order.append(key)
            groups[key] = []
        groups[key].append(row)
    for key in order:
        _upsert_with_timeout_split(
            sb,
            table_name,
            groups[key],
            on_conflict=on_conflict,
            ignore_duplicates=ignore_duplicates,
        )


def _upsert_with_timeout_split(
    sb: Any,
    table_name: str,
    rows: list[dict],
    *,
    on_conflict: str,
    ignore_duplicates: bool = False,
) -> None:
    if not rows:
        return
    try:
        sb.table(table_name).upsert(
            rows,
            on_conflict=on_conflict,
            ignore_duplicates=ignore_duplicates,
        ).execute()
    except Exception as exc:
        if not is_statement_timeout(exc) or len(rows) == 1:
            raise
        mid = max(1, len(rows) // 2)
        log.warning(
            "%s upsert timed out for %s rows; retrying as %s + %s",
            table_name,
            len(rows),
            mid,
            len(rows) - mid,
        )
        _upsert_with_timeout_split(
            sb,
            table_name,
            rows[:mid],
            on_conflict=on_conflict,
            ignore_duplicates=ignore_duplicates,
        )
        _upsert_with_timeout_split(
            sb,
            table_name,
            rows[mid:],
            on_conflict=on_conflict,
            ignore_duplicates=ignore_duplicates,
        )


def finalize_source_snapshot(
    sb: Any,
    *,
    feed_run_id: str,
    json_files: list,
    skill_id_map: dict[str, int],
    eligible_companies: set[str],
    quality_status: str,
    dry_run: bool,
    write_skill_facts: bool = True,
    eligible_job_ids: dict[str, set[str]] | None = None,
    company_scope: str | None = None,
) -> dict[str, Any]:
    """Seen/missing lifecycle, then full-scope age delist.

    Physical delete is True_Yodha's archive-then-retire after one hour.
    ``company_scope`` (a ``--company`` canary) skips the 30-day age backstop.
    """
    summary: dict[str, Any] = sync_import_run(
        sb,
        feed_run_id=feed_run_id,
        json_files=json_files,
        skill_id_map=skill_id_map,
        eligible_companies=eligible_companies,
        quality_status=quality_status,
        dry_run=dry_run,
        write_skill_facts=write_skill_facts,
        eligible_job_ids=eligible_job_ids,
    )
    if company_scope:
        summary["age_delist"] = {"skipped": True, "reason": "company_scope"}
    else:
        stale = delist_stale_jobs(sb, dry_run=dry_run)
        summary["age_delist"] = stale
        log.info(
            "Age delist (%sd): cutoff=%s candidates=%s changed=%s",
            AGE_STALE_DAYS,
            stale.get("cutoff"),
            stale.get("candidates"),
            stale.get("changed"),
        )
    return summary


def fill_blank_summaries(
    sb: Any,
    *,
    company: str,
    job_ids: list[str] | None = None,
) -> int:
    """Write extractive card copy onto rows whose job_summary is empty.

    Does not touch role_domain or other model-owned columns. LLM wording
    already lost cannot be restored here.
    """
    query = (
        sb.table("jobs")
        .select("job_id,job_title,job_description,job_summary")
        .eq("company_name", company)
    )
    if job_ids:
        query = query.in_("job_id", job_ids)
    rows = query.execute().data or []
    changed = 0
    for row in rows:
        if str(row.get("job_summary") or "").strip():
            continue
        job_id = str(row.get("job_id") or "")
        if not job_id:
            continue
        desc = str(row.get("job_description") or "")
        summary = extractive_job_summary(
            str(row.get("job_title") or ""),
            desc,
            metadata_only=len(desc.strip()) < MIN_JOB_DESCRIPTION_LEN,
        )
        if not summary:
            continue
        sb.table("jobs").update({"job_summary": summary}).eq("job_id", job_id).execute()
        changed += 1
    return changed
