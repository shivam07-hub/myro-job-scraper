# Architecture V3 Execution Phases (Codex + Claude Handoff)

## Purpose
This document translates `ARCHITECTURE_V3_MODULAR_PLAN.md` into an execution checklist that either Codex or Claude can continue from any phase.

Core objective:
- Make scraper architecture modular by backend website type (ATS/provider), while preserving current scrape behavior.

Critical rule:
- Finish architecture improvement first; then run the full scraper again.

## Execution Status
- [x] Phase 0 - Baseline Freeze
- [x] Phase 1 - Provider Interface + Registry Skeleton
- [x] Phase 2 - Migrate Workday as Reference Provider
- [x] Phase 3 - Migrate Remaining ATS Providers
- [x] Phase 4 - Shared Schema/Normalization Module
- [x] Phase 5 - Deterministic Validation Layer
- [x] Phase 6 - Observability + Diagnostics Hardening
- [x] Phase 7 - Final Verification and Go-Live Run

---

## Scope and Constraints
- Repo scope: `firecrawl_Supabase/` only.
- Keep LM calls local via LM Studio only.
- Firecrawl cloud is last resort; Docker path is preferred.
- No schema expansion during refactor (keep current canonical fields).
- No large behavior changes during Phase B migration; prioritize parity.

---

## Target Modular Shape

Directory target:
- `scraper/providers/base.py` (provider interface + common result types)
- `scraper/providers/registry.py` (ATS/provider dispatch map)
- `scraper/providers/workday.py`
- `scraper/providers/smartrecruiters.py`
- `scraper/providers/greenhouse.py`
- `scraper/providers/lever.py`
- `scraper/providers/phenom.py`
- `scraper/providers/generic_json.py`
- `scraper/providers/firecrawl_js.py`
- `scraper/providers/__init__.py`
- `scraper/pipeline/orchestrator.py` (optional in later phase; can stay in `main.py` initially)

Single responsibility split:
- `main.py` = CLI + run wiring
- provider modules = fetch/discovery/detail logic by backend type
- `writer.py` = canonical persistence
- `enricher.py` = LM enrichment only
- `csv_importer.py` = ingest/lifecycle/versioning only

---

## Phase 0 - Baseline Freeze (must do first)

Goal:
- Capture current behavior baseline before refactor.

Tasks:
1. Run and store dry-run portal list snapshot.
2. Run validate mode snapshot (`--validate`) and keep summary artifact.
3. Run pipeline smoke tests.
4. Record current outputs/known caveats in a short migration note.

Commands:
- `cd scraper && python main.py --dry-run`
- `cd scraper && python main.py --validate --skip-enrich`
- `cd scraper && python test_pipeline.py`

Deliverables:
- `logs/run_summary_*.json` snapshot reference
- `scraper/MIGRATION_BASELINE.md` with date, commit SHA, and notable issues

Exit criteria:
- We can compare post-refactor behavior against a known baseline.

---

## Phase 1 - Provider Interface + Registry Skeleton

Goal:
- Introduce modular contract without changing runtime behavior.

Tasks:
1. Add provider protocol/interface in `scraper/providers/base.py`.
2. Add provider registry in `scraper/providers/registry.py`.
3. Keep `main.py` behavior unchanged except dispatch call through registry.
4. Add fallback policy contract in one place (not spread across `main.py`).

Suggested interface shape:
- `scrape(portal: dict, max_jobs: int | None, validate_mode: bool) -> list[dict] | None`
- Return `None` only for "blocked, use fallback" semantics where needed.
- `diagnostics()` optional helper per provider.

Deliverables:
- New providers package with no-op wrappers to existing functions.
- `main.py` switched from hard-coded `if ats == ...` chain to registry dispatch.

Exit criteria:
- `python scraper/main.py --dry-run` and `--validate --skip-enrich` still work.

---

## Phase 2 - Migrate Workday as Reference Provider

Goal:
- Prove modular pattern with the most complex provider first.

Tasks:
1. Move Workday logic from `scrapers.py` into `providers/workday.py`.
2. Move Workday helper internals with it (`_workday_india_uuid`, `_find_india_id`, JD fetch logic).
3. Keep Firecrawl fallback semantics identical.
4. Add targeted tests for:
   - UUID discovery behavior
   - pagination de-dup behavior
   - JD fetch path success/fallback

Deliverables:
- `providers/workday.py` fully owning Workday behavior.
- `scrapers.py` references removed for Workday path.

Exit criteria:
- `python scraper/main.py --company "Salesforce" --skip-enrich`
- `python scraper/main.py --company "Accenture" --skip-enrich`
- Output parity with baseline (job counts and JD coverage within expected run variance).

---

## Phase 3 - Migrate Remaining ATS Providers

Goal:
- Complete backend-type modularization.

Migration order:
1. `smartrecruiters`
2. `greenhouse`
3. `lever`
4. `phenom_api`
5. `generic_get` bucket (`custom`, `sap`, `oracle`, `other`)
6. `firecrawl_js` extraction/validate helpers

Tasks per provider:
1. Move logic to `scraper/providers/<name>.py`.
2. Register provider in `registry.py`.
3. Keep input/output dict schema unchanged.
4. Preserve existing fallback and scope (`india_only`) behavior.

Deliverables:
- `scrapers.py` reduced to compatibility shims or removed.

Exit criteria:
- `python scraper/main.py --validate --skip-enrich`
- Spot checks:
  - `python scraper/main.py --company "Stripe" --skip-enrich`
  - `python scraper/main.py --company "ServiceNow" --skip-enrich`
  - `python scraper/main.py --company "Salesforce" --skip-enrich`

---

## Phase 4 - Shared Schema/Normalization Module

Goal:
- Remove schema drift across scraper/writer/importer.

Tasks:
1. Add central schema module (for canonical keys + conversions).
2. Reuse it in `writer.py` and `csv_importer.py`.
3. Remove duplicate key mapping logic where possible.
4. Keep backward compatibility for legacy dumps in importer.

Deliverables:
- `scraper/schema.py` (or `scraper/models/canonical.py`)
- `writer.py` and `csv_importer.py` consuming shared mapping constants.

Exit criteria:
- `python scraper/test_pipeline.py`
- `python csv_importer.py --dry-run`

---

## Phase 5 - Deterministic Validation Layer

Goal:
- Make quality gates explicit and reusable.

Tasks:
1. Create `scraper/validation.py` with hard reject and soft warning rules.
2. Reuse same validation taxonomy in run summaries + importer.
3. Include placeholder detection and rejection reasons in one taxonomy map.

Deliverables:
- Validation functions reusable by scraper runtime and importer.
- Updated run summary to include drop reasons consistently.

Exit criteria:
- Validate mode report includes deterministic reason buckets.
- Import dry-run report aligns with same taxonomy.

---

## Phase 6 - Observability + Diagnostics Hardening

Goal:
- Ensure every low-count or failure is actionable.

Tasks:
1. Standardize logging (replace provider `print` calls with structured logger).
2. Attach provider + reason metadata to unresolved entries.
3. Keep Supabase diagnostics write best-effort.
4. Add run-to-run comparison helper (optional script) for deltas.

Deliverables:
- cleaner `logs/run_summary_*.json` with stable keys
- migration note for common failure signatures

Exit criteria:
- A failed company entry always includes provider and primary reason.

---

## Phase 7 - Final Verification and Go-Live Run

Goal:
- Confirm architecture refactor is stable, then run scraper again.

Pre-flight checks:
1. `python scraper/main.py --dry-run`
2. `python scraper/main.py --validate --skip-enrich`
3. `python scraper/test_pipeline.py`
4. `python csv_importer.py --dry-run`

Smoke production sequence:
1. `python scraper/main.py --company "Stripe" --skip-enrich`
2. `python scraper/main.py --company "ServiceNow" --skip-enrich`
3. `python scraper/main.py --company "Salesforce" --skip-enrich`

After all checks pass:
- Run the full scraper again:
  - `cd scraper && python main.py --skip-enrich`
- Then enrichment pass:
  - `cd scraper && python main.py --enrich-only`
- Then import:
  - `python csv_importer.py`

Rule:
- If any pre-flight step fails, do not run the full scrape; fix and re-verify first.

---

## Handoff Protocol (for Codex or Claude)

At end of each phase, update:
1. `scraper/MIGRATION_STATUS.md`
2. `scraper/ARCHITECTURE_V3_EXECUTION_PHASES.md` checkbox status
3. `AGENTS.md` run-history note (short)

Use this handoff template:
- Phase completed:
- Files changed:
- Behavior changes:
- Verification commands run:
- Known issues remaining:
- Next immediate phase/task:

---

## Suggested Phase Ownership Split (parallel-safe)

Track A (Core modularization):
- Phase 1, Phase 2, Phase 3

Track B (Data model integrity):
- Phase 4, Phase 5

Track C (Ops reliability):
- Phase 6, Phase 7

Parallelization rule:
- Only run tracks in parallel if file ownership does not overlap.
- Prefer sequential for early phases to reduce merge risk.

---

## Definition of Done for This Refactor

1. ATS logic lives in provider modules by backend type.
2. `main.py` no longer contains ATS-specific branching logic.
3. Shared schema mapping is centralized.
4. Validation and diagnostics reason taxonomy is explicit.
5. Baseline parity checks pass on key companies.
6. After all above, we run the scraper again.
