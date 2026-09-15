# CLAUDE.md — v3.2

Guidance for Claude Code in this repository.
Run history → `RUN_HISTORY.md`. Portal config → `KNOWN_PORTALS.md`.

> **DURABLE REFERENCE — DO NOT PRUNE.**
> This file is the permanent architecture, design, and mission record for this project.
> Only two sections change across sessions: `CURRENT STATE` (update each run) and `PENDING WORK` (update as tasks move).
> All other sections — MISSION, PIPELINE, SCHEMA, ATS ROUTING, FIRECRAWL DISCIPLINE, LLM ENRICHMENT, CRACK-ONCE, KNOWN ISSUES, COMMUNITY FRESHNESS — are permanent and must never be deleted or truncated, even when tasks complete.

---

## SCOPE

All work must stay within the `myro-job-scraper/` directory. Do not read, write, or modify files outside this folder.

---

## CHANGE DISCIPLINE

Prefer running and reusing the existing pipeline code, configuration, CLI flags, scripts, and diagnostics before changing implementation.

- Do not write or modify code by default during scraper runs or pipeline iteration.
- First try existing commands, env flags, providers, importer dry-runs, logs, and Supabase diagnostics.
- Only propose a code change after a concrete failure is observed and the existing code/config cannot handle it safely.
- Before writing code, discuss the failure, root cause, options, and tradeoffs with the user, then wait for explicit approval.
- User-requested documentation updates are allowed, but implementation files should stay untouched unless approved.

---

## MISSION

Weekly global scrape of 100+ company portals → full JDs → LM Studio skill extraction → Supabase.
**Rule:** if a direct ATS API exists, use it. Firecrawl is the fallback, not the default.

---

## CURRENT STATE (as of 2026-09-07)

- **Session 2026-09-07 — source snapshot writer landed; Stripe canary found two publication bugs, now fixed.** `source_snapshot.py` owns homogeneous PostgREST upserts (omit-to-preserve cannot NULL sibling `job_summary` cells) and feed close (presence + 30-day age delist on full scope only). Physical unload is True_Yodha after a one-hour quarantine — this writer does not delete rows. Stripe `--company` upserted 40 rows then crashed on `p_limit=10000`; mixed fill/preserve also wiped 11 LLM summaries. Repair those 11 with extractive fill, re-run the Stripe canary, then a full-scope publish is safe to close `last_seen` older than 30 days. Clock stays on this laptop; uncommitted on `main` after `223578206`.
- **Job-feed contract (2026-09-07):** `--company-cap` default is **0 (unlimited)** on `main.py`, `daily_poll.py`, and `daily_cycle.py`. Provider listing loops no longer substitute a silent 2000. Workday lists up to `WORKDAY_MAX_JOBS` (runaway 100000) and fetches JDs for the full selected set when uncapped. Quality `select_for_cap` still runs only when a positive cap is passed. Every imported row gets an **extractive `job_summary`** at scrape/import if the DB cell is empty; the LLM summary remains an upgrade and is never overwritten by a re-scrape. After a full-scope publish, jobs with `last_seen` older than **30 days** are closed (`AGE_STALE_DAYS`); `--company` canaries skip that backstop. NULL `last_seen` (extension saves) is left alone. Clock stays on this laptop this version; cloud move is next. Opaque HTML boards try [Scrapling](https://github.com/D4Vinci/Scrapling) HTTP fetch before Firecrawl (`scrapling_client.py`). Direct ATS APIs stay the default.
- **Data:** 53,046 jobs in Supabase (`jobs`, project `gipvxuugajkugntwkeiz`), 46,206 currently active, and 413,836 `job_skills` rows (read-only snapshot 2026-07-12; active count moves as the delisting loop runs).
- **Portals:** `KNOWN_PORTALS.md` is the source of truth — current parser count **316 active rows**. The 2026-07-12 `career-ops` audit added five Greenhouse boards and first-class Ashby parsing for Deepgram/Zapier; ElevenLabs remains parked for location-semantic review. Per-crack history lives there + in git, not here.
- **Scale-out discovery pipeline (`scraper/discovery/`, built 2026-06-13):** path to grow company coverage toward 10k. **(a) College-seed path** — `phase0_discover.py` spends Firecrawl **cloud** credits (`cloud_extract`) to pull recruiter names off Tier-1/2 college placement pages (`college_sources.json`, 41 sources → 1,146 companies in `seed_companies.{json,csv}`); then FREE `resolve_ats.py` probes Greenhouse/Lever/Ashby/SmartRecruiters with slug candidates + collision guards → `promote_candidates.py` token+name-dedups. Yield ~18 net-new per ~1,150 seed (diminishing — top recruiters are Workday/Darwinbox, not token boards). **(b) Board-directory harvest (the real 10k lever, FREE)** — `harvest_boards.py` + shared `ats_probes.py`: feed candidate tokens (`board_tokens.txt`, collected free via `site:boards.greenhouse.io`/`jobs.lever.co`/etc. searches → real slugs, no 404 waste), probe, India-filter, dedup vs live portals, emit promote stubs. First run: 29 tokens → 23 net-new India boards (~80% conversion). **Quality caveat: SmartRecruiters + some Lever surface staffing/aggregator/microtask boards (Squircle, CapitalAim, TMI, Welocalize, Weekday) — exclude these from promotion; they pollute the candidate-facing DB. Promote product-company boards only.** Ashby routing is hardcoded in `portal_reader.py` (`ats_overrides`/`endpoint_overrides` dicts) — add new Ashby companies there, not just KNOWN_PORTALS. **Always regenerate `diagnose.py` on a fresh run before `--probe-crack`; a stale NEEDS_CRACK list wastes credits re-discovering already-cracked companies (happened 2026-06-13: all 10 stubs were already live).**
- **Saved-job discovery signal (`scraper/discovery/saved_job_portal_signals.py`):** read-only bridge from durable extension saves to scraper coverage. It reads `job_applications(status=saved)` plus extension-created `jobs`, reconciles company/host/ATS tokens against active `KNOWN_PORTALS.md`, validates missing Greenhouse/Lever/Ashby/SmartRecruiters boards with the existing free probes, and reports native-ID duplicates that may need a guarded application relink. Reports go to git-ignored `logs/`; the command never mutates Supabase or the registry. Run `cd scraper && python discovery/saved_job_portal_signals.py`; use `--no-probe` for an offline reconciliation-only pass.
- **Operating mode:** Firecrawl cloud = discovery microscope (`map → selective scrape`), then promote the durable direct route; never leave Firecrawl as the final architecture unless genuinely anti-bot/JS-opaque. Free plan throttles at **6 req/min** → `diagnose.py --probe-crack` needs `--crack-delay 11`; run cloud via `FIRECRAWL_URL= FIRECRAWL_API_KEY=<cloud key> python …`.
- **Self-healing diagnostic (Phase 4) is live** — see its section below.
- **Pagination:** shared `providers/_paginate.py` seam owns the stop decision; zwayam/hm_wp/eightfold migrated, the rest adopt on-touch.
- **Quality-aware per-company cap (optional probe, not the daily default):** when a positive `--company-cap` is passed, companies at/under that cap keep every role; over it, `scrape_select.select_for_cap()` keeps technical (`career_band=engineering_data`) + JD-bearing roles over an arbitrary tail (title stoplist drops guard/facilities/clerical; `CAP_MIN_JD_CHARS=300`). Daily poll default is uncapped. Design + guard tests: `docs/DESIGN_quality_aware_company_cap.md`, `tests/test_scrape_select.py`, `tests/test_workday_quality_cap.py`.
- **Layout:** tests in `scraper/tests/` (+ conftest); narrative docs + handoffs in `docs/`; root keeps CLAUDE/AGENTS/README/KNOWN_PORTALS/RUN_HISTORY/HANDOVER.
- **Health tracking:** official per-company counts only after a real `csv_importer.py` load; scrape-only counts are provisional and stay local.
- **Forward-only async enrichment is deployed, automated, and live-data verified:** `csv_importer.py --source-only` publishes source fields without erasing enrichment; `enrichment_worker.py` drains a durable queue after publication. Historical rows remain untracked and are never backfilled. Personalized search can request priority enrichment. One local Codex automation owns the poll-and-publish schedule and never duplicates active consumers; local enrichment continues independently across poll boundaries. Polls pin one immutable run date, so a scrape that crosses midnight still resolves and publishes one complete folder. The next poll is re-anchored 24 hours after publication finishes. Railway remains an optional always-on upgrade. See `scraper/ASYNC_ENRICHMENT.md`.
- **Source seniority normalization is forward-only:** `writer.to_canonical()` calls `job_seniority.py` before a future source publication. It combines provider metadata, explicit title signals, and source-JD experience requirements into Myro's canonical ladder (`intern`, `entry`, `mid`, `senior`, `lead`, `executive`); it is deterministic, uses no model or enrichment queue, and never rewrites historical Supabase rows.
- **Source Career Band normalization is forward-only:** `writer.to_canonical()` calls `job_career_band.py` before a future source publication. It maps explicit title signals and the controlled role domain into one of Myro's four role families; it is deterministic, uses no model or enrichment queue, and never rewrites historical Supabase rows.
- **Source-first semantic job retrieval is deployed:** active jobs with a parseable source posting date in the latest 14 calendar dates were enrolled once; unknown-date and older history is deliberately excluded. New jobs and material source changes are enrolled automatically. `job_embedding_worker.py` uses local LM Studio Nomic 768-dimensional embeddings, stores vectors in service-role-only `private.job_embeddings`, and exposes a trust-filtered nearest-neighbor RPC with no similarity/skill sieve. See `scraper/JOB_EMBEDDINGS.md`.
- **Upskilling question-bank pilot is implemented:** isolated `scraper/question_bank/` pipeline for Machine Learning, Product Strategy, Management Consulting, and Financial Accounting. Live schema/taxonomy preflight passes; `skill_questions` remains empty until source JSONL is supplied, local LM Studio is loaded, and an explicit `--publish` run succeeds. Unlike job enrichment, question-bank config still intentionally refuses non-loopback LLM URLs.

### Output folder location
> **In-repo.** CSV/JSON outputs live inside the repo (git-ignored, not committed).
> Path: `<repo>/All_CSV_Outputs` — the `config.py` default, so no `OUTPUT_BASE` env var is needed.
> Structure: 136 company folders, each containing `Outputs/<YYYY_MM_DD>/jobs.json` + `jobs.csv`
> This folder is the source of truth for Phase 3 (`csv_importer.py`) — it reads from here to upsert to Supabase.
> (Retired paths: `/Users/incognito/Mirror CV/...`, then `firecrawl_Supabase/All_CSV_Outputs_thru_firecrawl`.
> Renamed 2026-09-15 when the project split out of the Firecrawl fork into its own repo.)

---

## SCRAPER COMMANDS

```bash
cd scraper

# Phase 1 — scrape (Docker on, LM Studio off)
python main.py --dry-run                                        # verify portals parsed
python main.py --company "Stripe"                               # single company test
python main.py --skip-enrich --scope global --global-cap 2000  # full scrape, no LLM

# Inventory — safe by default (no Docker/Firecrawl)
python portal_inventory.py --no-probe                           # route/status inventory only
python portal_inventory.py --probe --sample-size 3              # direct providers only: current hiring sample
python portal_inventory.py --probe --sample-size 3 --limit 25   # batched direct-provider probe
python portal_inventory.py --merge ../logs/portal_inventory_*.json # merge batch reports
python portal_inventory.py --probe --include-js --sample-size 3 # includes JS routes; requires Docker/Firecrawl
python portal_inventory.py --probe --include-js --from-inventory ../logs/portal_inventory_<merged>.json --probe-states skipped_needs_docker,fallback_needs_docker --needs-docker-only --limit 10 --offset 0
                                                               # re-probe only prior Docker-needed rows

# Phase 2S — resolve source matching facts (career band + provenance). REQUIRED
# before any source publication; the importer rejects rows without provenance.
python source_matching_facts.py --run-date "$(date +%Y_%m_%d)"                    # fails if any job is unbanded
python source_matching_facts.py --run-date "$(date +%Y_%m_%d)" --allow-unresolved # daily lane: withhold instead

# Phase 3A — publish source fields immediately
python csv_importer.py --source-only --publish-unclassified --run-date "$(date +%Y_%m_%d)" --dry-run
python csv_importer.py --source-only --publish-unclassified --run-date "$(date +%Y_%m_%d)"

# Lazy Phase 2/3B — enrich queued forward-only jobs when inference is available
ENRICH_FORCE_LLM=1 python enrichment_worker.py --batch-size 10 --max-messages 100

# Semantic retrieval lane — local LM Studio Nomic embeddings
python job_embedding_worker.py --preflight-only
python job_embedding_worker.py --batch-size 32 --max-jobs 1000

# Legacy linear path (kept until async cutover verification)
python main.py --enrich-only
python csv_importer.py --dry-run    # verify counts, no writes
python csv_importer.py              # full upsert
python csv_importer.py --company "Stripe"  # single company smoke test
```

**During the legacy cutover path**, if using local LM Studio on a low-RAM machine, keep Docker off during enrichment. After the async migration is deployed, source publication no longer waits for inference; the worker can run later or against an approved remote open-weight endpoint.
**Never use `--resume` for a fresh weekly run** — it skips companies with existing output folders.
**Docker is only needed for** full scrape fallback paths or `portal_inventory.py --probe --include-js`.

---

## SCRAPER PIPELINE

```
KNOWN_PORTALS.md → main.py/providers → raw JSON
                                      ↓
                 source_matching_facts.py --run-date   ← MANDATORY
                 (stamps career_band + provenance in jobs.json)
                                      ↓
              csv_importer.py --source-only --publish-unclassified
                                      ↓
                     Supabase job visible immediately
                         ↙                         ↘
        private embedding queue/trigger       enrichment queue
                     ↓                              ↓
       job_embedding_worker.py (local)       enrichment_worker.py
                     ↓                              ↓
         semantic retrieval RPC        enrichment patch (job_summary + role_domain)
```

**The resolver step is not optional.** `csv_importer` refuses to publish a row
whose `career_band` has no current `career_band_source` + `career_band_source_hash`,
and `writer.to_canonical` never writes those keys — they are not in
`CANONICAL_FIELDS`. Scrape → publish with no resolver in between rejects the
entire run. `daily_poll.py` wires all three steps in order (2026-08-07).

**The model pass is off in the daily lane** (`--skip-model`, decided 2026-08-08).
Measured on a 33,246-job run: deterministic rules banded 86.5% in **13 seconds**,
while the model pass ran at **~2.7 calls/min and accepted ~7%** of candidates —
hours added to a 9-hour cycle for a few hundred jobs. The acceptance gate is
working, not broken: the unresolved tail is mostly titles with no groundable role
phrase (`IN-Expert`, `Fixed Term Appointment`, bare ladder grades), so there is
nothing for a grounded classifier to accept. Run `source_matching_facts.py`
without the flag by hand to chase the tail.

**One local-inference worker at a time (enforced 2026-08-12).** LM Studio holds
few models resident, so the embedding and enrichment workers running together
make it evict one to load the other — and the evicted side then fails as
`nodename nor servname provided` / `Server disconnected`, naming nothing about
the real cause. Three guards now hold this:
- `lm_worker_lock.local_inference_lock` — both workers take one exclusive flock;
  the second exits **3** (distinct from argparse's 2 and a drain failure) rather
  than queueing, since a waiting worker holds a model slot hostage.
- `daily_cycle.unload_embedding_model` — the cycle hands the slot over
  explicitly between the embedding and enrichment stages instead of stacking
  both models. Best-effort: a failed unload never abandons a finished scrape.
- `enrichment_worker.local_inference_ready` — `/v1/models` lists **downloaded**
  models, not **loaded** ones, so it also fires a 1-token probe. LM Studio
  JIT-loads to answer it, so the probe both forces the load and waits for it;
  paying that once is what stops every message paying it as a retry. Give the
  model a TTL longer than the drain (`lms load … --ttl 86400`).

**Midnight-spanning runs — fixed 2026-08-13.** `daily_poll` passes its start date
through `main.py` to every page flush and final `save_jobs`; the writer stamps
that same folder and `batch_date` even after wall-clock midnight. Resolve and
publish use the same date, and targeted importer discovery selects that exact
folder even if a newer folder exists. Markerless partial folders remain
quarantined. Regression coverage simulates partial + final saves across the
boundary and guards the scrape → resolve → publish command contract.

**Two `.env` files, one per consumer (declared 2026-09-01).** `<repo>/.env`
belongs to Docker Compose and configures the Firecrawl stack. `scraper/.env` is
the only file any Python entry point reads, through the single seam in
`environment.py` — nothing else may call `load_dotenv` or guess a key name.
Run `python environment.py` to see which capabilities the current environment
can run; it reports presence, never values. Publication asserts `supabase`, and
for a real run `stage_a` plus backend reachability, **before its first write**:
missing config used to surface only at the Stage A hand-off, after every source
row was already committed. The preflight now refuses in under a second.

**Unclassified rows.** Career band is matching metadata, not a publication
license. `--publish-unclassified` publishes every otherwise valid source row;
when no band can be proven it writes `career_band=NULL`, so the role remains
browseable without entering band-dependent matching. Only malformed identity,
seniority, or stale-provenance rows are withheld. `--resolved-only` remains a
deprecated CLI alias for operational compatibility. Extend deterministic rules
only where source evidence is unambiguous; never invent a band just to improve a
coverage percentage. Diagnostics and the baseline ledger record the **scraped**
count, while importer logs separate published-unclassified from truly withheld.

**Complete-source trust is part of publish.** `csv_importer.py` always invokes
`trusted_job_lifecycle.sync_import_run` after the source upsert. Complete rows are
promoted to `listing_confidence='active'`; a successful upsert alone is not a
user-visible outcome. Source-only imports deliberately skip company-skill facts
until Phase 2 evidence exists, but never skip the listing lifecycle.

**Partial provider results are evidence, not inventory.** Providers can return a
typed `partial` result when later pagination fails. Dispatch preserves the type;
`main.py` marks the checkpoint failed, writes no completion marker, and publishes
nothing from that prefix. PCSX bootstraps its public career page to acquire the
visitor session required by CloudFront, refreshes once on 401/403, and otherwise
fails closed.

## COMPANY RUN HEALTH TRACKING

Official company hiring-volume and scraper-health metrics are recorded **only after the final Supabase load for that company**.

- Scrape-only outputs (`main.py` logs, `run_summary_*.json`, and local `jobs.json`) are provisional debugging evidence, not official history.
- During batch iteration, set `SCRAPE_DIAGNOSTICS_DISABLED=1` for Phase 1 scrape-only runs when Supabase env vars are present, so provisional scrape counts do not write to `scrape_diagnostics`.
- After a successful real source load, use importer diagnostics as the source of truth; enrichment completion is tracked independently.
- For each loaded company, report: `company_name`, `run_id`, `raw_jobs`, `saved_new`, enriched percent, skill drift, unknown location rows, status/reason.
- If a company fails before final load, record it as a pipeline issue to investigate, not as an official company count.

**Key files:**

| File | Role |
|---|---|
| `environment.py` | **The declared environment surface.** Every env key, the capability it unlocks, and whether that capability can run without it. Owns the single `load_dotenv` seam and the `require()` preflight. `python environment.py` prints presence-only status; never a value |
| `config.py` | Resolved config values: inference/embedding endpoints, Firecrawl URL, output paths, tuning knobs |
| `portal_reader.py` | Parses `KNOWN_PORTALS.md` → list of portal dicts |
| `schema.py` | `Portal` TypedDict + `CANONICAL_FIELDS` — single source of truth |
| `providers/` | One module per ATS type — all scraping logic lives here |
| `providers/_paginate.py` | Shared `paginate()` seam — one tested home for the pagination stop decision (empty / `>= total` / `has_more` / no-new-id / max_pages). Adopted by zwayam and eightfold; other providers migrate on-touch |
| `workday_registry.json` | Per-tenant: India UUID, facet params, `blocked=true` flag — auto-written |
| `generic_registry.json` | Per-company: which JSON keys worked — auto-written on first success |
| `company_industries.json` | Company → Industry mapping — manual |
| `rag_skills.py` | IDF index over 35,108 Lightcast L3 skills — vocab for LLM |
| `enricher.py` | `enrich_job()` → RAG vocab → LM Studio → structured `skills` + back-compat arrays |
| `writer.py` | `to_canonical()` → deduped JSON+CSV saved to output folder |
| `job_career_band.py` | Deterministic source-level normalizer for Myro's four role families; no historical rewrite |
| `source_matching_facts.py` | Mandatory pre-publish pass: stamps `career_band` + provenance on a run's `jobs.json`. Deterministic rules first; only the remainder go to the local model, and a classification is accepted only on a grounded, high-confidence source phrase |
| `lm_worker_lock.py` | Exclusive flock so only ONE local-inference worker runs at a time. Second worker exits **3** instead of evicting the first one's model |
| `job_seniority.py` | Deterministic source-level normalizer for seniority and experience bounds; no historical rewrite |
| `main.py` | Orchestrator — all CLI flags; auto-runs self-diagnosis at run end |
| `source_snapshot.py` | Source snapshot writer: homogeneous jobs upsert + feed close (presence + full-scope age delist). Does not delete rows. |
| `csv_importer.py` | Phase 3A source-only publish or legacy full upsert; shapes rows then hands writes to `source_snapshot` |
| `enrichment_state.py` | Forward-only source hash and enrichment-version contract |
| `enrichment_worker.py` | Lazy Supabase queue consumer; retries inference outages and rejects stale/inactive work |
| `ASYNC_ENRICHMENT.md` | Cutover contract, commands, and rollout verification |
| `job_embedding_state.py` | Stable source-document/query prefix and content-hash contract for semantic retrieval |
| `job_embedding_worker.py` | Local LM Studio batch worker plus live semantic-query diagnostic |
| `JOB_EMBEDDINGS.md` | 14-day rollout boundary, private-vector design, operations, and Myro RPC contract |
| `CAREER_OPS_AUDIT.md` | Upstream provider audit, adopted boards, trust comparison, and direct-ATS expansion backlog |
| `diagnose.py` | Phase 4 self-healing diagnostic — classify a run's 0/low companies into buckets, `--probe` re-tests routes |
| `heal/` | Self-healing package: `baseline.py` (ledger), `classifier.py` (failure buckets), `probe.py` (live re-test seam) |
| `baseline_ledger.json` | Per-company last-known-good India count — auto-synced from `scrape_diagnostics`; forward-only |
| `sql/` | Migration files — run manually via Supabase dashboard |

---

## SELF-HEALING DIAGNOSTIC (Phase 4)

Turns the old hand-written `HANDOFF_skipped_companies_*.md` into a generated artifact. After a scrape, `main.py` auto-classifies every 0/low company; `diagnose.py` re-runs it and (with `--probe`) live-tests the cheap-win routes.

```bash
cd scraper
python diagnose.py                          # classify latest run -> logs/diagnosis_<run_id>.md
python diagnose.py --run <run_id>           # a specific run
python diagnose.py --bucket REGRESSION      # one bucket only
python diagnose.py --probe                  # live re-test REGRESSION + PARAM_SUSPECT routes (network, no Docker for direct routes)
python diagnose.py --propose                # emit reviewable fix diffs (free dedup analysis) -> logs/proposed_fixes_*.md
python diagnose.py --probe-crack            # Firecrawl-cloud discovery on NEEDS_CRACK companies (spends credits; cached)
python diagnose.py --json                   # machine-readable verdicts
```

**Auto-propose (propose-only, never applies).** `--propose` runs `heal/propose.py`: it statically finds *generic-duplicate masking* (a company listed in both its real ATS section and a generic CUSTOM/industry section, so `portal_reader` emits a phantom `ats=custom/other` portal that returns 0 and tanks the company) and emits the deletion diff. This is the bug that silently broke HSBC/Mphasis/Persistent on 2026-06-04; fixed 2026-06-07 and guarded by `test_heal_propose.py`. `--probe-crack` adds the Firecrawl-cloud discovery adapter (`heal/probe.probe_company_firecrawl`): map → rank candidate listing/API URLs → propose a `KNOWN_PORTALS.md` row stub for a human to promote.

**Buckets** (map 1:1 to the old handoff A–E): `REGRESSION` (had a baseline, now 0/dropped — cheapest win) · `PARAM_SUSPECT` (direct route, 0, never confirmed good) · `COOKIE_NEEDED` (Darwinbox) · `NEEDS_CRACK` (JS-opaque / `ats=other`) · `BLOCKED_EXPECTED` (known CF-blocked Workday) · `LOW_COUNT`.

**Regression detection** diffs this run's scrape count against `baseline_ledger.json` (last-known-good, synced from `scrape_diagnostics` after each load). Forward-only: a bad run never lowers a baseline — that drop *is* the signal.

**Probe** = `heal/probe.probe_company()` re-runs the exact provider via `dispatch_scrape` with a small cap and reports `RECOVERED` / `STILL_BROKEN` / `PARTIAL` / `ERROR`. Propose-only — never edits config (CHANGE DISCIPLINE).

> **Bootstrap note:** `baseline_ledger.json` was seeded from documented CLAUDE.md/handoff counts. From the next `csv_importer.py` load onward it self-maintains.

---

## CANONICAL SCHEMA (v3.1)

| Field | Source | Notes |
|---|---|---|
| `job_id` | ATS native ID | dedup key |
| `job_title` | ATS / page title | no LLM |
| `job_description` | ATS JD endpoint or Firecrawl | full text |
| `career_band` | `job_career_band.py` at source write | nullable matching fact: one of the four deterministic role families when provable; NULL remains browseable but makes no band-dependent matching claim; forward-only |
| `seniority_level` | `job_seniority.py` at source write | deterministic canonical ladder from provider metadata, title, and source JD; forward-only |
| `min_years_experience` / `max_years_experience` | `job_seniority.py` at source write | parsed source bounds where explicit; no model inference |
| `company_name` | KNOWN_PORTALS.md | |
| `industry` | company_industries.json | raw category (43 values) |
| `industry_group` | csv_importer mapping dict | 10-bucket super-category for UX filters |
| `role_domain` | LLM Phase 2 | 15-value controlled vocab |
| `location` | csv_importer `_normalize_location` | display string derived from raw |
| `location_raw` | ATS or Firecrawl | original scraped location string |
| `location_city` | csv_importer `_normalize_location` | canonical city name |
| `location_country` | csv_importer `_normalize_location` | canonical country — **required for True_Yodha match filter** |
| `location_mode` | csv_importer `_normalize_location` | `onsite` / `hybrid` / `remote` / `unknown` |
| `location_quality` | csv_importer `_normalize_location` | `ok` / `unknown` — hydration sentinel in True_Yodha |
| `apply_url` | ATS direct link | null if image/invalid URL |
| `skills` | LLM Phase 2 | ONE flat list of `{name, required_level}` (Lightcast L3); JSON-only field, drives `job_skills` — not a `jobs` column |
| `main_skills` | LLM Phase 2 | back-compat name mirror of `skills` (all needed skills; True_Yodha chips read this) |
| `side_skills` | — | **deprecated, always `[]`** (no more primary/side split) |
| `batch_date` | writer.py | integer YYYYMMDD |
| `first_seen` | csv_importer | set on INSERT only |
| `last_seen` | csv_importer | updated every run |
| `is_active` | community-owned | true on INSERT; only `job_reports` trigger sets false |
| `report_count` | job_reports trigger | incremented per report; at 5 → is_active=false |

### job_skills table (FK join table — canonical skill source)

> **⚠️ THE SCRAPER NO LONGER WRITES `job_skills` (2026-08-07).** It belongs to
> True_Yodha's skill engine: **Stage A** reads *where* in the JD each skill is
> named (must-have / preferred / mentioned, → `is_primary`) and **Stage B** judges
> *how deep* (→ `required_level`). Both key on this same Lightcast taxonomy.
>
> Why it moved: this side wrote every row with `is_primary=True`, so 94.2% of
> 361,165 prod rows carried a constant where the importance signal belongs —
> company demand reported every skill of every company as a 100% must-have. Worse,
> `apply_job_enrichment` DELETEd the whole set first, destroying Stage A's read
> and Stage B's verdicts on any newly scraped job, with `has_skill_floor` left
> true so Stage A never revisited it.
>
> `csv_importer._resolve_and_upsert_skills` now only counts taxonomy drift.
> `apply_job_enrichment` writes `job_summary` + `role_domain` only; its `p_skills`
> argument is accepted and ignored so the deployed worker keeps its signature.
> `jobs.main_skills` is derived from `job_skills` by a Supabase trigger.
> After a successful publication, `csv_importer` sends the immutable `run_id` to
> True_Yodha's authenticated `/internal/scrape/landed` hook. That hook enqueues
> the deterministic Stage A drain on Myro's durable bulk Work Lane and asserts
> the unattempted queue returns to zero. This hand-off uses no LM Studio or LLM
> tokens; Stage B remains the separate judgment-model pass. Publication is not
> complete until Myro returns `skill_floor_enqueued=true`: transport/5xx failures
> receive bounded retries, and a missing or rejected hand-off makes `daily_poll`
> fail at `publish`. Re-running is safe because source upserts and the run-id
> correlation key are idempotent.
> Design + migrations: `True_Yodha/SKILL_ENGINE.md`,
> `True_Yodha/database/migrations/20260807b_enrichment_stops_owning_skills.sql`.

`job_skills` is the source of truth for skill↔job relationships in True_Yodha.
`main_skills` TEXT array on `jobs` is the back-compat name mirror (True_Yodha chips read it); `side_skills` is deprecated (always `[]`) and can be dropped in a later cleanup.

| Column | Type | Notes |
|---|---|---|
| `job_id` | uuid FK → jobs | |
| `skill_id` | uuid FK → skills | resolved via `skills.taxonomy_key` (== Lightcast L3 name; verified 35,108/35,108 resolve) |
| `is_primary` | boolean | **always `true`** — primary/side split removed (2026-06-07); kept for back-compat, importance now lives in `required_level` |
| `required_level` | smallint (1–4) | scraper-owned proficiency signal; migration file: `scraper/sql/add_job_skills_required_level.sql` |

**Skill model (ONE bucket + level — updated 2026-06-07):**
- No more main-skill vs side-skill split. A skill is either needed or it is not; **how deeply** it's needed is the `required_level` (1–4). User directive: *"Either you need a skill or you don't."*
- L1 = awareness/basic, L2 = working proficiency, L3 = advanced/practitioner, L4 = expert/authority
- LM Studio returns `skills[]` objects: `{name, required_level}` (no `is_primary`)
- `_validate_enrichment()` canonicalizes against Lightcast L3, bounds level to 1–4 (default L2), caps the list at 10, sets `main_skills = [all names]` and `side_skills = []`
- `writer.to_canonical` now persists the structured `skills` array (with model levels) into `jobs.json` — previously dropped, which is why pre-2026-06-07 rows defaulted to level 2
- ~~`csv_importer` writes every `job_skills` row with `is_primary=True`~~ — **retired 2026-08-07**, see the box above. That constant is exactly what broke company demand; `is_primary` now carries Stage A's must-have zone
- **Forward-only: no backfill.** Existing rows keep their old levels; correctness applies from the next scrape onward (product philosophy: agile, downstream-only)
- True_Yodha should read `job_skills.required_level` directly and keep any heuristic only as a fallback

---

## COMMUNITY FRESHNESS LAYER

Scraper = discovery (new jobs). Community = freshness (is this still open?).

### job_reports table (live in Supabase)
- Single "Report as Inactive" button — no reason dropdown
- Auth required (True_Yodha user account)
- 1 report per user per job — UNIQUE(job_id, user_id) enforced in DB
- Max 3 reports/day per user — backend guard in True_Yodha
- Reporter earns +10 XP → written to `daily_logs.skills_delta` as `community_reporter`
- **5 reports → Supabase trigger sets `is_active = false`**

### is_active ownership
- `csv_importer` sets `is_active = true` on INSERT only
- Community reports can still deactivate jobs through the `job_reports` trigger
- Scraper decommissioning is opt-in: `csv_importer.py --deactivate-missing`
- Scraper decommissioning only compares companies represented by one run date; real writes require `--run-date YYYYMMDD`
- Dry-run decommissioning can omit `--run-date` to inspect the newest output date without writes
- Companies absent from that run date are never touched
- The importer blocks deactivation if upload quality fails or if one company would deactivate more than 75% of active rows, unless `--allow-large-deactivation` is explicitly passed

### Backend + frontend lives in True_Yodha repo
Full spec: `/Users/incognito/True_Yodha/docs/REPORT_INACTIVE_FEATURE.md`

---

## ATS ROUTING

| ATS | Method | Companies |
|---|---|---|
| Workday | Direct POST CXS API — India UUID + pagination + per-job JD fetch | Accenture, Thomson Reuters, 30+ others |
| SmartRecruiters | Direct GET `?country=in` — full JD in response | |
| Greenhouse | Direct GET — India filter in Python — full JD in response | |
| Lever | Direct GET `?location=india` | |
| Phenom | REST API per tenant | |
| Phenom SSR | GET search-results page → embedded `phApp.ddo.eagerLoadRefineSearch.data.jobs` → per-job JSON-LD detail | Adobe, ABB, Cisco, P&G |
| PCSX (Phenom CX) | Bootstrap public career board for visitor cookies, then GET `/api/pcsx/search?domain=X&location=india&start=N` + per-job HTML JSON-LD; later-page failures quarantine the whole snapshot | NVIDIA, Micron, PayPal, Infineon, Lam Research, Qualcomm |
| Pinpoint | GET `/en/postings.json?location_id[]=ID1&location_id[]=ID2` | |
| Darwinbox | POST `/ms/candidateapi/job/alljobs` — requires CF cookies in env vars | Swiggy, Flipkart, Myntra, OYO, IIFL |
| Oracle HCM | GET finder=findReqs + India locationId; JD from API or HTML `og:description` fallback | |
| Taleo (Oracle TBE) | POST `/services/jobs/search/` + per-job HTML BeautifulSoup | HCL Technologies |
| TalentBrew | Direct paginated HTML — India location filter in URL path + per-job detail page | Intuit, ADP |
| Siemens ExternalJobs | GET `/SearchJobs` paginate with `folderOffset` → per-job `/JobDetail/{id}` HTML | Siemens |
| Keka Hire | GET public `/careers/api/jobs/default/active`; full JD and locations in listing JSON | TVS Next |
| Yello (Recsolu) | GET `/job_boards/{board_id}/search?filters={country_id}&page_number=N` → per-job detail page | EY India |
| SAP Jobs2Web HTML | GET `/search/?locationsearch=india&startrow=N` paginated HTML → per-job detail page | Alstom, Monitor Deloitte, EY India Experienced |
| PepsiCo Jobs API | GET `pepsicojobs.com/api/jobs?country=India&page=N` JSON | PepsiCo |
| Deloitte USI (BrassRing) | GET `usijobs.deloitte.com/careersUSI/SearchJobs?jobOffset=N` paginated HTML | Deloitte India |
| Skima Careers | GET HTML `?page=N` → per-job `/{uuid}` detail page | Nykaa |
| Aditya Birla (custom) | GET `/api/v3/jobs` + per-job `/api/v3/job/{jcode}` — Bearer token | |
| Generic JSON | Configurable field mapping per company — auto-saved to `generic_registry.json` | Atlassian + others |
| JS-heavy (Eightfold, Avature, SPAs) | `scrape_extract()` via Firecrawl (Docker first, cloud last resort) | Goldman Sachs, Eightfold tenants |

---

## FIRECRAWL CREDIT DISCIPLINE

1. Always use `firecrawl-py` SDK — never raw HTTP.
2. One singleton `_app` instance in `firecrawl_client.py`. Never instantiate elsewhere.
3. Never use `crawl()`.
4. Three permitted discovery/extraction calls:
   - `fc.map_site(url, ...)` — discovery-first URL enumeration (1 credit per site)
   - `fc.scrape(url)` — targeted markdown fetch (1 credit per URL)
   - `fc.extract(urls, schema, prompt)` — JS-heavy structured fallback only
5. Preferred workflow for crack-hunt sessions: **Direct ATS guess → Firecrawl `map_site()` → selective `scrape()` on the best 1-3 URLs → save the direct endpoint.**
6. Priority order: Direct ATS API → Firecrawl map/scrape for discovery → Docker/Firecrawl fallback for opaque portals → later validation.
7. During the current endpoint-capture phase, **do not spend credits on broad verification runs**. Capture the route and move forward.

---

## LLM ENRICHMENT FLOW

1. `job_description` populated by scraper
2. `rag_skills.py` retrieves top-40 Lightcast L3 skills from JD as vocabulary
3. `enrich_job()` sends vocab + JD to LM Studio (`gemma-3-4b`, max_tokens=512, temp=0.0)
4. LLM returns `role_domain` + a single flat `skills[]` of `{name, required_level}` (no `is_primary`)
5. `_validate_enrichment()` canonicalizes against Lightcast L3, bounds levels to 1–4 (default L2), caps at 10, sets `main_skills = [all names]` and `side_skills = []`
6. `writer.to_canonical` persists the structured `skills` (with levels) to `jobs.json`. **They stop there** — `job_skills` is written by True_Yodha's Stage A/Stage B, not by this pipeline (see the job_skills box above). The importer resolves the names only to report taxonomy drift.

---

## "CRACK ONCE, REUSE FOREVER" — CORE PRINCIPLE

| Registry | Purpose | Auto-written? |
|---|---|---|
| `workday_registry.json` | Per-tenant: India UUID, facet params, `blocked=true` | Yes |
| `generic_registry.json` | Per-company: which JSON keys worked | Yes |
| `company_industries.json` | Company → Industry | Manual |

**`blocked=true`** = Cloudflare blocks all POSTs. Scraper skips API, goes straight to Firecrawl.
Confirmed blocked: Engie, GE Aerospace, Bank of America, Ford, Medtronic, Inspire Brands, Hitachi Vantara, Intuit, AMD, ANZ Bank, Keysight, Deutsche Bank, Standard Chartered Bank, Eli Lilly.

**Darwinbox CF Turnstile** (Swiggy, Flipkart, Myntra, OYO, IIFL Finance): provider built, needs `DARWINBOX_CF_BM` + `DARWINBOX_SESSION` env vars. Get from browser devtools → Network → `alljobs` POST → Copy as cURL. Cookies expire in 30 min, IP-bound.

---

## KNOWN ISSUES

- Micron old Eightfold apply API assumption is retired — use PCSX (`micron.eightfold.ai/api/pcsx/search`); Philip Morris remains Phenom client-side, not Eightfold
- MSCI: ✅ RESOLVED — was wrongly assumed Workday; actually Algolia (`msci_algolia` provider)
- Dell: Workday returns 200+empty — suspected CF-blocked; add `blocked=true` if confirmed
- EY India Experienced (`sap_jobs2web_html`): many postings have JD text of only `Requisition Id : <id>` — ~50% drop rate
- Goldman Sachs: cracked via GraphQL (`api-higher.gs.com`) — old TAL.NET Firecrawl route retired
- ARM Holdings: cracked as TalentBrew — old iCIMS assumption was wrong
- Mastercard: cracked as TalentBrew — was wrongly in Workday section
- Philip Morris: NOT Eightfold (tenant-not-identified error was because it's Phenom, not Eightfold)
- Syngenta: was in ANTIBOT BLOCKED with wrong SR company ID (`Syngenta`) — correct ID is `SyngentaGroup`
- **Stale dirty `job_title` rows — ✅ RESOLVED 2026-07-25.** Report (2026-06-21) flagged 127 legacy contaminated titles (escaped `\n`/backslashes/`###`/concatenated Location+Employment Type). By 2026-07-25 the pipeline had self-healed nearly all: the dominant dirty sources (Morgan Stanley Eightfold, D.E. Shaw, Micron, Rippling) re-crawled clean or delisted — detection query down to 3 rows. Closed by one targeted SQL pass: 1 genuinely-dirty legacy row (Vector Consulting `08a7b3ffb225f2a6`, never re-crawled since 20260429) set to its clean title; 2 Infosys rows (`Z\OS` → `z/OS`) normalized — those were false positives (literal backslash in the real source title, not contamination). Detection query now returns **0**. The 10 Morgan Stanley NULL-marker rows were already gone (cleaned/delisted). Parser guard confirmed holding — zero dirty crawls since 2026-04-30. **Separate follow-up (NOT this issue):** 15 active rows carry NULL `first_seen`/`last_seen` but they are extension/saved-job entries (hosts: linkedin.com, mail.google.com, amazon.jobs, start.mopid.me), not scraper rows — scraper must not touch them; they are a delisting blind-spot to route through the saved-job system, not the dirty-title cleanup. Original report retained: `docs/handoffs/REPORT_stale_dirty_titles_20260621.md`.

---

## PENDING WORK

> Agile/forward-only doc: completed work is pruned from here once shipped. History lives in git + `RUN_HISTORY.md`; portal status lives in `KNOWN_PORTALS.md`.

### 0 — Next: full-scope source publish

Stripe `--company` canary is green on the source snapshot writer (2026-09-08 re-run of run date `2026_09_07`: summaries survived, Stage A accepted). A full-scope importer without `--company` will close every active job with `last_seen` older than 30 days; True_Yodha unloads those rows one hour later after writing `job_archive_v1` files. Pin `--run-date` to the scrape folder. Clock stays on this laptop.

### 1 — Parked portals (no durable route)

| Company | Career URL | Blocker |
|---|---|---|
| Vehere | https://vehere.com/company/careers/ | Cloudflare 403 across sessions (`__cf_bm` session-bound, IP-locked). Deprioritized 2026-06-07 after 3+ tries. Revisit only with a browser-session XHR capture that yields a durable cookie-free route. |
| Godrej Industries (parent) | https://www.godrejcareers.com/ | Akamai 403; separate portal from Godrej Consumer (already live). May be internal/intranet. |
| Avendus Capital | https://avendus.darwinbox.in/ms/candidatev2/main/careers/allJobs | Darwinbox ATS confirmed, but listing requests still require fresh Cloudflare/session cookies. Revisit only if a cookie-free endpoint or renewable browser bootstrap is captured. |
| IndusInd Bank | https://app1100.workline.hr/careers/ | Workline ATS confirmed, but its public JSON method returns `not authorized`, unlike SBI MF. Revisit with a browser XHR capture that produces a repeatable token flow. |
| Uber | https://www.uber.com/careers/list/ | Firecrawl map returned a stale detail URL that now resolves to Uber's not-found page; no current listing API fingerprint. |
| Walmart | https://careers.walmart.com/results?q=india | Next.js shell renders no listings to direct HTTP or Firecrawl. Cloud map returns US detail pages despite the India query. Revisit only with the browser listing XHR contract. |

### 2 — 10k company scale-out (engine BUILT 2026-06-13; execution left)

Goal: grow tracked companies from ~307 toward **10,000**, biased to Tier-1/2 college recruiters.
The `scraper/discovery/` engine works; only repeated execution + one gate remain. All FREE — no Firecrawl credits.

- **2a — Broad token collection.** Expand `discovery/board_tokens.txt` via many `site:` searches across ATS × sector × city (e.g. `site:boards.greenhouse.io fintech bengaluru`, `site:jobs.lever.co saas hyderabad`, `site:jobs.ashbyhq.com mumbai`, `site:jobs.smartrecruiters.com pune`). These return REAL slugs → no 404 waste. Each query ≈ 8–12 tokens; thousands of tokens = hundreds of queries. Append in `ats:token` form.
- **2b — Harvester quality gate — ✅ SHIPPED 2026-07-26.** `harvest_boards.py:looks_like_pollution()` routes likely agency/aggregator/microtask boards to `status='review'` (held back from the auto-promote `net_new` bucket into a labeled REVIEW section in `harvest_promote.md`; no paste-ready stub). Gate = agency-word regex (`consult|staffing|\bstaff\b|advisory|recruit|manpower|outsourc|placement|marketplace`) **OR** `total>400 AND india/total<20%` (ratio refinement over a bare total rule — protects genuine large India employers). Principle (Myro/Kunal lens): **index single EMPLOYERS, not listings** — an undisclosed-multi-client agency breaks the "explain what THIS company wants" promise, so review = "confirm ONE real hiring company." Deliberately does NOT hard-code names or bare `network` (would false-flag real "…Networks" product cos); accepted misses (Weekday/TMI) surface in the promote list for the human single-employer check. Guarded by `tests/test_harvest_quality_gate.py` (13 cases). Live-verified: 24 hits → 5 net-new, 3 held (Squircle/Welocalize/Capital Aim).
- **2c — Run + promote at scale.** `python discovery/harvest_boards.py` → review `harvest_promote.md` → promote product-company India boards. For Ashby, also add `ats_overrides`+`endpoint_overrides` entries in `portal_reader.py` (Ashby is name-hardcoded). Consider an `apply_harvest.py` to auto-append correctly-formatted rows to KNOWN_PORTALS instead of hand-edits.
- **Reality:** college-seed path (`phase0_discover.py` + `resolve_ats.py`) is credit-bound + diminishing (~18 net-new per ~1,150 seed); the board-directory harvest (2a–2c) is the actual 10k lever.

### 4 — Upskilling question-bank pipeline (pilot implemented 2026-06-11; population pending — OWNED BY CODEX as of 2026-06-13)

Feed the Practice→Upskilling MCQ ladder. The True_Yodha side is **BUILT** (backend serves/grades sets, frontend ladder/quiz/results + job-gap calibration) but reads from an **empty** `skill_questions` table — until this pipeline fills it, the Upskilling home shows a "ladder on the way" empty state. PRD: `True_Yodha/docs/PRD_practice_upskilling_skillgap.md` §4.2 + §6. Migration `True_Yodha/database/migrations/20260609_upskilling_quiz_bank.sql` already applied (shared Supabase `gipvxuugajkugntwkeiz`).

**Implemented hybrid ingest → LLM-clean → verify → publish pipeline:**

1. **Ingest** transient raw candidates from git-ignored JSONL with `source_url`; hash them and never persist source prose. Direct scrape adapters can later emit the same in-memory contract.
2. **LLM clean** (cheap tier): per raw item → normalized MCQ: `question_text`, exactly 4 `options`, `correct_index` (0–3), one-sentence `explanation`, assigned `level` (1–5: L1 recall → L3 applied → L5 architecture/trade-off). Reject anything not reducible to a single unambiguous MCQ.
3. **Dedupe** with transient raw hash, normalized-text `dedupe_hash`, and near-duplicate similarity review.
4. **Answer-key verifier** — independent prompt, deterministically shuffled options, preferably a distinct local model. Disagreement/ambiguity/large level drift → `status='review'`.
5. **Publish** only behind explicit `--publish`; dry-run is the default. Existing active rows cannot be downgraded or overwritten by routine reruns.

**Target table `skill_questions` (already exists, service-write):** `skill_id INT REFERENCES skills(id)`, `skill_key TEXT` (== `skills.taxonomy_key`), `level SMALLINT 1–5`, `question_text TEXT`, `options JSONB` (4 strings), `correct_index SMALLINT 0–3`, `explanation TEXT`, `source_url TEXT`, `dedupe_hash TEXT`, `status TEXT default 'active'`. Aim **50–60 Qs/skill** (≥10 per level) so a skill's full ladder unlocks; the backend gracefully shows only levels with ≥10 active Qs.

- **Pilot skills locked:** Machine Learning (`skills.id=2772`), Product Strategy (`20985`), Management Consulting (`21871`), Financial Accounting (`28333`).
- **Scope boundary:** `True_Yodha/reference/Interview Prep/` was not accessed. Source candidates must be supplied inside this repository under the git-ignored `scraper/question_bank_inputs/`.
- **Legal posture (PRD §4.2 note):** store LLM-NORMALIZED questions + our own answer keys + `source_url` provenance — never verbatim scraped prose. Counsel sign-off on sourcing is an open item (cross-link True_Yodha Backlog #17).
- **Verification 2026-06-11:** `pytest -q scraper/tests/question_bank` → 40 passed. Live read-only preflight confirmed the table contract, all four taxonomy keys, and zero existing rows. LM Studio was offline, so no real model call or Supabase write was attempted.

**Commands:**

```bash
cd scraper
python -m question_bank.cli --preflight-only
python -m question_bank.cli --input question_bank_inputs/pilot.jsonl --dry-run
python -m question_bank.cli --input question_bank_inputs/pilot.jsonl --resume-run <run_id> --dry-run
python -m question_bank.cli --input question_bank_inputs/pilot.jsonl --publish
```

Operational details and safeguards: `scraper/question_bank/README.md`.

---

## CLAUDE CODE SKILLS

| Skill | Trigger |
|---|---|
| `graphify` | `/graphify` |
| `triage-issue` | `/triage-issue` |
| `to-issues` | `/to-issues` |
| `to-prd` | `/to-prd` |
| `review` | `/review` |
| `security-review` | `/security-review` |
| `tdd` | `/tdd` |
| `simplify` | `/simplify` |
| `improve-codebase-architecture` | `/improve-codebase-architecture` |
| `caveman` | `/caveman` |
| `grill-me` | `/grill-me` |
| `find-skills` | `/find-skills` |
| `karpathy-guidelines` | `/karpathy-guidelines` |
| `fewer-permission-prompts` | `/fewer-permission-prompts` |
