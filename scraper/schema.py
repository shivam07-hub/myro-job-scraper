"""
Canonical schema definition for the Dump 4+ job pipeline.

Single source of truth for:
  - Portal          — TypedDict for portal config dicts (ATS routing + metadata)
  - CANONICAL_FIELDS — ordered field list (matches Supabase `jobs` table columns)
  - RAW_FIELD_MAP    — scraper raw name → canonical name (for writer.to_canonical)
  - SKILL_FIELDS     — fields filled by LLM enrichment (enricher.py)
  - LEGACY_FIELD_ALIASES — older field names from pre-Dump4 dumps

Do not add fields here without also updating the Supabase DDL and CLAUDE.md.
"""
from __future__ import annotations
from typing import TypedDict

MIN_JOB_DESCRIPTION_LEN = 50
MISSING_JD_NOTE = (
    "No JD provided on the company page. Matching and skill extraction are "
    "unavailable for this role until a job description is published."
)


def is_missing_jd_description(value: str | None) -> bool:
    return (value or "").strip() == MISSING_JD_NOTE


class Portal(TypedDict, total=False):
    """
    Typed portal config dict produced by portal_reader.parse_portals().

    Required fields (total=False means all optional at type-check level,
    but company/ats/endpoint are always populated by portal_reader).
    ATS-specific fields (workday_*, sr_id, board_token, lever_slug) are only
    present for their respective ATS type.
    """
    # Universal
    company:      str   # display name — must match company_industries.json key
    ats:          str   # workday | smartrecruiters | greenhouse | lever | phenom_api
                        # | phenom_ssr | yello | sap_jobs2web_html | pepsico_jobs_api
                        # | skima_careers | deloitte_usi
                        # | apple_jobs | cognizant_xml | tata_elxsi | vector_consulting
                        # | deshaw_india | google_careers | intouchcx | microsoft_careers
                        # | hilabs_careers | blackbrix_jobs | icims_html | trakstar
                        # | sap | oracle | eightfold | avature | talentbrew | custom | other
                        # | ashby | rippling | dejobs_rss | talent500
    endpoint:     str   # URL to hit
    careers_url:  str   # human-facing careers page (fallback / reference)
    js_required:  bool  # True → route through FirecrawlJSProvider
    india_only:   bool  # True → apply is_india() filter post-scrape
    status:       str   # raw emoji status string from KNOWN_PORTALS.md
    industry:     str   # from company_industries.json

    # Workday-specific
    tenant:               str
    instance:             str        # wd1 | wd3 | wd5 …
    career_site:          str        # career site slug in Workday URL
    workday_search_text:  str        # use searchText= filter (no India UUID)
    workday_facet_param:  str        # locationCountry | locations | locationHierarchy1 …
    workday_india_uuids:  list[str]  # one UUID (standard) or many (office-level)
    workday_it_facet_param: str
    workday_it_uuids:     list[str]

    # SmartRecruiters-specific
    sr_id:        str

    # Greenhouse-specific
    board_token:  str
    greenhouse_match_content: bool

    # Lever-specific
    lever_slug:   str

    # Talent500-specific
    talent500_company_slug: str

    # Phenom-specific (no extra fields beyond endpoint)

# Ordered canonical field list — the schema of the written jobs.json / jobs.csv.
# Mirrors the Supabase `jobs` table columns EXCEPT JSON-only enrichment fields:
# `skills` (consumed for job_skills) and `candidate_profile*` (consumed for
# job_candidate_profiles). Lifecycle columns (first_seen, last_seen, is_active,
# change_fingerprint) are Supabase-managed and not included here.
CANONICAL_FIELDS: list[str] = [
    "job_id",
    "job_title",
    "job_description",         # full raw JD (kept for Tailor CV / detail view)
    "job_summary",             # extractive at scrape; LLM upgrade later (card body)
    "industry",
    "industry_group",
    "company_name",
    "location",
    "location_raw",
    "location_city",
    "location_country",
    "location_mode",
    "location_quality",
    "locations",
    "apply_url",
    "source_url",
    "source_platform",
    "ingestion_source",
    "quality_status",
    "role_domain",
    "career_band",
    # Skills: ONE flat list. `skills` carries the structured {name, required_level}
    # objects consumed by csv_importer to write job_skills (the FK source of truth).
    # `main_skills` mirrors the same skill names (back-compat column True_Yodha reads
    # for chips); `side_skills` is deprecated and always [] (no primary/side split).
    # `skills` is a JSON-output field only — it is NOT a `jobs` table column
    # (see csv_importer._JOB_FIELDS, which gates the actual jobs upsert).
    "skills",
    "main_skills",
    "side_skills",
    # Candidate-profile fields are JSON-output only — imported into the
    # `job_candidate_profiles` table, not the `jobs` table.
    "candidate_profile",
    "candidate_profile_version",
    "candidate_profile_hash",
    "candidate_profile_model",
    "job_content_hash",        # scraper-owned change signal for True_Yodha job embeddings; not the vector
    # Structured facts surfaced as card chips (kept OUT of the JD blob).
    "date_posted",             # original posting date string from the ATS
    "seniority_level",         # canonical ladder from source metadata, title, and JD
    "work_mode",               # provider's own onsite/hybrid/remote signal
    "min_years_experience",    # int or '' — "2–4 yrs" chip
    "max_years_experience",    # int or ''
    "batch_date",
]

# Maps scraper raw dict keys → canonical keys (used by writer.to_canonical).
# Only covers the non-obvious renames; identity mappings (company_name) are omitted.
RAW_FIELD_MAP: dict[str, str] = {
    "title":         "job_title",
    "raw_jd_text":   "job_description",
    "location_city": "location",
    "job_url":       "apply_url",
}

# Fields populated by LLM enrichment (Phase 2 of the pipeline).
# `skills` (structured {name, required_level}) is the real output; `main_skills`
# is the back-compat name mirror; `side_skills` is deprecated (always []).
SKILL_FIELDS: tuple[str, ...] = ("skills", "main_skills", "side_skills")

# Aliases from pre-Dump4 schemas — used by csv_importer.normalize_job for
# backward-compatible reading of older dump files.
LEGACY_FIELD_ALIASES: dict[str, list[str]] = {
    "job_title":       ["title"],
    "job_description": ["raw_jd_text", "job_description"],
    "location":        ["Location", "location_city", "location", "location_country", "location_raw"],
    "apply_url":       ["job_url", "apply_url"],
    "main_skills":     ["main_skills", "skills_required"],
    "side_skills":     ["side_skills", "skills_preferred"],
}
