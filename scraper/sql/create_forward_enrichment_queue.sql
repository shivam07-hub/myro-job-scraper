-- Forward-only asynchronous job enrichment.
--
-- IMPORTANT:
--   * This migration deliberately performs NO historical backfill.
--   * Existing jobs remain enrichment_status/source_content_hash = NULL.
--   * The first post-cutover source upsert may establish an existing row's hash,
--     but it does not enqueue or clear that legacy row.
--   * Only new post-cutover jobs and later source changes to already tracked jobs
--     are queued.
--
-- Draft only: review and apply explicitly after scraper code verification.

BEGIN;

CREATE SCHEMA IF NOT EXISTS private;
REVOKE ALL ON SCHEMA private FROM PUBLIC;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_extension WHERE extname = 'pgmq'
    ) OR NOT EXISTS (
        SELECT 1 FROM pgmq.list_queues() WHERE queue_name = 'job_enrichment'
    ) THEN
        RAISE EXCEPTION
            'Run enable_forward_enrichment_queue.sql before this migration';
    END IF;
END
$$;

ALTER TABLE public.jobs
    ADD COLUMN IF NOT EXISTS source_content_hash TEXT,
    ADD COLUMN IF NOT EXISTS enriched_source_hash TEXT,
    ADD COLUMN IF NOT EXISTS job_content_hash TEXT,
    ADD COLUMN IF NOT EXISTS enrichment_status TEXT,
    ADD COLUMN IF NOT EXISTS enrichment_model TEXT,
    ADD COLUMN IF NOT EXISTS enrichment_version TEXT,
    ADD COLUMN IF NOT EXISTS enrichment_queued_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS enrichment_priority_requested_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS enrichment_started_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS enriched_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS enrichment_last_error TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'jobs_enrichment_status_check'
          AND conrelid = 'public.jobs'::regclass
    ) THEN
        ALTER TABLE public.jobs
            ADD CONSTRAINT jobs_enrichment_status_check
            CHECK (
                enrichment_status IS NULL OR enrichment_status IN (
                    'pending', 'processing', 'retryable', 'complete',
                    'failed', 'not_applicable'
                )
            );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_jobs_enrichment_work
    ON public.jobs (enrichment_queued_at, job_id)
    WHERE enrichment_status IN ('pending', 'processing', 'retryable');

CREATE INDEX IF NOT EXISTS idx_jobs_job_content_hash
    ON public.jobs (job_content_hash)
    WHERE job_content_hash IS NOT NULL;

-- The scraper and worker use the service role only.  pgmq itself is not exposed
-- to anon/authenticated roles or added to the Data API schemas.
GRANT USAGE ON SCHEMA pgmq TO service_role;
-- pgmq 1.5.x queue functions are SECURITY INVOKER and operate on the physical
-- queue tables. Grant DML only for this queue, never the whole pgmq schema.
GRANT SELECT, INSERT, UPDATE, DELETE
    ON TABLE pgmq.q_job_enrichment, pgmq.a_job_enrichment
    TO service_role;
GRANT USAGE, SELECT
    ON SEQUENCE pgmq.q_job_enrichment_msg_id_seq
    TO service_role;
DO $$
DECLARE
    v_function REGPROCEDURE;
BEGIN
    -- pgmq has added overloads across releases (notably read/send/set_vt).
    -- Grant only the required operation names, but include every installed
    -- overload so this migration remains compatible with the project version.
    FOR v_function IN
        SELECT p.oid::REGPROCEDURE
        FROM pg_proc AS p
        JOIN pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname = 'pgmq'
          AND p.proname IN ('send', 'read', 'archive', 'set_vt', 'metrics')
    LOOP
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', v_function);
    END LOOP;
END
$$;

CREATE OR REPLACE FUNCTION private.prepare_job_enrichment_state()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    v_enrichable BOOLEAN;
    v_terminal BOOLEAN;
BEGIN
    -- Rows outside the scraper cutover remain legacy/untracked.
    IF NEW.source_content_hash IS NULL THEN
        RETURN NEW;
    END IF;

    v_enrichable :=
        char_length(btrim(COALESCE(NEW.job_description, ''))) >= 50
        AND btrim(COALESCE(NEW.job_description, '')) <>
            'No JD provided on the company page. Matching and skill extraction are unavailable for this role until a job description is published.';

    -- A skill-only result is not a complete trust-facing card.  Summary and
    -- controlled role domain are the minimum terminal core contract; skills
    -- may remain empty when the JD contains no defensible taxonomy match.
    v_terminal :=
        NULLIF(btrim(COALESCE(NEW.job_summary, '')), '') IS NOT NULL
        AND NULLIF(btrim(COALESCE(NEW.role_domain, '')), '') IS NOT NULL;

    IF TG_OP = 'INSERT' THEN
        IF v_terminal THEN
            NEW.enrichment_status := 'complete';
            NEW.enriched_source_hash := NEW.source_content_hash;
            NEW.enrichment_version := COALESCE(NEW.enrichment_version, 'job_core_v1');
            NEW.enriched_at := COALESCE(NEW.enriched_at, now());
        ELSIF v_enrichable THEN
            NEW.enrichment_status := 'pending';
            NEW.enrichment_version := 'job_core_v1';
            NEW.enrichment_queued_at := now();
        ELSE
            NEW.enrichment_status := 'not_applicable';
            NEW.enrichment_version := 'job_core_v1';
        END IF;
        RETURN NEW;
    END IF;

    -- Forward-only cutover guard.  The first source hash written to a historical
    -- row establishes a baseline but never queues or clears existing enrichment.
    IF OLD.source_content_hash IS NULL OR OLD.enrichment_status IS NULL THEN
        NEW.enrichment_status := OLD.enrichment_status;
        NEW.enriched_source_hash := OLD.enriched_source_hash;
        NEW.enrichment_model := OLD.enrichment_model;
        NEW.enrichment_version := OLD.enrichment_version;
        NEW.enrichment_queued_at := OLD.enrichment_queued_at;
        NEW.enrichment_started_at := OLD.enrichment_started_at;
        NEW.enriched_at := OLD.enriched_at;
        NEW.enrichment_last_error := OLD.enrichment_last_error;
        RETURN NEW;
    END IF;

    IF NEW.source_content_hash IS DISTINCT FROM OLD.source_content_hash THEN
        NEW.job_summary := NULL;
        NEW.role_domain := NULL;
        NEW.main_skills := ARRAY[]::TEXT[];
        NEW.side_skills := ARRAY[]::TEXT[];
        NEW.enriched_source_hash := NULL;
        NEW.job_content_hash := NULL;
        NEW.enrichment_model := NULL;
        NEW.enrichment_version := 'job_core_v1';
        NEW.enrichment_priority_requested_at := NULL;
        NEW.enrichment_started_at := NULL;
        NEW.enriched_at := NULL;
        NEW.enrichment_last_error := NULL;

        IF v_enrichable THEN
            NEW.enrichment_status := 'pending';
            NEW.enrichment_queued_at := now();
        ELSE
            NEW.enrichment_status := 'not_applicable';
            NEW.enrichment_queued_at := NULL;
        END IF;
    END IF;

    RETURN NEW;
END
$$;

CREATE OR REPLACE FUNCTION private.queue_job_enrichment_change()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    v_should_queue BOOLEAN := FALSE;
BEGIN
    IF TG_OP = 'INSERT' THEN
        v_should_queue := NEW.enrichment_status = 'pending';
    ELSE
        -- OLD.enrichment_status NULL is the historical cutover sentinel.
        IF OLD.enrichment_status IS NOT NULL
           AND OLD.source_content_hash IS NOT NULL
           AND NEW.source_content_hash IS DISTINCT FROM OLD.source_content_hash THEN
            DELETE FROM public.job_skills WHERE job_id = NEW.job_id;
            v_should_queue := NEW.enrichment_status = 'pending';
        END IF;
    END IF;

    IF v_should_queue THEN
        PERFORM pgmq.send(
            'job_enrichment',
            jsonb_build_object(
                'job_id', NEW.job_id,
                'source_content_hash', NEW.source_content_hash,
                'enrichment_version', NEW.enrichment_version,
                'queued_at', NEW.enrichment_queued_at
            ),
            0
        );
    END IF;

    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS prepare_job_enrichment_state ON public.jobs;
CREATE TRIGGER prepare_job_enrichment_state
    BEFORE INSERT OR UPDATE OF source_content_hash
    ON public.jobs
    FOR EACH ROW
    EXECUTE FUNCTION private.prepare_job_enrichment_state();

DROP TRIGGER IF EXISTS queue_job_enrichment_change ON public.jobs;
CREATE TRIGGER queue_job_enrichment_change
    AFTER INSERT OR UPDATE OF source_content_hash
    ON public.jobs
    FOR EACH ROW
    EXECUTE FUNCTION private.queue_job_enrichment_change();

REVOKE ALL ON FUNCTION private.prepare_job_enrichment_state() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION private.queue_job_enrichment_change() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION private.prepare_job_enrichment_state() TO service_role;
GRANT EXECUTE ON FUNCTION private.queue_job_enrichment_change() TO service_role;

-- Service-role-only Data API wrappers.  They are SECURITY INVOKER functions;
-- the service role receives only the specific pgmq permissions listed above.
CREATE OR REPLACE FUNCTION public.claim_job_enrichment(
    p_job_id TEXT,
    p_source_content_hash TEXT
)
RETURNS BOOLEAN
LANGUAGE sql
SECURITY INVOKER
SET search_path = ''
AS $$
    WITH claimed AS (
        UPDATE public.jobs AS j
        SET enrichment_status = 'processing',
            enrichment_started_at = now(),
            enrichment_last_error = NULL
        WHERE j.job_id = p_job_id
          AND j.source_content_hash = p_source_content_hash
          AND j.is_active IS TRUE
          AND (
              j.enrichment_status IN ('pending', 'retryable')
              OR (
                  j.enrichment_status = 'processing'
                  AND j.enrichment_started_at < now() - interval '30 minutes'
              )
          )
        RETURNING 1
    )
    SELECT EXISTS (SELECT 1 FROM claimed);
$$;

CREATE OR REPLACE FUNCTION public.request_job_enrichment_priority(p_job_id TEXT)
RETURNS TEXT
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    v_status TEXT;
BEGIN
    UPDATE public.jobs AS j
    SET enrichment_priority_requested_at = now()
    WHERE j.job_id = p_job_id
      AND j.is_active IS TRUE
      AND j.source_content_hash IS NOT NULL
      AND j.enrichment_status IN ('pending', 'retryable')
      AND (
          j.enrichment_priority_requested_at IS NULL
          OR j.enrichment_priority_requested_at < now() - interval '5 minutes'
      );

    SELECT j.enrichment_status
    INTO v_status
    FROM public.jobs AS j
    WHERE j.job_id = p_job_id;
    RETURN COALESCE(v_status, 'missing');
END
$$;

CREATE OR REPLACE FUNCTION public.read_priority_job_enrichment(p_qty INTEGER DEFAULT 10)
RETURNS TABLE (
    job_id TEXT,
    source_content_hash TEXT,
    enrichment_version TEXT
)
LANGUAGE sql
SECURITY INVOKER
SET search_path = ''
AS $$
    WITH candidates AS MATERIALIZED (
        SELECT j.job_id
        FROM public.jobs AS j
        WHERE j.is_active IS TRUE
          AND j.source_content_hash IS NOT NULL
          AND j.enrichment_priority_requested_at IS NOT NULL
          AND (
              j.enrichment_status IN ('pending', 'retryable')
              OR (
                  j.enrichment_status = 'processing'
                  AND j.enrichment_started_at < now() - interval '30 minutes'
              )
          )
        ORDER BY j.enrichment_priority_requested_at, j.job_id
        FOR UPDATE SKIP LOCKED
        LIMIT greatest(1, least(p_qty, 100))
    ), claimed AS (
        UPDATE public.jobs AS j
        SET enrichment_status = 'processing',
            enrichment_started_at = now(),
            enrichment_last_error = NULL
        FROM candidates AS c
        WHERE j.job_id = c.job_id
        RETURNING j.job_id, j.source_content_hash, j.enrichment_version
    )
    SELECT c.job_id, c.source_content_hash, c.enrichment_version
    FROM claimed AS c;
$$;

CREATE OR REPLACE FUNCTION public.read_job_enrichment_queue(
    p_visibility_seconds INTEGER DEFAULT 900,
    p_qty INTEGER DEFAULT 10
)
RETURNS TABLE (
    msg_id BIGINT,
    read_ct INTEGER,
    enqueued_at TIMESTAMPTZ,
    vt TIMESTAMPTZ,
    message JSONB
)
LANGUAGE sql
SECURITY INVOKER
SET search_path = ''
AS $$
    SELECT q.msg_id, q.read_ct, q.enqueued_at, q.vt, q.message
    FROM pgmq.read(
        'job_enrichment',
        greatest(30, least(p_visibility_seconds, 7200)),
        greatest(1, least(p_qty, 100))
    ) AS q;
$$;

CREATE OR REPLACE FUNCTION public.archive_job_enrichment_message(p_msg_id BIGINT)
RETURNS BOOLEAN
LANGUAGE sql
SECURITY INVOKER
SET search_path = ''
AS $$
    SELECT pgmq.archive('job_enrichment', p_msg_id);
$$;

CREATE OR REPLACE FUNCTION public.retry_job_enrichment_message(
    p_msg_id BIGINT,
    p_delay_seconds INTEGER
)
RETURNS BOOLEAN
LANGUAGE sql
SECURITY INVOKER
SET search_path = ''
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM pgmq.set_vt(
            'job_enrichment',
            p_msg_id,
            greatest(30, least(p_delay_seconds, 86400))
        )
    );
$$;

CREATE OR REPLACE FUNCTION public.job_enrichment_queue_metrics()
RETURNS TABLE (
    queue_name TEXT,
    queue_length BIGINT,
    newest_msg_age_sec INTEGER,
    oldest_msg_age_sec INTEGER,
    total_messages BIGINT,
    scrape_time TIMESTAMPTZ
)
LANGUAGE sql
SECURITY INVOKER
SET search_path = ''
AS $$
    SELECT m.queue_name, m.queue_length, m.newest_msg_age_sec,
           m.oldest_msg_age_sec, m.total_messages, m.scrape_time
    FROM pgmq.metrics('job_enrichment') AS m;
$$;

CREATE OR REPLACE FUNCTION public.apply_job_enrichment(
    p_job_id TEXT,
    p_source_content_hash TEXT,
    p_job_summary TEXT,
    p_role_domain TEXT,
    p_skills JSONB,
    p_model TEXT,
    p_version TEXT,
    p_job_content_hash TEXT
)
RETURNS BOOLEAN
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $$
DECLARE
    v_main_skills TEXT[] := ARRAY[]::TEXT[];
    v_applied BOOLEAN := FALSE;
BEGIN
    WITH parsed AS (
        SELECT
            item.ordinality,
            item.value ->> 'name' AS skill_name,
            CASE
                WHEN (item.value ->> 'required_level') ~ '^[1-4]$'
                    THEN (item.value ->> 'required_level')::SMALLINT
                ELSE 2::SMALLINT
            END AS required_level
        FROM jsonb_array_elements(
            CASE WHEN jsonb_typeof(COALESCE(p_skills, '[]'::JSONB)) = 'array'
                THEN COALESCE(p_skills, '[]'::JSONB)
                ELSE '[]'::JSONB
            END
        ) WITH ORDINALITY AS item(value, ordinality)
        WHERE jsonb_typeof(item.value) = 'object'
          AND NULLIF(btrim(item.value ->> 'name'), '') IS NOT NULL
    ),
    matched AS (
        SELECT DISTINCT ON (s.id)
            s.id AS skill_id,
            s.taxonomy_key AS skill_name,
            p.required_level,
            p.ordinality
        FROM parsed AS p
        JOIN public.skills AS s ON s.taxonomy_key = p.skill_name
        ORDER BY s.id, p.ordinality
    )
    SELECT COALESCE(array_agg(skill_name ORDER BY ordinality), ARRAY[]::TEXT[])
    INTO v_main_skills
    FROM matched;

    IF NOT (
        NULLIF(btrim(COALESCE(p_job_summary, '')), '') IS NOT NULL
        AND NULLIF(btrim(COALESCE(p_role_domain, '')), '') IS NOT NULL
    ) THEN
        RETURN FALSE;
    END IF;

    UPDATE public.jobs
    SET job_summary = NULLIF(btrim(COALESCE(p_job_summary, '')), ''),
        role_domain = NULLIF(btrim(COALESCE(p_role_domain, '')), ''),
        main_skills = v_main_skills,
        side_skills = ARRAY[]::TEXT[],
        enriched_source_hash = p_source_content_hash,
        job_content_hash = p_job_content_hash,
        enrichment_status = 'complete',
        enrichment_model = p_model,
        enrichment_version = p_version,
        enrichment_started_at = COALESCE(enrichment_started_at, now()),
        enriched_at = now(),
        enrichment_priority_requested_at = NULL,
        enrichment_last_error = NULL
    WHERE job_id = p_job_id
      AND source_content_hash = p_source_content_hash
      AND is_active IS TRUE
      AND enrichment_status IN ('pending', 'processing', 'retryable')
    RETURNING TRUE INTO v_applied;

    IF NOT COALESCE(v_applied, FALSE) THEN
        RETURN FALSE;
    END IF;

    DELETE FROM public.job_skills WHERE job_id = p_job_id;

    WITH parsed AS (
        SELECT
            item.ordinality,
            item.value ->> 'name' AS skill_name,
            CASE
                WHEN (item.value ->> 'required_level') ~ '^[1-4]$'
                    THEN (item.value ->> 'required_level')::SMALLINT
                ELSE 2::SMALLINT
            END AS required_level
        FROM jsonb_array_elements(
            CASE WHEN jsonb_typeof(COALESCE(p_skills, '[]'::JSONB)) = 'array'
                THEN COALESCE(p_skills, '[]'::JSONB)
                ELSE '[]'::JSONB
            END
        ) WITH ORDINALITY AS item(value, ordinality)
        WHERE jsonb_typeof(item.value) = 'object'
          AND NULLIF(btrim(item.value ->> 'name'), '') IS NOT NULL
    ),
    matched AS (
        SELECT DISTINCT ON (s.id)
            s.id AS skill_id,
            p.required_level,
            p.ordinality
        FROM parsed AS p
        JOIN public.skills AS s ON s.taxonomy_key = p.skill_name
        ORDER BY s.id, p.ordinality
    )
    INSERT INTO public.job_skills (job_id, skill_id, is_primary, required_level)
    SELECT p_job_id, skill_id, TRUE, required_level
    FROM matched
    ON CONFLICT (job_id, skill_id)
    DO UPDATE SET
        is_primary = EXCLUDED.is_primary,
        required_level = EXCLUDED.required_level;

    RETURN TRUE;
END
$$;

REVOKE ALL ON FUNCTION public.read_job_enrichment_queue(INTEGER, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.claim_job_enrichment(TEXT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.request_job_enrichment_priority(TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.read_priority_job_enrichment(INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.archive_job_enrichment_message(BIGINT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.retry_job_enrichment_message(BIGINT, INTEGER) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.job_enrichment_queue_metrics() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.apply_job_enrichment(TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;

GRANT EXECUTE ON FUNCTION public.read_job_enrichment_queue(INTEGER, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.claim_job_enrichment(TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.request_job_enrichment_priority(TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.read_priority_job_enrichment(INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.archive_job_enrichment_message(BIGINT) TO service_role;
GRANT EXECUTE ON FUNCTION public.retry_job_enrichment_message(BIGINT, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION public.job_enrichment_queue_metrics() TO service_role;
GRANT EXECUTE ON FUNCTION public.apply_job_enrichment(TEXT, TEXT, TEXT, TEXT, JSONB, TEXT, TEXT, TEXT) TO service_role;

COMMIT;
