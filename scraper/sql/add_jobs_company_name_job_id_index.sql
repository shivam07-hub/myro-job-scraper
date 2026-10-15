-- Let a company-wide summary repair page jobs in job_id order.
-- source_snapshot.fill_blank_summaries filters on company_name, not
-- company_id. Those sets differ (Axis Bank: 17,657 rows by name, 16,759
-- by company_id), so idx_jobs_company_id_job_id does not serve this read.
-- With only (company_name, is_active), each page re-sorts the company.
-- That re-sort timed out on the company_id read at ~16.8k rows
-- (measured 2026-10-14). CONCURRENTLY builds without blocking writes;
-- run it outside a transaction, before repairing a large company.

create index concurrently if not exists idx_jobs_company_name_job_id
  on public.jobs (company_name, job_id);
