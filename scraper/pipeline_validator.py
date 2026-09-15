"""
pipeline_validator.py — Single source of truth for all job validation gates.

Three stages, called in dependency order by main.py:

  post_scrape  — identity check (job_id, job_title) + placeholder detection
  pre_enrich   — description check (non-empty, min length)
  post_enrich  — skills check (main_skills populated after LLM enrichment)

Each returns a list of (job, reason) pairs for dropped jobs so callers can
funnel all drop counts into one unified summary counter.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from schema import MIN_JOB_DESCRIPTION_LEN, is_missing_jd_description

Stage = Literal["post_scrape", "pre_enrich", "post_enrich"]

MIN_DESC_LEN = MIN_JOB_DESCRIPTION_LEN  # chars — below this a "description" is metadata noise


# ── Placeholder detection ─────────────────────────────────────────────────────

_PLACEHOLDER_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"\bscraped via firecrawl\b", re.IGNORECASE),
)


def _is_placeholder(title: str) -> bool:
    return bool(title) and any(p.search(title) for p in _PLACEHOLDER_PATTERNS)


# ── Per-stage rules ───────────────────────────────────────────────────────────

def _post_scrape_reason(job: dict) -> str | None:
    if not job.get("job_id"):
        return "missing_job_id"
    if not job.get("job_title"):
        return "missing_job_title"
    if _is_placeholder(str(job.get("job_title", ""))):
        return "placeholder_title"
    return None


def _pre_enrich_reason(job: dict) -> str | None:
    desc = job.get("job_description") or ""
    if is_missing_jd_description(desc):
        return None
    if not desc:
        return "empty_job_description"
    if len(desc) < MIN_DESC_LEN:
        return f"desc_too_short_{len(desc)}chars"
    return None


def _post_enrich_reason(job: dict) -> str | None:
    if is_missing_jd_description(job.get("job_description")):
        return None
    if not job.get("main_skills"):
        return "no_main_skills_after_enrichment"
    return None


_STAGE_FN = {
    "post_scrape": _post_scrape_reason,
    "pre_enrich":  _pre_enrich_reason,
    "post_enrich": _post_enrich_reason,
}


# ── Public API ────────────────────────────────────────────────────────────────

@dataclass
class GateResult:
    passed: list[dict] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)  # each has _drop_reason key

    @property
    def drop_count(self) -> int:
        return len(self.dropped)

    @property
    def reasons(self) -> list[str]:
        return sorted({d["_drop_reason"] for d in self.dropped})


def run_gate(jobs: list[dict], stage: Stage) -> GateResult:
    """
    Run one validation gate over a list of canonical job dicts.
    Returns GateResult with passed/dropped split and drop reasons.
    """
    fn = _STAGE_FN[stage]
    result = GateResult()
    for job in jobs:
        reason = fn(job)
        if reason:
            result.dropped.append({**job, "_drop_reason": reason})
        else:
            result.passed.append(job)
    return result
