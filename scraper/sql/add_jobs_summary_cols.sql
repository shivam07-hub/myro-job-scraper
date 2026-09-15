-- job-card hygiene — LLM job_summary + structured chip columns.
--
-- Adds the columns the job CARD renders from, so the frontend stops dumping the
-- raw job_description blob (which carries scrape junk like nav links / "Date
-- published" / requisition IDs for some providers, e.g. cognizant_xml).
--
--   job_summary           — LLM-generated, ≤100-word clean role summary (card body)
--   date_posted           — original ATS posting date string ("Posted Apr 21" chip)
--   seniority_level       — provider-supplied level (Entry/Mid/Senior chip)
--   work_mode             — provider's onsite/hybrid/remote signal
--   min/max_years_experience — experience range chip ("2–4 yrs")
--
-- The full raw job_description is KEPT (used for "Tailor CV" / detail view).
--
-- csv_importer._upsert_jobs sends all of these on every row, so they MUST exist
-- before the next real load — csv_importer.main() preflight-checks them
-- (_jobs_missing_card_columns) and raise SystemExit(2) on a real load if absent.
-- Dry-run continues regardless.
--
-- Run manually in the Supabase SQL editor (project gipvxuugajkugntwkeiz).

ALTER TABLE public.jobs
    ADD COLUMN IF NOT EXISTS job_summary           TEXT,
    ADD COLUMN IF NOT EXISTS date_posted           TEXT,
    ADD COLUMN IF NOT EXISTS seniority_level       TEXT,
    ADD COLUMN IF NOT EXISTS work_mode             TEXT,
    ADD COLUMN IF NOT EXISTS min_years_experience  SMALLINT,
    ADD COLUMN IF NOT EXISTS max_years_experience  SMALLINT;

-- Optional: lets the card feed cheaply filter "has a clean summary".
CREATE INDEX IF NOT EXISTS idx_jobs_has_summary
    ON public.jobs ((job_summary IS NOT NULL));
