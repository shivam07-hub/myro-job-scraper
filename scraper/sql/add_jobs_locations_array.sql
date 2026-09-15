-- firecrawl #6 — per-city capture for multi-location postings.
--
-- Adds jobs.locations TEXT[] alongside the existing scalar location_city.
-- Scalar location_city stays the PRIMARY/first city (back-compat + the
-- location_country match filter in True_Yodha); locations[] carries every
-- city for postings the ATS lists under "N Locations".
--
-- csv_importer._normalize_location emits this array on every upsert; the
-- importer sends `locations` unconditionally, so this column MUST exist before
-- the next load or upserts will fail.
--
-- Run manually in the Supabase SQL editor (project gipvxuugajkugntwkeiz).

ALTER TABLE public.jobs
    ADD COLUMN IF NOT EXISTS locations TEXT[] NOT NULL DEFAULT '{}';

-- GIN index backs True_Yodha's containment filter (locations.cs.{city}).
CREATE INDEX IF NOT EXISTS idx_jobs_locations_gin
    ON public.jobs USING GIN (locations);

-- Optional backfill: seed locations[] from the existing scalar city for rows
-- that already resolved to a single known city. Multi-location rows
-- (location_quality='unknown') are left for a re-scrape that can recover the
-- individual cities from the source posting.
UPDATE public.jobs
SET locations = ARRAY[location_city]
WHERE location_city IS NOT NULL
  AND location_city <> ''
  AND (locations IS NULL OR locations = '{}');
