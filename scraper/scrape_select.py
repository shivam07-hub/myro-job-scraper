"""Quality-aware per-company cap selection (Phase A).

For a company whose scraped job count exceeds the cap, replace the blunt
`raw_jobs[:cap]` truncation with a deterministic quality selection: drop obvious
non-technical / no-JD-likely roles, then rank the rest so higher-importance
technical roles that carry a real JD survive the cap. Companies at or below the
cap are returned unchanged (small company → keep everything, no distinction).

Myro lens: for a big service integrator we index the roles we can actually
explain (technical, JD-bearing), not the PMO / security-guard tail. No model,
no network — deterministic and unit-testable.

Phase A works on whatever the provider already returned. Direct-API providers
(Greenhouse / SmartRecruiters / Lever) carry the full JD in the listing, so the
thin-JD hard-drop is fully effective for them. Workday only fetches JDs for the
first `WORKDAY_JD_FETCH_LIMIT` jobs, so here the ranker leans on career_band +
title; the deep-fetch reorder that makes JD-drop fully effective for Workday is
Phase B (see docs/DESIGN_quality_aware_company_cap.md).
"""
from __future__ import annotations

import re

from job_career_band import normalize_job_career_band

# Roles we never want to spend a cap slot on for a big company: non-technical /
# facilities / clerical, typically posted without a substantive JD.
STOPLIST_RE = re.compile(
    r"\b(security\s*guard|guard|housekeep\w*|janitor|driver|facilit\w*|"
    r"receptionist|peon|cafeteria|catering|gardener|cleaner|watchman|pantry|"
    r"office\s*boy|data\s*entry)\b",
    re.IGNORECASE,
)

CAP_MIN_JD_CHARS = 300  # >cap companies: hard-drop roles whose JD is thinner than this


def _title(job: dict) -> str:
    return str(job.get("title") or job.get("job_title") or "")


def _jd(job: dict) -> str:
    return str(job.get("raw_jd_text") or job.get("job_description") or "").strip()


def is_stoplisted(job: dict) -> bool:
    return bool(STOPLIST_RE.search(_title(job)))


def _rank_key(job: dict) -> tuple:
    """Sort key, DESC — higher survives the cap.

    1. technical career_band (engineering_data) first
    2. carries a substantial JD
    3. longer JD (the better-explained role) wins ties
    """
    technical = 1 if normalize_job_career_band(job) == "engineering_data" else 0
    jd_len = len(_jd(job))
    has_jd = 1 if jd_len >= CAP_MIN_JD_CHARS else 0
    return (technical, has_jd, jd_len)


def select_for_cap(raw_jobs: list[dict], cap: int | None) -> list[dict]:
    """Return the jobs to keep under `cap`, quality-first.

    - cap falsy (0 / None) → unchanged (unlimited).
    - len(raw_jobs) <= cap → unchanged (small company: keep everything).
    - len(raw_jobs) >  cap → drop stoplist + thin-JD, rank technical/JD-first,
      take the top `cap`. We never pad junk back in to hit the number: if quality
      filtering leaves fewer than `cap`, the survivors are returned as-is.
    """
    if not cap or len(raw_jobs) <= cap:
        return raw_jobs

    # 1. drop obvious non-technical / no-JD-likely roles
    kept = [j for j in raw_jobs if not is_stoplisted(j)]

    # 2. prefer a JD-bearing pool, but only if it still fills the cap. Where the JD
    #    is absent on the listing (Workday beyond its JD-fetch limit), falling back
    #    to the stoplist-filtered pool avoids discarding the whole deep tail — those
    #    still rank below JD-bearing technical roles in step 3. (Phase B fetches JDs
    #    for the selected set so this fallback stops mattering for Workday.)
    with_jd = [j for j in kept if len(_jd(j)) >= CAP_MIN_JD_CHARS]
    pool = with_jd if len(with_jd) >= cap else kept

    # 3. rank quality-first (stable → deterministic within equal rank), take top cap
    pool = sorted(pool, key=_rank_key, reverse=True)
    return pool[:cap]
