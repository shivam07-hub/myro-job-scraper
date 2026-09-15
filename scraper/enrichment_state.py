"""Shared state and hashing helpers for forward-only job enrichment.

Historical rows are intentionally not enrolled.  The database migration leaves
their ``enrichment_status`` and ``source_content_hash`` values null.  Only jobs
inserted after cutover (or later source changes to those tracked jobs) enter the
queue.
"""
from __future__ import annotations

import hashlib
import json

from schema import MIN_JOB_DESCRIPTION_LEN, is_missing_jd_description


CORE_ENRICHMENT_VERSION = "job_core_v1"
SOURCE_CONTENT_HASH_VERSION = "job_source_v1"
QUEUE_NAME = "job_enrichment"


def source_content_hash(job: dict) -> str:
    """Hash only source-owned inputs used by core enrichment.

    Do not include model outputs here.  The hash is used to reject an LLM result
    if the title or JD changes while the message is being processed.
    """
    payload = {
        "version": SOURCE_CONTENT_HASH_VERSION,
        "job_title": str(job.get("job_title") or "").strip(),
        "job_description": str(job.get("job_description") or "").strip(),
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def has_enrichable_description(job: dict) -> bool:
    description = str(job.get("job_description") or "").strip()
    return (
        len(description) >= MIN_JOB_DESCRIPTION_LEN
        and not is_missing_jd_description(description)
    )


def has_core_enrichment_payload(job: dict) -> bool:
    """Return True only when a row carries terminal core enrichment output."""
    if job.get("skills") or job.get("main_skills"):
        return True
    return bool(
        str(job.get("job_summary") or "").strip()
        and str(job.get("role_domain") or "").strip()
    )
