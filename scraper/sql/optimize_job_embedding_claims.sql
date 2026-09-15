-- Follow-up to create_job_embeddings_14d.
-- Match claim order to the partial work index and remove an audit hash index
-- that is never used for lookup.

BEGIN;

DROP INDEX IF EXISTS private.idx_job_embeddings_input_hash;

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
        WHERE j.is_active IS TRUE
          AND COALESCE(j.listing_confidence, 'uncertain') NOT IN ('closed', 'likely_closed')
          AND je.attempts < greatest(1, p_max_attempts)
          AND (
              je.status IN ('pending', 'retryable')
              OR (
                  je.status = 'processing'
                  AND je.started_at < now() - interval '30 minutes'
              )
          )
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

REVOKE ALL ON FUNCTION public.claim_job_embeddings(INTEGER, INTEGER)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_job_embeddings(INTEGER, INTEGER)
    TO service_role;

COMMIT;
