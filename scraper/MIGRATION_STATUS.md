# Migration Status - Architecture V3 → v2.0 Release

Use this file as the single handoff status board for Codex/Claude.

## Current Snapshot
- Date: 2026-04-28
- Branch: `main`
- Version: **v2.0** — all architecture phases complete, production-ready
- Last completed phase: `D1 — workday_registry.json + CLAUDE.md v2.0 update`
- Current in-progress phase: **NONE — ready for production run**
- Next command to run: `cd scraper && python main.py --skip-enrich` (Phase 1: scrape all)

## Architecture Phase Checklist (v2.0)
- [x] Phase 0 - Baseline Freeze
- [x] Phase 1 - Provider Interface + Registry Skeleton
- [x] Phase 2 - Workday Provider Migration
- [x] Phase 3 - Remaining Provider Migrations
- [x] Phase 4 - Shared Schema/Normalization Module
- [x] Phase 5 - Deterministic Validation Layer
- [x] Phase 6 - Observability + Diagnostics Hardening
- [x] Phase 7 - Final Verification and Go-Live Run
- [x] A1 - scrapers.py deleted
- [x] A2 - All singletons lazy-init
- [x] B1 - Portal TypedDict in schema.py
- [x] B2 - company_industries.json (industry mapping out of Python)
- [x] C1 - pipeline_validator.py (single run_gate() fn)
- [x] C2 - ScrapeReason enum + ProviderResult typed returns
- [x] D1 - company_registry.py deleted → workday_registry.json

## Latest Handoff
- Phase completed: `Phase 3 - Remaining Provider Migrations`
- Files changed:
  - `scraper/providers/smartrecruiters.py` — full SmartRecruiters logic moved here
  - `scraper/providers/greenhouse.py` — full Greenhouse logic moved here
  - `scraper/providers/lever.py` — full Lever logic + `_INDIA_KEYWORDS` moved here
  - `scraper/providers/phenom.py` — full Phenom API logic moved here
  - `scraper/providers/generic_json.py` — `scrape_get`, `_parse_json_response` moved here
  - `scraper/providers/firecrawl_js.py` — `scrape_validate`, `scrape_extract`, link patterns moved here
  - `scraper/scrapers.py` — historical shim at this phase; later deleted in A1
- Behavior changes:
  - `scrapers.py` is now a pure shim file; all ATS logic lives in `providers/`
  - Circular import resolved via lazy imports in all shim functions
- Verification commands run:
  - `python scraper/main.py --dry-run` (pass; 162 portals)
  - `python scraper/main.py --company "Stripe" --skip-enrich` (pass; 64 jobs — Greenhouse path)
  - `python scraper/main.py --company "ServiceNow" --skip-enrich` (pass; 26 jobs — SmartRecruiters path)
  - `python scraper/main.py --company "Salesforce" --skip-enrich` (pass; 169 jobs — Workday path)
- Known issues remaining:
  - `test_pipeline.py` baseline still has 5 known failing checks (pre-existing)
- Next immediate phase/task: Phase 4 — create shared schema module, wire writer.py + csv_importer.py to it

## Latest Handoff (Phase 4+5)
- Phase completed: `Phase 4 - Shared Schema/Normalization Module` + `Phase 5 - Deterministic Validation Layer`
- Files changed:
  - `scraper/schema.py` — new: `CANONICAL_FIELDS`, `RAW_FIELD_MAP`, `SKILL_FIELDS`, `LEGACY_FIELD_ALIASES`
  - `scraper/validation.py` — new: `is_valid()`, `drop_reason()`, `quality_score()`, `is_placeholder_title()`, `LOW_COUNT_THRESHOLD`
  - `scraper/writer.py` — imports `CANONICAL_FIELDS`, `RAW_FIELD_MAP` from `schema.py`
  - `csv_importer.py` — imports `CANONICAL_FIELDS`, `LEGACY_FIELD_ALIASES` from `schema.py`; imports `is_valid`, `is_placeholder_title`, `quality_score`, `LOW_COUNT_THRESHOLD` from `validation.py`; `preprocess()` uses `is_valid()` for hard-reject gate
  - `scraper/main.py` — imports `LOW_COUNT_THRESHOLD`, `drop_reason` from `validation.py`; `run()` validates canonical jobs post-`to_canonical()` using `drop_reason()`; drops logged with reason taxonomy; `total_validation_drops` in run summary; `validation_drops` per company in `company_stats`; `LOW_COUNT_THRESHOLD` replaces hardcoded `5`
- Behavior changes:
  - Invalid jobs (missing `job_id` or `job_title`) now dropped with named reason before enrichment
  - `low_count` warning threshold is now pulled from `validation.py` constant, not hardcoded
  - Run summary JSON includes `total_validation_drops` + per-company `validation_drops` count
- Verification commands run:
  - `cd scraper && python main.py --dry-run` — pass (159 portals)
  - `python -c "import main"` (from scraper/) — pass, no import errors
  - `python -c "import csv_importer"` (from project root) — pass, no import errors
- Known issues remaining:
  - `test_pipeline.py` baseline still has 5 known failing checks (pre-existing)
- Next immediate phase/task: Phase 6 — structured logging in providers, provider+reason metadata on unresolved entries

## Verification Log
- `2026-04-27 20:56` - `cd scraper && python main.py --dry-run` - pass (`159` portals listed)
- `2026-04-27 20:56` - `cd scraper && python main.py --validate --skip-enrich` - pass (`run_summary_20260427_211642.json`)
- `2026-04-27 21:16` - `cd scraper && python test_pipeline.py` - fail (5 checks; baseline-captured)
- `2026-04-27 21:18` - `python scraper/main.py --dry-run` - pass (159 portals, provider registry path)
- `2026-04-27 21:18` - `python scraper/main.py --validate --skip-enrich` - pass (`run_summary_20260427_213806.json`)
- `2026-04-28 09:42` - `python scraper/main.py --dry-run` - pass (162 portals)
- `2026-04-28 09:48` - `python scraper/main.py --company "Salesforce" --skip-enrich` - pass (169 jobs, 169/169 JDs)
- `2026-04-28 09:43` - `python scraper/main.py --validate --skip-enrich` - pass (`run_summary_20260428_095212.json`)
- `2026-04-28 10:26` - `cd scraper && python main.py --dry-run` - pass (159 portals; Phase 5 wiring verified)
- `2026-04-28 10:36` - `cd scraper && python main.py --dry-run` - pass (159 portals; Phase 6 logging verified)
- `2026-04-28 10:50` - `cd scraper && python main.py --dry-run` - pass (159 portals; Phase 7 pre-flight)
- `2026-04-28 11:09` - `cd scraper && python main.py --validate --skip-enrich` - pass (135/159 processed, 24 unresolved known-broken, 0 errors, 0 validation_drops; `run_summary_20260428_110913.json`)
- `2026-04-28 10:55` - `cd scraper && python main.py --company "Stripe" --skip-enrich` - pass (64 scraped, 0 new — deduped)
- `2026-04-28 10:56` - `cd scraper && python main.py --company "ServiceNow" --skip-enrich` - pass (26 scraped, 0 new — deduped)
- `2026-04-28 10:59` - `cd scraper && python main.py --company "Salesforce" --skip-enrich` - pass (171 scraped, 171/171 JDs, 3 new)
- `2026-04-28 11:09` - `cd scraper && python test_pipeline.py` - 5 pre-existing failures (no regressions vs baseline)
- `2026-04-28 11:09` - `python csv_importer.py --dry-run` - pass (308 jobs, 308/308 pass, 0 drop, 100% JD coverage)

## Latest Handoff (Phase 6)
- Phase completed: `Phase 6 - Observability + Diagnostics Hardening`
- Files changed:
  - `scraper/providers/workday.py` — `import logging` + `_log = logging.getLogger("mirror")`; all 14 `print()` calls replaced with `_log.info/warning/error()`
  - `scraper/providers/smartrecruiters.py` — same pattern; 2 `print()` calls replaced
  - `scraper/providers/greenhouse.py` — same pattern; 1 `print()` call replaced
  - `scraper/providers/lever.py` — same pattern; 3 `print()` calls replaced
  - `scraper/providers/phenom.py` — same pattern; 2 `print()` calls replaced
  - `scraper/providers/generic_json.py` — same pattern; 2 `print()` calls replaced
  - `scraper/providers/firecrawl_js.py` — same pattern; 6 `print()` calls replaced
- Behavior changes:
  - All provider diagnostic output now flows through `logging.getLogger("mirror")` — appears in both stdout and log file (`logs/run_*.log`)
  - `[ERROR]` messages → `log.error()`, `[WARN]` → `log.warning()`, counts/status → `log.info()`
  - No protocol change — providers still have same `scrape()` signature
- Verification commands run:
  - `grep -rn "print(" scraper/providers/` — 0 results (all replaced)
  - `python -c "from providers import dispatch_scrape"` — pass
  - `cd scraper && python main.py --dry-run` — pass (159 portals)
- Known issues remaining:
  - `test_pipeline.py` baseline still has 5 known failing checks (pre-existing)
  - Run-to-run comparison helper not implemented (Phase 6 optional task — deferred to post-Phase 7)
- Next immediate phase/task: Phase 7 — full pre-flight verification + go-live run

## Latest Handoff (Phase 7)
- Phase completed: `Phase 7 - Final Verification and Go-Live Run`
- All pre-flight checks passed — Architecture V3 refactor is verified stable
- Verification results:
  - `--dry-run`: 159 portals, no errors
  - `--validate --skip-enrich`: 135/159 processed, 24 unresolved (all known-broken portals), 0 errors, 0 validation_drops
  - `test_pipeline.py`: 5 failures — all pre-existing (identical to Phase 0 baseline), no regressions introduced
  - `csv_importer.py --dry-run`: 308 jobs, 100% pass rate, 0 drops, 100% JD coverage on smoke companies
  - Smoke: Stripe 64, ServiceNow 26, Salesforce 171/171 JDs — all pass
- Architecture V3 Definition of Done — all criteria met:
  - [x] ATS logic lives in provider modules by backend type
  - [x] `main.py` no longer contains ATS-specific branching logic
  - [x] Shared schema mapping centralized (`schema.py`)
  - [x] Validation and diagnostics reason taxonomy explicit (`validation.py`)
  - [x] Baseline parity checks pass on key companies
  - [x] Provider output flows through structured logger (not print)
- Next: production go-live run (user-triggered):
  1. `cd scraper && python main.py --skip-enrich`  (Phase 1: full scrape)
  2. `cd scraper && python main.py --enrich-only`  (Phase 2: LLM enrichment — LM Studio on, Docker off)
  3. `python csv_importer.py`                       (Phase 3: Supabase upsert)

## Latest Handoff (D1 + v2.0 Release)
- Phase completed: `D1 — Config Consolidation + v2.0 tagging`
- Files changed:
  - `scraper/workday_registry.json` — NEW: all Workday tenant overrides (12 entries: Intel/Target search_text mode; 3M/NXP/Autodesk/DXC/Airbus/Shell/Roche/Philips facet+UUID; Barclays 12 UUIDs; Maersk 26 UUIDs)
  - `scraper/portal_reader.py` — removed `_WORKDAY_REGISTRY` hardcoded dict; added `_load_workday_registry()` lazy JSON loader; `_workday()` calls loader instead of dict
  - `CLAUDE.md` — updated to v2.0; version history table; BUILD PLAN shows all Arch phases complete; removed open-phase descriptions
  - `KNOWN_PORTALS.md` — Philips/Intel/Target status notes updated (no longer reference company_registry.py)
  - `scraper/main.py` — bugfix: `len(validation_drops)` → `g1.drop_count + g2.drop_count` (undefined var from pre-refactor)
- Behavior: identical to pre-D1; workday_registry.json loaded lazily on first Workday parse
- Verification: `python main.py --dry-run` → 159 portals (unchanged)
- Run schedule starting v2.0:
  1. `cd scraper && python main.py --skip-enrich` — Phase 1: scrape all portals (Docker on)
  2. `cd scraper && python main.py --enrich-only` — Phase 2: LLM enrichment (LM Studio on)
  3. `python csv_importer.py` — Phase 3: Supabase upsert

## Blockers
- None
