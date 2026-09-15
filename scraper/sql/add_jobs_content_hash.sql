-- Optional change signal for True_Yodha job embeddings.
-- The scraper never writes jobs.embedding. This hash lets True_Yodha re-embed
-- only jobs whose title/JD/skill content changed across re-scrapes.

ALTER TABLE public.jobs
ADD COLUMN IF NOT EXISTS job_content_hash TEXT;

CREATE INDEX IF NOT EXISTS idx_jobs_job_content_hash
ON public.jobs (job_content_hash);
