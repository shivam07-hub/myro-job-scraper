-- Follow-up to optimize_job_embedding_claims.sql.
--
-- PROBLEM (observed 2026-08-08, queue at 30,248 pending)
-- `claim_job_embeddings` had stopped claiming at all: every call returned
-- `57014 canceling statement due to statement timeout`, and the embedding queue
-- had been stalled since 2026-07-14.
--
-- The status test was written as an OR whose branches each name a status:
--
--     je.status IN ('pending','retryable')
--     OR (je.status = 'processing' AND je.started_at < now() - interval '30 minutes')
--
-- `idx_job_embeddings_work` is partial on
-- `status = ANY (ARRAY['pending','processing','retryable'])`. The planner has to
-- prove the query predicate implies the index predicate before it may use a
-- partial index, and it cannot see through that OR to do so. So it fell back to
-- a parallel sequential scan of the whole queue plus a sort on
-- (queued_at, job_id) — work that grows with the queue and cannot be
-- short-circuited by the LIMIT.
--
-- FIX
-- State the status set explicitly, then apply the 30-minute reclaim rule as a
-- separate conjunct. The two forms select exactly the same rows:
--
--     status = ANY (ARRAY['pending','processing','retryable'])
--     AND (status <> 'processing' OR started_at < now() - interval '30 minutes')
--
-- Now the predicate matches the index, the index also supplies the ORDER BY, and
-- the LIMIT stops early.
--
-- MEASURED on the live queue (EXPLAIN ANALYZE, LIMIT 32):
--     before: Parallel Seq Scan + Sort   1498.6 ms
--     after:  Index Scan idx_job_embeddings_work  5.1 ms
--
-- Nothing else changes: same signature, same returned columns, same claim
-- semantics, no schema change, no new index, no row rewritten.

BEGIN;

CREATE OR REPLACE FUNCTION public.claim_job_embeddings(
    p_qty INTEGER DEFAULT 32,
    p_max_attempts INTEGER DEFAULT 5
)
RETURNS TABLE (
    job_id TEXT,
    claim_token UUID,
    attempts SMALLINT,
    job_title TEXT,
    job_description TEXT,
    company_name TEXT,
    industry TEXT,
    location TEXT,
    location_country TEXT,
    location_mode TEXT
)
LANGUAGE sql
SECURITY INVOKER
SET search_path = ''
AS $$
    WITH candidates AS MATERIALIZED (
        SELECT je.job_id
        FROM private.job_embeddings AS je
        JOIN public.jobs AS j ON j.job_id = je.job_id
        WHERE je.status = ANY (ARRAY['pending', 'processing', 'retryable'])
          AND (
              je.status <> 'processing'
              OR je.started_at < now() - interval '30 minutes'
          )
          AND je.attempts < greatest(1, p_max_attempts)
          AND j.is_active IS TRUE
          AND COALESCE(j.listing_confidence, 'uncertain') NOT IN ('closed', 'likely_closed')
        ORDER BY je.queued_at, je.job_id
        FOR UPDATE OF je SKIP LOCKED
        LIMIT greatest(1, least(p_qty, 100))
    ), claimed AS (
        UPDATE private.job_embeddings AS je
        SET status = 'processing',
            attempts = je.attempts + 1,
            claim_token = gen_random_uuid(),
            started_at = now(),
            last_error = NULL
        FROM candidates AS c
        WHERE je.job_id = c.job_id
        RETURNING je.job_id, je.claim_token, je.attempts
    )
    SELECT
        c.job_id,
        c.claim_token,
        c.attempts,
        j.job_title,
        j.job_description,
        j.company_name,
        j.industry,
        j.location,
        j.location_country::TEXT,
        j.location_mode::TEXT
    FROM claimed AS c
    JOIN public.jobs AS j ON j.job_id = c.job_id
    ORDER BY c.job_id;
$$;

COMMIT;
