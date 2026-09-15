-- Correct the initial enrollment boundary from scraper ingestion date
-- (first_seen) to the source's actual posting date. Unknown or unparseable
-- dates are deliberately excluded rather than guessed recent.

BEGIN;

CREATE TEMP TABLE recent_posted_jobs_14d (
    job_id TEXT PRIMARY KEY
) ON COMMIT DROP;

INSERT INTO recent_posted_jobs_14d (job_id)
SELECT parsed.job_id
FROM (
    SELECT
        j.job_id,
        j.is_active,
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
) AS parsed
WHERE parsed.is_active IS TRUE
  AND parsed.posted_on BETWEEN
      (now() AT TIME ZONE 'Asia/Kolkata')::DATE - 13
      AND (now() AT TIME ZONE 'Asia/Kolkata')::DATE;

-- Return claims from deliberately stopped rollout consumers before narrowing.
UPDATE private.job_embeddings
SET status = CASE WHEN attempts >= 5 THEN 'failed' ELSE 'retryable' END,
    claim_token = NULL,
    started_at = NULL,
    last_error = 'rollout boundary corrected to source posting date'
WHERE status = 'processing';

DELETE FROM private.job_embeddings AS je
WHERE je.enrollment_reason = 'recent_backfill_14d'
  AND NOT EXISTS (
      SELECT 1
      FROM recent_posted_jobs_14d AS recent
      WHERE recent.job_id = je.job_id
  );

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
FROM recent_posted_jobs_14d AS recent
JOIN public.jobs AS j ON j.job_id = recent.job_id
ON CONFLICT (job_id) DO NOTHING;

UPDATE private.job_embeddings AS je
SET enrollment_reason = 'recent_posted_backfill_14d'
WHERE je.enrollment_reason = 'recent_backfill_14d'
  AND EXISTS (
      SELECT 1
      FROM recent_posted_jobs_14d AS recent
      WHERE recent.job_id = je.job_id
  );

COMMIT;
