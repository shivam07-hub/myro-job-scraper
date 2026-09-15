# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

---

## SCOPE

All work must stay within the `myro-job-scraper/` directory. Do not read, write, or modify files outside this folder.

## CHANGE DISCIPLINE

Prefer running and reusing the existing pipeline code, configuration, CLI flags, scripts, and diagnostics before changing implementation.

- Do not write or modify code by default during scraper runs or pipeline iteration.
- First try existing commands, env flags, providers, importer dry-runs, logs, and Supabase diagnostics.
- Only propose a code change after a concrete failure is observed and the existing code/config cannot handle it safely.
- Before writing code, discuss the failure, root cause, options, and tradeoffs with the user, then wait for explicit approval.
- User-requested documentation updates are allowed, but implementation files should stay untouched unless approved.

## LLM CONFIGURATION — LM Studio only

**No cloud AI APIs are permitted.** All LLM calls must route through a locally running LM Studio instance.

LM Studio exposes an OpenAI-compatible REST API at `http://localhost:1234/v1`. Configure your `.env` (or `apps/api/.env`) like this:

```
OPENAI_BASE_URL=http://localhost:1234/v1
OPENAI_API_KEY=lm-studio
MODEL_NAME=<model-id-as-shown-in-lm-studio>
MODEL_EMBEDDING_NAME=<embedding-model-id-or-omit>
```

Alternatively, if you run LM Studio in Ollama-compatible mode (port 11434):
```
OLLAMA_BASE_URL=http://localhost:11434
MODEL_NAME=<model-id>
```

The API auto-selects the provider: if `OLLAMA_BASE_URL` is set it uses the Ollama provider; otherwise it uses OpenAI provider (which LM Studio's `/v1` satisfies). Both paths are in `apps/api/src/lib/generic-ai.ts`.

Do not set `OPENAI_API_KEY` to a real OpenAI key, and do not set `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, or any other cloud provider keys. The `HAS_AI` guard in tests (`apps/api/src/__tests__/snips/lib.ts`) checks for `OPENAI_API_KEY || OLLAMA_BASE_URL` — your local setup satisfies this.

---

## COMMANDS

### Start the full stack (Docker — recommended)
```bash
# From firecrawl/ root
cp apps/api/.env.example apps/api/.env   # then edit with LM Studio settings above
docker compose build
docker compose up
```
API is available at `http://localhost:3002`. Queue admin at `http://localhost:3002/admin/CHANGEME/queues`.

### Development (Node.js, no Docker)
```bash
cd apps/api
pnpm install
pnpm dev           # API server in watch mode
pnpm workers       # Queue workers in watch mode (separate terminal)
```

### Running tests
```bash
# Always use the harness — it starts API + workers automatically
pnpm harness jest <pattern>      # e.g. pnpm harness jest scrape

# Self-hosted / local suite (no external auth needed)
pnpm test:local-no-auth

# Snippet (E2E) tests only
pnpm test:snips
```
The full test suite is slow; run only the relevant pattern locally and let CI run the full suite.

### Python SDK
```bash
cd apps/python-sdk
pip install -r requirements.txt
python example.py
```
Point the client at your local API: `Firecrawl(api_key="local", api_url="http://localhost:3002")`.

---

## ARCHITECTURE

Firecrawl is a monorepo. The production system has these moving parts:

| Component | Path | Role |
|---|---|---|
| **API server** | `apps/api/src/` | Express HTTP server — handles all `/v1` and `/v2` routes |
| **Queue workers** | `apps/api/src/services/queue-worker*` | BullMQ consumers that execute scrape/crawl/extract jobs |
| **Playwright service** | `apps/playwright-service-ts/` | Headless browser microservice (separate Docker container, port 3000) |
| **Redis** | `apps/redis/` | Job queue backing store + rate-limit cache |
| **RabbitMQ** | docker-compose | Alternate message bus for some worker flows |
| **PostgreSQL** | `apps/nuq-postgres/` | Job metadata, crawl state |

### Request flow
```
Client → POST /v1/scrape (or /v2/*)
  → Route handler (apps/api/src/routes/)
    → Validation (zod schemas)
    → Job enqueued to BullMQ (Redis)
      → Queue worker picks up job
        → Scrape engine (cheerio for simple, Playwright microservice for JS-heavy)
        → Optional AI enrichment (generic-ai.ts → LM Studio)
        → Result stored / returned to client
```

### AI layer
- `apps/api/src/lib/generic-ai.ts` — single entry point for all LLM calls. Provider is selected at runtime based on env vars. Supports OpenAI (incl. custom baseURL), Ollama, Anthropic, Groq, Vertex, etc.
- `apps/api/src/config.ts` — validated env schema (Zod). Key AI fields: `MODEL_NAME`, `MODEL_EMBEDDING_NAME`, `OLLAMA_BASE_URL`, `OPENAI_BASE_URL`.

### SDKs
`apps/js-sdk/`, `apps/python-sdk/`, `apps/rust-sdk/`, `apps/java-sdk/`, `apps/elixir-sdk/` — thin clients over the HTTP API. SDK changes rarely need matching API changes.

---

## SCRAPER (`scraper/`)

Current scraper architecture and state are maintained in `CLAUDE.md`, `KNOWN_PORTALS.md`, `RUN_HISTORY.md`, and `scraper/schema.py`. Treat older dump/session notes in this file as historical context only.

The scraper reads `KNOWN_PORTALS.md`, routes each portal through `scraper/providers/`, writes canonical JSON/CSV output, enriches with LM Studio, and loads to Supabase.

### Files

| File | Role |
|---|---|
| `config.py` | Env vars: LM Studio base URL/key/model, Firecrawl URL, output paths |
| `utils.py` | `strip_html`, `is_india`, `job_hash`, `company_slug` |
| `portal_reader.py` | Parses `KNOWN_PORTALS.md` by section → list of portal dicts |
| `schema.py` | `Portal` TypedDict + canonical field list |
| `providers/` | Workday, SmartRecruiters, Greenhouse, Lever, Phenom, SAP, Oracle, custom provider modules |
| `firecrawl_client.py` | Firecrawl singleton helpers; `crawl()` is intentionally not exposed |
| `enricher.py` | Open-weight enrichment: `enrich_job()` fills `job_summary`, `role_domain`, and structured skills |
| `enrichment_state.py` | Forward-only source hash + core enrichment version contract |
| `enrichment_worker.py` | Lazy Supabase queue worker for post-cutover jobs only |
| `job_embedding_state.py` | Stable source-document and query prefix/hash contract for semantic retrieval |
| `job_embedding_worker.py` | Local LM Studio Nomic embedding worker and semantic-search diagnostic |
| `writer.py` | `to_canonical()` → canonical schema; `save_jobs()` → deduplicated JSON + CSV |
| `main.py` | Orchestrator: `--company`, `--ats`, `--dry-run`, `--skip-enrich`, `--resume`, `--enrich-only` |
| `csv_importer.py` | Source-only immediate publish or legacy full upsert; lifecycle + diagnostics |
| `test_llm.py` / `test_pipeline.py` | Test scripts |

### Setup (once)

```bash
cd scraper
cp .env.example .env
# Required: set FIRECRAWL_API_KEY to your paid Firecrawl API key (fc-...)
# If API key is not given, run through Docker — Firecrawl should be configured to run through Docker
# Required: set LM_STUDIO_MODEL to exact model name shown in LM Studio
# LM Studio must be running on localhost:1234 (for --enrich-only phase)
# pip install -r requirements.txt
```

**MCP setup (Codex):**
Edit `~/.Codex/mcp.json` — replace `fc-YOUR_API_KEY_HERE` with your real key.
After editing, restart Codex. The `firecrawl_scrape`, `firecrawl_extract`,
`firecrawl_map`, etc. tools will then be available in your Codex session.

### Run commands

```bash
python main.py --dry-run                 # verify KNOWN_PORTALS.md parsed correctly
python main.py --company "Syngenta"      # test single company
python main.py --ats smartrecruiters     # test one ATS type
python main.py --skip-enrich --scope global --global-cap 2000  # full scrape, no LLM
python main.py --resume --skip-enrich    # resume an interrupted run only
python csv_importer.py --source-only --run-date "$(date +%Y_%m_%d)"  # publish this completed run only
python job_embedding_worker.py --batch-size 32 --max-jobs 1000  # source-first semantic retrieval lane
python enrichment_worker.py --max-messages 100  # lazy Phase 2 when inference is available
python main.py --enrich-only             # legacy local-file enrichment during cutover only
```

### Forward-only publish + lazy enrichment

Source publication and model enrichment are independent. Historical jobs are not backfilled.

**Phase 1 — Scraping** (Docker/Firecrawl on, LM Studio off):
```bash
python main.py --skip-enrich --scope global --global-cap 2000
```
Scrapes all active portals. Workday uses CXS API + JD fetch.
JS-heavy: use direct ATS APIs where possible; otherwise use Firecrawl Docker first and cloud only as a last resort.
`--skip-enrich` suppresses the LM Studio enrichment pass only.

**Phase 3A — Immediate source publication** (queue migration deployed 2026-07-11):
```bash
python csv_importer.py --source-only --run-date "$(date +%Y_%m_%d)"
```
This writes source-owned fields and lifecycle evidence without touching model-owned fields. New post-cutover jobs become visible immediately and are queued.

**Lazy Phase 2/3B — Enrichment** (local LM Studio or approved remote open-weight endpoint available; no Firecrawl needed):
```bash
python enrichment_worker.py --batch-size 10 --max-messages 100
```
The worker reads only durable queue messages created after cutover. It never scans missing historical enrichment. If LM Studio is disconnected, it exits without claiming work.

### Company run health tracking

Official per-company job-count tracking happens **only after final Supabase load** for that company.

- Treat scrape-only counts from `main.py`, local `run_summary_*.json`, and intermediate JSON files as provisional debugging signals only.
- During Phase 1 scrape-only iteration runs, prefer disabling Supabase scrape diagnostics so provisional counts do not become official history:
  `SCRAPE_DIAGNOSTICS_DISABLED=1 python main.py --company "<Company>" --skip-enrich`
- The official health record is written by `csv_importer.py` after the source snapshot is loaded into Supabase; enrichment completion is tracked separately.
- For every loaded company, track/report: `company_name`, `run_id`, `raw_jobs`, `saved_new`, enriched percent, skill drift, unknown location rows, status/reason.
- Do not use scrape-only diagnostics as the source of truth for company hiring volume or scraper health. If a company fails before final load, report it as a pipeline issue, not as an official company count.

### ATS routing

- **Workday** → direct POST API (India UUID + pagination + CXS JD fetch per job)
- **SmartRecruiters** → direct GET `?country=in` (includes full JD in API response)
- **Greenhouse** → direct GET, India filter in Python (includes full JD in API response)
- **Custom/SAP/Oracle** → direct GET, fallback to Firecrawl extract if HTML response
- **JS-heavy** (Eightfold, Avature, custom SPAs) → Firecrawl Docker fallback or a dedicated provider when cracked
- Firecrawl cloud is a last resort for portals that cannot be handled directly or through Docker

### LLM enrichment flow (Dump 4+)

1. Scraper populates `job_description` and source fields.
2. `csv_importer.py --source-only` publishes the job and the database queues new post-cutover rows.
3. `enrichment_worker.py` sends the cleaned JD to the configured open-weight inference endpoint when compute is available.
4. LLM extracts the active enrichment fields only:
   - `job_summary` — factual role summary, capped at 100 words
   - `role_domain` — one controlled functional area
   - `skills` — up to 10 Lightcast L3 skills with `required_level`
   - `main_skills` mirrors skill names for backward compatibility; `side_skills` stays empty/deprecated
5. LLM output is validated by `_validate_enrichment()` before writing — invalid values dropped, not kept.
6. A hash-guarded RPC patches enrichment fields and `job_skills` atomically; stale or inactive work is discarded.

Do not seed or scan historical missing enrichment. Existing rows use NULL enrichment state as the deliberate legacy/untracked sentinel.

**Do NOT add other enrichment fields** — seniority, work_mode, employment_type, degree_required, etc. are all retired from the schema. If needed in future, add as a separate enrichment pass, not in the core flow.

### Known issues

- **Quality-aware per-company cap (shipped 2026-07-26) — affects `daily_cycle`.** `--company-cap` default is now **2500** (was 1000). Companies at/under the cap keep all roles; over it, `scrape_select.select_for_cap()` keeps technical (`career_band=engineering_data`) + JD-bearing roles and drops the arbitrary tail (title stoplist + `CAP_MIN_JD_CHARS=300`). Deterministic, no LLM, forward-only. **Workday contract change (Phase B):** the provider now pages listing **metadata only**, selects, then fetches JDs for **only the selected set** in `WORKDAY_PAGE_SIZE` chunks. Page-flush granularity moved from *per listing page* → *per JD-fetched chunk* — durability semantics (incremental writes, end marker, checkpoint updates) preserved and `test_daily_cycle` is green, but Codex owns `daily_cycle` so verify the durable-queue/checkpoint flow on the next real run. `WORKDAY_MAX_JOBS` raised 500→5000 (listing ceiling; the real prior bottleneck — every tenant was silently cut to 500 listings). Full detail: `docs/DESIGN_quality_aware_company_cap.md`; guards `tests/test_scrape_select.py`, `tests/test_workday_quality_cap.py`.
- Workday India UUID response structure varies per tenant — if 0 jobs returned, run with `--company` and add debug prints
- Eightfold API 404 as of 2026-04-10 — Firecrawl path may or may not extract clean listings
- Goldman Sachs (TAL.NET) requires browser JS — Firecrawl handles it but markdown quality varies
- MSCI: `careers.msci.com` is 404; Workday slug unknown (skipped in parser)
- Capgemini, HCL: Workday slugs unconfirmed (skipped in parser)

### Recommended test order

Start with low-risk targets before JS-heavy ones: **Stripe → ServiceNow → Salesforce**, then Goldman Sachs / Eightfold portals.

---

## ARCHIVED PIPELINE v2 NOTES

This section is preserved for historical context. The current schema is defined in `scraper/schema.py` and summarized in `CLAUDE.md`.

### Canonical schema — 8 fields total

| Field | Source | Notes |
|---|---|---|
| `job_id` | ATS native ID | Deduplicate on this field |
| `job_title` | ATS / page title | Scraped directly, no LLM |
| `job_description` | ATS JD endpoint or Firecrawl scrape | Full text, HTML stripped |
| `company_name` | KNOWN_PORTALS.md | Static per portal entry |
| `Industry_name` | KNOWN_PORTALS.md | Static per portal entry |
| `Location`  | ATS JD endpoint or Firecrawl scrape | Full text, HTML stripped |
| `apply_url` | ATS direct link or career page URL | Candidate-facing application link |
| `main_skills` | LLM enrichment (Phase 2) | Top 5 must-have skills from JD |
| `side_skills` | LLM enrichment (Phase 2) | Nice-to-have skills from JD |
| `batch_date` | Set at import time in writer.py | Integer YYYYMMDD — tracks which run produced this row |

5 fields are scraped raw. 2 are added by LLM enrichment. 1 (`batch_date`) is stamped automatically. No other fields.

Firecrawl API is **never used** — banned - unless extremely important. Only `scrape_extract()` (1 call per JS-heavy portal) is permitted when a direct ATS API is unavailable or docker is not able to work.

### E2E pipeline stages

```
Phase 1 — Scrape
  → ATS direct API (Workday CXS, SmartRecruiters, Greenhouse, Phenom, etc.)
  → Firecrawl scrape() ONLY as fallback for JS-heavy portals (not crawl) and through docker.
  → Output: canonical raw JSON per company

Phase 2 — LLM Enrichment (LM Studio)
  → Input: job_description (raw JD text)
  → Output: main_skills (top 5 must-have), side_skills (nice-to-have)
  → _validate_enrichment() enforces controlled vocabulary before writing

Phase 3 — Supabase Load
  → csv_importer.py / load_to_supabase()
  → Upsert on job_id (deduplication)
  → Quality gate: drop jobs with missing job_id or job_title
```

### Firecrawl credit discipline

**Firecrawl is a paid API — credits are finite.** Rules:

1. **Always use the official `firecrawl-py` SDK** — never raw HTTP requests to the API.
   ```python
   from firecrawl import Firecrawl
   app = Firecrawl(api_key="fc-YOUR_API_KEY")
   result = app.scrape(career_url)
   ```
2. **One singleton instance** — `_app` is created at import in `firecrawl_client.py`. Never instantiate `Firecrawl` elsewhere.
3. **Never use `crawl()`** — it is not exposed in `firecrawl_client.py` and must not be added back. N credits per company = too expensive.
4. **Two permitted calls only:** `fc.scrape(url)` (1 credit, validate URL + fetch JS content) and `fc.extract(urls, schema, prompt)` (js-required portals only).
5. `scrape()` use cases: (a) verify a careers URL is reachable, (b) fetch JS-heavy page when no direct ATS API exists.
6. If a direct ATS JSON API exists → use it. If Firecrawl works through docker, make it work. Firecrawl API is always the last resort.

### Supabase table schema (v2)

```sql
CREATE TABLE jobs (
  job_id          TEXT PRIMARY KEY,
  job_title       TEXT NOT NULL,
  job_description TEXT NOT NULL,
  company_name    TEXT NOT NULL,
  Industry	  TEXT NOT NULL,
  Location	  TEXT NOT NULL,
  apply_url       TEXT,
  main_skills     TEXT[],   -- array of up to 5 must-have skill strings
  side_skills     TEXT[],   -- array of nice-to-have skill strings
  batch_date      INTEGER   -- YYYYMMDD integer — tracks which run produced this row
);
```

---

## ARCHIVED RUN HISTORY

Do not use this section as current state or an active task list. Current state lives in `CLAUDE.md`; chronological updates live in `RUN_HISTORY.md`.

### Session 2026-05-02 — Procter & Gamble cracked via Phenom SSR

**Objective:** Move P&G from ambiguous SSR/manual fallback state to a direct, repeatable route.

**Validation performed:**
- Confirmed `https://www.pgcareers.com/in/en/search-results?m=3&location=MUMBAI%2C%20India` embeds `phApp.ddo.eagerLoadRefineSearch.data.jobs` in HTML.
- Confirmed embedded records include `jobSeqNo`, `jobId/reqId`, `title`, `country/location`, `applyUrl`, `descriptionTeaser`.
- Targeted run passed: `python3 scraper/main.py --company "Procter & Gamble" --skip-enrich --company-cap 200` → `23 raw`, `23 saved`.

**Code + docs updated:**
- `scraper/portal_reader.py` PHENOM override added: `Procter & Gamble -> ats=phenom_ssr`, endpoint `https://www.pgcareers.com/in/en/search-results?qcountry=India`.
- `KNOWN_PORTALS.md` P&G row updated to `✅ CRACKED 2026-05-02`.
- `RUN_HISTORY.md` and `CODEX_HANDOFF.md` updated with this route.

### Session 2026-05-02 — Nykaa cracked via Skima careers SSR HTML

**Objective:** Convert Nykaa from `js-required` to a direct, repeatable scraper route.

**Validation performed:**
- Confirmed `GET https://careers.nykaa.com/` returns server-rendered listings with UUID detail links.
- Confirmed pagination via `?page=N` and `data-last-page` (snapshot: 2 pages).
- Confirmed detail pages `/{job_uuid}` contain full JD in `.job-description-panel`.
- Targeted run passed: `python3 scraper/main.py --company "Nykaa" --skip-enrich --company-cap 200` → `11 raw`, `11 saved`.

**Code + docs updated:**
- Added provider `scraper/providers/skima_careers.py` (listing + pagination + detail parser).
- Registered provider in `scraper/providers/registry.py` as `ats=skima_careers`.
- Routed Nykaa in `scraper/portal_reader.py` (`_ATS_OVERRIDES` + `india_only=True` override).
- Updated `KNOWN_PORTALS.md` Nykaa row to `✅ CRACKED 2026-05-02`.

### Session 2026-05-02 — Tech Mahindra cracked (URL + endpoint fix)

**Objective:** Resolve Tech Mahindra from `url-changed`/broken to a stable scrape route.

**Validation performed:**
- Confirmed `https://www.techmahindra.com/en-in/careers/` returns 404.
- Confirmed `https://www.techmahindra.com/careers/` returns 200 and links `Join Us` to `https://careers.techmahindra.com/`.
- Confirmed `GET https://careers.techmahindra.com/` returns 200 with HTML job cards and direct detail links: `JobDetails.aspx?JobCode=...`.
- Confirmed `GET JobDetails.aspx?...` pages contain full `Job Description`, `Location`, and apply controls.

**Docs updated:**
- `KNOWN_PORTALS.md` Tech Mahindra row updated to `✅ cracked 2026-05-02` with new URL and extraction path.
- `KNOWN_PORTALS.md` `SCRAPE_QUEUE` pending line for Tech Mahindra removed.

### Session 2026-05-02 — Cisco cracked via browser cURL (Phenom SSR)

**Objective:** Resolve Cisco from "needs investigation" to a reproducible direct scrape route.

**Validation performed:**
- Confirmed `https://careers.cisco.com/global/en/search-results?qcountry=India` returns embedded structured payload in page HTML: `phApp.ddo.eagerLoadRefineSearch`.
- Confirmed India filter is active in payload: `ui_selections.country=["India"]`; country aggregation shows `India=226`.
- Confirmed pagination works with `from=10&s=1` (10 jobs/page in embedded payload).
- Confirmed job objects include scraper-ready fields: `jobId/reqId`, `title`, `location`, `descriptionTeaser`, `applyUrl`.

**Docs updated:**
- `KNOWN_PORTALS.md` Cisco row updated to `✅ cracked 2026-05-02` with endpoint + parsing notes.
- `KNOWN_PORTALS.md` `SCRAPE_QUEUE` entry for Cisco removed (no longer pending).
- `CODEX_HANDOFF.md` progress table/addendum updated with Cisco route details.

### Session 2026-05-02 — Atlassian cracked via careers endpoint JSON

**Objective:** Resolve Atlassian from broken Greenhouse token to a reproducible direct API route.

**Validation performed:**
- Confirmed `GET https://www.atlassian.com/company/careers/all-jobs?team=Interns%2CGraduates&location=&search=` is JS-rendered careers shell.
- Confirmed bundled careers code resolves listing endpoint to `GET /endpoint/careers/listings` (production).
- Confirmed `GET https://www.atlassian.com/endpoint/careers/listings` returns JSON array (`82` jobs in snapshot).
- Confirmed records include scrapeable fields: `id`, `title`, `locations[]`, `overview`, `responsibilities`, `qualifications`, `applyUrl`.

**Code + docs updated:**
- `scraper/providers/generic_json.py` updated to parse `locations[]`, sectioned JD fields, and `applyUrl` (needed for Atlassian payload shape).
- `KNOWN_PORTALS.md` Atlassian moved from Greenhouse to `CUSTOM / PROPRIETARY APIs` with `✅ CRACKED 2026-05-02`.
- `KNOWN_PORTALS.md` `SCRAPE_QUEUE` Atlassian pending line removed.
- `RUN_HISTORY.md` and `CODEX_HANDOFF.md` updated with validation notes.

### Session 2026-04-27 — Architecture V3 Phase 0 baseline freeze

**Objective:** Run Phase 0 exactly as defined before Phase 1 modularization work.

**Commands executed:**
- `cd scraper && python main.py --dry-run` ✅
- `cd scraper && python main.py --validate --skip-enrich` ✅
- `cd scraper && python test_pipeline.py` ⚠️ (failed checks captured as baseline caveats)

**Artifacts captured:**
- `logs/run_summary_20260427_211642.json`
- `scraper/MIGRATION_BASELINE.md`
- `scraper/MIGRATION_STATUS.md` (Phase 0 marked complete; Phase 1 set in progress)

**Baseline notes:**
- Validate run finished with 135 processed, 24 skipped, 339 new validate rows.
- `test_pipeline.py` has 5 known failing checks (industry completeness, `strip_html` formatting, schema field count expectation, and LM-dependent enrichment checks while LM unavailable).

### Session 2026-04-27 — Architecture V3 Phase 1 provider registry skeleton

**Objective:** Complete Phase 1 modular contract without changing scrape behavior.

**Code changes:**
- Added provider contract + result model: `scraper/providers/base.py`
- Added ATS wrapper providers:
  - `scraper/providers/workday.py`
  - `scraper/providers/smartrecruiters.py`
  - `scraper/providers/greenhouse.py`
  - `scraper/providers/lever.py`
  - `scraper/providers/phenom.py`
  - `scraper/providers/generic_json.py`
  - `scraper/providers/firecrawl_js.py`
- Added central dispatch + fallback policy: `scraper/providers/registry.py`
- Added package export: `scraper/providers/__init__.py`
- Switched `scraper/main.py` dispatch from ATS `if/elif` chain to `dispatch_scrape(...)`.

**Phase 1 verification executed:**
- `python scraper/main.py --dry-run` ✅
- `python scraper/main.py --validate --skip-enrich` ✅

**Verification artifact:**
- `logs/run_summary_20260427_213806.json`

**Phase 1 outcome:**
- Runtime parity preserved; direct paths and fallback paths continued to behave as baseline.
- Fallback policy is now centralized in registry, not distributed across `main.py`.

### Session 2026-04-19 — Portal expansion + JD fix

**Code changes:**
- `scraper/config.py` — `WORKDAY_JD_FETCH_LIMIT` default raised 200→500. Was silently capping JD fetch for all large Workday companies (Accenture 500 jobs had only 200 JDs, State Street 351→200, DBS 285→200).
- Historical note: these Workday entries later moved from `company_registry.py` into `scraper/workday_registry.json`.
- Historical note: this logic later moved from `scrapers.py` into provider modules under `scraper/providers/`.
- `scraper/probe_cxs.py` — New tool for probing Workday CXS India UUIDs for a list of tenants.

**New companies scraped (2026-04-19):**
| Company | ATS | Jobs | JD% |
|---------|-----|------|-----|
| 3M | Workday (Location_Country) | 81 | 100% |
| NXP Semiconductors | Workday (Location_Country) | 161 | 100% |
| Autodesk | Workday (locationCountry) | 111 | 100% |
| DXC Technology | Workday (locationCountry) | 211 | 100% |
| Barclays | Workday (12 location UUIDs) | 500 | 100% |
| Maersk | Workday (26 location UUIDs) | 97 | 100% |
| Bosch | SmartRecruiters | 100 | 100% |
| Airbnb | Greenhouse | 15 | 100% |
| Razorpay | Greenhouse | 46 | 100% |
| PhonePe | Greenhouse | 43 | 100% |
| Thoughtworks | Greenhouse | 2 | 100% |
| Meesho | Lever | 52 | 100% |
| CRED | Lever | 7 | 100% |
| Paytm | Lever | 203 | 96% |

**Re-scraped to fix JD cap:**
- Accenture: 500 jobs → 100% JD (was 40%)
- State Street: 351 jobs → 100% JD (was 56%)
- DBS Bank: 285 jobs → 100% JD (was 70%)

**Demoted:**
- Publicis Sapient → 🔴 SmartRecruiters returns 0 for all IDs tried; careers site is SPA with unknown ATS
- ING Bank → 🔴 no India locations in ICSGBLCOR portal
- Roche → 🔴 only 1 India job (not worth scraping)

**Unresolved for next session:**
- Societe Generale: SmartRecruiters `SocieteGenerale4` — `country=in` returns 0; try location text filter
- Storable: Greenhouse board confirmed but India jobs TBD
- 74 companies returning 1 Firecrawl blob — need direct API scrapers (see FC-fallback companies list)

### Session 2026-04-17 — Phase 1 full scrape + RAG enrichment pipeline

**Code changes this session:**
- `scraper/rag_skills.py` (NEW) — IDF-weighted keyword inverted index over 35,108 Lightcast L3 skills. `retrieve(text, k=40)` returns the top-k canonical skill names via token overlap scoring (IDF-weighted + length-normalized). No model calls — builds in <0.5s at import. Used in enricher to inject a constrained vocabulary into every LLM prompt.
- `scraper/enricher.py` — RAG-augmented: `enrich_job()` now calls `_retrieve_skills(title + jd[:800], k=40)` and injects the result into `_ENRICH_PROMPT` as "Approved skill vocabulary — choose ONLY from this list". System prompt removed from code (moved to LM Studio GUI for KV-cache reuse across requests). `max_tokens` lowered 300→150. JD truncation 2000→1500 chars.
- `scraper/main.py` — `enrich_only_run()` parallelised with `ThreadPoolExecutor(max_workers=ENRICH_WORKERS)`. Added `from concurrent.futures import ThreadPoolExecutor, as_completed`.
- `scraper/config.py` — added `ENRICH_WORKERS = int(os.getenv("ENRICH_WORKERS", "4"))`.
- `scraper/.env` — added `ENRICH_WORKERS=4`; dual model presets (`MODEL_SPEED=fast` → `google/gemma-3-4b`, `MODEL_SPEED=quality` → `deepseek-r1-0528-qwen3-8b-mlx`).

**LM Studio GUI changes (save as preset `mirror-cv-fast`):**
- System Prompt: "You are a precise job data extractor. Read the job title and description and return a single valid JSON object. No explanation, no markdown, no extra text."
- Limit Response Length: enabled → 150 tokens
- Temperature: 0.0

**Phase 1 run results (2026-04-17):**
- `python main.py --skip-enrich` completed. 94 output files, 2,376 total jobs, 1,730 with `job_description`.
- Output path: `/Users/incognito/firecrawl_Supabase/All_CSV_Outputs_thru_firecrawl/` (set via `OUTPUT_BASE` in .env)

**Historical Phase 2 status (completed later):**
- `python main.py --enrich-only` running as PID 58046, log at `/tmp/enrich_rag.log`
- 1,530 jobs need enrichment (have JD, no main_skills). ~4h ETA at ~10s/job.
- All skills now sourced directly from Lightcast L3 taxonomy via RAG retrieval.

**Historical next step (completed later):**
- Run `python csv_importer.py` (Phase 3 — Supabase upsert)
- Verify row count in Supabase matches enriched job count

### Session 2026-04-16 — Taxonomy + Workflow setup

**Code changes this session:**
- `scraper/lightcast_skills_taxonomy.json` — created; full Lightcast Open Skills L1→L2→L3 hierarchy (31 L1, 442 L2, 35,108 L3 skills)
- `scraper/lightcast_skills_flat.csv` — flat table (l1_category, l2_subcategory, l3_skill_name, l3_skill_id, 35,108 rows)
- `scraper/enricher.py` — updated: LLM skills now validated against Lightcast L3 taxonomy only. Three match strategies: exact, stripped-parenthetical ("Docker" → "Docker (Software)"), fuzzy (cutoff=0.88, min 8 chars)
- `.archon/workflows/scraper-weekly-run.yaml` — created; 7-node DAG workflow: check-docker + check-lm + test-portals (parallel) → scrape → enrich → upload → summarize

**Workflow run notes:**
- Ran `archon workflow run scraper-weekly-run --no-worktree` (Phase 1 only — LM Studio was off)
- `check-lm` failed as expected; `scrape` completed in 18 min but scraped **0 new data** because `--resume` was mistakenly left in the workflow command — all 44 companies already had output from 2026-04-12 and were skipped
- **Fixed**: removed `--resume` from the `scrape` node command. Next weekly run will do a full fresh scrape of all companies.

**Current state of All_CSV_Outputs_thru_firecrawl/ (44 companies, last scraped 2026-04-12):**
Accenture (500), Sanofi (596), Novartis (592), Wells Fargo (224), Salesforce (168), Continental (99), Airbus (144), Stripe (66), Volvo Group (43), Shell (32), ServiceNow (35), Fidelity (29), Amazon (81), Michelin (21), LDC (20), WESCO (20), AstraZeneca (25), Schneider Electric (126), Philips (136), Eli Lilly (10), Dell (18), Stellantis (18)
Low/broken: Engie (2), Baker Hughes (2), Morgan Stanley (2), AmEx (3), Google (3), Infosys (3), TCS (3), Wipro (3), Cognizant (0), Alstom (1), Chanel (1), Apple (2), CNHI (3), CMA CGM (0), TotalEnergies (0), Synopsys (0), Mastercard (0), Microsoft (0), Volkswagen (5/excluded)

### Session 2026-04-10 — First full run (interrupted)
- Ran `python main.py` (full run, all portals).
- Run was force-closed mid-way due to memory pressure from running Docker + LM Studio simultaneously.
- **15 companies fully scraped** before interruption:
  Accenture, Airbus, Amazon, American Express, Chanel, Continental, Fidelity Investments,
  LDC (Louis Dreyfus), Morgan Stanley, STMicroelectronics, Sanofi, ServiceNow, Shell, Stripe, Wells Fargo
- Output location: `All_CSV_Outputs/{Company}/Outputs/YYYY_MM_DD/jobs.json` + `jobs.csv`

### Session 2026-04-11 — Phase 1 + Phase 2 COMPLETE ✅

**Code fixes made this session:**
- Workday headers → browser-like UA + Accept-Language + dynamic Referer
- Workday facet param → `_find_india_id()` now returns `(facet_param, uuid)` tuple (tenant-specific names)
- Workday Cloudflare 303 → automatic Firecrawl fallback using `careers_url` (not API URL)
- `--skip-enrich` now suppresses LLM in Firecrawl path; saves `firecrawl_raw.md` staging file
- `--enrich-only` Phase 1 processes all `firecrawl_raw.md` staging files → extract + enrich
- `portal_reader.py` passes `careers_url` field for Workday portals
- No-India-Jobs companies consolidated into a dedicated excluded block in KNOWN_PORTALS.md

**25 companies with enriched jobs.json as of 2026-04-11:**
Accenture (8240), Amazon (92), Wells Fargo (235), Salesforce (169), Continental (99),
Sanofi (93), Stripe (66), ServiceNow (35), Airbus (40), Fidelity (30), Shell (27),
LDC (20), STMicro (3), Morgan Stanley (3), AmEx (3), Chanel (1),
Eli Lilly (3), Google (3), Infosys (3), L'Oréal (3), TCS (3), Wipro (3),
Cognizant (2), Stellantis (3), AstraZeneca (3)

**Historical broken list (superseded by `KNOWN_PORTALS.md`):**
- Engie, Mastercard, Novartis, Synopsys — Workday fallback URL fix applied; re-run to verify
- Baker Hughes, Philips, TotalEnergies, Volvo Group — need India-filtered URL in KNOWN_PORTALS.md
- Microsoft — Firecrawl crawled Azure error page; needs correct careers URL
- Atlassian (board token changed), Michelin/CNHI/Schneider Electric (404s)
- Alstom, CMA CGM, Air France, SAP — Firecrawl crawl timeout; try `scrape` instead of `crawl`
- Apple, Dell — needs further investigation
- IBM, Goldman Sachs — login-required; users directed to careers page

**Excluded from scraper (confirmed no India jobs) :**
Volkswagen, RTX (Raytheon), Syngenta, Solvay — see `## NO INDIA JOBS` section in KNOWN_PORTALS.md 

---

## DUMP 2 ANALYSIS — Root Cause Diagnosis (2026-04-11)

**Context:** Dump 2 (uploaded 2026-04-11) contained 2,774 jobs from 25 companies but with severe data quality issues. After code inspection, these are confirmed root causes.

### Problem 1 — Workday: zero raw_jd_text (confirmed)
`scrapers.py:76` reads `p.get('jobDescription', '')` from the Workday listing API response. **The listing endpoint `/wday/cxs/{tenant}/{site}/jobs` never returns full JD text** — it returns only metadata (title, location, postedOn, bulletFields). The `jobDescription` key exists but is empty in listing responses. Full JD lives at the individual job detail endpoint: `GET https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs/{externalPath}`. Fix: add a second-pass fetch for each job's `externalPath` to get the actual JD.

### Problem 2 — Accenture: 8,240 jobs scraped, 1,841 unique (6,399 duplicates)
Two sub-issues:
1. **India filter not working**: Accenture's Workday returns ~1,841 unique India jobs (vs expected ~800). The `_find_india_id()` may be matching a broader location facet than just India.
2. **Pagination overlap**: 8,240 records for 1,841 unique items = each job appears ~4.5× on average. Workday offset-based pagination on Accenture's tenant is returning overlapping result sets across pages (known Workday tenant behavior when results change between page requests). Fix: deduplication in `writer.py:save_jobs()` exists but only at save time — need to deduplicate during pagination by tracking seen `jobReqId` values.

### Problem 3 — Firecrawl companies: exactly 3 jobs each
`main.py:109` slices Firecrawl output to `pages[:5]` (first 5 crawled pages), then `enricher.py:extract_jobs_from_markdown()` asks LM Studio to extract listings from that combined markdown. LM Studio on a listing page with typical card layout extracts the first visible 3-5 jobs from the markdown. Not a pagination issue — the LLM just stops after a few. Fix: need either direct API calls for these companies OR increase the crawl depth/page limit and use a more structured extraction prompt.

### Problem 4 — skills_required, seniority_level all empty
These are populated by `enricher.py:enrich_job()` — but enrichment requires `raw_jd_text` to exist first (`_needs_enrichment()` checks `has_jd`). Since `raw_jd_text` is empty for all Workday jobs, enrichment is skipped for all of them. Fix is the same as Problem 1 — once JD text is populated, enrichment will work.

### Recommended Fix Strategy (Option A — hybrid APIs + targeted fixes)

**Priority 1 — Workday JD fetch (fixes ~90% of data):**
Add individual job detail fetching to `scrape_workday()`. After collecting all job listings, fetch each job's full JD via:
```
GET https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{career_site}/jobs/{externalPath}
```
Response has `jobPostingInfo.jobDescription` with full HTML JD. This one change fixes Workday companies: Accenture, Airbus, Chanel, Eli Lilly, Fidelity, Sanofi, Salesforce, Shell, Wells Fargo.

**Priority 2 — Workday deduplication during pagination:**
Track seen `jobReqId` in a set during the `while True` pagination loop. Break early if new page returns >50% already-seen IDs (signals overlapping pagination).

**Priority 3 — Firecrawl extraction improvement:**
For JS-heavy companies (Google, TCS, Wipro, Infosys, etc.) that go through `_scrape_firecrawl()`, increase `fc.crawl(url, limit=40)` and don't slice `pages[:5]` — use all pages. Or better: identify the actual JSON API behind each (Google has `careers/applications/jobs/results` JSON endpoint, Infosys has an XHR endpoint, etc.) and add direct API scrapers.

**Priority 4 — Paid Firecrawl tier:**
User is upgrading to paid Firecrawl. With paid tier, rate limiting is removed. Retry the Firecrawl-dependent companies (SAP timeout companies, Dell, etc.) before rebuilding them with Playwright. Use this only as last resort - before that try to work whether docker is working or not.

### What NOT to do
- Do not switch to Playwright wholesale — Workday, Greenhouse, SmartRecruiters are already solved with direct APIs
- Do not add fields beyond the 5-field raw schema in scrapers — enrich only main_skills and side_skills

---

## MISSION STATEMENT

**Goal:** Keep Firecrawl running to capture all job openings + full JDs from 100+ company portals every week. The JD corpus is used to extract skills required in the age of AI (via LM Studio enrichment → Supabase). Every scraper build decision must serve this mission — if a direct API exists, use it; Firecrawl is the fallback, not the default.

---

## BUILD PLAN — CHUNKS (session-by-session)

### Chunk 1 — Audit existing coverage ✅ COMPLETED 2026-04-16
- Ran `--dry-run`: **106 portals parsed** (43 direct API ⚡, 63 Firecrawl/js-required 🌐)
- Direct API breakdown: Workday (18), SmartRecruiters (4), Greenhouse (2), Custom (5), SAP (6), Oracle (1), Phenom (4), Other-direct (3)
- Firecrawl path: 63 companies (all [other] + eightfold + avature + some custom)
- Missing from parse (historical): Atlassian (broken Greenhouse token; now resolved via custom endpoint on 2026-05-02), Capgemini/HCL/MSCI (unconfirmed Workday slugs), Technip Energies (Oracle — dropped)

**Spot-check results (5-job test per ATS type):**

| ATS | Company | Jobs | JD populated | Location | Verdict |
|-----|---------|------|-------------|----------|---------|
| Greenhouse | Stripe | 69 | ✅ 3-5k chars | ❌ Empty | Fix location mapping |
| SmartRecruiters | ServiceNow | 29 | ✅ 2-3k chars | ✅ | Working |
| Custom JSON | Amazon | 93 | ✅ 1-3k chars | ❌ None | Fix location mapping |
| Workday | Salesforce | 169 | ❌ 0 chars (0/169 JDs fetched) | ❌ None | JD fetch broken — critical |
| Phenom REST | Schneider Electric | 10 | ✅ 6-12k chars | ❌ None | Fix location mapping |

**Two systemic bugs confirmed and FIXED in Chunk 2:**
1. **Workday JD fetch: 0/N always failing** — Root cause: `cxs_base` was missing `career_site` segment. Was `/wday/cxs/{tenant}{ext}`, should be `/wday/cxs/{tenant}/{career_site}{ext}`. Fixed in `scrapers.py:_fetch_workday_jds()`. Now 169/169 JDs fetched via direct CXS API.
2. **Location = None/empty** — Fixed in `writer.py:to_canonical()`: `raw.get('location_city') or 'India'` — defaults to 'India' when scraper returns empty (all jobs passing the India filter ARE India jobs).
3. **Firecrawl Workday fallback also added** — if CXS API fails (some tenants block it), `_fetch_workday_jds()` falls back to `fc.batch_scrape()` on the human-facing job URL. Threshold set to 500 chars to reject error pages.

**Verified clean after fixes:**
| ATS | Company | Jobs | JD | Location |
|-----|---------|------|-----|----------|
| Workday | Salesforce | 169 | ✅ 8-11k chars | ✅ Real city |
| Greenhouse | Stripe | 69 | ✅ 4-5k chars | ✅ Bengaluru |
| Custom JSON | Amazon | 93 | ✅ 1-3k chars | ✅ City+State+IND |
| Phenom REST | Schneider Electric | 10 | ✅ 6-12k chars | ✅ |

### Chunk 2 — Fix broken direct scrapers (NEXT — run after full scrape reveals which companies fail)
- Verify Phenom REST endpoints: BCG, PMI, Oliver Wyman (🟡 unverified API paths)
- Fix broken Workday slugs: Capgemini, HCL Technologies, MSCI
- Fix SmartRecruiters entries: Zomato, S&P Global, CRISIL (unconfirmed IDs)
- Atlassian resolved via `GET https://www.atlassian.com/endpoint/careers/listings` (custom route, not Greenhouse)
- Fix Oracle HCM: Technip Energies (dropped from parse), EXL Digital (verify India filter)
- Target: every ⚡ direct-API company returns ≥5 jobs with populated job_description

### Chunk 3 — New ATS scrapers (where Firecrawl alone is unreliable)
- **Workable scraper**: Elevation Capital (`apply.workable.com/elevation-capital-3/`)
  - API: `GET https://apply.workable.com/api/v3/accounts/{slug}/jobs` with `state=published`
- **Darwinbox scraper**: IIFL Finance (`iifl.darwinbox.in/ms/candidate/careers`)
  - API: POST to Darwinbox candidate search endpoint (inspect XHR)
- **SAP SuccessFactors direct REST**: Monitor Deloitte, GMR Group, CMA CGM, CNHI, Deutsche Bank
  - API: `GET https://{tenant}/odata/v2/JobRequisitionLocale?$filter=...&$format=json`
- Wire all new providers into `to_canonical()` → `save_jobs()` using `scraper/schema.py` as the field source of truth.

### Chunk 4 — Retired cadence note
The old 3-day cadence proposal is retired. The active operating model is a weekly full run, with `RUN_HISTORY.md` and changed `KNOWN_PORTALS.md` rows updated after each run.

---

## DAILY SCRAPER RUN

**Current deployment state:** The database queue migration and live queue drain
are complete. One daily cycle publishes source data first, then starts/loads the
selected local open-weight model and drains enrichment. Publication never waits
for inference, and historical rows are never backfilled.

**Daily command:**

```bash
cd scraper
python daily_cycle.py --scope india --company-cap 2000 --max-messages 100000
```

**How to run through Archon:**
```bash
archon workflow run scraper-weekly-run --no-worktree "Weekly dump $(date +%Y-%m-%d)"
```
- Layer 0: validate portals.
- Layer 1: scrape and publish source fields to Supabase.
- Layer 2: start/load LM Studio only after publication, then drain the durable queue.
- Final layer: write `logs/daily_cycle_*.json` and re-anchor the next automation run.

**If inference cannot start:** source publication remains committed and queue
messages remain durable. The cycle report identifies the inference failure.

**Legacy workflow before cutover:**
```bash
archon workflow run scraper-weekly-run --no-worktree "Weekly dump $(date +%Y-%m-%d)"
```

**IMPORTANT — do NOT add --resume for a fresh weekly run.** `--resume` is only for recovering from a mid-run crash within the same session. Using it on a new week skips all companies that already have output folders (18 min run that does nothing).

**Current architecture:**
```
KNOWN_PORTALS.md  ←  portal config (URL, ATS type, company name)
      ↓
providers/  ←  ATS direct API → canonical raw JSON per company
  (Firecrawl scrape/extract only as JS-heavy fallback; Docker first, cloud last)
      ↓
csv_importer.py --source-only  → immediate source-field publication
      ↓
Supabase forward-only pgmq queue
      ↓
enrichment_worker.py  ← open-weight inference endpoint
      ↓
hash-guarded enrichment patch + job_skills
```

**What to do for Market Data_V1_of_Scrapers/ folder:**
1. Treat it as historical reference only.
2. Build new reusable scrapers in `scraper/providers/`.
3. Keep `KNOWN_PORTALS.md` as the URL/provider config source and update rows after every verified route change.

**Note on LM Studio:** User runs LM Studio locally. Multiple processes can share `localhost:1234` safely — it is stateless per request. If model outputs look wrong, verify `LM_STUDIO_MODEL` in `.env` matches the loaded model.

---

## DEVELOPMENT WORKFLOW

1. Write E2E tests ("snips") in `apps/api/src/__tests__/snips/` before writing code.
   - Minimum: 1 happy path + 1 failure path.
   - E2E is always preferred over unit tests.
   - Unit tests are conducted end-to-end to retrieve 3 jobs from each company in known_portal.md to ensure that all company career pages are able to be scraper through Firecrawl Docker.
   - Always use `scrapeTimeout` from `./lib` for any scrape timeout.
   - Gate tests on capabilities:
     - Requires fire-engine: `!process.env.TEST_SUITE_SELF_HOSTED`
     - Requires AI: `!process.env.TEST_SUITE_SELF_HOSTED || process.env.OPENAI_API_KEY || process.env.OLLAMA_BASE_URL`
2. Run `pnpm harness jest <your-test-file>` — never `pnpm start` manually.
3. Push branch, open PR, let CI verify.
