# Forward-only asynchronous enrichment

Status: deployed to production and live-data verified. One local Codex
automation runs the complete source-first daily cycle. Railway is an optional
hosted-resilience upgrade, not a launch dependency.

## Operating model

The scraper no longer needs inference to publish a job:

1. `main.py --skip-enrich` writes the current source snapshot.
2. `csv_importer.py --source-only` upserts source-owned fields immediately.
3. A database trigger queues new post-cutover jobs in the durable `pgmq`
   `job_enrichment` queue.
4. `enrichment_worker.py` drains the queue whenever LM Studio or an approved
   remote open-weight endpoint is available.
5. A hash-guarded database function atomically patches the enrichment-owned job
   summary and role-domain fields.
6. After publication, `csv_importer.py` sends the immutable run id to Myro's
   authenticated scrape-landed hook. True_Yodha queues its deterministic Stage A
   worker, which writes `job_skills` and asserts the unattempted queue is empty.
   The publish step requires `skill_floor_enqueued=true`; it retries transient
   failures and exits non-zero otherwise, so `daily_poll` cannot report a run
   complete while its jobs remain outside Stage A.

The existing trusted lifecycle/delisting loop remains independent and owns
whether a listing is active.

## Forward-only contract

- The migration contains no historical seed or backfill statement.
- Existing rows keep `source_content_hash = NULL` and
  `enrichment_status = NULL` (`legacy/untracked`).
- The first post-cutover source upsert may establish an existing row's source
  hash, but the trigger does not queue or clear it.
- A new row inserted after cutover is queued when it has a usable JD.
- A later title/JD change is queued only when that row was already tracked after
  cutover.
- An inactive job is archived without spending inference compute.

## Column ownership

Source import owns title, JD, company, industry, location, apply URL, source
metadata, provider chips, batch markers, lifecycle input, and a first-fill
extractive `job_summary` (only written when the database cell is empty).

The lazy enrichment worker upgrades `job_summary`, and owns `role_domain`,
enrichment hashes/status/model/version, and enrichment timestamps. True_Yodha's
Stage A and Stage B own `job_skills`; the trigger-derived `main_skills` mirror
follows those rows. `side_skills` is retired.

Source-only upserts never send `role_domain` or skill arrays, and they never
overwrite a non-empty `job_summary`. The source snapshot writer splits mixed
fill/preserve batches so PostgREST cannot NULL an omitted summary on a sibling
row. Closed listings wait one hour, then True_Yodha archives to `job_archive_v1` files and deletes. This writer does not call `retire_closed_jobs`.

## Live commands

```bash
cd scraper

# Fast lane: scrape and publish without waiting for an LLM.
python main.py --skip-enrich --scope global --global-cap 2000
python csv_importer.py --source-only --run-date "$(date +%Y_%m_%d)"

# Lazy lane: safe to run repeatedly. If local LM Studio is disconnected, it
# exits without claiming queue messages.
ENRICH_FORCE_LLM=1 python enrichment_worker.py --batch-size 10 --max-messages 100
```

Cloudflare Workers AI and other remote endpoints must serve an explicitly
allowlisted open-weight model through the existing inference configuration.

## Production deployment record

1. `enable_forward_enrichment_queue` installed pgmq 1.5.1 and the durable
   logged queue in a separate transaction. This separation avoids holding a
   `public.jobs` lock while Supabase Realtime observes pgmq table creation.
2. `create_forward_enrichment_queue` installed the nullable columns, triggers,
   indexes, invoker RPCs, and forward-only guards.
3. `grant_forward_enrichment_queue_service_role` added queue-specific DML and
   sequence privileges required by pgmq 1.5.1 invoker functions.
4. Stripe canary: 37 source rows published; 35 historical rows received only a
   baseline hash and remained untracked; 2 genuinely new jobs were queued.
5. The worker enriched and archived both new jobs exactly once. Their source
   and enriched hashes match and the live queue returned to length zero.
6. Supabase advisors reported no security finding for the new objects. The two
   fresh indexes initially report the expected unused-index informational lint.
7. Growth coverage is now capped at `1.0` for the lifecycle audit while the raw
   ratio remains available in failure diagnostics. A growing portal cannot
   violate the database constraint or interrupt the delisting audit.
8. Terminal enrichment now requires a factual `job_summary` and controlled
   `role_domain`; skills alone are not marked complete. `ENRICH_FORCE_LLM=1`
   keeps deterministic skill grounding while asking the model for those fields.
9. `harden_forward_enrichment_priority` adds an atomic priority lane. A pending
   job selected by personalized search can be claimed ahead of FIFO work; its
   original pgmq message remains the crash-safe fallback.
10. On 2026-07-12, seven newly validated direct boards published 92 jobs to
    Supabase before enrichment: Celonis 32, Glean 26, Boomi 26, Hightouch 2,
    Hootsuite 1, Deepgram 2, and Zapier 3. All seven lifecycle audits completed
    and retired zero jobs.
11. A real Deepgram personalized-search priority request was claimed first and
    enriched successfully with local `google/gemma-3-4b`, proving the urgent
    lane, strict trust contract, hash guard, and live database apply path.
12. The full 92-job live batch drained to zero with 92 terminal-complete rows,
    zero missing summaries, zero missing domains, zero hash mismatches, and zero
    jobs without taxonomy skills. Two concurrent consumers completed safely;
    the priority canary's original pgmq message became `duplicate_complete`.

## Scheduling

`.archon/workflows/scraper-weekly-run.yaml` defines the manual
`scraper-daily-forward` workflow without an independent cron schedule. It calls
`daily_cycle.py`, which publishes first, starts/loads the local embedding model,
drains new job embeddings, then starts/loads the generative model and drains
the durable enrichment queue. `daily_poll.py` publishes every local calendar date
spanned by a long scrape, so crossing midnight cannot omit late companies. An
inference failure cannot roll back published jobs.

Codex automation `Daily trusted career poll` owns the recurring source run. It
is re-anchored for 24 hours after poll-and-publish finishes and never creates
consumers when enrichment workers are already active. The old 15-minute `Lazy
job enrichment worker` automation is deleted, preventing duplicate tasks and
repeated model starts. Local automation requires this Mac to be on. The 2026-09-07 architecture cutover keeps the clock on the laptop; moving `daily_cycle.py` to Railway/Fly is the next version.

For an always-on worker independent of this Mac (next version), authenticate Railway, link the
intended project, and run the same worker command with the scraper environment
variables. Do not move the long scrape into Supabase Cron; Cron is suitable only
for a short trigger/watchdog, while a container performs long-running work.

The legacy `main.py --enrich-only` + `csv_importer.py` path remains available as
an operational fallback, but it is not the daily architecture.
