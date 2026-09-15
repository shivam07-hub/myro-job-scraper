"""Failure classifier — turns a run_summary into per-company verdicts.

The scrape already emits structured evidence per company (run_summary_*.json:
company_stats / unresolved / low_count, each with a `reason` code). But those
codes are shallow: they say *what* happened (0 jobs) not *why* (Cloudflare
block vs param drift vs never-cracked vs a regression of a route that used to
work). The "why" was, until now, supplied by a human hand-writing
HANDOFF_skipped_companies_*.md and bucketing into A-E.

This module is that human, made into code. Given a run_summary, the baseline
ledger, the set of blocked Workday tenants, and the portal->ats map, it assigns
each non-OK company a Bucket. The bucket taxonomy is the test surface: feed a
fixture run_summary, assert the buckets.

Pure: no IO. Loaders live in diagnose.py.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Buckets (map 1:1 to the hand-written handoff sections) ---------------
REGRESSION = "REGRESSION"          # Bucket A: had a good baseline, now 0 / big drop
INCOMPLETE_SNAPSHOT = "INCOMPLETE_SNAPSHOT"  # provider failed after returning some pages
PARAM_SUSPECT = "PARAM_SUSPECT"    # Bucket E: direct-API route, 0, never confirmed good
NEEDS_CRACK = "NEEDS_CRACK"        # Bucket C: JS-opaque / ats=other, never cracked
COOKIE_NEEDED = "COOKIE_NEEDED"    # Bucket D: Darwinbox, needs CF cookies
BLOCKED_EXPECTED = "BLOCKED_EXPECTED"  # Bucket B: known CF-blocked Workday tenant
LOW_COUNT = "LOW_COUNT"            # >0 but under the floor
OK = "OK"                          # not a failure

# Priority order for reporting (cheap wins first).
BUCKET_ORDER = [
    INCOMPLETE_SNAPSHOT,
    REGRESSION,
    PARAM_SUSPECT,
    COOKIE_NEEDED,
    NEEDS_CRACK,
    BLOCKED_EXPECTED,
    LOW_COUNT,
    OK,
]

# Thresholds.
LOW_THRESHOLD = 5          # < this saved/raw == not a healthy company (matches below_5)
REGRESSION_MIN = 5         # baseline must have been at least this to call a drop a regression
REGRESSION_DROP_RATIO = 0.5  # this_count < baseline*ratio counts as a regression

# ATS families. Anything not JS-opaque and not cookie-gated is a single direct
# route whose 0 is most likely a per-company param/casing/id bug (param-suspect).
JS_OPAQUE_ATS = {"other", "firecrawl_js", "avature", "eightfold"}
COOKIE_ATS = {"darwinbox"}


@dataclass
class Verdict:
    company: str
    ats: str
    bucket: str
    this_count: int
    last_good_count: int | None
    reason: str            # run_summary reason code, if any
    evidence: str          # one-line human explanation
    suggested_action: str

    @property
    def is_failure(self) -> bool:
        return self.bucket != OK


def _per_company(run_summary: dict) -> dict[str, dict]:
    """Collapse company_stats / unresolved / low_count into one row per company."""
    rows: dict[str, dict] = {}
    for s in run_summary.get("company_stats", []):
        rows[s["company"]] = {
            "ats": s.get("ats", ""),
            "raw_jobs": int(s.get("raw_jobs", 0) or 0),
            "saved_new": int(s.get("saved_new", 0) or 0),
            "status": s.get("status", ""),
            "reason": "",
        }
    for u in run_summary.get("unresolved", []):
        row = rows.setdefault(u["company"], {"ats": u.get("ats", ""), "raw_jobs": 0, "saved_new": 0, "status": ""})
        row["reason"] = u.get("reason", "")
    for lc in run_summary.get("low_count", []):
        row = rows.setdefault(lc["company"], {"ats": lc.get("ats", ""), "saved_new": 0, "status": ""})
        row["raw_jobs"] = int(lc.get("raw_jobs", 0) or 0)
        row.setdefault("reason", lc.get("reason", ""))
    return rows


def _classify_one(
    company: str,
    row: dict,
    baseline_count: int | None,
    blocked_tenants: set[str],
) -> Verdict:
    ats = row.get("ats", "")
    this_count = int(row.get("raw_jobs", 0) or 0)
    reason = row.get("reason", "") or row.get("status", "")

    def v(bucket: str, evidence: str, action: str) -> Verdict:
        return Verdict(company, ats, bucket, this_count, baseline_count, reason, evidence, action)

    if reason in {"partial", "partial_snapshot"}:
        return v(
            INCOMPLETE_SNAPSHOT,
            f"provider returned {this_count} rows before the career-page snapshot failed",
            "quarantine these rows; retry the provider until pagination completes",
        )

    # 1. Regression — had a real baseline, now collapsed. Highest ROI, cheap fix.
    if baseline_count and baseline_count >= REGRESSION_MIN:
        if this_count < baseline_count * REGRESSION_DROP_RATIO:
            return v(
                REGRESSION,
                f"was {baseline_count} India jobs, now {this_count} — route/param/registry drift",
                "re-test the known-good endpoint; diff provider since last_good_run; check casing/domain/id",
            )

    healthy = this_count >= LOW_THRESHOLD
    if healthy:
        return v(OK, f"{this_count} India jobs", "none")

    # From here: this_count is 0..4 and there is no protective baseline.
    if ats in COOKIE_ATS:
        return v(
            COOKIE_NEEDED,
            "Darwinbox — needs CF Turnstile cookies (DARWINBOX_CF_BM + DARWINBOX_SESSION)",
            "refresh browser cookies into env; cookies expire ~30 min, IP-bound",
        )

    if ats == "workday" and company in blocked_tenants:
        return v(
            BLOCKED_EXPECTED,
            "Workday tenant marked blocked=true (Cloudflare) — expected 0, not a bug",
            "accept as blocked, or pursue Firecrawl-cloud listing for fresher-relevant roles",
        )

    if 0 < this_count < LOW_THRESHOLD:
        return v(
            LOW_COUNT,
            f"only {this_count} scraped (under floor of {LOW_THRESHOLD})",
            "verify location filter/param; confirm genuinely low hiring vs missed pagination",
        )

    # this_count == 0, no baseline -> split by ATS family.
    if ats in JS_OPAQUE_ATS or not ats:
        return v(
            NEEDS_CRACK,
            f"ats={ats or 'unknown'} — JS-opaque, no direct route captured",
            "re-crack via Firecrawl Cloud map->scrape; save durable endpoint to KNOWN_PORTALS.md",
        )

    return v(
        PARAM_SUSPECT,
        f"direct route ats={ats} returned 0 and was never confirmed good",
        "verify company-id / location param / facet UUID for this route",
    )


def classify_run(
    run_summary: dict,
    baseline: dict[str, dict],
    blocked_tenants: set[str],
) -> list[Verdict]:
    """Classify every company in the run. Sorted by bucket priority then company."""
    rows = _per_company(run_summary)
    verdicts: list[Verdict] = []
    for company, row in rows.items():
        bl = baseline.get(company, {})
        baseline_count = bl.get("last_good_count")
        verdicts.append(_classify_one(company, row, baseline_count, blocked_tenants))
    order = {b: i for i, b in enumerate(BUCKET_ORDER)}
    verdicts.sort(key=lambda x: (order.get(x.bucket, 99), x.company.lower()))
    return verdicts


def bucket_counts(verdicts: list[Verdict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for v in verdicts:
        counts[v.bucket] = counts.get(v.bucket, 0) + 1
    return counts
