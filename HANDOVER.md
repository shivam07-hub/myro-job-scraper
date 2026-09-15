# HANDOVER — Job Scraper & Skill Intelligence Pipeline

**Audience:** incoming CTO · **Date:** 2026-06-08 · **Maintainer:** Shivam

A one-page orientation. Deep reference lives in `CLAUDE.md` (architecture),
`KNOWN_PORTALS.md` (per-portal config), `RUN_HISTORY.md` (run log).

---

## 1. What this is

A weekly pipeline that scrapes corporate job postings (India-first) directly
from company career portals, extracts the **skills** each job demands, and loads
them into Supabase. Downstream, the **True_Yodha** product turns that into skill
intelligence for users: which skills are being hired for in the AI age, and how
to build them.

**Core rule:** if a company's ATS exposes a direct API, we use it. Firecrawl
(headless browser) is a fallback for JS-opaque portals, not the default — it
keeps cost and fragility down.

---

## 2. Architecture

```
KNOWN_PORTALS.md            portal config (URL, ATS type, company)  ── 290 portals, 54 ATS types
        │
        ▼
main.py + providers/        one module per ATS → direct API → raw jobs   ── 54 providers
   (Firecrawl only for JS-opaque portals, via Docker)
        │
        ▼
enricher.py + LM Studio     job description → role_domain + skills[] (Lightcast L3 + level 1–4)
        │
        ▼
csv_importer.py             upsert to Supabase (dedup, lifecycle, location, skills)
        │
        ▼
diagnose.py + heal/         Phase 4 self-healing: classify failures, probe routes, propose fixes
```

Two-phase by necessity: Docker (scrape) and LM Studio (enrich) can't share RAM,
so scrape → enrich → load run sequentially.

---

## 3. Current state

| Metric | Value |
|---|---|
| Jobs in Supabase | ~19,000 (`jobs` table) |
| Resolved skill edges | ~212,000 (`job_skills`) |
| Skill taxonomy | 35,108 Lightcast L3 skills |
| Portals configured | 290 across 54 ATS types |
| Direct-API providers | 54 (Workday, SmartRecruiters, Greenhouse, Phenom/PCSX, Eightfold, Zwayam, RippleHire, …) |
| Tests | 14 suites (provider + pipeline + self-healing) |

---

## 4. What works / what's pending

**Works**
- Direct-API scraping across 54 ATS types; "crack once, reuse forever" registries
  (`workday_registry.json`, `generic_registry.json`) so a solved portal stays solved.
- LM Studio skill enrichment → flat `skills[]` with proficiency level (1–4).
- Supabase load with dedup, location normalization, community freshness layer
  (users can report stale jobs; 5 reports auto-deactivates).
- **Self-healing diagnostic (new):** `diagnose.py` auto-classifies every run's
  0-job companies into buckets (regression / param-suspect / needs-crack /
  blocked / cookie-needed), live-probes the recoverable routes, and proposes
  fixes as reviewable diffs. Replaces a hand-written triage doc.

**Pending / known**
- **Shared paginator (tracked):** pagination stop-logic is copy-pasted across ~28
  providers; the correctness depends on an implicit "did we control the page size?"
  invariant. One provider (Zwayam) violated it and silently truncated 3 companies
  to a handful of jobs — now fixed + tested. The durable fix is to extract a single
  `paginate()` seam so the bug becomes structurally impossible. ~28-file refactor,
  deferred.
- A few portals have no durable route (Vehere, Godrej Industries) — Cloudflare/Akamai
  blocked; parked.
- Darwinbox portals (Swiggy/Flipkart/Myntra…) need short-lived CF cookies in env.

---

## 5. How to run

```bash
cd scraper

# Phase 1 — scrape (Docker on, LM Studio off)
python main.py --skip-enrich --scope india --global-cap 2000

# Phase 2 — enrich (LM Studio on, Docker off)
python main.py --enrich-only

# Phase 3 — load to Supabase
python csv_importer.py --dry-run   # verify counts
python csv_importer.py             # upsert

# Phase 4 — self-healing diagnostic (after a scrape)
python diagnose.py                 # classify failures → logs/diagnosis_<run>.md
python diagnose.py --probe         # live re-test recoverable routes
python diagnose.py --propose       # emit reviewable fix diffs

# Tests
python -m pytest -q
```

**Weekly automation:** `0 2 * * 0` via `.archon/workflows/scraper-weekly-run.yaml`.

---

## 6. Where to look

| Question | File |
|---|---|
| How a given company is scraped | `KNOWN_PORTALS.md` + `scraper/providers/<ats>.py` |
| Full architecture & schema | `CLAUDE.md` |
| What happened in past runs | `RUN_HISTORY.md` |
| Why a run had 0-job companies | `logs/diagnosis_<run_id>.md` (generated) |
| Downstream product spec | `True_Yodha/` repo |
