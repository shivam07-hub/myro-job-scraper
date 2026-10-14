-- Let the publish lifecycle page through one company's jobs in job_id order.
-- trusted_job_lifecycle._fetch_company_jobs reads 1,000 rows per request,
-- keyed on job_id. With only (company_id) indexed, every page re-read and
-- re-sorted the whole company: 2-8 s per page for Axis Bank's ~16.8k rows,
-- past PostgREST's 8 s statement timeout under load (measured 2026-10-14).
-- CONCURRENTLY builds without blocking writes; run it outside a transaction.

create index concurrently if not exists idx_jobs_company_id_job_id
  on public.jobs (company_id, job_id);
