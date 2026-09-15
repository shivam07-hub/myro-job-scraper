# RUN HISTORY

Chronological log of scraper sessions, data quality incidents, and resolved bugs.
Current architecture and run commands live in `CLAUDE.md`. Portal config lives in `KNOWN_PORTALS.md`.

---

## Session 2026-09-07 — Job-feed architecture (uncap, extractive summary, 30-day delist, Scrapling fetch)

**Closed without an E2E import.** Next session runs the canary → source-only publish path.

**Shipped locally, not committed** (on `main` after `223578206`):
- `--company-cap` default **0** (unlimited) on `main.py` / `daily_poll.py` / `daily_cycle.py`; provider loops no longer stop at a silent 2000.
- Extractive `job_summary` at scrape; source-only import writes it only when the DB cell is empty.
- Full-scope publish closes active rows with `last_seen` older than **30 days**. `--company` canaries skip that backstop. NULL `last_seen` left alone.
- Scrapling HTTP fetch in front of Firecrawl for opaque HTML (`scrapling_client.py`). Direct ATS APIs unchanged. StealthyFetcher not wired.
- Laptop clock kept; cloud schedule deferred.

**Do not full-publish first.** A complete import will retire April-era active rows by design. Start with `--company "Stripe"`.

---

## Session 2026-08-13 — 54-company failure incident and trusted publication closure

**Objective:** Recover current jobs from durable official career-page routes,
prevent incomplete snapshots from becoming user inventory, and classify every
company in the failed cohort without pretending a block or genuine zero is a
successful scrape.

**Root causes and repairs:** The five failed PCSX tenants needed visitor cookies
from a career-page bootstrap before paginated API calls. The provider also
collapsed a later-page 403 into a successful prefix; Micron demonstrated the bug
by saving 170 rows as complete. PCSX now reuses/refreshes a visitor session and
returns a typed partial result. Dispatch preserves it and the orchestrator
quarantines it. Writer/provider batch dedupe also removes overlapping page ids.
H&M moved from its 403 WordPress proxy to SmartRecruiters; Tekion moved from a
404 Greenhouse board to Ashby; TVS Next gained a Keka provider. The retired H&M
provider was removed. Diagnostics now resolve persisted run ids, execute JSON
probes, and keep Firecrawl out of cheap direct-route probes.

**Measured closure:** Complete targeted collections produced H&M 62, Tekion 61,
TVS Next 23, Binance 1, NVIDIA 218, Micron 261, PayPal 3, Infineon 140, and Lam
Research 73: **842 unique jobs**, each with a full JD and apply URL. Resolver
facts were deterministic for 760; the other 82 published truthfully with a null
career band. Import run `6eb699b7-64d0-4ad4-b2b2-344b866ea7f4` published all
842, using timeout-splitting during Supabase degradation.

**Visibility bug found during closure:** The importer said it tracked lifecycle
but never called `trusted_job_lifecycle`; a successful upsert could remain
`listing_confidence='uncertain'` and invisible. Lifecycle sync is now mandatory
after import. Source-only publication promotes seen listings but defers company
skill facts until Phase 2. Reconciliation accepted 9/9 complete source runs;
live reads confirmed **842/842 active, trusted, and applyable**.

**Opaque-route budget:** Firecrawl Cloud checked all eight NEEDS_CRACK companies.
Six returned no listing signal; Tech Mahindra returned generic careers pages;
FinIQ returned a campus aggregate table, not atomic public jobs with apply URLs.
No weak candidate was promoted.

The final direct-route probe sweep measured 8 recovered, 16 reachable-zero, 7
fallback-needed, 5 typed errors, and 1 coverage drop. The probe vocabulary was
fixed so `PARTIAL` now means only a typed torn snapshot; an undersized but
successful sample is `COVERAGE_DROP`.

**Verification:** 343 scraper tests pass; owned Python passes Ruff; production
publication, lifecycle reconciliation, and exact trusted/applyable counts were
verified.

---

## Session 2026-08-13 — Unclassified jobs restored to browse without invented matching truth

**Objective:** Close the recurring 13% publication loss without expanding
employer-specific regex or weakening Myro's four-band evidence contract.

**Decision:** Publication eligibility and matching readiness are separate.
Source-valid jobs whose career band cannot be proven publish with
`career_band=NULL`; they remain browse/search eligible and make no
band-dependent matching claim. Invalid identity, seniority, and stale band
claims still fail publication. The existing `listing_confidence` lifecycle
continues to decide trusted user visibility.

**Implementation:** `csv_importer --publish-unclassified` now separates
unclassified, malformed-withheld, and duplicate-source counts; explicitly
writes NULL on conflict so an old band cannot survive a source change; and keeps
`--resolved-only` as a deprecated operational alias. `daily_poll.py` uses the
new contract. The resolver CLI's percent-bearing help text was also fixed after
Python 3.14 exposed an argparse formatting crash.

**Measured closure:** The 2026-08-08 source corpus contained 33,246 rows. After
deduplication, production run `1867389a-b29c-4377-b363-ed2214d0ab31` published
**33,215 unique jobs** in 1,065s: **28,957 classified + 4,258 unclassified**, 31
duplicate source rows collapsed, 0 malformed withheld, and 33 unknown locations
(0.099%). All 261 company diagnostics and the `ok` run audit are persisted.
Live SQL found zero empty-string bands. Trust was not bypassed: 747 unclassified
rows were already trusted-active and 3,036 remain uncertain. Intel refresh and
the scrape-landed sweep both accepted the run.

**Verification:** 331 scraper tests passed under `/opt/anaconda3/bin/python`;
owned Python files passed Ruff and `git diff --check`.

---

## Session 2026-08-08 — First run under the career-band publication gate

**Objective:** Fresh full India scrape through `daily_cycle.py`, after verifying
no staged work would change how data is captured.

**Preflight caught a hard blocker before the run.** The staged (uncommitted)
matching-fact preflight in `csv_importer` rejects any row whose `career_band`
lacks current provenance, but `writer.to_canonical` never writes
`career_band_source`/`career_band_source_hash` — they are not in
`CANONICAL_FIELDS`. `source_matching_facts.py` was wired into nothing. Scrape →
publish would have rejected the entire run after 9 hours of scraping. Verified
empirically, not inferred, then wired `scrape → resolve → publish` into
`daily_poll.py`.

**Run:** 261 companies complete, 54 failed, 25,402 new jobs (9h, 23:28→08:26).
Published **28,957** rows; **4,289 withheld** for an unresolved band; location
quality 24 unknown (0.08%). Docker was off, so the 7 JS/Firecrawl portals
returned 0.

**Three latent defects found and fixed:**
1. `source_matching_facts._write_jobs` sat inside `if not dry_run and pending:`,
   so a company whose titles all resolved deterministically never had its
   provenance persisted — the publish then withheld **the entire company**.
   Caught live: resolver reported `0 unresolved` while the publish still
   withheld 3. Guarded by `test_fully_deterministic_run_still_persists_provenance`.
2. `public.claim_job_embeddings` wrote its status test as an OR whose branches
   each name a status, which the planner cannot prove implies the partial index
   predicate. It seq-scanned and sorted the whole queue on every claim and had
   exceeded the statement timeout: **the embedding queue was dead since
   2026-07-14** (30,248 pending). Predicate rewritten to match the index —
   1,499ms → **5ms**. Migration: `sql/fix_job_embedding_claim_index_usage.sql`.
3. `_PUBLIC_IMPACT_OCCUPATION` matched bare `scientist` ahead of the technical
   check, so **every Data Scientist banded as research/people/public impact** —
   contradicting the band guide ("data, AI" → engineering_data) and dropping
   them from the technical keep-set `scrape_select` uses when a company is over
   its cap. Fixed with `_TECHNICAL_SCIENTIST`, placed before the public-impact
   rule; "Research Scientist" deliberately left in the research band.

**Model pass retired from the daily lane.** Deterministic rules banded 86.5% of
33,246 jobs in 13 seconds; the model pass ran at ~2.7 calls/min and accepted ~7%.
`--skip-model` is now the daily default.

**Band-rule expansion recovered only +242 of 4,501 withheld.** The remainder are
titles that name no function (`IN-Expert`, `Fixed Term Appointment`, bare ladder
grades) or hide it behind an employer-private prefix (`CBG:`, `DAS/MUM/…`).
Generic rules cannot reach them; an employer-prefix map was considered and
declined. ~13% withheld per run is the standing cost of withhold-don't-guess.

**Cycle did not complete as one command.** The publish step for the spanned date
`2026_08_07` exited 2 — see the midnight-spanning note in `CLAUDE.md`. Embeddings,
skill floor, and enrichment were run separately afterwards, sequentially:
running the embedding and enrichment workers concurrently made LM Studio evict
one model for the other, failing both. Supabase was also materially degraded
during the session (a trivial REST root request measured 10.0s/1.3s/2.6s), which
caused repeated connection resets across all three workers; they are idempotent
and were drained with retry loops.

---

## Session 2026-07-13 — Source-first semantic job embeddings

**Objective:** Unblock Myro's "brain is boss, no sieve" retrieval direction by
embedding only recent jobs, keeping vectors private, and making source-published
jobs searchable before slower generative enrichment completes.

**Implementation:**
- Added `scraper/job_embedding_state.py`: stable `search_document:` /
  `search_query:` prefixes, source-only document construction, versioning, and
  exact input hashes.
- Added `scraper/job_embedding_worker.py`: local-only LM Studio preflight,
  validated 768-dimensional batch embeddings, durable claim tokens,
  apply/retry handling, graceful interrupt recovery, and a live semantic-query
  diagnostic. Bounded rollout workers may use exact-weight runtime aliases while
  rows retain one canonical model identity.
- Added service-role-only `private.job_embeddings`, a partial HNSW cosine index,
  forward insert/source-change enrollment, claim/apply/retry/metrics RPCs, and
  `match_jobs_semantic`. Retrieval filters only inactive/closed jobs and explicit
  request scope; it has no similarity threshold or skill-term prefilter.
- Integrated the embedding lane into `daily_cycle.py` between immediate source
  publication and generative enrichment. The cycle starts/loads the embedding
  model independently, so it cannot claim work against a disconnected runtime.
- Documented the stable contract and Myro handoff in
  `scraper/JOB_EMBEDDINGS.md`.

**14-day boundary correction:**
- The first live seed used `first_seen`, which incorrectly treated old jobs from
  a recent bulk import as recent and enrolled 31,888 rows. The transaction was
  narrowed before broad completion to the source `date_posted` value.
- Supported ISO, Workday relative, English abbreviated-month, and `M/D/YY`
  formats are parsed against the Asia/Kolkata calendar. Unknown dates are
  excluded rather than guessed recent.
- Final bounded enrollment is 12,442 active postings from 2026-06-30 through
  2026-07-13. Older/unknown ingestion-date rows and any provisional vectors were
  removed transactionally. New jobs and material source changes remain
  forward-enrolled.

**Live rollout notes:**
- Initial DDL correctly rolled back when the empty function search path could
  not resolve pgvector's cosine operator. Qualifying it as
  `OPERATOR(public.<=>)` fixed the root cause; the full migration then applied.
- An advisor-driven follow-up removed an unused input-hash index and aligned
  claim order with the durable queue index. RLS plus explicit grants leave
  `anon` and `authenticated` without vector-table access; `service_role` alone
  can claim or search.

**Verification:**
- Local scraper suite: `217 passed`; Ruff and Python bytecode checks passed.
- Production canaries applied without rejection and the HNSW index served the
  semantic query. Final drain and post-rollout counts are recorded below once
  terminal coverage is reached.

---

## Session 2026-07-12 — Daily polling, lazy priority enrichment, and live surface-area expansion

**Objective:** Complete the forward-only architecture on live data: daily direct
career-page polling, immediate trusted Supabase cards, independent/lazy open-weight
enrichment, personalized-search priority, delisting-safe lifecycle checks, and a
Click Apply intent-rate north-star.

**Career-ops audit and live source expansion:**
- Audited `santifer/career-ops` for provider ideas and board discovery. Reused
  the direct-ATS pattern, not its browser-per-job orchestration or model stack.
  The comparison and next provider families are recorded in
  `scraper/CAREER_OPS_AUDIT.md`.
- Added and live-scraped five Greenhouse boards plus two Ashby boards: Celonis
  32, Glean 26, Boomi 26, Hightouch 2, Hootsuite 1, Deepgram 2, Zapier 3.
- Published all 92 jobs with full JDs using `csv_importer.py --source-only`.
  Official lifecycle audit: seven complete companies, zero unknown locations,
  zero retirements. Run id: `04cf7f3d-6ca9-4af3-96c7-5a1c85a9e41a`.
- ElevenLabs remains review-only because India is mainly secondary/multi-location
  eligibility and should not be promoted without a semantics check.

**Source-first polling and lifecycle:**
- Added `scraper/daily_poll.py`: Phase 1 → Phase 3 only, with overlap lock,
  Asia/Kolkata dates, canary mode, structured reports, and no inference dependency.
- Converted the Archon workflow from weekly linear processing to one manual
  `scraper-daily-forward` cycle. The Codex automation owns recurring scheduling.
- Capped lifecycle audit coverage at 1.0 for growing portals, preventing growth
  from violating the database check constraint while retaining raw diagnostics.

**Lazy Phase 2 and personalized search:**
- Hardened the queue with atomic claims, stale-processing reclaim, and a
  service-role-only priority lane backed by the original durable pgmq message.
- Terminal completion now requires `job_summary` plus a controlled `role_domain`;
  skill-only model output becomes retryable instead of trusted-complete.
- A live Deepgram personalized-search request was claimed first and completed
  through local `google/gemma-3-4b` with a summary, domain, and grounded skills.
- `ENRICH_FORCE_LLM=1` is the worker deployment contract: deterministic evidence
  still grounds skills while the model supplies the trust-facing fields.
- Full live drain: 92/92 complete, zero missing summaries/domains, zero source
  hash mismatches, zero no-skill rows, and pgmq queue length zero. Two concurrent
  consumers completed safely; the priority canary's original message archived
  as `duplicate_complete`.

**Myro product integration / Delta 4:**
- Pending jobs enter personalized search immediately through a deterministic,
  explicit-evidence matcher; only selected provisional matches request priority
  enrichment. The dashboard refreshes while those rows are non-terminal.
- Added authenticated Apply-intent capture on dashboard, market, and CV export
  surfaces, plus the `verified_apply_intent_daily` view. The denominator reuses
  distinct verified user/job/day recommendation exposures; the numerator
  records trusted Apply clicks idempotently on the same grain. A live audit
  found 1,902 render events but only 185 distinct daily cards, so using raw
  renders would have understated the rate by roughly 10x.
- Cards continue to show day-level `last_verified_live_at`; no hour-level noise.

**Verification:**
- Scraper test suite: `205 passed`.
- Myro focused backend tests: `18 passed`; full backend: `662 passed, 1 skipped`,
  with one unrelated pre-existing frontend/backend CV stylesheet parity failure.
- Frontend strict TypeScript and lint: passed with no warnings/errors.
- Archon workflow validation: `scraper-daily-forward` valid.
- Supabase migrations and live queue/RPC/apply paths verified on project
  `gipvxuugajkugntwkeiz`.

**Automation update:** one `Daily trusted career poll` automation owns recurring
source publication and does not duplicate already-running consumers. Local
enrichment workers continue independently across poll boundaries. The old
15-minute worker is deleted; the next source run is anchored 24 hours after the
preceding poll-and-publish finishes. Railway remains an optional always-on
deployment independent of this Mac.

**2026-07-13 full-cycle recovery:** the first consolidated live run processed
266/314 portals and safely skipped 48 pipeline/config failures. It crossed
midnight, exposing that `daily_poll.py` had captured only its start date for
publication: 18,979 July 12 rows reached Supabase while 75 completed July 13
company files were omitted. The existing importer recovered the omitted 75
files (11,312 source rows; one unknown location, 0.01%). `daily_poll.py` now
publishes every local date spanned by a scrape, with regression coverage.

LM Studio's `/models` endpoint was also found to list downloaded rather than
loaded models. `daily_cycle.py` now checks `lms ps --json` and explicitly loads
Gemma when needed. A real Data Scientist canary initially failed because Gemma
emitted a trailing comma before `]`; the parser now repairs only trailing commas
outside strings before schema/taxonomy validation. The same canary then reached
terminal `complete`. Non-terminal per-job model output now retries that job and
continues the queue; only endpoint/quota failures pause a consumer. Full scraper
tests: 201 passed. Two atomic consumers were started for the initial forward-only
queue and protected with macOS awake guards.

The recovery import also exposed two native ATS IDs reused by different
companies: `29401` (Nokia/WESCO) and `32568` (Adani Thermal Power/WESCO). Because
`public.jobs.job_id` is a global primary key, the later WESCO import had replaced
the earlier cards. `csv_importer.py` now checks the live owner before each batch
upsert and namespaces only an incoming cross-company collision as
`company_slug::native_id`; it does not rewrite existing IDs or backfill history.
The July 13 source-only republish restored `nokia::29401` and
`adani_thermal_power::32568` while preserving both WESCO rows. Live verification
confirmed exactly 11,312 July 13 cards, both restored rows pending enrichment,
two active consumers, and no failed or retryable rows.

---

## Session 2026-07-11 — Forward-only asynchronous enrichment implemented

**Objective:** Publish newly scraped jobs to Supabase immediately, then enrich
them lazily when local LM Studio or an approved remote open-weight endpoint is
available. Historical rows must not be scanned or backfilled, and the existing
delisting loop remains the lifecycle authority.

**Implementation:**
- Added `scraper/enrichment_state.py` for deterministic source-content hashes
  and enrichment state constants.
- Added the production migration
  `scraper/sql/create_forward_enrichment_queue.sql`. It adds nullable tracking
  fields, forward-only trigger behavior, service-role queue RPCs, and a
  hash-guarded atomic enrichment apply function. Durable pgmq bootstrap is kept
  in `scraper/sql/enable_forward_enrichment_queue.sql` so it commits separately
  from `public.jobs` DDL and avoids Realtime lock-order deadlocks.
- Added `scraper/enrichment_worker.py`. It consumes queue messages only, exits
  without claiming work when local LM Studio is unavailable, retries temporary
  inference failures, and archives stale/inactive/legacy messages without
  spending inference compute.
- Added `csv_importer.py --source-only --run-date YYYY_MM_DD`. It imports only
  completed output for the selected run, computes the source hash, and never
  sends model-owned fields or skill rows.
- Kept the legacy `main.py --enrich-only` plus full importer path available
  during cutover.
- Documented the contract and rollout in `scraper/ASYNC_ENRICHMENT.md`.

**Forward-only guarantees:**
- The migration contains no historical queue seed or backfill.
- Pre-cutover jobs remain `NULL`/untracked when their first source hash is
  established and are not queued or cleared.
- New post-cutover jobs with usable descriptions are queued; subsequent source
  changes requeue only rows that were already tracked.
- Inactive jobs are skipped by the worker; the existing auto-delisting loop is
  unchanged.

**Verification:**
- `python3 -m pytest -q scraper/tests` ✅ 200 passed.
- Ruff passed for all new/modified Python paths; isolated mypy validation of
  the new worker passed (the wider imported graph retains pre-existing type
  debt).
- Pre-deployment source-only dry-run against a completed Stripe output ✅ 36
  jobs scoped, 0 skill/profile writes; the missing migration was correctly
  reported before rollout.

**Live rollout (2026-07-11):**
- Initial combined migration hit a transactional deadlock between
  `public.jobs` and Supabase Realtime's subscription table; rollback was
  confirmed with 0 async columns and no pgmq schema. Queue bootstrap was split
  into its own migration to remove the reciprocal lock order.
- Applied migrations: `enable_forward_enrichment_queue`,
  `create_forward_enrichment_queue`, and
  `grant_forward_enrichment_queue_service_role` (the last adds the exact queue
  table/sequence privileges required by pgmq 1.5.1 invoker functions).
- Post-migration invariant: all 52,951 historical jobs remained untracked with
  NULL source/status/enriched hashes; the queue started empty.
- Fresh Stripe scrape returned 37 jobs: 35 existing rows were baselined without
  queuing and 2 new jobs (`8053011`, `8031833`) became pending.
- LM Studio loaded local open-weight model `google/gemma-3-4b`; the worker
  completed both jobs, archived both messages after one read, and returned the
  live queue to zero. Both source/enriched hashes match.
- Advisors reported no security lint for the new objects. New indexes reported
  only expected unused-index informational notices immediately after rollout.

**Observed follow-ups:**
- The existing trusted lifecycle audit rejected growth coverage `37/36 =
  1.027778` against a `<= 1.0` constraint after the source upsert had committed.
  No lifecycle/delisting update occurred in that failed step.
- Stripe job `8031833` completed with skill-only enrichment (`Error Messages`,
  `Service Discovery`) but no summary/domain; review before broad scheduling.
- Recurring schedules were not changed. No staging, commit, or push was done.

---

## Session 2026-06-29 — Remote open-weight inference path added

**Objective:** Allow job enrichment to run off the Mac while preserving the no-closed-model policy and the existing OpenAI-compatible architecture.

**Code/config updated:**
- `scraper/config.py`: added `resolve_inference_config()` plus generic `INFERENCE_BASE_URL`, `INFERENCE_API_KEY`, `INFERENCE_MODEL`, and `OPEN_WEIGHT_MODEL_ALLOWLIST` support. Local LM Studio remains the default. Remote endpoints are allowed only when the selected model is explicitly allowlisted.
- `scraper/enricher.py`: switched the enrichment client to the generic inference constants while keeping legacy `LM_STUDIO_*` aliases in config for backward compatibility.
- `scraper/test_llm.py`: refreshed the smoke script to use `INFERENCE_*` and the current JSON-only prompt shape.
- `scraper/.env.example`, `scraper/LM_STUDIO_PRESET.md`, `AGENTS.md`, and `CLAUDE.md`: documented local LM Studio as the default and approved remote OpenAI-compatible open-weight endpoints as the Mac-RAM-friendly path.

**Policy now in effect:**
- Closed/proprietary provider keys such as real OpenAI/Anthropic/Groq/Gemini keys remain disallowed by default.
- Remote inference is permitted only for approved OpenAI-compatible endpoints serving open-weight models, with `OPEN_WEIGHT_MODEL_ALLOWLIST` or `INFERENCE_MODEL_ALLOWLIST` set.

**Verification:**
- `python -m pytest scraper/tests/test_inference_config.py` ✅ 5 passed.
- `python -m pytest scraper/tests/test_inference_config.py scraper/tests/test_enricher_levels.py` ✅ 10 passed.
- `python -m py_compile scraper/config.py scraper/enricher.py scraper/test_llm.py` ✅

---

## Session 2026-06-29 — GCC portal refresh: AmEx, TI, MSD, Vanguard

**Objective:** Save the supplied GCC careers pages in `KNOWN_PORTALS.md` and scrape current jobs without Firecrawl/cloud AI.

**Docs/config updated:**
- `KNOWN_PORTALS.md`: refreshed Vanguard and Texas Instruments human URLs to the supplied pages; American Express was already present at the supplied Oracle CE URL.
- `KNOWN_PORTALS.md`: added MSD under Phenom SSR evidence with the supplied `jobs.msd.com/gb/en/jobs-in-india` page.
- `scraper/company_industries.json`: added `MSD → Pharma`.

**Validation and scrape:**
- `SCRAPE_DIAGNOSTICS_DISABLED=1 python main.py --dry-run --company "<Company>"` ✅ parsed American Express (`oracle`), Texas Instruments (`oracle`), Vanguard Group (`workday`), and MSD (`phenom_api`).
- American Express: `SCRAPE_DIAGNOSTICS_DISABLED=1 python main.py --company "American Express" --skip-enrich --company-cap 1000` ✅ scraped/saved **46** jobs with full JDs.
- Texas Instruments: `SCRAPE_DIAGNOSTICS_DISABLED=1 python main.py --company "Texas Instruments" --skip-enrich --company-cap 1000` ✅ scraped/saved **140** jobs with full JDs.
- Vanguard Group: `SCRAPE_DIAGNOSTICS_DISABLED=1 python main.py --company "Vanguard" --skip-enrich --company-cap 1000` ✅ output has **45** jobs with full JDs; Workday page-flush saved rows before final summary, so final `saved_new` reported 0 while the dated output file contains 45 rows.
- MSD: normal parser currently routes the row to `phenom_api`; a full one-off `phenom_ssr` detail run stalled in detail-page HTTP waits. A listing-only Phenom SSR one-off using existing parser helpers saved **52** India jobs from 7 listing pages after skipping 2 test/no-apply rows.

**Outputs:**
- `All_CSV_Outputs_thru_firecrawl/American_Express/Outputs/2026_06_29/jobs.json`
- `All_CSV_Outputs_thru_firecrawl/Texas_Instruments/Outputs/2026_06_29/jobs.json`
- `All_CSV_Outputs_thru_firecrawl/Vanguard_Group/Outputs/2026_06_29/jobs.json`
- `All_CSV_Outputs_thru_firecrawl/MSD/Outputs/2026_06_29/jobs.json`

**Follow-up needed:**
- Add an approved `portal_reader.py` parser override for MSD so normal `python main.py --company "MSD"` dispatches to `ats=phenom_ssr` instead of `phenom_api`.
- Consider a provider-level guard for Phenom SSR test/no-apply rows and slow detail-page timeouts before enabling full MSD detail scraping.

---

## Session 2026-06-27 — Jindal Stainless Darwinbox route captured

**Objective:** Add the Jindal Stainless careers board to the active portal registry and run the existing scraper path for Myro job-feed coverage.

**Route evidence:**
- Human page: `https://jslhrms.darwinbox.in/ms/candidatev2/main/careers/allJobs`.
- Browser render verified the board title/open-jobs page and showed **107 open jobs**.
- Direct API: `POST https://jslhrms.darwinbox.in/ms/candidateapi/job/alljobs?companyId=main` with body `{"companyId":"main","page":N,"sort_option":"new","limit":50}`.
- This tenant sets a fresh `__cf_bm` cookie but did not expose a `session` cookie during the probe. Direct curl without browser-minted Cloudflare cookie returned 403; browser-minted `__cf_bm` worked with the existing Darwinbox provider when `DARWINBOX_SESSION` was set to a dummy value.

**Docs/config updated:**
- `KNOWN_PORTALS.md`: added `Jindal Stainless` under Darwinbox companies as `✅ CRACKED 2026-06-27`.
- `scraper/company_industries.json`: added `Jindal Stainless → Industrial`.

**Validation and scrape:**
- `python main.py --company "Jindal Stainless" --dry-run` ✅ parsed one active `darwinbox` portal.
- `DARWINBOX_CF_BM=<fresh browser cookie> DARWINBOX_SESSION=not-required-for-jsl SCRAPE_DIAGNOSTICS_DISABLED=1 python main.py --company "Jindal Stainless" --skip-enrich --company-cap 200` ✅
- Initial result under the old gate: **107 raw jobs**, **39 canonical jobs saved** after JD quality gates; 68 listings had empty/too-short JD text.
- Follow-up behavior change: metadata-only jobs are now retained globally with `job_description = "No JD provided on the company page. Matching and skill extraction are unavailable for this role until a job description is published."`; they skip LM Studio enrichment and produce no `job_skills` rows.
- Rerun result after behavior change: **107 canonical jobs saved** — 39 full-JD/matchable rows + 68 metadata-only/applyable rows.
- Output: `All_CSV_Outputs_thru_firecrawl/Jindal_Stainless/Outputs/2026_06_27/jobs.json`.
- `python csv_importer.py --company Jindal --dry-run` ✅ Supabase contract preflight passed; 107 jobs, 229 job_skills rows, 36% enriched, 0 unknown locations.

**Enrichment and Supabase load:**
- LM Studio launched locally on `localhost:1234`; enrichment used local model `google/gemma-3-4b`.
- Targeted Jindal enrichment completed: **39/39 full-JD jobs enriched**, **68 metadata-only jobs skipped**, **0 failures**.
- `python csv_importer.py --company Jindal` ✅ uploaded 107 jobs, 229 job_skills rows, wrote `scrape_diagnostics` and `job_feed_run_audits`, and refreshed the backend analytics snapshot.
- Supabase read-back verification: 107 active `jobs` rows for Jindal Stainless, 39 rows with `main_skills`, 68 metadata-only rows, 229 matching `job_skills` rows, and 0 skill rows attached to metadata-only jobs.

---

## Session 2026-06-13 — Scale-out discovery + board harvester (+33 portals)

**Objective:** spend expiring Firecrawl cloud credits on credit-bound discovery; grow company coverage toward 10k via Tier-1/2 college recruiters. (Question-bank handed to Codex.)

**Built `scraper/discovery/`:**
- `phase0_discover.py` (cloud credits, `cloud_extract`) — 41 college recruiter pages → 1,146 unique companies.
- `resolve_ats.py` + `ats_probes.py` (FREE) — probe Greenhouse/Lever/Ashby/SmartRecruiters; 93 matched, 32 India.
- `harvest_boards.py` (FREE, the 10k lever) — `site:`-collected tokens → probe → India-filter → promote; 29 tokens → 23 net-new India boards (~80% conversion).
- `promote_candidates.py` — token+name dedup vs live portals.

**Promoted (274 → 307 active, +33 net-new India companies), all validated via `dispatch_scrape`:**
- College→resolve: Zinnov, Tekion, WorldQuant, Da Vinci Derivatives, Arista Networks, Refyne, Cars24, NoBroker, Lendingkart, Newton School, Leucine, Intervue, GreyCampus, Carbynetech, AdaptNXT, Safe Security, Auxia, Lyric.
- Harvest: Brillio(80), AHEAD(62), Beghou(54), NETGEAR(22), Atomicwork(21), LinkedIn(18), 6sense(17), Coupa(11), Pebl(8), Meltplan(6), Redpin(4), Resilinc(3), Truecaller(2), SentiLink(2), Binance(1).
- Parked ⚠️ (identity unverified): TSMG, Genesis, Verve.

**Learnings:**
- Dedup MUST be by `(ats, token)` not name — suffixes ("Inc") create false net-new and re-trigger generic-duplicate-masking.
- Slug collisions real (`tcs`→Thornbury, `linkedin`→"LI Test Company") — confirm board name before promoting.
- SmartRecruiters/some Lever surface staffing/aggregator/microtask boards (Squircle, CapitalAim, TMI, Welocalize, Weekday) — quality-gate before promotion.
- `--probe-crack` on a STALE diagnosis (June 4) wasted credits re-discovering 10 already-cracked (June 9-11) companies → regenerate diagnosis first.
- Ashby routing is name-hardcoded in `portal_reader.py` dicts.

Full detail: `docs/handoffs/HANDOFF_scaleout_discovery_20260613.md`. 10k execution sub-tasks (2a/2b/2c): `CLAUDE.md` PENDING WORK §2.

---

## Session 2026-06-11 — NEEDS_CRACK Task 2 closed

**Objective:** Convert the Firecrawl-discovered lead list into durable saved routes or explicit evidence-based dispositions.

**Promoted routes:**
- Sanas → Rippling dehydrated-state parser.
- Premji Invest → Zoho Recruit.
- SBI Mutual Fund → Workline listing JSON + detail HTML.
- Lodha Group → PeopleStrong listing/detail APIs.
- UBS → BrassRing TGNewUI tokenized search.
- BDO India → dynamically discovered Kentico Careers JSON API; cloud map retained only as fallback.
- Simon-Kucher → Cornerstone OnDemand public search/detail APIs.
- Virtusa → explicit Firecrawl Cloud map + cached batch detail scrape.
- Kearney → Yello/Recsolu direct board.

**Merged/closed/parked:**
- EY Parthenon merged into EY India; Strategy& merged into PwC India.
- CK Birla, HCL Software, Mu Sigma, Takshashila and TAS have no automatable public feed.
- Mankind, L.E.K., FinIQ and Ola were verified with no current qualifying India jobs.
- Mondee's Ashby board is expired; TotalEnergies remains France-scoped.
- Avendus, IndusInd, Uber and Walmart moved to the parked list with concrete revisit conditions.

**Verification:**
- Direct provider parser suite and routing suite passed.
- Live probes returned full JDs for Sanas, Premji, SBI MF, UBS, Virtusa and Lodha.
- Simon-Kucher and Kearney direct APIs correctly returned `no_jobs` for India rather than route failures.
- Firecrawl cloud is explicit and cached; `crawl()` remains unavailable.

---

## Session 2026-06-11 — Upskilling question-bank pilot implemented

**Scope:** Built the smallest isolated end-to-end pipeline for the existing
Supabase `skill_questions` table. No job scraping or enrichment behavior was
changed, and the out-of-scope `True_Yodha` directory was not accessed.

**Pilot skills:**
- Machine Learning (`skills.id=2772`)
- Product Strategy (`skills.id=20985`)
- Management Consulting (`skills.id=21871`)
- Financial Accounting (`skills.id=28333`)

**Implementation:**
- Added `scraper/question_bank/` with a dry-run-by-default CLI, four-skill
  manifest, transient JSONL ingestion, local LM Studio normalizer, independent
  verifier prompt, deterministic option shuffling, structural validation,
  exact/near dedupe, resumable copyright-safe JSONL checkpoints, diagnostics,
  and guarded Supabase upserts.
- Added `QUESTION_NORMALIZER_MODEL` and `QUESTION_VERIFIER_MODEL` support. A
  distinct verifier model is preferred; same-model fallback is recorded locally.
- Added source-prose safeguards: candidate text is hashed and discarded, raw
  input lives under git-ignored `scraper/question_bank_inputs/`, and checkpoints
  reject copyright-sensitive field names.
- Existing active rows cannot be downgraded or overwritten; review rows may be
  promoted after successful verification.
- Added design, implementation plan, and operator runbook.

**Verification:**
- `pytest -q scraper/tests/question_bank` → 40 passed.
- Live `python -m question_bank.cli --preflight-only` passed.
- Live table count remained `0`; all four exact `skills.taxonomy_key` values
  resolved.
- LM Studio and local Firecrawl were offline, so no real-model normalization,
  scrape ingestion, or Supabase publish was performed.

**Next operational step:**
- Add provenance-bearing candidate JSONL under
  `scraper/question_bank_inputs/`, load the preferred two local LM Studio
  models, run a dry-run, inspect `review` diagnostics and explanations, then
  publish explicitly.

---

## Session 2026-05-21 — Firecrawl cloud endpoint hunt: high-value product companies

**Scope:** User provided Firecrawl cloud key and approved broader search usage for cracking respectable non-services companies hiring in India. Discovery used Firecrawl search/map/scrape as a microscope, then promoted durable direct routes where plain HTTP/ATS endpoints worked.

**Firecrawl discovery evidence:**
- `Palo Alto Networks`: Firecrawl search/map found India Radancy pages under `jobs.paloaltonetworks.com`; direct listing page exposes `data-total-job-results="104"` and `/en/job/{city}/{slug}/47263/{job_id}` links.
- `CrowdStrike`: Firecrawl search/scrape surfaced `crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers`; Workday CXS route verified directly.
- `PayPal`: Firecrawl scrape surfaced `paypal.eightfold.ai/careers?location=india&domain=paypal.com`; PCSX route verified directly.
- `Nutanix`: Firecrawl search found `careers.nutanix.com` and `nutanix.dejobs.org`; direct RSS feed verified at `https://nutanix.dejobs.org/jobs/feed/rss?location=India`.
- `Rippling`: Firecrawl search found `rippling.com/careers/open-roles`; direct Next.js payload and `ats.rippling.com` detail pages verified directly.
- `Uber`, `Walmart Global Tech`, `HashiCorp`: searched/mapped/scraped within the three-career-page cap; no durable non-Firecrawl ATS route promoted in this pass. HashiCorp now points to IBM careers and was skipped as not matching the non-services/product-company target.

**Direct routes promoted as active (existing providers):**
- `Databricks` — Greenhouse board `databricks`; 80 India jobs with full JDs.
- `MongoDB` — Greenhouse board `mongodb`; 51 India jobs with full JDs.
- `Rubrik` — Greenhouse board `rubrik`; 49 India jobs with full JDs.
- `Zscaler` — Greenhouse board `zscaler`; 112 India jobs with full JDs.
- `Twilio` — Greenhouse board `twilio`; 20 India jobs with full JDs.
- `Okta` — Greenhouse board `okta`; 93 India jobs with full JDs.
- `Pure Storage` — Greenhouse board `purestorage`; 68 India jobs with full JDs.
- `Datadog` — Greenhouse board `datadog`; 12 India jobs with full JDs.
- `Elastic` — Greenhouse board `elastic`; 7 India jobs with full JDs.
- `CrowdStrike` — Workday CXS `https://crowdstrike.wd5.myworkdayjobs.com/wday/cxs/crowdstrike/crowdstrikecareers/jobs`; 66 India jobs with full JDs.
- `PayPal` — PCSX `https://paypal.eightfold.ai/api/pcsx/search?domain=paypal.com&query=&location=india&start=0`; 7 India jobs; detail pages expose JSON-LD JDs.

**Routes captured for provider work before activation:**
- `Snowflake` — Ashby API `https://api.ashbyhq.com/posting-api/job-board/snowflake`; 13 India jobs; full JD in `descriptionPlain` / `descriptionHtml`.
- `Confluent` — Ashby API `https://api.ashbyhq.com/posting-api/job-board/confluent`; 15 India jobs; full JD in `descriptionPlain` / `descriptionHtml`.
- `Rippling` — Next.js listing `__NEXT_DATA__.props.pageProps.jobs.items`; 90 India jobs; detail payload at `ats.rippling.com/rippling/jobs/{uuid}`.
- `Nutanix` — DirectEmployers RSS `https://nutanix.dejobs.org/jobs/feed/rss?location=India`; 82 India jobs with full descriptions.
- `Palo Alto Networks` — Radancy/TalentBrew India page `https://jobs.paloaltonetworks.com/en/location/india-jobs/47263/1269750/2`; 104 India jobs; provider needs section29 markup support before activation.

**Docs/data updated:**
- `KNOWN_PORTALS.md` now records all promoted and captured routes.
- `scraper/company_industries.json` has industry mappings for the new companies.

**Continuation 2026-05-21 — captured routes activated + Perplexity list processed:**
- Activated previously captured provider-needed companies so they run in the next normal scrape without Firecrawl:
  - `Snowflake` and `Confluent` via new `ashby` provider.
  - `Rippling` via new `rippling` Next.js/ATS detail provider.
  - `Nutanix` via new `dejobs_rss` provider.
  - `Palo Alto Networks` via enhanced `talentbrew` provider with section29 listing support.
- Added direct reusable routes for new Perplexity names not already captured:
  - Greenhouse: `Anthropic`, `Postman`, `Zuora`, `Cloudflare`, `Point72`.
  - Workday CXS: `Workday`, `Sprinklr`, `Automation Anywhere`, `Vanguard Group`, `KLA Corporation`, `Carrier Global`.
  - SmartRecruiters: `Western Digital`.
  - PCSX: `Infineon Technologies`, `Lam Research`.
  - SAP Jobs2Web HTML: `Teradyne`, `McDonald's GCC`.
  - Oracle CE: `Vertiv`.
  - Ashby: `UiPath`.
  - Talent500: `Costco Wholesale`.
  - TalentBrew: `Cargill`.
  - Classic iCIMS HTML: `JAGGAER`.
- New/updated providers: `ashby`, `rippling`, `dejobs_rss`, `talent500`, `icims_html`; `greenhouse` now supports content/title India matching for generic-location boards; `talentbrew` now handles Palo Alto section29 cards and Cargill bare result anchors.
- Not promoted: `Qualtrics` currently returns 0 India jobs from its Phenom SSR search; `MathWorks` direct careers search is Akamai 403 from plain HTTP, so no durable non-Firecrawl endpoint was saved in this pass.

**Validation evidence:**
- `PYTHONPATH=scraper python3 scraper/test_direct_endpoint_providers.py` ✅
- `PYTHONPATH=scraper python3 scraper/test_direct_endpoint_routing.py` ✅
- Live `probe_scrape(..., allow_firecrawl=False, max_jobs=3)` succeeded for every new active company above; all returned direct jobs and JDs. Focused McDonald's probe returned 5/5 JDs; focused JAGGAER probe returned 3/3 JDs.

**Continuation 2026-05-22 — second Firecrawl-assisted product-company sweep:**
- Used Firecrawl search as discovery only, then promoted only direct, reusable ATS/API routes that run with `allow_firecrawl=False`.
- Added Greenhouse boards: `Figma`, `GitLab`, `Druva`, `Sumo Logic`, `Netskope`, `HackerRank`, `Observe.ai`, `ClickHouse`, `DAT Freight & Analytics`, `Energy Exemplar`, `AlphaSense India`, `Bluevine India`, `Kaseya`, `NICE`, `Ivalua`, `Abacus Insights`.
- Added Lever boards: `Mindtickle`, `Zeta`, `JumpCloud`, `Zimperium`, `Hevo Data`, `Acceldata`, `Onehouse`.
- Added Ashby boards: `Airwallex`, `Notion`, `Atlan`, `Cartesia`, `Fermi AI`, `Flagright`, `Skylo Technologies`, `Cognition`.
- Added Workday CXS: `ThoughtSpot` (`searchText=India`), `Cohesity` (`locationCountry` India UUID), and `BrowserStack` (`searchText=India`; previously skipped only because no India facet UUID existed).
- Added Oracle CE: `Icertis` via `Jobs-at-Icertis` finder with `location=India`.
- Added `Whatfix` via new `trakstar` provider for Trakstar Hire / Recruiterbox server-rendered listing cards and detail JDs.
- Not promoted in this pass: `Chargebee` (SAP SuccessFactors shell found, no stable direct India listing route yet), `Qualtrics` (0 India jobs at current Phenom SSR endpoint), `MathWorks` (Akamai 403 from plain HTTP), and Conviva-style hits with no current India direct route.
- Validation: JSON sanity checks passed; `PYTHONPATH=scraper python3 scraper/test_direct_endpoint_providers.py` passed; `PYTHONPATH=scraper python3 scraper/test_direct_endpoint_routing.py` passed; live `probe_scrape(..., allow_firecrawl=False, max_jobs=3)` returned jobs for all second-wave active companies. A Whatfix title parsing defect found during live probing was fixed and re-probed successfully.

**Continuation 2026-05-21 — management-recruiter endpoint capture (discovery-only):**
- User provided a new list of FMCG/BFSI/new-age/industrial recruiters and approved Firecrawl cloud use for endpoint discovery.
- Raw Firecrawl evidence saved:
  - `logs/firecrawl_ats_discovery_mgmt_recruiters_20260521_raw.json`
  - `logs/firecrawl_ats_discovery_mgmt_recruiters_20260521_scrapes.json`
  - `logs/firecrawl_ats_discovery_mgmt_recruiters_20260521_validated.json`
  - Plus focused renders for Clear Darwinbox, HDFC Ergo PeopleStrong, and Modelama Adrenalin.
- `KNOWN_PORTALS.md` now has a non-active "DISCOVERY CAPTURE — MANAGEMENT RECRUITER ATS ENDPOINTS" section so future runs do not spend Firecrawl credits rediscovering these hosts.
- Validated capture currently covers 21 findings; these are discovery notes only and are intentionally not parsed as active scraper portals.
- Cracked direct routes ready for promotion with existing/near-existing providers:
  - SAP Jobs2Web: `Asian Paints`, `Bajaj Auto` (BACL board), `Sun Pharma`, `Syngene`; `Tata Consumer Products` also works but needs bare `IN` location-token tolerance in the provider.
  - Workday CXS: `AB InBev`, `Mondelez`, `Kraft Heinz`.
  - Oracle CE: `Kotak Mahindra Bank` (`hcbt.fa.em2.oraclecloud.com`, site `CX_1001`; alternates `CX`, `CX_1`).
  - RippleHire: `Axis Bank` and `Tata Steel` routes confirmed, but the existing provider needs support for `jobVoList` plus `/candidate/candidatejobdetail`.
  - Zoho Recruit SSR: `NPCI` embeds 14 full-JD jobs; provider needs page_id/apply URL generalization beyond ITC.
  - Astro/static/custom: `Juspay` embeds 7 jobs in Astro props; `Waaree Group` renders 3 static roles.
- Parked / not active:
  - `HDFC Ergo` PeopleStrong renders via Firecrawl with full JDs, but the direct API still needs session/payload cracking.
  - `ClearTax` Darwinbox shows 27 jobs through Firecrawl, but direct API is Cloudflare 403 without cookies.
  - `Policybazaar` is static role categories plus resume form, not a discrete ATS feed.
  - `Dabur` was already present as blocked; Firecrawl now renders the page, but it currently shows no jobs.
  - `Amul / GCMMF`, `Lava International`, and `Modelama Exports` need further portal-specific work or are broken.

**Continuation 2026-05-21 — management-recruiter routes promoted into data flow:**
- Promoted 14 discovery captures into active scraper routes and ran low-cap scrape-only probes with `SCRAPE_DIAGNOSTICS_DISABLED=1` so trial counts do not become official Supabase health history.
- New/updated provider behavior:
  - `sap_jobs2web_html` now accepts bare Jobs2Web `IN` location tokens, needed by Tata Consumer Products.
  - `ripplehire` now supports the `jobVoList` listing shape and `/candidate/candidatejobdetail` full-JD fetch, needed by Axis Bank and Tata Steel.
  - `zoho_recruit` now reads `input#jobs` hidden JSON and builds company-specific apply URLs, needed by NPCI.
  - Added `juspay_astro` for Juspay's Astro-embedded job objects.
  - Added `waaree_static` for Waaree's rendered static careers page; no discrete ATS API exists.
- Active rows added:
  - SAP Jobs2Web: `Asian Paints`, `Bajaj Auto`, `Tata Consumer Products`, `Sun Pharma`, `Syngene`.
  - Workday CXS: `AB InBev`, `Mondelez`, `Kraft Heinz`.
  - RippleHire: `Axis Bank`, `Tata Steel`.
  - Oracle CE: `Kotak Mahindra Bank`.
  - Custom/static: `NPCI`, `Juspay`, `Waaree Group`.
- Low-cap outputs with JD coverage were written under `All_CSV_Outputs_thru_firecrawl/*/Outputs/2026_05_21/jobs.json`; all 14 promoted companies produced rows with non-empty `job_description`.
- Still parked and why:
  - `HDFC Ergo`: Firecrawl renders PeopleStrong job pages, but direct API returns session-expired/500 without the correct browser session + payload contract.
  - `ClearTax / Clear`: Darwinbox API endpoint is known, but Cloudflare blocks direct POST without live browser cookies.
  - `Policybazaar`: careers page exposes generic categories and a resume form, not discrete job postings.
  - `Dabur`: page renders now, but currently reports no matching jobs.
  - `Amul / GCMMF`: custom ASP.NET portal requires postback/session handling; direct current-vacancies table is not exposed in static HTML.
  - `Lava International`: Next.js joblist route found, but the listing data API is still hidden in JS bundles.
  - `Modelama Exports`: Adrenalin CandidateMAX renders an internal system error.

## Session 2026-05-13 — Firecrawl-as-microscope direct route promotion

**Scope:** User provided Firecrawl access and clarified that Firecrawl should be used for endpoint discovery, not as the final weekly scrape architecture. Local Docker Firecrawl was running on `localhost:3002`.

**Code/docs updated:**
- Added a 7-day Firecrawl markdown cache in `scraper/firecrawl_client.py`:
  - `scrape()` returns cached markdown before touching the SDK.
  - `batch_scrape()` sends only cache misses and preserves cached hits.
  - `scraper/firecrawl_cache.json` is gitignored.
- Added a cached Firecrawl `map_site()` wrapper and rewired `scraper/discover_endpoints.py` to use `map -> selective scrape` instead of homepage scrape only:
  - Firecrawl cloud discovery now surfaces candidate ATS/job URLs with much lower credit spend.
  - Added `scraper/test_discover_endpoints.py` to lock in map-first behavior.
- Improved Oracle Candidate Experience handling in `scraper/providers/generic_json.py`:
  - finder=`findReqs` routes now paginate with `offset=...` instead of stopping at the first page.
  - Added provider test coverage for Oracle pagination in `scraper/test_direct_endpoint_providers.py`.
- Promoted five Firecrawl/fallback candidates to durable direct routes:
  - **STMicroelectronics**: Eightfold API works with `domain=stmicroelectronics.com`; 4 India jobs in live probe; no Firecrawl needed.
  - **GMR Group**: SAP Jobs2Web HTML route at `https://careers.gmrgroup.in/search/?q=&locationsearch=india&startrow=N`; direct listing/detail parse; no Firecrawl needed.
  - **HP (HPE)**: Phenom SSR route at `https://careers.hpe.com/us/en/search-results?qcountry=India`; `qcountry=IN` returned 0; `qcountry=India` returned 363 India jobs in live probe; no Firecrawl needed.
  - **HiLabs**: Next.js SSR payload route at `https://www.hilabs.com/careers/all-open-positions?location=india`; jobs embedded in `self.__next_f.push`; no Firecrawl needed.
  - **Black Brix**: WordPress Job Openings HTML route at `https://blackbrix.com/job-openings/`; server-rendered listing cards + detail page JDs; no Firecrawl needed.
- Promoted **American Express** off the broken Eightfold assumption and onto a durable Oracle Candidate Experience route:
  - careers shell: `https://careers.americanexpress.com/en/sites/CX_1/jobs`
  - API host: `egug.fa.us2.oraclecloud.com`
  - finder route: `recruitingCEJobRequisitions?finder=findReqs`
  - India facet: `locationsFacet -> India (Id=300000000228786)`
- Updated `KNOWN_PORTALS.md` and `scraper/portal_reader.py` so these routes are parsed as direct providers.
- Added cache tests in `scraper/test_firecrawl_cache.py` and direct routing assertions in `scraper/test_direct_endpoint_routing.py`.
- Added direct-provider parser coverage for `HiLabs` and `Black Brix` in `scraper/test_direct_endpoint_providers.py`.

**Validation evidence:**
- Targeted runs used `OUTPUT_BASE=/Users/incognito/firecrawl_Supabase/_local/test_outputs` to keep generated outputs inside the repo-local ignored folder.
- `python3 main.py --company "STMicroelectronics" --skip-enrich --company-cap 3` -> 3 saved; JD lengths 4,646-6,168 chars.
- `python3 main.py --company "GMR Group" --skip-enrich --company-cap 3` -> 3 saved; JD lengths 2,815-3,503 chars.
- `python3 main.py --company "HP (HPE)" --skip-enrich --company-cap 3` -> 3 saved; JD lengths 5,836-9,520 chars.
- `python3 main.py --company "HiLabs" --skip-enrich --company-cap 3` -> 3 saved; JD lengths 2,893-3,266 chars.
- `python3 main.py --company "Black Brix" --skip-enrich --company-cap 3` -> 1 saved; JD length 2,431 chars.
- `python3 main.py --company "American Express" --skip-enrich --company-cap 5` -> 5 saved; India locations included Bengaluru/Gurugram/Chennai; JD lengths 790-1,015 chars.

- Promoted **Oracle** off the broken Workday assumption and onto durable Oracle CE route:
  - Oracle was incorrectly listed as Workday (wd1/OracleJobs, CF-blocked) — XHR cURL confirmed Oracle CE
  - API host: `eeho.fa.us2.oraclecloud.com`; siteNumber `CX_45001`; `location=India` text param (no numeric locationId)
  - Added `_ORACLE_ENDPOINT_OVERRIDES` in `portal_reader.py`; `oracle_nested=True`; 5+ India jobs verified live
  - Moved from WORKDAY to ORACLE HCM section in `KNOWN_PORTALS.md`
- **Bank of America** — provided URL `careers.bankofamerica.com/en/jobs/` tested → 404; Workday entry stands unchanged; needs correct URL from browser XHR
- **Godrej Consumer Products** — `careers.godrejcp.com` confirmed DNS-dead; real portal at `careers.godrejindustries.com` (Phenom SSR); `utm_medium=phenom-feeds` confirmed; India jobs visible at `/in/en/search-results?qcountry=India`; needs PCSX/Phenom probe to crack

**Still not promoted:**
- Oliver Wyman Phenom SSR returned India listings, but full descriptions appear behind Workday-blocked apply URLs; keep as Firecrawl/further-investigation until full JD extraction is solved.
- Mondee/Ashby `jobs.ashbyhq.com/mondee` is reachable, but `api.ashbyhq.com/posting-api/job-board/mondee` returned 404; slug/API still needs discovery.
- Morgan Stanley, Micron, and Qualcomm Eightfold APIs returned `403 Not authorized for PCSX`.
- Meta Firecrawl cloud scrape can read listing content at `https://www.metacareers.com/jobs/?locations[0]=India`, but a stable direct JSON/GraphQL route still needs XHR capture.
- Vehere Interactive is still anti-bot from direct requests (Cloudflare 403), but Firecrawl cloud surfaced durable detail URLs under `/positions/...`; promote to a dedicated fallback provider if direct HTML stays blocked.

**Verification:**
- `python3 test_firecrawl_cache.py` ✅
- `python3 test_discover_endpoints.py` ✅
- `python3 test_direct_endpoint_routing.py` ✅
- `python3 test_direct_endpoint_providers.py` ✅

## Session 2026-05-08 — Direct ATS/API endpoint promotion

**Scope:** Promoted high-value Firecrawl/Docker-discovered companies to direct API/ATS/HTML routes so Firecrawl is no longer needed for extraction.

**Code updated:**
- Added `scraper/providers/tata_elxsi.py` for Tata Elxsi's server-rendered careers pages:
  - listing cards at `https://www.tataelxsi.com/careers/job-openings?page=N`
  - full JD and Ramco apply URL from each detail page
- Added `scraper/providers/vector_consulting.py` for Vector Consulting Group's Next.js SSR payload:
  - jobs embedded in `__NEXT_DATA__.props.pageProps.jobsData.dataset`
  - full JD assembled from `description` and sectioned `body`
- Added `scraper/providers/deshaw_india.py` for D. E. Shaw India's Next.js SSR payload:
  - public jobs embedded in `__NEXT_DATA__.props.pageProps.regularJobs`
  - full JD assembled from `jobDescription` fields, including string/list variants
  - apply URL through `/recruit/jobs/Ads/Link/{jobUrl}`
- Added `scraper/providers/cognizant_xml.py` for Cognizant's public XML feed (`/india-en/jobs/xml/?rss=true`) with full JD descriptions and India filtering.
- Added `scraper/providers/apple_jobs.py` for Apple's JSON careers API:
  - `POST https://jobs.apple.com/api/v1/search`
  - `GET https://jobs.apple.com/api/v1/jobDetails/{positionId}`
- Extended `scraper/providers/talentbrew.py` to parse Radancy/TalentBrew search-result cards used by Citibank and AstraZeneca.
- Routed direct providers in `scraper/portal_reader.py`:
  - Apple -> `apple_jobs`
  - Cognizant -> `cognizant_xml`
  - Citibank -> `talentbrew`
  - AstraZeneca -> `talentbrew`
  - Eli Lilly -> `phenom_ssr`
  - Cisco -> `phenom_ssr`
  - BCG -> `phenom_ssr`
  - LTIMindtree -> `sap_jobs2web_html`
  - Tata Elxsi -> `tata_elxsi`
  - Vector Consulting Group -> `vector_consulting`
  - DE Shaw -> `deshaw_india`
- `writer.to_canonical()` now emits every field in `schema.CANONICAL_FIELDS`, including the current jobs-table location/enrichment columns with safe defaults.

**Docs/metadata updated:**
- `KNOWN_PORTALS.md` now records the direct endpoints and ATS routes for Apple, Cognizant, Citibank, BCG, AstraZeneca, Eli Lilly, LTIMindtree, Tata Elxsi, Vector Consulting Group, and DE Shaw.
- `scraper/schema.py` ATS comment updated with `apple_jobs`, `cognizant_xml`, `tata_elxsi`, `vector_consulting`, and `deshaw_india`.

**Validation evidence:**
- Live targeted runs succeeded for Cognizant, Citibank, AstraZeneca, Eli Lilly, Cisco, BCG, and LTIMindtree with `--skip-enrich --company-cap 3`; each route used direct providers and returned jobs with JDs.
- Direct Apple probe returned 3 India jobs with full detail JDs through Apple's JSON API.
- Direct registry probes with Firecrawl disabled succeeded for Tata Elxsi, Vector Consulting Group, and DE Shaw:
  - Tata Elxsi: 3 capped India jobs with JDs.
  - Vector Consulting Group: 2 current India jobs with JDs.
  - DE Shaw: 3 capped India jobs with JDs from a 76-role public payload.
- Canonical shape validation confirmed each promoted provider maps through `writer.to_canonical()` to exactly `CANONICAL_FIELDS`.

**Verification:**
- `python3 test_writer_canonical.py` ✅
- `python3 test_direct_endpoint_providers.py` ✅
- `python3 test_direct_endpoint_routing.py` ✅
- `python3 -m py_compile providers/deshaw_india.py providers/tata_elxsi.py providers/vector_consulting.py providers/registry.py portal_reader.py schema.py test_direct_endpoint_providers.py test_direct_endpoint_routing.py` ✅

## Session 2026-05-08 — Docker-backed JS/Fallback inventory pass

**Scope:** User started Docker/Firecrawl locally, so the previous direct-provider inventory backlog was re-probed through the local Firecrawl container only (`FIRECRAWL_URL=http://localhost:3002`, `FIRECRAWL_API_KEY=local`).

**Code/docs updated:**
- `scraper/portal_inventory.py` now supports targeted re-probes from a prior JSON report:
  - `--from-inventory <json>` selects exact companies from a previous inventory.
  - `--probe-states skipped_needs_docker,fallback_needs_docker --needs-docker-only` focuses only the Docker-needed queue.
  - Source row positions are preserved so batch reports merge cleanly back into the all-portal report, even when older reports do not contain `inventory_index`.
- Inventory reports now add `sample_quality` and `quality_flags` so Firecrawl page-chrome hits are not treated as clean hiring evidence. Current flags include company-name-only titles, weak button/navigation titles, anchor/listing URLs, missing JDs, and likely `IN` as US state false positives.
- Documented targeted Docker re-probe commands in `CLAUDE.md` and `.claude/commands/scraper.md`.

**Reports generated:**
- Docker batch reports covered all 80 previously Docker-needed rows from `logs/portal_inventory_20260508_143513_180142.json`.
- Final merged report: `logs/portal_inventory_20260508_174834_733158.{json,md}`.
- Final merged summary: 175 active portals, 105 sampled as hiring, 66 no-open-jobs samples, 2 blocked, 2 config errors.
- Quality summary: 91 usable samples, 14 hiring samples marked `needs_review`, 70 no-usable-sample rows.

**Usable Docker/fallback hits from the prior queue:**
- Synopsys — 2 India jobs with JDs.
- Qualcomm — 1 India job with JD.
- Citibank — 3 India jobs with JDs.
- Apple — 2 India jobs with JDs.
- Eli Lilly — 2 India jobs with JDs.
- Cisco — 3 India jobs with JDs.
- LTIMindtree — 2 India jobs with JDs.
- Black Brix — 1 India job with JD.

**Needs review / direct-provider follow-up after current promotions:**
- Google, Microsoft, Genpact, EY Parthenon, PwC India, CK Birla Group, and HiLabs returned job-like content but weak titles/page text; use dedicated direct routes before promoting.
- L'Oréal returned `IN`-as-Indiana false positives (`Greenwood`, `Plainfield`) and should not be trusted through the current generic Firecrawl path.
- Meta and Virtusa remained blocked in Docker probing.

**Verification:**
- `python3 test_portal_inventory.py` ✅
- `python3 -m py_compile portal_inventory.py test_portal_inventory.py` ✅
- `python3 portal_inventory.py --merge <direct-report> <docker-batches...>` ✅

## Session 2026-05-07 — Known portals inventory and hiring probe

**Scope:** Added a repeatable inventory mechanism for `KNOWN_PORTALS.md` so route health and current hiring samples can be generated without a bespoke spreadsheet.

**Code/docs updated:**
- Added `scraper/portal_inventory.py`:
  - `--no-probe` writes route/status inventory only.
  - `--probe` samples direct providers only.
  - `--probe --include-js` intentionally includes Firecrawl/JS routes and should be run only when Docker/Firecrawl is available.
  - `--limit` + `--offset` support controlled batches.
- Added `scraper/test_portal_inventory.py` for no-network tests.
- Added `providers.registry.probe_scrape(...)` so inventory probes do not silently fall through to Firecrawl unless explicitly allowed.
- Documented commands in `CLAUDE.md` and `.claude/commands/scraper.md`.
- Probe side effects persisted useful fast paths in registries: Workday India UUIDs for Accenture/Chanel/Fidelity/Novartis/Salesforce/Sanofi/Wells Fargo/State Street/DBS Bank, and generic JSON item keys for Amazon/Atlassian.

**Reports generated:**
- Metadata-only: `logs/portal_inventory_20260508_141855_602506.{json,md}` — 175 active portals parsed, 54 requiring Docker/Firecrawl.
- Direct probe batches: offsets `0,25,50,75,100,125,150` with `--sample-size 3 --limit 25`, direct providers only.
- Merged direct-probe report: `logs/portal_inventory_20260508_143513_180142.{json,md}` — 175 active portals, 83 sampled as hiring, 80 requiring Docker/Firecrawl, 10 no-open-jobs samples, 2 config errors.

**Portal status corrected:**
- BlackBerry promoted from `🟡 India UUID TBD` to `✅ CRACKED 2026-05-07`; targeted run scraped 5 raw jobs with 5/5 JDs using the Workday UUID already present in `workday_registry.json`.

**Quality fix:**
- `scraper/providers/talentbrew.py`: tightened ADP listing link detection so navigation/filter links no longer appear as fake jobs. ADP probe now returns real job titles, ADP apply URLs, and full JDs.
- ADP targeted run: `python3 main.py --company "ADP" --skip-enrich --company-cap 3` -> `3 raw`, `3 saved`.

**Verification:**
- `python3 -m py_compile portal_inventory.py test_portal_inventory.py providers/registry.py` ✅
- `python3 test_portal_inventory.py` ✅
- `python3 portal_inventory.py --no-probe` ✅
- `python3 portal_inventory.py --probe --sample-size 3 --limit 25` ✅
- `python3 portal_inventory.py --probe --sample-size 3 --limit 25 --offset 25` ✅
- `python3 portal_inventory.py --merge <batch-json...>` ✅

## Session 2026-05-07 — Market Data V1 route recovery + provider promotion

**Scope:** Captured reusable company route intelligence from `Market Data_V1_of_Scrapers/` and promoted verified routes into the active provider-based scraper.

**Routes promoted:**
- WESCO: Oracle HCM finder route recovered from legacy `run_wesco.py` (`eklm.fa.us2.oraclecloud.com`, site `CX`, India location ID `300000000302954`). `generic_json` now preserves Oracle site numbers in candidate job URLs (`/sites/CX/job/{Id}`).
- CMA CGM: old legacy `country=India` Jobs2Web URL was stale and returned global/US false positives. Correct direct route is `optionsFacetsDD_country=IN`; routed to `ats=sap_jobs2web_html`.
- Volvo Group: routed India Jobs2Web listing to `ats=sap_jobs2web_html`; direct table parse + per-job detail JD extraction.
- Michelin: added `scraper/providers/michelin_astro.py` for server-rendered Astro/CXF listings on `jobs.michelin.in`; provider applies India criteria JSON, paginates `page=N`, and fetches full JDs from detail pages.

**Validation evidence:**
- WESCO targeted run: `python3 main.py --company "WESCO" --skip-enrich --company-cap 30` -> `7 raw`, `7 saved`.
- Direct provider smoke test: CMA CGM -> `4` India jobs, Volvo Group -> `27` India jobs, Michelin -> `19` India jobs; sample JD lengths were all non-empty.
- Dry-run routing confirmed:
  - `CMA CGM [sap_jobs2web_html]`
  - `Volvo Group [sap_jobs2web_html]`
  - `Michelin [michelin_astro]`

**Docs/metadata updated:**
- `KNOWN_PORTALS.md`: WESCO, CMA CGM, Volvo Group, and Michelin marked `✅ CRACKED 2026-05-07` with route notes.
- `scraper/company_industries.json`: WESCO industry mapping added.
- `scraper/LEGACY_MARKET_DATA_V1_AUDIT.md`: 53-company legacy inventory captured with active-system status.

**Rejected stale signal:**
- Microsoft legacy GCS endpoint (`gcsservices.careers.microsoft.com/search/api/v1/search?...loc=India`) is stale: certificate hostname mismatch and `curl -k` returns an Azure test 404 page, not job JSON. Kept as JS-required until fresh XHR discovery.

**Operational fix:**
- `main.py` run IDs/log/summary filenames now include microseconds to avoid checkpoint temp-file collisions when multiple quick validation runs start in the same second.

## Session 2026-05-02 — Procter & Gamble cracked via Phenom SSR embed

**Scope:** Parser + portal docs update for P&G direct route (no Firecrawl fallback).

**Validation evidence:**
- `GET https://www.pgcareers.com/in/en/search-results?m=3&location=MUMBAI%2C%20India` returns embedded `phApp.ddo.eagerLoadRefineSearch.data.jobs`.
- Same page embeds fields needed by scraper: `jobSeqNo`, `jobId/reqId`, `title`, `location/country`, `applyUrl`, `descriptionTeaser`.
- Country aggregation in snapshot confirms India results are available; global India facet count observed as `23`.

**Code/docs updated:**
- `scraper/portal_reader.py`: PHENOM section override added for `Procter & Gamble` → `ats=phenom_ssr`, endpoint `https://www.pgcareers.com/in/en/search-results?qcountry=India`.
- `KNOWN_PORTALS.md`: P&G row updated to `✅ CRACKED 2026-05-02` with route details.

**Targeted run result:**
- Command: `python3 scraper/main.py --company \"Procter & Gamble\" --skip-enrich --company-cap 200`
- Result: `23 raw` scraped, `23` saved.
- Output: `All_CSV_Outputs_thru_firecrawl/Procter_Gamble/Outputs/2026_05_02/jobs.json`

---

## Session 2026-05-02 — H&M cracked via WordPress jobs API

**Scope:** Added direct provider route for H&M (no manual DevTools cURL required at runtime).

**Validation evidence:**
- Careers URL observed: `https://career.hm.com/in-en/search/?l=cou%3Ain`
- Jobs endpoint confirmed: `POST https://career.hm.com/in-en/wp-json/hm/v1/sr/jobs/search?_locale=user`
- India payload filter confirmed: `{"locations":["cou:in"],"page":N}`
- API response contains `jobs[]` + `total`; snapshot observed `111` India jobs.

**Code/docs updated:**
- Added provider: `scraper/providers/hm_wp_jobs.py`
- Registered provider: `scraper/providers/registry.py` (`hm_wp_jobs`)
- Parser mapping: `scraper/portal_reader.py` (`H&M -> ats=hm_wp_jobs`, `india_only=True`)
- Schema comment updated: `scraper/schema.py`
- Industry mapping updated: `scraper/company_industries.json` (`"H&M": "Retail"`)
- Portal registry updated: `KNOWN_PORTALS.md` (OTHER PLATFORMS row + tracker entry)
- Handoff updated: `CODEX_HANDOFF.md` (progress table + validation signal)

**Targeted run result:**
- Command: `python main.py --company "H&M" --skip-enrich --company-cap 300`
- Result: `111 raw` scraped, `111` saved.
- Output: `All_CSV_Outputs_thru_firecrawl/HM/Outputs/2026_05_02/jobs.json`
- Run summary: `logs/run_summary_20260502_132049.json`

---

## Session 2026-05-02 — Nykaa cracked via Skima careers SSR HTML

**Scope:** Code + registry + docs update for direct Nykaa route (no Firecrawl fallback).

**Validation evidence:**
- `GET https://careers.nykaa.com/` returns server-rendered job listing HTML with UUID links (no auth/cookies).
- Pagination confirmed via `data-last-page` + query param `?page=N` (snapshot: 2 pages, 11 jobs).
- Job detail pages (`/{job_uuid}`) return full JD in `.job-description-panel`.

**Code/docs updated:**
- Added provider: `scraper/providers/skima_careers.py` (listing + pagination + detail scraping).
- Routed Nykaa to provider: `portal_reader.py` (`Nykaa -> ats=skima_careers`, `india_only=True`).
- Registered provider in `scraper/providers/registry.py`.
- `KNOWN_PORTALS.md`: Nykaa changed to `✅ CRACKED 2026-05-02` with Skima route notes.

**Targeted run result:**
- Command: `python3 scraper/main.py --company \"Nykaa\" --skip-enrich --company-cap 200`
- Result: `11 raw` scraped, `11` saved.
- Output: `All_CSV_Outputs_thru_firecrawl/Nykaa/Outputs/2026_05_02/jobs.json`

---

## Session 2026-05-02 — Atlassian route confirmed from browser cURL + bundle inspection

**Scope:** Parser + documentation update for direct JSON route.

**Validation evidence:**
- `https://www.atlassian.com/company/careers/all-jobs?team=Interns%2CGraduates&location=&search=` resolves as JS-rendered careers shell.
- Bundled careers code points production listings to `GET /endpoint/careers/listings`.
- `GET https://www.atlassian.com/endpoint/careers/listings` returns JSON array (82 jobs in snapshot).
- Job objects include `id`, `title`, `locations`, `overview`, `responsibilities`, `qualifications`, `applyUrl`.

**Code/docs updated:**
- `scraper/providers/generic_json.py`: added support for `locations[]`, sectioned JD fields, and `applyUrl` mapping.
- `KNOWN_PORTALS.md`: Atlassian moved from broken Greenhouse row to `CUSTOM / PROPRIETARY APIs` as `✅ CRACKED 2026-05-02`.
- `KNOWN_PORTALS.md`: Atlassian removed from `SCRAPE_QUEUE`.
- `AGENTS.md` and `CODEX_HANDOFF.md`: updated with Atlassian validation notes.

---

## Session 2026-05-02 — Cisco route confirmed from browser cURL

**Scope:** Documentation + handoff status update (no scraper code change in this session).

**Validation evidence:**
- `https://careers.cisco.com/global/en/search-results?qcountry=India` returns embedded `phApp.ddo.eagerLoadRefineSearch` payload.
- India filter present in payload: `ui_selections.country=["India"]`; country aggregation reports `India=226`.
- Pagination confirmed with `from=10&s=1` (10 jobs/page payload).
- Job objects include `jobId/reqId`, `title`, `location`, `descriptionTeaser`, `applyUrl`.

**Docs updated:**
- `KNOWN_PORTALS.md`: Cisco changed from `🔍 needs investigation` to `✅ cracked 2026-05-02`; queue item removed.
- `AGENTS.md`: new run-history entry for Cisco crack confirmation.
- `CODEX_HANDOFF.md`: progress table and validation notes updated with Cisco route.

---

## Session 2026-05-02 — Tech Mahindra route confirmed

**Scope:** Documentation + handoff status update (no scraper code change in this session).

**Validation evidence:**
- `https://www.techmahindra.com/en-in/careers/` is 404.
- `https://www.techmahindra.com/careers/` is live and links out to `https://careers.techmahindra.com/`.
- `https://careers.techmahindra.com/` returns listing cards with direct `JobDetails.aspx?JobCode=...` links.
- `JobDetails.aspx` pages include full JD sections and apply controls; suitable for direct scrape + India filter by location text.

**Docs updated:**
- `KNOWN_PORTALS.md`: Tech Mahindra moved from broken/url-changed to `✅ cracked 2026-05-02`.
- `KNOWN_PORTALS.md`: removed Tech Mahindra from `SCRAPE_QUEUE`.
- `AGENTS.md`: run-history entry added for Tech Mahindra crack.

---

## Session 2026-04-27 — Global scope controls + lifecycle/versioning + diagnostics

**Code changes:**
- `scraper/main.py`
  - Added `--scope india|global` (default `india`) and `--global-cap` (default `2000`).
  - Added unresolved-company diagnostics in run summary JSON (`no_jobs_returned`, scrape/save exceptions).
  - Added best-effort Supabase diagnostics sink (`scrape_diagnostics` table).
- `scraper/scrapers.py`
  - Removed placeholder fallback rows from Firecrawl paths (`scrape_validate`, `scrape_extract` now return `[]` when no links are parseable).
  - Made provider filters scope-aware so `india_only` can be forced by run scope.
  - Added adapter-level cap wiring for global mode (`greenhouse`, `lever`, `phenom_api`, generic JSON parse path).
- `csv_importer.py`
  - Default quality gate changed to `--min-score 0` to keep all valid non-placeholder jobs.
  - Added mixed-schema normalization support (legacy + canonical).
  - Added lifecycle/versioning logic:
    - `first_seen`, `last_seen`, `is_active`, `change_fingerprint`.
    - Meaningful-change version events (`insert` / `update` / `deactivate`) in `job_versions`.
    - **Inactive after 1 miss** (if a previously active job is absent in a successful company run).
- `.archon/workflows/scraper-weekly-run.yaml`
  - Switched cadence to weekly.
  - Made dry-run and scrape phases global-scope by default.
- New docs/scripts:
  - `scraper/ARCHITECTURE_V3_MODULAR_PLAN.md`
  - `scraper/sql/create_scrape_diagnostics.sql`
  - `scraper/sql/create_job_lifecycle.sql`
  - `scraper/sql/create_jobs_india_view.sql`

**Data quality impact (2026-04-27):**
- Placeholder cleanup completed (historic Firecrawl placeholder rows removed from Supabase).
- Import path now preserves real low-count companies instead of forcing synthetic 1-row placeholders.
- Confirmed global-scope smoke test: `Thoughtworks` returned 46 jobs in one company run.

**Infrastructure status (confirmed by user):**
- All 3 SQL scripts executed successfully on Supabase:
  - `create_scrape_diagnostics.sql`
  - `create_job_lifecycle.sql`
  - `create_jobs_india_view.sql`

**Operating model decision (locked):**
- Weekly full run in **global** scope.
- On-demand full/targeted dumps anytime the scraper agent is called.
- India dataset is derived downstream from global via `jobs_india` view/filter.
- Global per-company cap: `2000`.
- Versioning tracks **meaningful changes only** (`job_title`, `job_description`, `location`, `apply_url`).

---

## Session 2026-04-19 — Portal expansion + JD fix

**Code changes:**
- `scraper/config.py` — `WORKDAY_JD_FETCH_LIMIT` default raised 200→500. Was silently capping JD fetch for all large Workday companies (Accenture 500 jobs had only 200 JDs, State Street 351→200, DBS 285→200).
- `scraper/company_registry.py` — Added 4 new standard Workday tenants (3M, NXP, Autodesk, DXC) with `locationCountry` facet. Added Roche (`locations` facet). Added Barclays (12 India office UUIDs) and Maersk (26 India office UUIDs) using `india_uuids` list support.
- `scraper/scrapers.py` — `india_uuids` list support: `reg.get('india_uuids') or [reg['india_uuid']]` allows multi-UUID facet queries for tenants with per-office location facets (Barclays, Maersk).
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
- Publicis Sapient → SmartRecruiters returns 0 for all IDs tried; careers site is SPA with unknown ATS
- ING Bank → no India locations in ICSGBLCOR portal
- Roche → only 1 India job (not worth scraping)

**Unresolved:**
- Societe Generale: SmartRecruiters `SocieteGenerale4` — `country=in` returns 0; try location text filter
- Storable: Greenhouse board confirmed but India jobs TBD
- 74 companies returning 1 Firecrawl blob — need direct API scrapers

---

## Session 2026-04-17 — Phase 1 full scrape + RAG enrichment pipeline

**Code changes this session:**
- `scraper/rag_skills.py` (NEW) — IDF-weighted keyword inverted index over 35,108 Lightcast L3 skills. `retrieve(text, k=40)` returns top-k canonical skill names via token overlap scoring (IDF-weighted + length-normalized). Builds in <0.5s at import. Used in enricher to inject constrained vocabulary into every LLM prompt.
- `scraper/enricher.py` — RAG-augmented: `enrich_job()` calls `_retrieve_skills(title + jd[:800], k=40)`, injects into `_ENRICH_PROMPT` as "Approved skill vocabulary — choose ONLY from this list". System prompt moved to LM Studio GUI for KV-cache reuse. `max_tokens` 300→150. JD truncation 2000→1500 chars.
- `scraper/main.py` — `enrich_only_run()` parallelised with `ThreadPoolExecutor(max_workers=ENRICH_WORKERS)`.
- `scraper/config.py` — added `ENRICH_WORKERS = int(os.getenv("ENRICH_WORKERS", "4"))`.
- `scraper/.env` — added `ENRICH_WORKERS=4`; dual model presets (`MODEL_SPEED=fast` → `google/gemma-3-4b`, `MODEL_SPEED=quality` → `deepseek-r1-0528-qwen3-8b-mlx`).

**LM Studio GUI preset (`mirror-cv-fast`):**
- System Prompt: "You are a precise job data extractor. Read the job title and description and return a single valid JSON object. No explanation, no markdown, no extra text."
- Limit Response Length: 150 tokens
- Temperature: 0.0

**Phase 1 run results:**
- `python main.py --skip-enrich` completed. 94 output files, 2,376 total jobs, 1,730 with `job_description`.
- Output path: `/Users/incognito/firecrawl_Supabase/All_CSV_Outputs_thru_firecrawl/` (set via `OUTPUT_BASE` in .env)

---

## Session 2026-04-16 — Taxonomy + Workflow setup

**Code changes:**
- `scraper/lightcast_skills_taxonomy.json` — created; full Lightcast Open Skills L1→L2→L3 hierarchy (31 L1, 442 L2, 35,108 L3 skills)
- `scraper/lightcast_skills_flat.csv` — flat table (l1_category, l2_subcategory, l3_skill_name, l3_skill_id, 35,108 rows)
- `scraper/enricher.py` — LLM skills validated against Lightcast L3 taxonomy. Three match strategies: exact, stripped-parenthetical ("Docker" → "Docker (Software)"), fuzzy (cutoff=0.88, min 8 chars)
- `.archon/workflows/scraper-weekly-run.yaml` — created; 7-node DAG: check-docker + check-lm + test-portals (parallel) → scrape → enrich → upload → summarize

**Workflow run notes:**
- `check-lm` failed as expected (LM Studio was off); `scrape` completed in 18 min but scraped 0 new data because `--resume` was mistakenly left in the workflow command — all 44 companies already had output from 2026-04-12 and were skipped.
- **Fixed**: removed `--resume` from the `scrape` node command.

**State of All_CSV_Outputs_thru_firecrawl/ at session close (44 companies, last scraped 2026-04-12):**
Accenture (500), Sanofi (596), Novartis (592), Wells Fargo (224), Salesforce (168), Continental (99), Airbus (144), Stripe (66), Volvo Group (43), Shell (32), ServiceNow (35), Fidelity (29), Amazon (81), Michelin (21), LDC (20), WESCO (20), AstraZeneca (25), Schneider Electric (126), Philips (136), Eli Lilly (10), Dell (18), Stellantis (18)
Low/broken: Engie (2), Baker Hughes (2), Morgan Stanley (2), AmEx (3), Google (3), Infosys (3), TCS (3), Wipro (3), Cognizant (0), Alstom (1), Chanel (1), Apple (2), CNHI (3), CMA CGM (0), TotalEnergies (0), Synopsys (0), Mastercard (0), Microsoft (0), Volkswagen (5/excluded)

---

## Session 2026-04-11 — Phase 1 + Phase 2 COMPLETE

**Code fixes:**
- Workday headers → browser-like UA + Accept-Language + dynamic Referer
- Workday facet param → `_find_india_id()` returns `(facet_param, uuid)` tuple (tenant-specific names)
- Workday Cloudflare 303 → automatic Firecrawl fallback using `careers_url`
- `--skip-enrich` suppresses LLM in Firecrawl path; saves `firecrawl_raw.md` staging file
- `--enrich-only` processes all `firecrawl_raw.md` staging files → extract + enrich
- `portal_reader.py` passes `careers_url` field for Workday portals
- No-India-Jobs companies consolidated into excluded block in KNOWN_PORTALS.md

**25 companies with enriched jobs.json:**
Accenture (8240), Amazon (92), Wells Fargo (235), Salesforce (169), Continental (99),
Sanofi (93), Stripe (66), ServiceNow (35), Airbus (40), Fidelity (30), Shell (27),
LDC (20), STMicro (3), Morgan Stanley (3), AmEx (3), Chanel (1),
Eli Lilly (3), Google (3), Infosys (3), L'Oréal (3), TCS (3), Wipro (3),
Cognizant (2), Stellantis (3), AstraZeneca (3)

---

## Session 2026-04-10 — First full run (interrupted)

- Ran `python main.py` (full run, all portals).
- Force-closed mid-way due to memory pressure from running Docker + LM Studio simultaneously.
- 15 companies scraped before interruption: Accenture, Airbus, Amazon, American Express, Chanel, Continental, Fidelity Investments, LDC (Louis Dreyfus), Morgan Stanley, STMicroelectronics, Sanofi, ServiceNow, Shell, Stripe, Wells Fargo.
- Output location: `All_CSV_Outputs/{Company}/Outputs/YYYY_MM_DD/jobs.json` + `jobs.csv`

---

## DUMP 2 ANALYSIS — Root Cause Diagnosis (2026-04-11)

**Context:** Dump 2 contained 2,774 jobs from 25 companies with severe data quality issues.

### Problem 1 — Workday: zero raw_jd_text
`scrapers.py:76` reads `p.get('jobDescription', '')` from the listing endpoint `/wday/cxs/{tenant}/{site}/jobs`. That endpoint never returns full JD — it returns only metadata. Full JD lives at the individual job detail endpoint: `GET https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs/{externalPath}`.
**Fix applied:** second-pass fetch per job's `externalPath`. Now 169/169 JDs fetched.

### Problem 2 — Accenture: 8,240 jobs scraped, 1,841 unique (6,399 duplicates)
- India filter matched broader facet than just India.
- Workday offset-based pagination returns overlapping result sets on Accenture's tenant.
**Fix applied:** deduplicate by `jobReqId` during pagination loop; break early if >50% already-seen IDs.

### Problem 3 — Firecrawl companies: exactly 3 jobs each
`main.py:109` sliced Firecrawl output to `pages[:5]`; LM Studio extracted first 3-5 visible jobs and stopped.
**Fix applied:** removed `pages[:5]` slice; use all pages. Longer-term: direct ATS APIs where possible.

### Problem 4 — skills_required, seniority_level all empty
Enrichment skipped because `raw_jd_text` was empty (Problem 1). Resolved by fixing Problem 1.

### BUILD CHUNK 1 — Audit + fixes (COMPLETED 2026-04-16)

**Dry-run results:** 106 portals parsed (43 direct API, 63 Firecrawl/js-required).

**Spot-check (5-job test per ATS type):**
| ATS | Company | Jobs | JD populated | Location | Verdict |
|-----|---------|------|-------------|----------|---------|
| Greenhouse | Stripe | 69 | ✅ 3-5k chars | ❌ Empty | Fix location mapping |
| SmartRecruiters | ServiceNow | 29 | ✅ 2-3k chars | ✅ | Working |
| Custom JSON | Amazon | 93 | ✅ 1-3k chars | ❌ None | Fix location mapping |
| Workday | Salesforce | 169 | ❌ 0 chars | ❌ None | JD fetch broken — critical |
| Phenom REST | Schneider Electric | 10 | ✅ 6-12k chars | ❌ None | Fix location mapping |

**Fixes applied:**
1. Workday JD fetch — `cxs_base` was missing `career_site` segment. Fixed in `scrapers.py:_fetch_workday_jds()`.
2. Location empty — `writer.py:to_canonical()` now defaults to `'India'` when location is empty.
3. Firecrawl Workday fallback — if CXS API fails, falls back to `fc.batch_scrape()` on human-facing job URL.

**Verified clean after fixes:**
| ATS | Company | Jobs | JD | Location |
|-----|---------|------|-----|----------|
| Workday | Salesforce | 169 | ✅ 8-11k chars | ✅ Real city |
| Greenhouse | Stripe | 69 | ✅ 4-5k chars | ✅ Bengaluru |
| Custom JSON | Amazon | 93 | ✅ 1-3k chars | ✅ City+State+IND |
| Phenom REST | Schneider Electric | 10 | ✅ 6-12k chars | ✅ |
