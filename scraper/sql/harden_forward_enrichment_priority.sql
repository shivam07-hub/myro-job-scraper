-- Production follow-up for the already-deployed forward enrichment queue.
-- Adds website-requested priority, atomic singleflight claims, and requires
-- summary + role domain before a result can become complete.

BEGIN;

ALTER TABLE public.jobs
    ADD COLUMN IF NOT EXISTS enrichment_priority_requested_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_jobs_enrichment_priority
    ON public.jobs (enrichment_priority_requested_at, job_id)
    WHERE enrichment_priority_requested_at IS NOT NULL
      AND enrichment_status IN ('pending', 'processing', 'retryable');

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
    IF NEW.source_content_hash IS NULL THEN
        RETURN NEW;
    END IF;

    v_enrichable :=
        char_length(btrim(COALESCE(NEW.job_description, ''))) >= 50
        AND btrim(COALESCE(NEW.job_description, '')) <>
            'No JD provided on the company page. Matching and skill extraction are unavailable for this role until a job description is published.';

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

    IF OLD.source_content_hash IS NULL OR OLD.enrichment_status IS NULL THEN
        NEW.enrichment_status := OLD.enrichment_status;
        NEW.enriched_source_hash := OLD.enriched_source_hash;
        NEW.enrichment_model := OLD.enrichment_model;
        NEW.enrichment_version := OLD.enrichment_version;
        NEW.enrichment_queued_at := OLD.enrichment_queued_at;
        NEW.enrichment_priority_requested_at := OLD.enrichment_priority_requested_at;
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

    SELECT j.enrichment_status INTO v_status
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
        SELECT item.ordinality, item.value ->> 'name' AS skill_name,
            CASE WHEN (item.value ->> 'required_level') ~ '^[1-4]$'
                THEN (item.value ->> 'required_level')::SMALLINT ELSE 2::SMALLINT END AS required_level
        FROM jsonb_array_elements(
            CASE WHEN jsonb_typeof(COALESCE(p_skills, '[]'::JSONB)) = 'array'
                THEN COALESCE(p_skills, '[]'::JSONB) ELSE '[]'::JSONB END
        ) WITH ORDINALITY AS item(value, ordinality)
        WHERE jsonb_typeof(item.value) = 'object'
          AND NULLIF(btrim(item.value ->> 'name'), '') IS NOT NULL
    ), matched AS (
        SELECT DISTINCT ON (s.id) s.id AS skill_id, s.taxonomy_key AS skill_name,
            p.required_level, p.ordinality
        FROM parsed AS p
        JOIN public.skills AS s ON s.taxonomy_key = p.skill_name
        ORDER BY s.id, p.ordinality
    )
    SELECT COALESCE(array_agg(skill_name ORDER BY ordinality), ARRAY[]::TEXT[])
    INTO v_main_skills FROM matched;

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
      AND enrichment_status = 'processing'
    RETURNING TRUE INTO v_applied;
    IF NOT COALESCE(v_applied, FALSE) THEN RETURN FALSE; END IF;

    DELETE FROM public.job_skills WHERE job_id = p_job_id;
    WITH parsed AS (
        SELECT item.ordinality, item.value ->> 'name' AS skill_name,
            CASE WHEN (item.value ->> 'required_level') ~ '^[1-4]$'
                THEN (item.value ->> 'required_level')::SMALLINT ELSE 2::SMALLINT END AS required_level
        FROM jsonb_array_elements(
            CASE WHEN jsonb_typeof(COALESCE(p_skills, '[]'::JSONB)) = 'array'
                THEN COALESCE(p_skills, '[]'::JSONB) ELSE '[]'::JSONB END
        ) WITH ORDINALITY AS item(value, ordinality)
        WHERE jsonb_typeof(item.value) = 'object'
          AND NULLIF(btrim(item.value ->> 'name'), '') IS NOT NULL
    ), matched AS (
        SELECT DISTINCT ON (s.id) s.id AS skill_id, p.required_level, p.ordinality
        FROM parsed AS p JOIN public.skills AS s ON s.taxonomy_key = p.skill_name
        ORDER BY s.id, p.ordinality
    )
    INSERT INTO public.job_skills (job_id, skill_id, is_primary, required_level)
    SELECT p_job_id, skill_id, TRUE, required_level FROM matched
    ON CONFLICT (job_id, skill_id) DO UPDATE SET
        is_primary = EXCLUDED.is_primary,
        required_level = EXCLUDED.required_level;
    RETURN TRUE;
END
$$;

REVOKE ALL ON FUNCTION public.claim_job_enrichment(TEXT, TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.request_job_enrichment_priority(TEXT) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.read_priority_job_enrichment(INTEGER) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.claim_job_enrichment(TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.request_job_enrichment_priority(TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.read_priority_job_enrichment(INTEGER) TO service_role;

COMMIT;
