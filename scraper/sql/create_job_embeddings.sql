-- Source-first semantic job embeddings for the Myro Career Ops brain.
--
-- Rollout boundary:
--   * enroll active jobs posted in the latest 14 calendar dates only;
--   * automatically enroll new jobs and materially changed source rows later;
--   * do not enroll untouched older history.
--
-- Vectors stay in the private schema.  Public jobs are readable through the
-- Data API, so placing the vector on public.jobs would expose it to anon users.

BEGIN;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        RAISE EXCEPTION 'pgvector extension is required';
    END IF;
END
$$;

CREATE SCHEMA IF NOT EXISTS private;
REVOKE ALL ON SCHEMA private FROM PUBLIC, anon, authenticated;

CREATE TABLE IF NOT EXISTS private.job_embeddings (
    job_id TEXT PRIMARY KEY REFERENCES public.jobs(job_id) ON DELETE CASCADE,
    embedding public.halfvec(768),
    input_hash TEXT,
    model TEXT,
    version TEXT NOT NULL DEFAULT 'job_search_v1',
    status TEXT NOT NULL DEFAULT 'pending',
    attempts SMALLINT NOT NULL DEFAULT 0,
    claim_token UUID,
    enrollment_reason TEXT NOT NULL DEFAULT 'source_insert',
    enrolled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    queued_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    embedded_at TIMESTAMPTZ,
    last_error TEXT,
    CONSTRAINT job_embeddings_status_check CHECK (
        status IN ('pending', 'processing', 'retryable', 'complete', 'failed', 'not_applicable')
    ),
    CONSTRAINT job_embeddings_attempts_check CHECK (attempts >= 0)
);

ALTER TABLE private.job_embeddings ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE private.job_embeddings FROM PUBLIC, anon, authenticated;
GRANT USAGE ON SCHEMA private TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE private.job_embeddings TO service_role;

CREATE INDEX IF NOT EXISTS idx_job_embeddings_work
    ON private.job_embeddings (queued_at, job_id)
    WHERE status IN ('pending', 'processing', 'retryable');

CREATE INDEX IF NOT EXISTS idx_job_embeddings_hnsw
    ON private.job_embeddings
    USING hnsw (embedding public.halfvec_cosine_ops)
    WHERE status = 'complete' AND embedding IS NOT NULL;

CREATE OR REPLACE FUNCTION private.prepare_job_embedding()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    v_enrichable BOOLEAN;
    v_changed BOOLEAN;
    v_reason TEXT;
BEGIN
    v_enrichable :=
        char_length(btrim(COALESCE(NEW.job_description, ''))) >= 50
        AND btrim(COALESCE(NEW.job_description, '')) <>
            'No JD provided on the company page. Matching and skill extraction are unavailable for this role until a job description is published.';

    IF TG_OP = 'INSERT' THEN
        v_changed := TRUE;
        v_reason := 'source_insert';
    ELSE
        v_changed :=
            NEW.job_title IS DISTINCT FROM OLD.job_title
            OR NEW.job_description IS DISTINCT FROM OLD.job_description
            OR NEW.company_name IS DISTINCT FROM OLD.company_name
            OR NEW.industry IS DISTINCT FROM OLD.industry
            OR NEW.location IS DISTINCT FROM OLD.location
            OR NEW.location_country IS DISTINCT FROM OLD.location_country
            OR NEW.location_mode IS DISTINCT FROM OLD.location_mode;
        v_reason := 'source_change';
    END IF;

    IF NOT v_changed THEN
        RETURN NEW;
    END IF;

    INSERT INTO private.job_embeddings (
        job_id, embedding, input_hash, model, version, status, attempts,
        claim_token, enrollment_reason, enrolled_at, queued_at, started_at,
        embedded_at, last_error
    ) VALUES (
        NEW.job_id, NULL, NULL, NULL, 'job_search_v1',
        CASE WHEN v_enrichable THEN 'pending' ELSE 'not_applicable' END,
        0, NULL, v_reason, now(), CASE WHEN v_enrichable THEN now() ELSE NULL END,
        NULL, NULL, NULL
    )
    ON CONFLICT (job_id) DO UPDATE SET
        embedding = NULL,
        input_hash = NULL,
        model = NULL,
        version = 'job_search_v1',
        status = EXCLUDED.status,
        attempts = 0,
        claim_token = NULL,
        enrollment_reason = EXCLUDED.enrollment_reason,
        enrolled_at = now(),
        queued_at = EXCLUDED.queued_at,
        started_at = NULL,
        embedded_at = NULL,
        last_error = NULL;

    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS prepare_job_embedding ON public.jobs;
CREATE TRIGGER prepare_job_embedding
    AFTER INSERT OR UPDATE OF
        job_title, job_description, company_name, industry,
        location, location_country, location_mode
    ON public.jobs
    FOR EACH ROW
    EXECUTE FUNCTION private.prepare_job_embedding();

REVOKE ALL ON FUNCTION private.prepare_job_embedding() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION private.prepare_job_embedding() TO service_role;

-- One-time, explicitly bounded enrollment.  Parse only known source formats;
-- unknown posting dates are not treated as recent.  current_date - 13 yields
-- fourteen calendar dates including today.  Older untouched rows receive no
-- queue row.
WITH parsed_jobs AS (
    SELECT
        j.*,
        CASE
            WHEN j.date_posted ~ '^\d{4}-\d{2}-\d{2}'
                THEN substring(j.date_posted FROM 1 FOR 10)::DATE
            WHEN lower(btrim(j.date_posted)) = 'posted today'
                THEN (now() AT TIME ZONE 'Asia/Kolkata')::DATE
            WHEN lower(btrim(j.date_posted)) = 'posted yesterday'
                THEN (now() AT TIME ZONE 'Asia/Kolkata')::DATE - 1
            WHEN j.date_posted ~* '^Posted [0-9]+ Days? Ago$'
                THEN (now() AT TIME ZONE 'Asia/Kolkata')::DATE
                    - substring(j.date_posted FROM '[0-9]+')::INTEGER
            WHEN j.date_posted ~ '^[A-Z][a-z]{2} [0-9]{1,2}, [0-9]{4}$'
                THEN to_date(j.date_posted, 'Mon DD, YYYY')
            WHEN j.date_posted ~ '^\d{1,2}/\d{1,2}/\d{2}$'
                THEN make_date(
                    2000 + split_part(j.date_posted, '/', 3)::INTEGER,
                    split_part(j.date_posted, '/', 1)::INTEGER,
                    split_part(j.date_posted, '/', 2)::INTEGER
                )
            ELSE NULL
        END AS posted_on
    FROM public.jobs AS j
)
INSERT INTO private.job_embeddings (
    job_id, status, version, attempts, enrollment_reason, enrolled_at, queued_at
)
SELECT
    j.job_id,
    CASE
        WHEN char_length(btrim(COALESCE(j.job_description, ''))) >= 50
         AND btrim(COALESCE(j.job_description, '')) <>
            'No JD provided on the company page. Matching and skill extraction are unavailable for this role until a job description is published.'
            THEN 'pending'
        ELSE 'not_applicable'
    END,
    'job_search_v1',
    0,
    'recent_posted_backfill_14d',
    now(),
    CASE
        WHEN char_length(btrim(COALESCE(j.job_description, ''))) >= 50
         AND btrim(COALESCE(j.job_description, '')) <>
            'No JD provided on the company page. Matching and skill extraction are unavailable for this role until a job description is published.'
            THEN now()
        ELSE NULL
    END
FROM parsed_jobs AS j
WHERE j.is_active IS TRUE
  AND j.posted_on BETWEEN
      (now() AT TIME ZONE 'Asia/Kolkata')::DATE - 13
      AND (now() AT TIME ZONE 'Asia/Kolkata')::DATE
ON CONFLICT (job_id) DO NOTHING;

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

CREATE OR REPLACE FUNCTION public.apply_job_embeddings(
    p_items JSONB,
    p_model TEXT,
    p_version TEXT
)
RETURNS TABLE (applied INTEGER, rejected INTEGER)
LANGUAGE sql
SECURITY INVOKER
SET search_path = ''
AS $$
    WITH parsed AS MATERIALIZED (
        SELECT
            item.value ->> 'job_id' AS job_id,
            (item.value ->> 'claim_token')::UUID AS claim_token,
            item.value ->> 'input_hash' AS input_hash,
            (item.value -> 'embedding')::TEXT::public.halfvec(768) AS embedding
        FROM jsonb_array_elements(
            CASE
                WHEN jsonb_typeof(COALESCE(p_items, '[]'::JSONB)) = 'array'
                    THEN COALESCE(p_items, '[]'::JSONB)
                ELSE '[]'::JSONB
            END
        ) AS item(value)
        WHERE jsonb_typeof(item.value) = 'object'
    ), updated AS (
        UPDATE private.job_embeddings AS je
        SET embedding = p.embedding,
            input_hash = p.input_hash,
            model = p_model,
            version = p_version,
            status = 'complete',
            claim_token = NULL,
            embedded_at = now(),
            last_error = NULL
        FROM parsed AS p
        JOIN public.jobs AS j ON j.job_id = p.job_id
        WHERE je.job_id = p.job_id
          AND je.claim_token = p.claim_token
          AND je.status = 'processing'
          AND j.is_active IS TRUE
          AND COALESCE(j.listing_confidence, 'uncertain') NOT IN ('closed', 'likely_closed')
        RETURNING je.job_id
    )
    SELECT
        (SELECT count(*)::INTEGER FROM updated) AS applied,
        greatest(
            (SELECT count(*) FROM parsed) - (SELECT count(*) FROM updated),
            0
        )::INTEGER AS rejected;
$$;

CREATE OR REPLACE FUNCTION public.retry_job_embeddings(
    p_items JSONB,
    p_error TEXT,
    p_max_attempts INTEGER DEFAULT 5
)
RETURNS INTEGER
LANGUAGE sql
SECURITY INVOKER
SET search_path = ''
AS $$
    WITH parsed AS MATERIALIZED (
        SELECT
            item.value ->> 'job_id' AS job_id,
            (item.value ->> 'claim_token')::UUID AS claim_token
        FROM jsonb_array_elements(
            CASE
                WHEN jsonb_typeof(COALESCE(p_items, '[]'::JSONB)) = 'array'
                    THEN COALESCE(p_items, '[]'::JSONB)
                ELSE '[]'::JSONB
            END
        ) AS item(value)
        WHERE jsonb_typeof(item.value) = 'object'
    ), updated AS (
        UPDATE private.job_embeddings AS je
        SET status = CASE
                WHEN je.attempts >= greatest(1, p_max_attempts) THEN 'failed'
                ELSE 'retryable'
            END,
            claim_token = NULL,
            started_at = NULL,
            last_error = left(COALESCE(NULLIF(btrim(p_error), ''), 'embedding failure'), 1000)
        FROM parsed AS p
        WHERE je.job_id = p.job_id
          AND je.claim_token = p.claim_token
          AND je.status = 'processing'
        RETURNING 1
    )
    SELECT count(*)::INTEGER FROM updated;
$$;

CREATE OR REPLACE FUNCTION public.match_jobs_semantic(
    p_query_embedding TEXT,
    p_match_count INTEGER DEFAULT 100,
    p_target_countries TEXT[] DEFAULT NULL,
    p_include_remote BOOLEAN DEFAULT TRUE,
    p_excluded_job_ids TEXT[] DEFAULT ARRAY[]::TEXT[]
)
RETURNS TABLE (
    job_id TEXT,
    job_title TEXT,
    company_name TEXT,
    location TEXT,
    similarity DOUBLE PRECISION
)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = ''
SET hnsw.iterative_scan = 'relaxed_order'
AS $$
    SELECT
        j.job_id,
        j.job_title,
        j.company_name,
        j.location,
        1 - (
            je.embedding OPERATOR(public.<=>) p_query_embedding::public.halfvec(768)
        ) AS similarity
    FROM private.job_embeddings AS je
    JOIN public.jobs AS j ON j.job_id = je.job_id
    WHERE je.status = 'complete'
      AND je.embedding IS NOT NULL
      AND je.version = 'job_search_v1'
      AND j.is_active IS TRUE
      AND COALESCE(j.listing_confidence, 'uncertain') NOT IN ('closed', 'likely_closed')
      AND NOT (
          j.job_id = ANY(COALESCE(p_excluded_job_ids, ARRAY[]::TEXT[]))
      )
      AND (
          p_target_countries IS NULL
          OR cardinality(p_target_countries) = 0
          OR EXISTS (
              SELECT 1
              FROM unnest(p_target_countries) AS country(value)
              WHERE lower(btrim(country.value)) = lower(btrim(COALESCE(j.location_country::TEXT, '')))
          )
          OR (
              p_include_remote
              AND lower(COALESCE(j.location_mode::TEXT, '')) = 'remote'
          )
      )
    ORDER BY je.embedding OPERATOR(public.<=>) p_query_embedding::public.halfvec(768)
    LIMIT greatest(1, least(p_match_count, 500));
$$;

CREATE OR REPLACE FUNCTION public.job_embedding_metrics()
RETURNS TABLE (status TEXT, job_count BIGINT)
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = ''
AS $$
    SELECT je.status, count(*)
    FROM private.job_embeddings AS je
    GROUP BY je.status
    ORDER BY je.status;
$$;

REVOKE ALL ON FUNCTION public.claim_job_embeddings(INTEGER, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.apply_job_embeddings(JSONB, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retry_job_embeddings(JSONB, TEXT, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.match_jobs_semantic(TEXT, INTEGER, TEXT[], BOOLEAN, TEXT[]) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.job_embedding_metrics() FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.claim_job_embeddings(INTEGER, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.apply_job_embeddings(JSONB, TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.retry_job_embeddings(JSONB, TEXT, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.match_jobs_semantic(TEXT, INTEGER, TEXT[], BOOLEAN, TEXT[]) TO service_role;
GRANT EXECUTE ON FUNCTION public.job_embedding_metrics() TO service_role;

COMMIT;
