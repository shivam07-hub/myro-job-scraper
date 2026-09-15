"""
Deterministic validation layer for the Dump 4+ job pipeline.

Single source of truth for quality-gate rules shared between:
  - csv_importer.py  (batch ingest quality gate)
  - main.py          (per-company run warnings + validate mode)

Rule taxonomy
─────────────
HARD REJECT  — job is silently dropped (missing primary key / identity).
PLACEHOLDER  — job title pattern known to be synthetic noise; counted separately.
QUALITY      — 0-3 score; used for --min-score gate in csv_importer.

Do NOT add domain-specific enrichment checks here (skills taxonomy validation
belongs in enricher.py:_validate_enrichment).
"""
from __future__ import annotations

import re

# ── Hard-reject: missing required identity fields ─────────────────────────────

REQUIRED_FIELDS = ("job_id", "job_title")


def is_valid(job: dict) -> bool:
    """Hard-reject gate: job must have both job_id and job_title."""
    return bool(job.get("job_id")) and bool(job.get("job_title"))


# ── Placeholder detection ─────────────────────────────────────────────────────

_PLACEHOLDER_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bscraped via firecrawl\b", re.IGNORECASE),
)


def is_placeholder_title(title: str) -> bool:
    """Return True if job title is a known synthetic/placeholder value."""
    if not title:
        return False
    return any(p.search(title) for p in _PLACEHOLDER_PATTERNS)


# ── Quality scoring ───────────────────────────────────────────────────────────

def quality_score(job: dict) -> int:
    """
    0-3 completeness score:
      +1  job_description non-empty
      +1  main_skills non-empty list
      +1  Location non-empty
    """
    score = 0
    if job.get("job_description"):
        score += 1
    if job.get("main_skills"):
        score += 1
    if job.get("location") or job.get("Location"):
        score += 1
    return score


# ── Soft-warning thresholds (scraper runtime) ─────────────────────────────────

LOW_COUNT_THRESHOLD = 5   # companies returning fewer than this log a warning


def drop_reason(job: dict) -> str | None:
    """Return a human-readable reason string if the job would be dropped, else None."""
    if not job.get("job_id"):
        return "missing_job_id"
    if not job.get("job_title"):
        return "missing_job_title"
    if is_placeholder_title(str(job.get("job_title", ""))):
        return "placeholder_title"
    return None
