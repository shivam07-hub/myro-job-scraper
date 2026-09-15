-- Add the scraper-owned proficiency signal used by the consumption layer.
-- Run once in the Supabase SQL editor before uploading level-aware enrichment.

alter table public.job_skills
  add column if not exists required_level smallint not null default 2;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'job_skills_required_level_check'
      and conrelid = 'public.job_skills'::regclass
  ) then
    alter table public.job_skills
      add constraint job_skills_required_level_check
      check (required_level between 1 and 4);
  end if;
end $$;

create index if not exists idx_job_skills_required_level
  on public.job_skills(required_level);
