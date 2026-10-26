# HANDOVER — Job Scraper & Skill Intelligence Pipeline

**Audience:** incoming CTO · **Updated:** 2026-10-26 (first written 2026-06-08) · **Maintainer:** Shivam

A one-page orientation. Deep reference lives in `CLAUDE.md` (architecture,
current state, pending work), `KNOWN_PORTALS.md` (per-portal config),
`RUN_HISTORY.md` (run log), `docs/RAILWAY.md` (the schedule).

---

## 1. What this is

A daily pipeline that scrapes corporate job postings (India-first) directly
from company career portals and publishes them to Supabase. Downstream, the
**True_Yodha** product (Myro) turns that into skill intelligence for users:
which skills are being hired for in the AI age, and how to build them.

**Core rule:** if a company's ATS exposes a direct API, we use it. Scrapling
(plain HTTP fetch) and then Firecrawl (headless browser) are fallbacks for
JS-opaque portals, not the default — it keeps cost and fragility down.

---

## 2. Architecture

```
KNOWN_PORTALS.md            portal config (URL, ATS type, company)  ── 318 portals, 62 ATS types
        │
        ▼
main.py + providers/        one module per ATS → direct API → raw jobs.json   ── 63 provider modules
        │
        ▼
source_matching_facts.py    MANDATORY: stamps career_band + provenance (deterministic rules)
        │
        ▼
csv_importer.py             --source-only publish: upsert, lifecycle, location, feed close
        │                   (job is live immediately; hands run_id to True_Yodha Stage A)
        ▼
enrichment_worker.py        later, on local LM Studio: job_summary + role_domain
job_embedding_worker.py     later, on local LM Studio: semantic-search vectors
        │
        ▼
diagnose.py + heal/         Phase 4 self-healing: classify failures, probe routes, propose fixes
```

**Where it runs (since 2026-10-10):** a Railway cron runs `daily_poll.py`
(scrape → resolve → publish) at 01:00 IST. The laptop only drains inference,
through an hourly launchd agent (`daily_cycle.py --inference-only`).
Publication never waits for a model.

**Who owns skills:** the `job_skills` table is written by True_Yodha's skill
engine (Stage A / Stage B), not by this pipeline. The importer only reports
taxonomy drift.

---

## 3. Current state (read-only, 2026-10-26)

| Metric | Value |
|---|---|
| Jobs in Supabase | 62,692 (`jobs`), 55,484 active |
| Skill edges | 572,946 (`job_skills`, owned by True_Yodha) |
| Skill taxonomy | 35,108 Lightcast L3 skills |
| Portals configured | 318 across 62 ATS types |
| Provider modules | 63 (Workday, SmartRecruiters, Greenhouse, Phenom/PCSX, Eightfold, Zwayam, RippleHire, …) |
| Enrichment backlog | 96 jobs |
| Tests | 66 `test_*.py` files in `scraper/tests/` + `scraper/tests/question_bank/` |

**🔴 Publication is down.** No source publish since 2026-10-20: the 5 GB
Railway volume filled on 2026-10-21 and every run since dies before
publishing. The fix is on branch `feat/railway-volume-retention`, not yet
merged. See `CLAUDE.md` → PENDING WORK → 0.

---

## 4. What works / what's pending

**Works**
- Direct-API scraping across 62 ATS types; "crack once, reuse forever" registries
  (`workday_registry.json`, `generic_registry.json`) so a solved portal stays solved.
- Source-first publication: jobs go live without waiting for AI; summaries,
  role domains and embeddings arrive later as upgrades and never get overwritten
  by a re-scrape.
- Listing lifecycle: jobs missing from a complete run, or unseen for 30 days,
  are closed. A partial run demotes nothing.
- Community freshness layer (users can report stale jobs; 5 reports deactivates).
- **Self-healing diagnostic:** `diagnose.py` auto-classifies every run's
  0-job companies into buckets (regression / param-suspect / needs-crack /
  blocked / cookie-needed), live-probes the recoverable routes, and proposes
  fixes as reviewable diffs.
- Shared paginator `providers/_paginate.py` (zwayam and eightfold use it; the
  other providers adopt it when next touched).

**Pending / known** (full list: `CLAUDE.md` → PENDING WORK)
- Restore daily publication (merge the Railway volume fix).
- Location release: database side live since 2026-10-07; code branch
  `claude/blissful-mclean-a9f285` awaits review.
- About 24% of active jobs have no seniority level, concentrated in a few adapters.
- Portals with no durable route (Vehere, Godrej Industries, Avendus, IndusInd,
  Uber, Walmart) are parked.
- Darwinbox portals (Swiggy/Flipkart/Myntra…) need short-lived CF cookies in env.
- Scale-out toward 10k companies: the discovery engine works; execution is left.

---

## 5. How to run

```bash
cd scraper

python environment.py              # which capabilities this env can run (no secret values)

# Daily lane (what Railway runs): scrape → resolve → publish, run date pinned
python daily_poll.py --scope india

# The same steps by hand
RUN_DATE=$(date +%Y_%m_%d)
python main.py --skip-enrich --scope india
python source_matching_facts.py --run-date "$RUN_DATE" --allow-unresolved
python csv_importer.py --source-only --publish-unclassified --run-date "$RUN_DATE" --dry-run
python csv_importer.py --source-only --publish-unclassified --run-date "$RUN_DATE"

# Inference lane (what the laptop runs hourly)
python daily_cycle.py --inference-only

# Phase 4 — self-healing diagnostic (after a scrape)
python diagnose.py                 # classify failures → logs/diagnosis_<run>.md
python diagnose.py --probe         # live re-test recoverable routes
python diagnose.py --propose       # emit reviewable fix diffs

# Tests
python -m pytest -q
```

---

## 6. Where to look

| Question | File |
|---|---|
| How a given company is scraped | `KNOWN_PORTALS.md` + `scraper/providers/<ats>.py` |
| Full architecture, schema, open work | `CLAUDE.md` |
| The Railway schedule and its checks | `docs/RAILWAY.md`, `docs/handoffs/HANDOFF_2026-10-10_railway_cutover.md` |
| Async enrichment contract | `scraper/ASYNC_ENRICHMENT.md` |
| What happened in past runs | `RUN_HISTORY.md` |
| Why a run had 0-job companies | `logs/diagnosis_<run_id>.md` (generated) |
| Downstream product spec | `True_Yodha/` repo |
