-- Phase 3 contract columns for jobs table.
-- Run once in Supabase SQL editor.

alter table public.jobs
  add column if not exists role_domain text,
  add column if not exists industry_group text,
  add column if not exists location_city text,
  add column if not exists location_raw text,
  add column if not exists location_country text,
  add column if not exists location_mode text default 'unknown',
  add column if not exists location_quality text default 'unknown';

-- Keep existing rows queryable while forward-only normalized uploads take over.
update public.jobs
set location_raw = location
where location_raw is null
  and location is not null;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'jobs_location_mode_check'
  ) then
    alter table public.jobs
      add constraint jobs_location_mode_check
      check (location_mode in ('onsite', 'hybrid', 'remote', 'unknown'));
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'jobs_location_quality_check'
  ) then
    alter table public.jobs
      add constraint jobs_location_quality_check
      check (location_quality in ('ok', 'unknown'));
  end if;
end $$;

create index if not exists idx_jobs_role_domain
  on public.jobs(role_domain);

create index if not exists idx_jobs_industry_group
  on public.jobs(industry_group);

create index if not exists idx_jobs_location_city
  on public.jobs(location_city);

create index if not exists idx_jobs_location_country
  on public.jobs(location_country);

create index if not exists idx_jobs_location_mode
  on public.jobs(location_mode);
