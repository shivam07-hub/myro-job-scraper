# DESIGN — Quality-aware per-company cap

**Status:** Phase A ✅ SHIPPED 2026-07-26 · Phase B ✅ SHIPPED 2026-07-26 (approved defaults: HARD_CAP 2500, MIN_JD 300, stoplist as listed)

## Phase B — shipped 2026-07-26

**Blocker found during build:** `main.py:185` always wires the page-flush callback, so every real Workday run is "streaming" (per-page JD fetch + flush for crash durability). The original Phase-B branch (list-all → select → fetch) therefore never fired — the first live smoke hit the stream early-stop and returned first-N-by-pagination.

**Resolution — decoupled listing from JD fetch:**
- `providers/workday.py` loop now pages **metadata only** (no per-page JD fetch). Real runs page the full India listing (up to the raised ceiling); only validate mode early-stops at the cap.
- After the loop: `select_for_cap(jobs, cap)` ranks the whole pool (title/`career_band` — JD not needed), then JDs are fetched for the selected set **in `WORKDAY_PAGE_SIZE` chunks**, each chunk flushed via `on_page_complete` (durability preserved) and — for a quality-capped company — filtered to JD-bearing before flush (drop-empties).
- JD-fetch budget = the company cap (falls back to `WORKDAY_JD_FETCH_LIMIT` when uncapped), so a big tenant fetches JDs for exactly the selected set, not the whole listing.
- `config.py`: `WORKDAY_MAX_JOBS` 500→5000 (listing ceiling — the real prior bottleneck: every Workday tenant was silently cut to 500 listings). `WORKDAY_JD_FETCH_LIMIT` stays 500 as the uncapped fallback.
- `main.py`: `_DEFAULT_COMPANY_CAP` 1000→2500.

**Contract note:** page-flush granularity shifts from "after each 20-job listing page" to "after each JD-fetched chunk." Durability semantics (incremental writes, marker at end, checkpoint updates) preserved; `daily_cycle` tests green. The short listing phase is now unflushed (cheap/fast); the slow JD phase is still chunk-flushed.

- Guard `tests/test_workday_quality_cap.py` (JD-fetch `limit` honored / defaults / skip-already-fetched) + full suite 269 green.
- Live-verified: Autodesk `--company-cap 30` → 56 listed → 30 selected, **all 30 `engineering_data`, 0 thin-JD**, JDs fetched only for the 30.

---

**Date:** 2026-07-26
**Author:** Claude Code, from Shivam's direction + Myro/Kunal single-employer-signal-quality lens

## Phase A — shipped 2026-07-26

- New pure module `scraper/scrape_select.py` — `select_for_cap(raw_jobs, cap)` + `is_stoplisted()`; deterministic, no model/network. `CAP_MIN_JD_CHARS = 300` (separate from schema's 50-char metadata sentinel).
- Wired at `main.py` cap seam: real runs call `select_for_cap`; validate mode keeps the blunt `[:max_jobs]`.
- Guard `scraper/tests/test_scrape_select.py` — 11 cases (pass-through ≤cap, stoplist, technical/JD ranking, Workday no-JD-tail fallback, never-pad-junk, deterministic). Green.
- Live-verified: Razorpay (Greenhouse, JD in listing) `--company-cap 5` → 46→5, all survivors JD-rich (5–8k chars) and technical-leaning (3× Engineering + Full Stack + Design). Not first-5.
- **Effective now** for direct-API providers (Greenhouse/SmartRecruiters/Lever — full JD in listing). Workday big tenants (Accenture) get title/`career_band` ranking only until Phase B.

Below is the original proposal, retained for Phase B.

---


---

## Problem

`main.py:49` `_DEFAULT_COMPANY_CAP = 1000`. Every company is truncated to 1000 jobs/run by a blunt slice:

```python
# main.py:222-223
if max_jobs:
    raw_jobs = raw_jobs[:max_jobs]
```

For a service integrator (Accenture: 2–3k India roles) this drops the tail **arbitrarily** — whatever paginated last is lost, regardless of quality. And it caps genuinely large India employers we'd want fully.

## Principle (Myro lens)

Signal-quality over volume. For a big integrator we don't want *all* 3k rows (PMO, security guard, facilities — often no JD, no technical signal); we want the **higher-importance technical roles that carry a real JD** so Myro can explain what the company wants. For companies under the cap, no distinction needed — keep everything.

## Policy

- **India job count ≤ SOFT_CAP (default 1000)** → keep ALL. No selection, no change in behavior.
- **India job count > SOFT_CAP** → quality-select instead of dumb truncation:
  1. **Drop** obvious non-technical / no-JD-likely roles via a title stoplist (guard, security, housekeeping, driver, facilities, receptionist, peon, cafeteria, PMO-admin, etc.).
  2. **Rank** the rest: technical `career_band` (`engineering_data`) first, then substantial-JD present, then seniority, then JD length.
  3. **Keep** the top `HARD_CAP` (default 2500 — bounded, but lets big integrators exceed 1000).
  4. **Hard drop** any kept row with empty/thin JD (< N chars) — the user's core ask: no-JD role = not indexable.

## The Workday wrinkle (why this is phased)

Accenture (the headline case) is **Workday**. Workday fetches JDs only for the first `WORKDAY_JD_FETCH_LIMIT=500` jobs and stops pagination at `max_jobs`. So JD-presence is available only for the first slice — a JD-based ranker would just re-favor pagination order. Direct-API providers (Greenhouse / SmartRecruiters / Lever) return full JD in the listing response, so JD-presence is available for ALL their jobs.

→ Split the work:

### Phase A — generic quality selector at the slice seam (low risk, ship first)

Replace the `raw_jobs[:max_jobs]` slice with a `select_for_cap(raw_jobs, cap)` that applies the stoplist + `career_band`/JD rank + top-N. Fully effective immediately for Greenhouse/SR/Lever big boards (JD present for all). For Workday it still ranks on `career_band`+title (no JD needed for ranking) and keeps JD-drop as best-effort on the ≤500 that have JD.

- **Only seam touched:** `main.py:222` → call `select_for_cap`. New pure module `scrape_select.py` (stoplist regex, rank key, selector) — deterministic, unit-testable, no network, no LLM.
- Providers that internally stop at `max_jobs` (Workday validate cap) must be allowed to page deeper for big companies — see Phase B; until then Phase A works on whatever the provider returned.

### Phase B — Workday listing-uncap + post-rank JD fetch (the Accenture fix)

For a Workday tenant whose India listing count > SOFT_CAP:
1. Page **all** listing metadata uncapped (cheap — title/location/id only).
2. Rank + stoplist-filter on metadata (no JD needed) → pick top `HARD_CAP` technical roles.
3. Fetch JDs **only** for those (raise/replace `WORKDAY_JD_FETCH_LIMIT` with "fetch the selected set").
4. Drop any selected role that still returns no JD.

Bounds request cost (JD-fetch the selected 2500, not all 3000) while capturing deep technical roles the current order loses. Touches `providers/workday.py` fetch ordering — bigger, riskier, so it lands after Phase A is verified.

## Ordering constraint (already verified in code)

`normalize_job_career_band(job)` (job_career_band.py:52) ranks on `title` alone — no JD, no role_domain needed. So metadata-only ranking (Phase B step 2) is already possible with existing deterministic code. No new model calls anywhere.

## Thresholds (defaults — confirm)

| Knob | Proposed default | Note |
|---|---|---|
| `SOFT_CAP` (keep-all below) | 1000 | = current `_DEFAULT_COMPANY_CAP` |
| `HARD_CAP` (max for big cos) | 2500 | or "uncapped among quality-passing"? |
| `MIN_JD_CHARS` (hard-drop thin JD) | 300 | tune vs real thin-but-valid JDs |
| Title stoplist | guard/security/housekeeping/driver/facilities/receptionist/peon/cafeteria/… | grows on-touch |

## Test plan

- `tests/test_scrape_select.py`: stoplist drops guard/PMO-admin; technical ranks above non-technical; thin-JD dropped; ≤SOFT_CAP input returned unchanged; deterministic order.
- Live smoke: `--company "Accenture" --skip-enrich --company-cap 2500` after Phase B → confirm technical share up, no-JD share down vs a baseline `[:1000]` run.

## Rollout / safety

- Forward-only, source-write path — no historical rewrite, consistent with all other normalizers.
- Phase A is behavior-preserving for every company ≤1000 (the vast majority) — only >1000 companies change.
- `--company-cap 0` still = unlimited (bypasses selector) for debugging.

## Open decisions for approval

1. **Scope:** ship Phase A first then B (recommended), or design both then implement together?
2. **HARD_CAP:** 2500, or uncapped among quality-passing roles?
3. **MIN_JD_CHARS:** 300 ok, or different? Applies only to >SOFT_CAP companies.
4. **Stoplist seed:** confirm the drop-word list (add/remove terms).
