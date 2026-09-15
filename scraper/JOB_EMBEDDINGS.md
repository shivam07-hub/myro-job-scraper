# Source-first job embeddings

Status: deployed to production on 2026-07-13. The initial enrollment is
deliberately limited to active jobs posted in the latest 14 calendar dates.
New jobs and material source changes are enrolled automatically from now on.

## Why this lane exists

Myro's Career Ops brain must retrieve jobs by meaning before slower generative
enrichment is available. Embeddings therefore use source-owned job data only:
title, company, industry, normalized location, work mode, and job description.
`job_summary`, `role_domain`, and skill enrichment are intentionally excluded.

The database RPC returns nearest active jobs in similarity order. It has no
similarity threshold, taxonomy gate, or provisional skill sieve. The brain owns
the final interpretation and ranking. Database filters are limited to trust and
request scope: inactive/closed listings, country/remote scope, and explicitly
excluded job IDs.

## Privacy and storage

Vectors live in `private.job_embeddings`, not `public.jobs`. The public jobs
table is candidate-readable through the Data API, while the private table:

- has RLS enabled;
- grants no table or RPC access to `anon` or `authenticated`;
- grants access only to `service_role`;
- uses `halfvec(768)` plus a partial HNSW cosine index for complete rows.

The schema, trigger, bounded seed, claim/apply/retry functions, semantic-search
RPC, and metrics RPC are defined in `sql/create_job_embeddings.sql`.

## Stable embedding contract

Both sides use the locally hosted LM Studio model
`text-embedding-nomic-embed-text-v1.5` with 768 dimensions.

- Job documents use `search_document: `.
- Candidate/profile queries use `search_query: `.
- Contract version is `job_search_v1`.
- Job descriptions are normalized and capped at 6,000 characters.
- The stored SHA-256 input hash covers the contract version and exact document.

`job_embedding_state.py` is the canonical text/prefix/hash implementation.
Changing the model, dimension, prefix, field set, or truncation requires a new
contract version and an explicit re-embedding decision.

## Rollout boundary

The one-time seed parses supported `date_posted` formats and applies:

```sql
posted_on BETWEEN current_date - 13 AND current_date
```

That is fourteen Asia/Kolkata calendar dates including the deployment date. ISO dates,
Workday-style relative dates, English abbreviated month dates, and `M/D/YY`
dates are supported. Unknown dates are excluded rather than guessed recent.
Only active jobs are seeded. Untouched older history receives no queue row. Jobs
with missing or placeholder descriptions are recorded as `not_applicable` so
they are auditable without spending inference time.

After deployment, the `prepare_job_embedding` trigger enrolls new jobs and
resets a row only when a source field in the embedding document changes. Model
enrichment updates do not trigger re-embedding.

## Commands

```bash
cd scraper

# Verify LM Studio and the exact model/dimension without claiming DB work.
python job_embedding_worker.py --preflight-only

# Drain safely in bounded batches.
python job_embedding_worker.py --batch-size 32 --max-jobs 1000

# Exercise the production query contract.
python job_embedding_worker.py \
  --semantic-query "Entry-level Python backend and data engineering roles" \
  --country India \
  --match-count 20
```

For a large bounded rollout, LM Studio may load the exact same model weights
under additional identifiers. Separate workers can select those instances via
`--runtime-model <alias>`; applied rows still record the canonical configured
model. Never point an alias at different weights.

The worker claims rows with `FOR UPDATE ... SKIP LOCKED`, applies only when the
per-claim token still matches, retries transient failures, and never claims
database work when model preflight fails. `daily_cycle.py` starts/loads the
embedding model, drains this lane, then starts the separate generative model
and drains enrichment.

## Myro service contract

The trusted backend should:

1. build a rich candidate/profile query and prefix it via
   `build_job_query_text()`;
2. embed it with the same local model and 768 dimensions;
3. call `public.match_jobs_semantic` using the service role;
4. let the Career Ops brain reason over the ordered candidates without adding
   a fixed similarity cutoff or skill-term prefilter.

RPC arguments are `p_query_embedding` (JSON vector encoded as text),
`p_match_count`, `p_target_countries`, `p_include_remote`, and
`p_excluded_job_ids`. The response contains job ID, title, company, location,
and cosine similarity. The backend should load full trusted job records by the
returned IDs before presenting or reasoning over them.
