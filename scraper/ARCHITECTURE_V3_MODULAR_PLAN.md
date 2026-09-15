# Scraper Architecture v3 (Modular, Global-Scale)

## Objective

Build a modular scraper platform that:

1. Tracks every real job posting per company (including genuine low-count companies).
2. Avoids synthetic placeholder rows.
3. Makes scraper failures observable and fixable via diagnostics.
4. Lets us add new ATS/providers with minimal code churn.
5. Supports configurable geographic scope per run (`india` or `global`).
6. Ingests global by default for full dumps, with downstream India filtering.

---

## What Is Already Fixed

1. Importer supports mixed schemas (legacy + canonical) and no longer drops latest dumps.
2. Placeholder Firecrawl rows are filtered at import.
3. Firecrawl placeholder generation is removed at scrape source:
   - No fake "scraped via Firecrawl" job rows.
4. Import default now keeps all valid non-placeholder rows (`--min-score 0` default).
5. Run summaries now emit low-count company diagnostics and per-company stats.
6. Runtime scope selector exists (`--scope india|global`, default `india`).
7. Best-effort Supabase diagnostics table write is supported (`scrape_diagnostics` by default).
8. Weekly workflow now runs in global scope by default.

---

## v3 Target Design

### 1) Provider Adapter Layer

Each provider implements a stable interface:

- `discover_jobs(portal) -> list[JobRef]`
- `fetch_job_detail(job_ref) -> RawJob`
- `normalize(raw_job) -> CanonicalJob`
- `diagnostics() -> ProviderDiagnostics`

Providers:
- Workday
- SmartRecruiters
- Greenhouse
- Lever
- Phenom
- SAP/Oracle/custom JSON
- Firecrawl link-extract fallback

### 2) Pipeline Stages

1. Discovery
2. Detail fetch
3. Normalize (single canonical schema)
4. Validate (hard gates)
5. Enrich (LM Studio)
6. Persist (JSON/CSV + Supabase)
7. Audit report

### 3) Validation Rules

Hard reject:
- Missing `job_id`
- Missing `job_title`
- Placeholder/synthetic title patterns

Soft warnings (do not drop):
- Missing JD
- Missing location
- Missing apply URL
- Low-count company (<5 jobs)

Lifecycle policy:
- `is_active = false` after one miss in a successful company run.
- Version rows are written only for meaningful changes.

Meaningful-change fields:
- `job_title`
- `job_description`
- `location`
- `apply_url`

### 4) Diagnostics & Observability

Per company report:
- `raw_scraped`
- `valid_rows`
- `dropped_rows` by reason
- `saved_new`
- `low_count_flag`
- `provider`
- `run_date`
- `scope`

Artifacts:
- `logs/run_summary_YYYYMMDD_HHMMSS.json`
- Optional Supabase table: `scrape_diagnostics`

---

## Implementation Phases

### Phase A (done)

- Remove placeholder row generation.
- Keep all valid non-placeholder jobs by default in importer.
- Write low-count diagnostics in run summaries.

### Phase B (next)

1. Extract provider interfaces into `scraper/providers/`.
2. Move ATS-specific logic from `scrapers.py` into provider modules.
3. Add provider registry + dispatch map.

### Phase C

1. Add deterministic validation module (`scraper/validation.py`).
2. Add explicit rejection-reason taxonomy.
3. Add lifecycle + versioning write path:
   - `first_seen`, `last_seen`, `is_active`
   - `job_versions` append-only history
4. Add regression tests for:
   - placeholder rejection
   - mixed schema normalization
   - low-count diagnostics emission
   - meaningful-change versioning only
   - inactive-after-one-miss behavior

### Phase D

1. Build remediation worker:
   - auto-rank low-count companies by impact
   - attach probable root cause (token changed, parser drift, JS-only page, auth block, etc.)
2. Add run-to-run delta comparisons.

---

## Definition of Done

1. No synthetic placeholder rows reach Supabase.
2. Every low-count company is either:
   - truly low volume, or
   - flagged with actionable root cause and queued remediation.
3. Adding a new provider requires:
   - one new provider module
   - one registry entry
   - no edits to existing provider logic.
