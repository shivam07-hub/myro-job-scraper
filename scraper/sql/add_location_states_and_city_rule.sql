-- Location release (CEO decision record 2026-10-04, Q1–Q9).
--
-- 1. jobs.location_states TEXT[] — the Indian state(s) a posting names or whose
--    cities it names. A posting that names only "Maharashtra" now has
--    location_city NULL and location_states {Maharashtra}, so Myro can show it
--    to Pune and Mumbai users but not Delhi users.
-- 2. public.location_vocab — one copy of the scraper's place list
--    (scraper/india_cities.json + location_vocab.py) that Myro and the rule
--    below read. Fill it with scraper/sql/seed_location_vocab.sql.
-- 3. A rule on jobs: a country or a state is never a city, for every writer
--    (scraper, browser extension, anything later). It cleans the value; it never
--    rejects a save.
-- 4. public.location_rule_violations() — the daily check. Every count should
--    be 0 once the rows written before this release have been re-scraped or aged
--    out (no backfill).
--
-- Order: this file, then seed_location_vocab.sql, then deploy Myro, then merge
-- the scraper. csv_importer refuses real writes until location_states exists.
-- Run manually in the Supabase SQL editor (project gipvxuugajkugntwkeiz).

ALTER TABLE public.jobs
    ADD COLUMN IF NOT EXISTS location_states TEXT[] NOT NULL DEFAULT '{}';

-- Backs Myro's state overlap filter (location_states.ov.{Maharashtra}).
CREATE INDEX IF NOT EXISTS idx_jobs_location_states_gin
    ON public.jobs USING GIN (location_states);


CREATE TABLE IF NOT EXISTS public.location_vocab (
    kind      TEXT NOT NULL CHECK (kind IN ('country', 'state', 'city', 'alias', 'metro')),
    key       TEXT NOT NULL,          -- lowercase match key
    canonical TEXT NOT NULL,          -- canonical name (metro: one member city per row)
    state     TEXT,                   -- Indian state for state/city/alias/metro rows
    PRIMARY KEY (kind, key, canonical)
);

ALTER TABLE public.location_vocab ENABLE ROW LEVEL SECURITY;

-- Public reference data: readable by everyone, writable only by the service role.
DROP POLICY IF EXISTS location_vocab_read ON public.location_vocab;
CREATE POLICY location_vocab_read ON public.location_vocab
    FOR SELECT TO anon, authenticated USING (true);


-- SECURITY DEFINER so the rule can read location_vocab under any writer's role.
CREATE OR REPLACE FUNCTION private.enforce_location_city_rule()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_city_key TEXT;
    v_state    TEXT;
BEGIN
    IF NEW.location_city IS NOT NULL THEN
        v_city_key := lower(btrim(NEW.location_city));
        IF length(v_city_key) <= 2
           OR v_city_key = lower(btrim(coalesce(NEW.location_country, '')))
           OR EXISTS (
               SELECT 1 FROM public.location_vocab v
               WHERE v.kind = 'country' AND v.key = v_city_key
           ) THEN
            -- "India", "IN", "United States": a country or a code, not a city.
            NEW.location_city := NULL;
        ELSE
            SELECT v.state INTO v_state
            FROM public.location_vocab v
            WHERE v.kind = 'state' AND v.key = v_city_key
            LIMIT 1;
            IF v_state IS NOT NULL THEN
                -- "Maharashtra": keep it as the posting's state, not its city.
                NEW.location_city := NULL;
                NEW.location_country := coalesce(NEW.location_country, 'India');
                IF NOT (v_state = ANY (coalesce(NEW.location_states, '{}'))) THEN
                    NEW.location_states := coalesce(NEW.location_states, '{}') || v_state;
                END IF;
            END IF;
        END IF;
    END IF;

    IF cardinality(NEW.locations) > 0 THEN
        NEW.locations := coalesce(array(
            SELECT l
            FROM unnest(NEW.locations) WITH ORDINALITY AS t(l, i)
            WHERE length(btrim(l)) > 2
              AND NOT EXISTS (
                  SELECT 1 FROM public.location_vocab v
                  WHERE v.kind IN ('country', 'state') AND v.key = lower(btrim(l))
              )
            ORDER BY i
        ), '{}');
    END IF;

    RETURN NEW;
END;
$$;

REVOKE ALL ON FUNCTION private.enforce_location_city_rule() FROM PUBLIC;

DROP TRIGGER IF EXISTS enforce_location_city_rule ON public.jobs;
CREATE TRIGGER enforce_location_city_rule
    BEFORE INSERT OR UPDATE OF location_city, location_country, locations, location_states
    ON public.jobs
    FOR EACH ROW EXECUTE FUNCTION private.enforce_location_city_rule();


-- The daily check. csv_importer logs it after every publish.
CREATE OR REPLACE FUNCTION public.location_rule_violations()
RETURNS jsonb
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
    WITH active AS (
        SELECT j.location_city,
               j.location_country,
               lower(btrim(j.location_city)) AS city_key
        FROM public.jobs j
        WHERE j.is_active
    ),
    flagged AS (
        SELECT a.*,
               EXISTS (SELECT 1 FROM public.location_vocab v
                       WHERE v.kind = 'country' AND v.key = a.city_key) AS city_is_country_word,
               EXISTS (SELECT 1 FROM public.location_vocab v
                       WHERE v.kind = 'state' AND v.key = a.city_key) AS city_is_state_word,
               EXISTS (SELECT 1 FROM public.location_vocab v
                       WHERE v.kind IN ('city', 'alias') AND v.key = a.city_key) AS city_is_indian
        FROM active a
    )
    SELECT jsonb_build_object(
        'city_is_country', count(*) FILTER (
            WHERE location_city IS NOT NULL
              AND (city_is_country_word OR length(city_key) <= 2
                   OR city_key = lower(btrim(location_country)))
        ),
        'city_is_state', count(*) FILTER (WHERE city_is_state_word),
        'outside_india', count(*) FILTER (
            WHERE location_country IS NOT NULL AND location_country <> 'India'
        ),
        'indian_city_without_country', count(*) FILTER (
            WHERE location_country IS NULL AND city_is_indian
        )
    )
    FROM flagged;
$$;

REVOKE ALL ON FUNCTION public.location_rule_violations() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.location_rule_violations() TO service_role;
