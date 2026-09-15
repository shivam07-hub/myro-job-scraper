-- Create feed run audit table for location quality monitoring.
-- Run once in Supabase SQL editor.

create table if not exists public.job_feed_run_audits (
  id bigserial primary key,
  run_id uuid not null unique,
  source text not null default 'job_feed_importer',
  parser_version text not null,
  total_rows integer not null default 0,
  unknown_location_rows integer not null default 0,
  unknown_location_rate numeric(6,5) not null default 0
    check (unknown_location_rate >= 0 and unknown_location_rate <= 1),
  top_unknown_aliases jsonb not null default '[]'::jsonb,
  status text not null default 'ok' check (status in ('ok', 'blocked')),
  message text,
  created_at timestamptz not null default now()
);

create index if not exists idx_job_feed_run_audits_created_at
  on public.job_feed_run_audits(created_at desc);
