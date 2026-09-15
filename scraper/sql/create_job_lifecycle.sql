-- Job lifecycle + meaningful-change version history.
-- Run once in Supabase SQL editor.

-- 1) Add lifecycle fields to current jobs table.
alter table public.jobs
  add column if not exists first_seen integer,
  add column if not exists last_seen integer,
  add column if not exists is_active boolean default true,
  add column if not exists change_fingerprint text;

create index if not exists idx_jobs_company_active
  on public.jobs (company_name, is_active);

create index if not exists idx_jobs_last_seen
  on public.jobs (last_seen desc);

-- 2) Version table: only meaningful changes are recorded.
create table if not exists public.job_versions (
  id bigserial primary key,
  job_id text not null,
  company_name text not null,
  batch_date integer not null,
  change_type text not null check (change_type in ('insert', 'update', 'deactivate')),
  changed_fields text[] default '{}',
  old_fingerprint text,
  new_fingerprint text,
  old_snapshot jsonb,
  new_snapshot jsonb,
  created_at timestamptz not null default now()
);

create index if not exists idx_job_versions_job_id
  on public.job_versions (job_id);

create index if not exists idx_job_versions_company_batch
  on public.job_versions (company_name, batch_date desc);

create index if not exists idx_job_versions_change_type
  on public.job_versions (change_type);
