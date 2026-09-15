-- Skill definitions enrichment — adds a human-readable description to each taxonomy skill.
-- Description is a property of the SKILL (one row per skill in public.skills), NOT of the
-- job<->skill edge (public.job_skills) — storing it on job_skills would duplicate every
-- definition across hundreds of edges. Home is public.skills, which already carries
-- lightcast_id / l1_domain / l2_cluster.
--
-- Source: Lightcast Open Skills public skill page <meta name="description"> (server-rendered,
-- no JS / no Firecrawl credits). Populated by scraper/skill_descriptions.py.
-- Forward-only: NULL means "not fetched yet" — the recurring job self-heals the gap.
--
-- Run once in the Supabase SQL editor before the first --write-supabase run.

alter table public.skills
  add column if not exists description text;

alter table public.skills
  add column if not exists description_source text;

alter table public.skills
  add column if not exists description_fetched_at timestamptz;

-- Cheap partial index to find the still-missing set fast on each recurring run.
create index if not exists idx_skills_description_missing
  on public.skills (id)
  where description is null;
