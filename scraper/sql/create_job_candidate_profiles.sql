-- CV-tailoring Phase 2 profile table.
--
-- Stores compact per-job candidate guidance generated from the JD + relational
-- job_skills evidence. The table is scraper-owned and backend-readable through
-- the service role; do not expose it directly to anon/authenticated clients
-- until a product API and RLS policy are deliberately designed.
--
-- Run manually in the Supabase SQL editor (project gipvxuugajkugntwkeiz).

CREATE TABLE IF NOT EXISTS public.job_candidate_profiles (
    job_id                  TEXT PRIMARY KEY REFERENCES public.jobs(job_id) ON DELETE CASCADE,
    profile_version         TEXT NOT NULL,
    generated_from_hash     TEXT NOT NULL,
    ideal_candidate_summary TEXT NOT NULL,
    cv_positioning          JSONB NOT NULL DEFAULT '[]'::jsonb,
    proof_points            JSONB NOT NULL DEFAULT '[]'::jsonb,
    gap_risks               JSONB NOT NULL DEFAULT '[]'::jsonb,
    project_suggestions     JSONB NOT NULL DEFAULT '[]'::jsonb,
    resume_keywords         JSONB NOT NULL DEFAULT '[]'::jsonb,
    interview_themes        JSONB NOT NULL DEFAULT '[]'::jsonb,
    model_name              TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.job_candidate_profiles ENABLE ROW LEVEL SECURITY;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.job_candidate_profiles TO service_role;

CREATE INDEX IF NOT EXISTS idx_job_candidate_profiles_version
    ON public.job_candidate_profiles (profile_version);

CREATE INDEX IF NOT EXISTS idx_job_candidate_profiles_hash
    ON public.job_candidate_profiles (generated_from_hash);
