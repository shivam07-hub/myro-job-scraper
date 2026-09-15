# CV-Tailoring Enrichment Design

**Date:** 2026-07-03

**Status:** Approved for specification

## Goal

Turn Phase 2 enrichment into a CV-tailoring data layer that helps a user map
their own CV to a job description. The system should keep the existing
relational skill backbone, then add compact candidate-profile guidance that
explains how the job's requirements should appear in a strong CV.

Primary use case: CV tailoring.

Secondary use cases that should naturally follow:

- CV-to-JD gap analysis
- Candidate readiness scoring
- Project recommendations for weak areas
- Interview preparation themes
- Role clustering by candidate archetype

## Operating Constraints

- All work stays under `/Users/incognito/firecrawl_Supabase/`.
- No closed or proprietary cloud model APIs are allowed.
- Enrichment uses local LM Studio/Ollama or an approved remote
  OpenAI-compatible endpoint serving an open-weight model.
- Supabase/Postgres remains the production persistence target.
- `job_skills` remains the canonical skill relationship table.
- The candidate profile must optimize for compute, speed, storage, and
  transfer cost.
- A job whose source JD has not changed must not be regenerated.
- Scrape-only counts remain provisional until final Supabase import.

## Cost Philosophy

Maximize reusable signal per model token, database row, and network transfer.

The pipeline should avoid verbose generated text when structured, reusable
facts are enough. It should preserve relational facts that support joins,
filters, analytics, and CV matching, while storing only compact prose where
human-facing guidance is genuinely valuable.

The design favors:

- One model call per job instead of separate skills and profile calls
- Cleaned, compressed JD input instead of raw full-page text
- Retrieved skill candidates instead of asking the model to rediscover skills
- Compact JSONB guidance instead of long narrative prose
- Hash-based skip logic instead of repeated generation
- Batch checkpoints so interrupted runs resume without wasted work

## Existing Data Backbone

The current job pipeline already has the right foundation:

```text
jobs
  job_id
  job_title
  job_description
  job_summary
  company_name
  industry
  industry_group
  role_domain
  location fields

job_skills
  job_id
  skill_id
  required_level
  is_primary

skills
  id
  taxonomy_key
  description
  taxonomy hierarchy
```

`job_skills` should not be collapsed into encoded strings such as
`python_2`. Those strings are useful as optional read caches, but they should
not become the source of truth. The relational table protects taxonomy
integrity, supports joins, and keeps CV matching explainable.

## Recommended Storage Model

Add one compact profile table:

```text
job_candidate_profiles
  job_id primary key references jobs(job_id)
  profile_version text not null
  generated_from_hash text not null
  ideal_candidate_summary text not null
  cv_positioning jsonb not null
  proof_points jsonb not null
  gap_risks jsonb not null
  project_suggestions jsonb not null
  resume_keywords jsonb not null
  interview_themes jsonb not null
  model_name text
  created_at timestamptz not null default now()
  updated_at timestamptz not null default now()
```

Field intent:

- `ideal_candidate_summary`: one compact sentence or short paragraph describing
  the candidate archetype.
- `cv_positioning`: 3-5 bullets explaining how to frame the user's CV for this
  role.
- `proof_points`: 4-6 evidence items the CV should demonstrate, such as
  shipped systems, ownership, metrics, domain exposure, or stakeholder work.
- `gap_risks`: 2-4 missing signals that would weaken the application.
- `project_suggestions`: 2-4 portfolio or work-example ideas that could close
  gaps.
- `resume_keywords`: 8-12 terse keywords useful for tailoring and retrieval.
- `interview_themes`: 3-5 themes likely to matter in screening or interviews.

The table stores guidance once per job, not repeated per user. User-specific CV
tailoring can later combine this profile with a user's CV data without
regenerating the job profile.

## Deferred Optional Cache

If read performance or transfer size becomes a bottleneck, add a compact cache
on `jobs` or a materialized view:

```text
skill_level_keys = ["python:2", "sql:3", "stakeholder-management:2"]
```

This is a cache only. It must be derived from `job_skills` and never replace
the relational source of truth.

## Phase 2 Enrichment Flow

The preferred Phase 2 pass generates both existing enrichment and the new
candidate profile in one call.

```text
jobs.json
  -> clean JD text
  -> retrieve Lightcast skill candidates
  -> one open-weight model call
  -> validate skills, levels, role_domain, summary, profile JSON
  -> write enriched local jobs.json and profile checkpoint
  -> Supabase dry-run
  -> Supabase import
```

The model input should include only:

- Job title
- Compact cleaned JD excerpt
- Existing company/industry/role metadata where useful
- A short retrieved skill candidate list
- The required JSON schema

The model output should include:

- `job_summary`
- `role_domain`
- `skills[]` with `name` and `required_level`
- `candidate_profile`

## Input Compression

Before inference, strip or down-rank:

- Company marketing boilerplate
- Equal opportunity and legal blocks
- Benefits, office perks, and repeated HR text
- Navigation text and page chrome
- Duplicate sections
- Long lists that do not describe role requirements

Retain:

- Responsibilities
- Required qualifications
- Preferred qualifications
- Experience requirements
- Tools, technologies, methods, and domain context
- Ownership, seniority, and success signals

The system should prefer a dense 1,200-1,800 character role-relevant input over
the full raw JD. The raw JD remains stored on `jobs.job_description`; the model
does not need all of it for every call.

## Output Contract

The candidate profile output must be compact and structured:

```json
{
  "ideal_candidate_summary": "Backend engineer with production API ownership, strong SQL, cloud deployment exposure, and evidence of reliable service delivery.",
  "cv_positioning": [
    "Lead with backend systems ownership and measurable reliability or performance outcomes.",
    "Show API, database, and deployment work through concrete projects."
  ],
  "proof_points": [
    "Production API shipped or maintained",
    "SQL query or data model ownership",
    "Incident, latency, scale, or reliability metric"
  ],
  "gap_risks": [
    "No evidence of production ownership",
    "Skills listed without project context"
  ],
  "project_suggestions": [
    "Build a deployed API with auth, migrations, logging, and monitoring."
  ],
  "resume_keywords": ["Python", "REST APIs", "SQL", "AWS", "CI/CD"],
  "interview_themes": ["system reliability", "database tradeoffs", "API design"]
}
```

Validation caps:

- `ideal_candidate_summary`: max 60 words
- `cv_positioning`: max 5 items, each max 140 characters
- `proof_points`: max 6 items, each max 100 characters
- `gap_risks`: max 4 items, each max 120 characters
- `project_suggestions`: max 4 items, each max 160 characters
- `resume_keywords`: max 12 items, each max 40 characters
- `interview_themes`: max 5 items, each max 60 characters

These caps keep transfer and storage predictable.

## Hash And Resume Strategy

Compute `generated_from_hash` from:

- `job_id`
- `job_title`
- cleaned JD text
- retrieved skill candidate names
- profile schema version

If the same job already has a profile with the same hash and profile version,
skip generation.

Local checkpoints should record:

- job_id
- generated_from_hash
- generation status
- validation errors
- model name
- profile version

Checkpoints must not duplicate full JD text.

## Supabase Import Strategy

Phase 3 should remain dry-run first.

The importer should:

1. Confirm the `job_candidate_profiles` table contract.
2. Upsert `jobs` and `job_skills` as it does today.
3. Upsert candidate profiles only after profile validation passes.
4. Report profile coverage alongside enriched skill coverage.
5. Avoid official health diagnostics until final import succeeds.

Profile rows should be upserted on `job_id`. The importer should avoid partial
profile writes if job upsert fails.

## Failure Handling

- If the model returns invalid profile JSON, keep the job enriched with any
  valid skills, but do not write a profile row.
- If skills validate but profile fails, record a profile validation error for
  retry.
- If the inference endpoint is unavailable, stop Phase 2 before starting a
  large run.
- If a run is interrupted, resume from checkpoints and hash-skipped rows.
- If profile generation quality is weak for a role family, adjust prompt and
  validation before increasing model size.

## Rollout

1. Write and review the implementation plan.
2. Add the Supabase table migration.
3. Add local profile validation tests.
4. Update enrichment to produce the combined output in one call.
5. Add profile checkpoints and hash-skip behavior.
6. Update importer dry-run to check profile table contract.
7. Run a small pilot on 10-20 jobs across varied role domains.
8. Review profile quality manually.
9. Run Phase 2 for the fresh scrape only when the pilot is acceptable.
10. Run Supabase dry-run, then import.

## Verification

Required checks before broad Phase 2:

- Unit tests for profile validation and field caps
- Unit tests for hash skip behavior
- Unit tests that `job_skills` remains the source of truth
- Importer dry-run against Supabase
- Pilot output review for usefulness in CV tailoring
- Enrichment endpoint smoke test against the configured open-weight model

The feature is accepted when one enrichment pass can produce validated skills
and compact CV-tailoring profiles, skip unchanged jobs, resume after
interruption, and dry-run cleanly against Supabase without increasing model
calls beyond one call per generated job.
