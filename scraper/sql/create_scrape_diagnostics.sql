-- Create diagnostics table for scraper run observability.
-- Run once in Supabase SQL editor.

create table if not exists public.scrape_diagnostics (
  id bigserial primary key,
  run_id text not null,
  scope text not null check (scope in ('india', 'global')),
  started_at timestamptz,
  ended_at timestamptz,
  company_name text not null,
  ats text,
  raw_jobs integer default 0,
  saved_new integer default 0,
  status text,
  reason text,
  details text,
  created_at timestamptz not null default now()
);

create index if not exists idx_scrape_diag_run_id
  on public.scrape_diagnostics (run_id);

create index if not exists idx_scrape_diag_company
  on public.scrape_diagnostics (company_name);

create index if not exists idx_scrape_diag_status
  on public.scrape_diagnostics (status);

create index if not exists idx_scrape_diag_created_at
  on public.scrape_diagnostics (created_at desc);
