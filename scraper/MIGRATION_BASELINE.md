# Migration Baseline (Phase 0)

- Date: 2026-04-27
- Branch: `main`
- Commit SHA: `05d6c4e35`
- Baseline mode: pre-Phase-1 runtime dispatch (`main.py` ATS branching path active)

## Commands Run

1. `cd scraper && python main.py --dry-run`
2. `cd scraper && python main.py --validate --skip-enrich`
3. `cd scraper && python test_pipeline.py`

## Artifacts

- Dry-run log: `/Users/incognito/firecrawl_Supabase/logs/run_2026_04_27_205627.log`
- Validate log: `/Users/incognito/firecrawl_Supabase/logs/run_2026_04_27_205638.log`
- Validate summary JSON: `/Users/incognito/firecrawl_Supabase/logs/run_summary_20260427_211642.json`

## Validate Snapshot Summary

- Portals processed: `135`
- Portals skipped: `24`
- Total new jobs in validate output: `339`
- Low-count companies (<5 scraped jobs): `31`
- Unresolved companies: `24`
- Hard runtime errors: `0`

## Known Caveats Captured in Baseline

- `test_pipeline.py` failed with 5 checks:
  - `All portals have industry` (`24` missing)
  - `strip_html: normal HTML` (spacing issue in expected string)
  - `10 fields` (`to_canonical` currently emits `11`)
  - `role_domain set` (LM call failed; LM Studio unavailable during test)
  - `main_skills filled` (same LM connectivity issue)
- Validate run shows expected recurring warning patterns:
  - Workday API blocked/unauthorized tenants falling back to Firecrawl
  - Firecrawl anti-bot/no-link pages returning `0` jobs for some portals
  - Low-count warnings on several JS-heavy portals
