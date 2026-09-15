"""Probe seam — cheaply re-test one company's configured route, post-mortem.

The classifier says "NVIDIA looks like a regression". The probe answers the next
question without a human: *does the endpoint work right now?* It re-runs the
exact provider/route for one company with a small cap, counts India jobs, and
diffs against the baseline — turning the handoff's hypothesis ("PCSX casing
drift broke NVIDIA+Micron together") into a measurement.

One adapter today: the live HTTP route via `dispatch_scrape` (the same path the
real scrape uses, so a probe pass means the scrape would pass). A second adapter
— a Firecrawl-cloud probe for JS-opaque NEEDS_CRACK companies — is the obvious
next one; that makes this a real seam, not a hypothetical one.

Propose-only: the probe never edits config. It returns a verdict + a suggested
fix for a human to approve (CLAUDE.md CHANGE DISCIPLINE).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

_QUIET = logging.getLogger("heal.probe")

# A URL that smells like a job-listing page or a listing API.
_LISTING_URL_RE = re.compile(
    r"(job|career|search|vacanc|opening|position|recruit|api|/jobs|/careers)",
    re.IGNORECASE,
)
_INDIA_RE = re.compile(
    r"\b(india|bengaluru|bangalore|hyderabad|mumbai|pune|chennai|delhi|gurugram|gurgaon|noida|kolkata)\b",
    re.IGNORECASE,
)


@dataclass
class ProbeResult:
    company: str
    ats: str
    reachable: bool          # route returned without raising
    this_count: int          # India jobs the probe pulled now
    baseline_count: int | None
    verdict: str             # RECOVERED | STILL_BROKEN | PARTIAL | COVERAGE_DROP | FALLBACK_NEEDED | ERROR
    error: str = ""
    sample_titles: list[str] = field(default_factory=list)
    suggested_fix: str = ""


def probe_company(
    portal: dict,
    baseline_count: int | None = None,
    *,
    max_jobs: int = 25,
    log: logging.Logger | None = None,
) -> ProbeResult:
    """Re-test one portal's live route. Network only — no Docker needed for the
    cookie-free direct routes that make up the regression bucket."""
    log = log or _QUIET
    company = portal.get("company", "?")
    ats = portal.get("ats", "")
    portal = dict(portal)
    portal["india_only"] = True

    try:
        from providers import probe_scrape
        from providers.base import ScrapeReason

        result = probe_scrape(
            portal,
            log,
            max_jobs=max_jobs,
            allow_firecrawl=False,
        )
    except Exception as e:  # noqa: BLE001 — a probe failure is data, not a crash
        return ProbeResult(
            company, ats, reachable=False, this_count=0, baseline_count=baseline_count,
            verdict="ERROR", error=str(e),
            suggested_fix="route raised — diff the provider since last_good_run; check host/cookies",
        )

    jobs = result.jobs
    if result.reason == ScrapeReason.FALLBACK:
        return ProbeResult(
            company, ats, reachable=False, this_count=0, baseline_count=baseline_count,
            verdict="FALLBACK_NEEDED", error=result.fallback_reason or "",
            suggested_fix="direct route requires Firecrawl; re-probe only with Docker/cloud enabled",
        )
    if result.reason == ScrapeReason.PARTIAL:
        return ProbeResult(
            company, ats, reachable=False, this_count=len(jobs), baseline_count=baseline_count,
            verdict="PARTIAL", error=result.fallback_reason or "",
            sample_titles=[str(j.get("job_title") or j.get("title") or "") for j in jobs[:5]],
            suggested_fix="provider returned a torn snapshot; do not publish until pagination completes",
        )
    if result.reason not in {ScrapeReason.SUCCESS, ScrapeReason.NO_JOBS}:
        return ProbeResult(
            company, ats, reachable=False, this_count=0, baseline_count=baseline_count,
            verdict="ERROR", error=result.fallback_reason or result.reason.value,
            suggested_fix="direct route failed — inspect the typed provider reason and endpoint contract",
        )

    count = len(jobs)
    titles = [str(j.get("job_title", "")) for j in jobs[:5] if j.get("job_title")]

    if count == 0:
        return ProbeResult(
            company, ats, reachable=True, this_count=0, baseline_count=baseline_count,
            verdict="STILL_BROKEN", sample_titles=titles,
            suggested_fix=(
                "endpoint reachable but 0 India jobs — check location param casing "
                "(india vs India), domain/siteNumber, or facet/company id"
            ),
        )

    # count < cap means the route genuinely ran dry early; == cap is just our
    # sample ceiling, so a capped probe is a healthy route, not a partial one.
    if count < max_jobs and baseline_count and count < baseline_count * 0.5:
        return ProbeResult(
            company, ats, reachable=True, this_count=count, baseline_count=baseline_count,
            verdict="COVERAGE_DROP", sample_titles=titles,
            suggested_fix=f"recovered {count} of ~{baseline_count} — check pagination cap / partial facet",
        )

    return ProbeResult(
        company, ats, reachable=True, this_count=count, baseline_count=baseline_count,
        verdict="RECOVERED", sample_titles=titles,
        suggested_fix="route healthy now — re-run the scrape for this company to reload",
    )


# ── Second adapter: Firecrawl-cloud discovery probe for NEEDS_CRACK ──────────

@dataclass
class FirecrawlProbeResult:
    company: str
    careers_url: str
    verdict: str                       # CANDIDATE_FOUND | NO_SIGNAL | ERROR
    candidate_urls: list[str] = field(default_factory=list)
    india_signal: bool = False         # India job text seen on the scraped page
    error: str = ""


def _score_url(link: dict) -> int:
    blob = f"{link.get('url', '')} {link.get('title', '')} {link.get('description', '')}"
    score = len(_LISTING_URL_RE.findall(blob))
    if _INDIA_RE.search(blob):
        score += 2
    return score


def probe_company_firecrawl(
    portal: dict,
    *,
    map_limit: int = 30,
    scrape_top: bool = True,
) -> FirecrawlProbeResult:
    """Firecrawl-cloud discovery for a JS-opaque company with no direct route.

    map_site -> rank candidate listing/API URLs -> optionally scrape the best one
    and look for India job signals. The durable direct endpoint still has to be
    promoted by hand into KNOWN_PORTALS.md (CLAUDE.md FIRECRAWL DISCIPLINE) — this
    just hands a human the candidate. Calls are cached by firecrawl_client, so
    re-runs don't re-spend credits.
    """
    company = portal.get("company", "?")
    careers_url = portal.get("endpoint") or portal.get("url") or ""
    if not careers_url:
        return FirecrawlProbeResult(company, "", "ERROR", error="no careers URL in portal")
    try:
        from firecrawl_client import map_site, scrape
        links = map_site(careers_url, search="jobs india careers", limit=map_limit)
        ranked = sorted(links, key=_score_url, reverse=True)
        candidates = [link["url"] for link in ranked[:5] if _score_url(link) > 0]
        if not candidates:
            return FirecrawlProbeResult(company, careers_url, "NO_SIGNAL", candidate_urls=[])
        india = False
        if scrape_top:
            md = scrape(candidates[0]) or ""
            india = bool(_INDIA_RE.search(md))
        return FirecrawlProbeResult(
            company, careers_url, "CANDIDATE_FOUND",
            candidate_urls=candidates, india_signal=india,
        )
    except Exception as e:  # noqa: BLE001
        return FirecrawlProbeResult(company, careers_url, "ERROR", error=str(e))
