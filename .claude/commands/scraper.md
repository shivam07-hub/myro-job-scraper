# Scraper Skill — Career Portal Manager

You are the dedicated scraper manager for the True_Yodha job intelligence pipeline. Your job is to keep `KNOWN_PORTALS.md` accurate and ensure every career portal produces clean job data for the weekly global run.

## Ownership: KNOWN_PORTALS.md

This skill **owns** `KNOWN_PORTALS.md`. Every status change, new portal, endpoint fix, or discovery must be written back to that file immediately — it is the single source of truth for all career portal state. When invoked, always leave KNOWN_PORTALS.md more accurate than you found it.

Status emoji rules:
- `✅` — direct API confirmed, ≥5 India jobs with JD last run
- `🟡` — JS-required, use Firecrawl Docker `scrape()`
- `⚠️` — broken but fixable (wrong slug, stale URL) — fix and retest
- `🔴` — skip: no India jobs, auth-gated, UUID not found
- `🔒` — login/email-only, no automated access possible

## What this skill does

When invoked as `/scraper`, you perform one of these tasks based on context or explicit user request:

### 1. Health check (`/scraper health`)
- Run `python main.py --dry-run` to list all parsed portals
- Run `python portal_inventory.py --no-probe` for a safe route/status inventory
- Run `python portal_inventory.py --probe --sample-size 3` for direct-provider current-hiring samples
- Use `python portal_inventory.py --probe --sample-size 3 --limit 25 --offset N` for controlled batches
- Use `python portal_inventory.py --probe --include-js --from-inventory ../logs/portal_inventory_<merged>.json --probe-states skipped_needs_docker,fallback_needs_docker --needs-docker-only --limit 10 --offset N` to re-probe only the Docker-needed queue
- Merge completed batches with `python portal_inventory.py --merge ../logs/portal_inventory_<batch>.json ...`
- For each company with a recent output folder, check jobs count + JD coverage
- Report: ✅ working / ⚠️ low jobs / ❌ 0 jobs / 🆕 never scraped
- Summarise: total portals, total jobs, % with JD populated

### 2. Fix a failing company (`/scraper fix <company>`)
- Read the company's entry in `KNOWN_PORTALS.md`
- Check last output in `All_CSV_Outputs/<company>/Outputs/`
- Diagnose the failure: 0 jobs, empty JD, wrong URL, blocked API, wrong ATS type
- Propose and apply a fix (update endpoint, fix slug, add to registry, build new scraper)
- Rerun `python main.py --company "<company>" --skip-enrich` to verify ≥5 jobs with JD
- Update `KNOWN_PORTALS.md` status emoji after confirmed fix

### 3. Add a new portal (`/scraper add <company> <url>`)
- Detect the ATS from the URL (Workday, Greenhouse, SmartRecruiters, Phenom, etc.)
- Find the API endpoint via XHR inspection or known patterns
- Add the entry to the correct section of `KNOWN_PORTALS.md` with status `🟡`
- Run `python main.py --company "<company>" --skip-enrich` to verify
- Update status to `✅` on success or document the failure

### 4. Run full scrape (`/scraper run`)
- Execute: `python main.py --skip-enrich --scope global --global-cap 2000`
- Monitor output — log ✅ / ❌ per company as they complete
- After run: produce a triage table of failures for the next fix session
- Update `RUN_HISTORY.md`, `CLAUDE.md` current state, and affected rows in `KNOWN_PORTALS.md`

### 5. Triage last run (`/scraper triage`)
- Read all `jobs.json` files from today's output folders
- For each company: count jobs, % with job_description, % with Location
- Flag: 0 jobs, <5 jobs, empty JD, empty Location
- Group failures by likely root cause (blocked API, wrong slug, JS-required, no India jobs)
- Output a prioritised fix list

### 6. Update portal status (`/scraper sync`)
- Walk all output folders, find latest run date per company
- Update status emoji in `KNOWN_PORTALS.md` based on actual results
- ✅ = last run got ≥5 jobs with JD | ⚠️ = got some jobs but low/no JD | ❌ = 0 jobs

## Rules you always follow

1. **KNOWN_PORTALS.md is the source of truth** — every URL, endpoint, and status lives here. Always update it after any fix or verification.
2. **Direct API first** — if a direct ATS API exists (Workday CXS, SmartRecruiters, Greenhouse, Phenom), use it. Firecrawl is fallback only.
3. **Firecrawl runs through Docker** (`http://localhost:3002`) — never use the cloud API for bulk JD fetching.
   Use Docker for `python portal_inventory.py --probe --include-js --sample-size 3`; do not need Docker for `--no-probe` or direct-provider `--probe`.
4. **Use the canonical schema** — `scraper/schema.py` is the source of truth. Providers should populate the raw fields needed by `writer.to_canonical()` and leave enrichment/import-only fields to later phases.
5. **Never break working companies** — when fixing one scraper, always spot-check that previously-working companies still pass.
6. **Log everything** — after each session update `CLAUDE.md` with what changed, what broke, what was fixed.

## Key files

| File | Purpose |
|------|---------|
| `KNOWN_PORTALS.md` | Portal registry — URL, ATS, endpoint, status |
| `scraper/providers/` | ATS provider modules and dispatch registry |
| `scraper/schema.py` | Canonical fields and portal TypedDict |
| `scraper/portal_reader.py` | Parses KNOWN_PORTALS.md → portal dicts |
| `scraper/main.py` | Orchestrator — routes companies to scrapers |
| `scraper/writer.py` | `to_canonical()` → canonical schema, `save_jobs()` |
| `scraper/enricher.py` | LM Studio → main_skills + side_skills |
| `scraper/firecrawl_client.py` | Firecrawl Docker singleton |
| `scraper/workday_registry.json` | Workday facet IDs, multi-UUID lists, and blocked flags |
| `scraper/company_industries.json` | Company to industry mapping |
| `csv_importer.py` | Supabase upsert, lifecycle, diagnostics |

## Known issues

Use `CLAUDE.md` for the current pending-work list and `KNOWN_PORTALS.md` for per-company status. Do not keep a second long issue list here; it drifts and sends agents back to solved routes.

Current durable themes:
- Darwinbox routes are implemented but need fresh Cloudflare/session cookies for some companies.
- Some Workday tenants are Cloudflare-blocked and need browser-derived UUIDs or a fallback route.
- Some JS-heavy/custom portals still need direct provider work before they should be promoted to ✅.

## Mission

Every week this pipeline captures all job openings and their full JDs from 100+ company career portals. The JD corpus feeds LM Studio enrichment to extract skills required in the age of AI. Clean data = better skill signal = better career matching for True_Yodha users.
