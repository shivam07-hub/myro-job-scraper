-- Bootstrap the durable queue separately from the jobs-table migration.
--
-- Supabase Realtime observes DDL. Keeping pgmq queue creation in its own
-- transaction avoids holding an ACCESS EXCLUSIVE lock on public.jobs while
-- Realtime processes creation of the pgmq queue tables.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgmq;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pgmq.list_queues()
        WHERE queue_name = 'job_enrichment'
    ) THEN
        PERFORM pgmq.create('job_enrichment');
    END IF;
END
$$;

COMMIT;
