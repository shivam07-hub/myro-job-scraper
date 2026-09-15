# Backlog — carry into the next run

Written 2026-08-13, after the 2026-08-08 full India scrape (28,957 published) and
the dashboard data audit that followed it.

Every item below is either **measured** or **reproduced**. Where a number appears,
it came from a query against prod, not an estimate. Items are ordered by what
costs the user most, not by effort.

Two repos are involved. `FC` = `firecrawl_Supabase`, `TY` = `True_Yodha`.

---

## DONE in this session (context, not work)

| Fix | Where | State |
|---|---|---|
| Resolver dropped provenance when the model didn't run | FC `source_matching_facts.py` | committed `5e803b040` |
| `claim_job_embeddings` defeated its partial index (1499ms → 5ms) | FC `sql/fix_job_embedding_claim_index_usage.sql` | applied to prod + committed |
| Every Data Scientist mis-banded out of the technical keep-set | FC `job_career_band.py` | committed |
| Skill-floor count detoasted ~386 MB per call | TY `20260808_skill_floor_count_stops_detoasting.sql` | applied + committed |
| Resolver CSV didn't flatten `locations` | FC `source_matching_facts.py` | committed |
| Two local-inference workers could collide / model TTL expiry stalled drains | FC `lm_worker_lock.py`, `daily_cycle`, `enrichment_worker` | committed |
| Skill-demand snapshot 22 days stale | prod refresh run — 19 cities / 374 rows | data fixed, **trigger not** → see #2 |
| `Requisition` etc. surviving the demand guards | TY `20260813_skill_demand_skill_deny.sql` | applied to prod |

---

## P0 — the pipeline cannot run unattended

### 1. ✅ DONE — `daily_cycle` survives a run crossing midnight
**Evidence.** The 2026-08-07 run scraped 23:28 → 08:26 and exited 2 at the publish
step: `No complete jobs.json files found for source-only run date 20260807`.

**Cause.** `daily_poll` publishes every date a run spanned, but
`csv_importer._find_json_files` only considers each company's **newest** date
folder. A company that scrapes across midnight leaves an earlier-date folder that
can never be selected again.

**Also.** The pre-midnight folder has no `jobs.complete` marker, so its rows are
stranded until that company is next scraped — 1,380 Accenture jobs on 2026-08-08.

**Acceptance.** A run started before midnight completes all stages in one command,
and no folder from it is left unpublished. Decide explicitly whether a
markerless partial folder should ever publish (current contract says no — that is
defensible, but then the scrape must not split a company across two folders).

**Resolution (2026-08-13).** `daily_poll` now pins one logical run date into the
scrape command. Page flushes, the final completion marker, source-fact resolution,
and publication all use that date. `csv_importer` also selects an explicitly
requested date rather than first discarding everything except each company's
newest folder. Markerless partial folders remain unpublished. Focused regression
coverage and the full `scraper/tests` suite pass.

---

### 2. ✅ DONE — skill-demand / analytics refresh is durable and independently retryable
**Evidence.** Every publish logged
`Intel refresh failed (…/jobs/analytics/refresh-snapshot): Read timed out (read timeout=30)`.
The snapshot then sat at 2026-07-21 for 22 days while the UI kept rendering it.

**Three separate faults.**
1. The endpoint does analytics + skill demand + search index **synchronously inside
   the request**, and the scraper's client gives it 30s.
2. Skill demand is coupled to the analytics dirty-guard — it recomputes only when
   `summary["refreshed"]` is true. Once analytics is fresh and skill demand is not,
   nothing ever repairs it. That is the state prod was in.
3. The scraper's call is fire-and-forget (correctly — it must not fail an import),
   so nobody is paged when it fails every single time.

**Acceptance.** Freshness is enforced, not hoped for: the refresh runs
asynchronously or on its own schedule, each snapshot's staleness is observable,
and the panel refuses to render a snapshot older than N days rather than showing
a stale number with an apology label.

**Implemented 2026-08-13.** The scraper now sends `force=true`, accepts the
backend's asynchronous `202`, and waits at most 5 seconds. The backend persists
one refresh request before acknowledging, then claims analytics, skill demand,
and search independently; one failure is recorded without gating either sibling.
Prod now has per-product status/lease/error state plus staggered hourly SQL retry
crons for skill demand and global search. The existing daily analytics HTTP cron
was deliberately left unchanged until `Develop` is promoted. Skill-demand reads
suppress snapshots older than 48 hours while preserving `computed_at` for
operational diagnosis. Live ACL verification denies both API roles and permits
only `service_role`; Supabase advisors are clean for this subsystem. Focused
backend contracts, the full 326-test scraper suite, and transactional live RPC
smoke coverage pass.

---

### 3. ✅ DONE — `new_jobs_count` follows trusted live inventory and cannot freeze
**Audit correction.** The dashboard's **4,095 new roles** was the product-correct
count when notification 619 was written. The claimed **12,108** comparison used
only `is_active=true`; it included more than 8,000 listings classified
`uncertain`, `likely_closed`, or `closed`. Jobs RLS exposes only
`is_active=true AND listing_confidence='active'` (plus a user's own extension
rows), and new importer rows default to `uncertain`. Therefore an in-progress
source publish was already invisible to students: no batch-atomicity layer was
needed, and adding one would have hidden independently trusted inventory.

**Real faults.** The newer one-hop RPC was service-role-only and counted
`is_active` without the trust predicate, changing both the old token/RLS
semantics and its caller ACL. Separately, the inbox persisted a point-in-time
number and returned it indefinitely. Code tracing found one writer: the
`/jobs/matches` path records the count after recompute. Historical Railway HTTP
logs were unavailable because the local CLI session was not authenticated; that
missing log lane is not treated as evidence for the discarded batch theory.

**Resolution (2026-08-13).** The security-invoker RPC now explicitly counts only
active, trusted roles and is executable by `authenticated` and `service_role`
while remaining denied to `anon`. RLS keeps an authenticated caller owner-scoped.
Opening the inbox re-derives every unread new-role projection, repairs a changed
count through the service client, resolves it at zero, and hides it if the live
count is unavailable. The one-time live repair left **2 unread / 0 mismatched**
projections and resolved the one zero-count row. A partial `ingested_at` index for trusted active roles cut
the measured production query from **7,295ms / 13,369 buffers** to
**0.84ms / 91 buffers**. Live smoke: auth-own **4,094**, auth-other **0**,
service **4,094**, anon execute denied. Focused backend contracts pass.

---

## P1 — data the user sees is wrong or missing

### 4. ✅ DONE — unclassified source jobs publish without a fabricated band
**Evidence.** The 2026-08-08 run scraped 33,246 rows but published 28,957;
4,289 were withheld solely because career band was treated as a publication
license. Current deterministic rules resolve 28,987, leaving 4,259 unresolved.
The remaining titles either name no function (`IN-Expert`, `Fixed Term
Appointment`, bare ladder grades) or hide it behind employer-private vocabulary.
More regex would turn a coverage metric into invented matching truth.

**Decision.** Publication eligibility and matching readiness are different
contracts. A source-valid role without a provable career band is useful in
browse/search and must publish with `career_band=NULL`; it does not enter
band-dependent matching until evidence supports one of Myro's four real bands.
This uses the database's existing nullable contract—production already had
9,170 trusted active browseable jobs with no band—and adds no fake fifth band or
employer-prefix dictionary.

**Resolution (2026-08-13).** The daily lane now runs
`--publish-unclassified`; `--resolved-only` remains a compatibility alias.
Preflight separates unique published, truthfully unclassified, malformed
withheld, and duplicate-source counts. Upserts explicitly write NULL so a source
change cannot retain a stale former band. The resolver CLI's previously crashing
percent-bearing help text is also guarded. Measured dry run: **33,215 unique
publishable, 4,258 uniquely unclassified, 0 malformed withheld, 31 duplicate
source rows collapsed**. Production run
`1867389a-b29c-4377-b363-ed2214d0ab31` completed all **261 companies** in
**1,065s** and recorded an `ok` run audit. Live verification is exact:
**33,215 rows = 28,957 classified + 4,258 unclassified**, with **0 empty-string
bands**. The existing trust lifecycle remains the visibility gate: 747 of those
unclassified rows were already trusted-active, while 3,036 remain uncertain.
Intel refresh and the scrape-landed sweep both accepted the completed run.

### 5. ✅ DONE — 54 failed companies are measured, recoverable routes restored
**Correction to the premise.** Qualcomm was not one of the failures: it completed
the source run with 260 jobs. Five PCSX tenants failed together. The shared cause
was a missing career-page bootstrap: PCSX/CloudFront issues visitor cookies on the
public board before accepting paginated API traffic. Worse, the provider returned
an already-fetched prefix as success when a later page failed. Micron proved the
impact live: 170 rows were saved and its checkpoint was marked complete after the
next page returned 403.

**Resolution (2026-08-13).** PCSX now bootstraps and reuses a visitor session,
retries one auth-like failure after refreshing it, and returns a typed partial
result if pagination still breaks. `main.py` quarantines that evidence and cannot
write a completion marker or publish it. The result contract survives provider
dispatch and diagnostics; cheap probes no longer invoke Firecrawl implicitly.
The diagnostic CLI now resolves an actual persisted run id and `--probe --json`
really executes probes. Overlapping upstream pages are deduplicated at both the
provider and writer boundaries.

Three stale routes were replaced end to end: H&M's 403 WordPress proxy with
SmartRecruiters, Tekion's 404 Greenhouse board with Ashby, and TVS Next's unwired
Keka board with a first-class provider. The retired H&M provider and registry
override were deleted. Binance's existing Lever route also recovered.

**Measured user outcome.** Nine complete company snapshots produced **842 unique
India jobs**, all with full descriptions and apply URLs: H&M 62, Tekion 61, TVS
Next 23, Binance 1, NVIDIA 218, Micron 261, PayPal 3, Infineon 140, and Lam
Research 73. Source-only publication run
`6eb699b7-64d0-4ad4-b2b2-344b866ea7f4` completed despite Supabase batch timeouts
by recursively splitting writes. A second stale seam was closed: the importer
claimed lifecycle tracking but never called it. The trusted lifecycle is now
part of every import; source-only mode promotes observed jobs without fabricating
company-skill facts. Reconciliation accepted all nine source runs as complete,
and live verification found **842/842 active + `listing_confidence='active'` +
apply URL**.

**Disposition of the original 54.** Recovered and published: the nine above.
Known Cloudflare-blocked Workday tenants: Bank of America, Engie, Ford, GE
Aerospace, Hitachi Vantara, Inspire Brands, Medtronic. Cookie-gated Darwinbox:
Flipkart and IIFL Finance. The bounded Firecrawl pass over all eight opaque routes
found no durable listing signal for Amdocs, Arvind SmartSpaces, Coromandel
International, Integrow Asset Management, Lodha Ventures, or Syneriq Global;
Tech Mahindra mapped only generic careers pages, and FinIQ's page exposes a
campus hiring table rather than atomic public jobs/apply URLs. None were promoted
or fabricated. The remaining direct-route failures retain explicit typed probe
evidence instead of being counted as empty career pages; future route work can
start from that evidence without repeating this incident. The final direct-route
sweep measured **8 recovered, 16 reachable-zero, 7 fallback-needed, 5 typed
errors, and 1 coverage drop**. `PARTIAL` is now reserved for a provider that
actually tore a snapshot; a capped probe below its historical baseline reports
`COVERAGE_DROP` instead.

### 6. ✅ DONE — L3 practice mode separates levelled and scenario demand
After the refresh, `Communication` ranks #1 in Gurugram (117 roles, 30 employers)
and appears in **15 cities / 4,157 roles**; `Collaboration` in 9 cities.

These are real extractions, not artefacts, so the denylist deliberately does not
touch them — whether "Communication" is useful market intelligence for a job
seeker is a judgement call. If the answer is no, the fix is a soft-skill class in
the taxonomy, not individual denies.

**Decision (2026-08-14).** Domain → Cluster → Skill remains the three-level
taxonomy. How Myro may practise a canonical L3 Skill is a separate L3 contract:
`levelled` for objective L1-L5 assessment, `scenario` for behavioral/case-study
evidence, and `observed` for real demand with no current practice mode. This is
not a five-domain "technical" allowlist: objectively assessable professional
skills such as Financial Accounting, Management Consulting, and Product Strategy
remain levelled. Only levelled skills may drive the current demand rail,
Learning Ladder, numeric gaps, public/authenticated fit, or matching.

**Resolution.** TY `4f2b97e3` adds generated `skills.practice_mode` with asserted
L3 overrides for mixed Communication areas, splits behavioral demand into the
service-only `skill_scenario_demand_snapshot`, and carries required depth plus
practice mode through the job-skill RPC. It closes a second real seam: the RPC
previously discarded `required_level` and the soft/levelled boundary on scoped
reads. Scenario/observed skills are now excluded consistently from matching,
public fit, authenticated skill gaps, Mentor gap plans, and job-anchored
practice—not merely hidden in one UI.

Learning proof remains separate: a clear writes `skill_assessed_level`, never
silently mutating CV-derived skills, matching, or score truth. The result now
offers an explicit **Update Main CV** action. Existing evidence opens Mentor on
the living Main CV; without a CV bullet, the existing Skills Refresh/autosave
path adds only the selected assessed Skill to the Main CV skills line and never
fabricates an achievement bullet.

**Live verification.** Prod holds **34,831 levelled / 283 scenario** Skills.
Communication, Collaboration, and Cross-Functional Collaboration are scenario;
the three professional examples above are levelled. The projections contain
**350 levelled rows / 117 scenario rows with 0 cross-mode leaks**. Current
scenario demand remains measured separately: Communication 30 cells / 4,118
roles, Collaboration 25 / 2,270, Cross-Functional Collaboration 17 / 953. The
V2 RPC returned depth + mode in **8.6ms**, permits authenticated/service roles,
and denies anon. Supabase security advisors report no finding on the new objects.
All TY gates pass: **2,175 backend tests**, frontend typecheck/lint, **612 + 21
frontend tests**, UI-drift guard, and production build.

---

## P2 — dashboard design (from the 2026-08-12 critique)

### 7. Four scoring systems in one viewport
Myro Score 30, Worth It 76, Citibank 84%, "1/5 skills" — four scales, four
meanings, no stated relationship. Directly against the standardization-as-trust
principle. **Pick one, express it identically everywhere, delete the rest.**

### 8. The score removes status instead of conferring it
The page opens by telling a job seeker they are a **30 · Emerging**, with 40
labelled "Developing". That is a report card. If a human is going to be scored,
the number has to be something they would screenshot.

### 9. Ranking has no resolution
Both visible cards scored exactly **76**. Two significant figures of precision
the model does not have.

### 10. `× MoEngage` is listed as a missing skill on a MoEngage job
Company name leaking into the skill taxonomy — the same class of bug as
`Requisition`. Contradicts the principle that Myro indexes identifiable employers
and explains what *they* want. Check whether company names are enterable as
skills at all.

### 11. Smaller items
- `Practice Business To Bu…` — the most prominent CTA in the left rail is truncated.
- "Your next moves" ranks *practice* above an 84% match. Order by expected value.
- Job title `Senior Customer Success Manager -Gurugram` carries the location, and
  so does the location chip, and so does the filter pill — three statements of one
  fact, plus a missing space after the hyphen from dirty source text.
- "Company Signals" renders as an empty/blurred panel with no empty state.
- `Run Myro Search · **Free**` — saying "free" tells the user there is a price.

### 12. The visual identity is the AI default
Near-black + single acid-teal accent, one geometric sans doing display, body and
data. Nothing in the palette or type comes from hiring, careers, or the Indian job
market. The most differentiated fact on the page — **`Verified 1d ago`**, live
listing verification almost nobody does — is set in the smallest, dimmest type on
the card. That is the asset worth building an identity around.

---

## P3 — infrastructure

### 13. Supabase is materially degraded
A trivial REST root request measured **10.0s / 1.3s / 2.6s**. The second publish
took **3,127s vs 872s** for the first, and every worker hit repeated connection
resets and DNS failures. All three workers had to be run under retry loops.

`jobs` is ~611 MB. Check the instance size against the corpus, and whether the
8s `statement_timeout` inherited from `authenticator` is right for batch workers
(it is what broke skill-floor, item DONE above).

### 14. Two migrations applied to prod, one uncommitted
`TY/database/migrations/20260813_skill_demand_skill_deny.sql` is applied to prod
and written to disk but **not committed**. True_Yodha work belongs on `Develop`.
