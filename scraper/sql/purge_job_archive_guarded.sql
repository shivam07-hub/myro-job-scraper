-- Guarded historical-job purge for the Excel archive workflow.
--
-- Preconditions:
--   1. Export and verify the matching archive_jobs.json + archive_job_skills.json.
--   2. Use the same fixed YYYYMMDD cutoff as the archive manifest.
--   3. Run the preview first. The batch statement deletes at most 5,000 jobs.
--
-- Product safety:
--   - active jobs with NULL last_seen are not selected;
--   - no job with a user match, application, feedback event, or report is deleted;
--   - FK-owned non-user data (job_skills, embeddings, intelligence snapshots) cascades
--     from public.jobs by the existing database contract.

-- ── Preview: replace 20260531 only when creating a new archive ───────────────
WITH eligible AS (
  SELECT j.job_id
  FROM public.jobs AS j
  WHERE (
    j.is_active IS FALSE
    OR (j.last_seen IS NOT NULL AND j.last_seen < 20260531)
  )
  AND NOT EXISTS (
    SELECT 1 FROM public.user_job_matches AS m WHERE m.job_id = j.job_id
  )
  AND NOT EXISTS (
    SELECT 1 FROM public.job_applications AS a WHERE a.job_id = j.job_id
  )
  AND NOT EXISTS (
    SELECT 1 FROM public.job_feedback_events AS f WHERE f.job_id = j.job_id
  )
  AND NOT EXISTS (
    SELECT 1 FROM public.job_reports AS r WHERE r.job_id = j.job_id
  )
)
SELECT count(*) AS purge_eligible_jobs
FROM eligible;

-- ── One bounded batch: run repeatedly until deleted_jobs = 0 ─────────────────
-- WITH batch AS (
--   SELECT j.job_id
--   FROM public.jobs AS j
--   WHERE (
--     j.is_active IS FALSE
--     OR (j.last_seen IS NOT NULL AND j.last_seen < 20260531)
--   )
--   AND NOT EXISTS (
--     SELECT 1 FROM public.user_job_matches AS m WHERE m.job_id = j.job_id
--   )
--   AND NOT EXISTS (
--     SELECT 1 FROM public.job_applications AS a WHERE a.job_id = j.job_id
--   )
--   AND NOT EXISTS (
--     SELECT 1 FROM public.job_feedback_events AS f WHERE f.job_id = j.job_id
--   )
--   AND NOT EXISTS (
--     SELECT 1 FROM public.job_reports AS r WHERE r.job_id = j.job_id
--   )
--   ORDER BY j.job_id
--   LIMIT 5000
-- ), deleted AS (
--   DELETE FROM public.jobs AS j
--   USING batch
--   WHERE j.job_id = batch.job_id
--   RETURNING j.job_id
-- )
-- SELECT count(*) AS deleted_jobs FROM deleted;

-- ── After all batches: reclaim reusable space and refresh stats ──────────────
-- VACUUM (ANALYZE, VERBOSE) public.jobs;
-- VACUUM (ANALYZE, VERBOSE) public.job_skills;
--
-- To return physical database bytes to the Free-plan quota, schedule a short
-- jobs-table maintenance window and run VACUUM FULL on each materially reduced
-- table. It takes an ACCESS EXCLUSIVE lock, so only run it after checking locks.
-- VACUUM FULL (ANALYZE, VERBOSE) public.jobs;
-- VACUUM FULL (ANALYZE, VERBOSE) public.job_skills;
