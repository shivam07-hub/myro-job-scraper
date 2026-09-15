-- Age-based delisting — last_seen older than 30 days.
--
-- Owned by source_snapshot after a full-scope publish (no --company canary).
-- Presence close (3 complete misses) is the primary clock for companies in
-- the run. This SQL is the manual/emergency equivalent of that 30-day
-- backstop: ghost jobs on the live feed after ~one month.
-- last_seen is an integer YYYYMMDD. NULL last_seen is left alone (extension
-- saved-job rows, not scraper inventory).
--
-- Closing starts a one-hour quarantine. True_Yodha archives then deletes.
-- This script must not DELETE rows.
--
-- SAFETY: run the PREVIEW first. Reactivation happens when a later complete
-- scrape sees the job again (apply_seen).

-- ── 1. PREVIEW ────────────────────────────────────────────────────────────────
WITH cutoff AS (SELECT to_char(current_date - 30, 'YYYYMMDD')::int AS d)
SELECT
    (SELECT d FROM cutoff)                                   AS cutoff_yyyymmdd,
    count(*) FILTER (WHERE is_active)                        AS active_total,
    count(*) FILTER (WHERE is_active
                     AND last_seen IS NOT NULL
                     AND last_seen < (SELECT d FROM cutoff)) AS would_delist
FROM public.jobs;

WITH cutoff AS (SELECT to_char(current_date - 30, 'YYYYMMDD')::int AS d)
SELECT company_name, count(*) AS delist_count
FROM public.jobs
WHERE is_active AND last_seen IS NOT NULL AND last_seen < (SELECT d FROM cutoff)
GROUP BY company_name
ORDER BY delist_count DESC;

-- ── 2. APPLY: uncomment only for a one-off repair ─────────────────────────────
-- WITH cutoff AS (SELECT to_char(current_date - 30, 'YYYYMMDD')::int AS d)
-- UPDATE public.jobs
-- SET is_active = false,
--     listing_confidence = 'closed',
--     confidence_reason = 'last_seen_older_than_30_days',
--     lifecycle_updated_at = now(),
--     quarantined_at = now(),
--     quarantine_until = now() + interval '1 hour',
--     deletion_eligible_at = now() + interval '1 hour',
--     retired_at = now()
-- WHERE is_active
--   AND last_seen IS NOT NULL
--   AND last_seen < (SELECT d FROM cutoff);
