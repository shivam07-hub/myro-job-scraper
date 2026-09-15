from __future__ import annotations

from job_seniority import normalize_job_seniority
from writer import to_canonical


def test_normalize_job_seniority_prefers_explicit_title_level() -> None:
    normalized = normalize_job_seniority({
        "job_title": "Vice President, People Operations",
        "job_description": "Minimum 10 years of professional experience.",
    })

    assert normalized.seniority_level == "executive"
    assert normalized.min_years_experience == 10


def test_normalize_job_seniority_emits_entry_for_graduate_role() -> None:
    normalized = normalize_job_seniority({
        "job_title": "Graduate Research Associate",
        "job_description": "0-1 years of experience in research, writing, or policy analysis.",
    })

    assert normalized.seniority_level == "entry"
    assert normalized.min_years_experience == 0
    assert normalized.max_years_experience == 1


def test_normalize_job_seniority_uses_experience_when_title_is_ambiguous() -> None:
    normalized = normalize_job_seniority({
        "job_title": "Policy Researcher",
        "job_description": "Requires 5+ years of relevant experience.",
    })

    assert normalized.seniority_level == "senior"
    assert normalized.min_years_experience == 5


def test_normalize_job_seniority_reads_requirements_years_without_experience_word() -> None:
    normalized = normalize_job_seniority({
        "job_title": "Gold Loan Officer",
        "job_description": "Requirements: 2 to 6 years of handling Gold Loan Operations.",
    })

    assert normalized.seniority_level == "mid"
    assert normalized.min_years_experience == 2
    assert normalized.max_years_experience == 6


def test_normalize_job_seniority_reads_experience_before_year_range() -> None:
    normalized = normalize_job_seniority({
        "job_title": "Business Management Support",
        "job_description": "Preferable expert experience of 8-10 years in a similar role.",
    })

    assert normalized.seniority_level == "lead"
    assert normalized.min_years_experience == 8
    assert normalized.max_years_experience == 10


def test_normalize_job_seniority_ignores_age_and_benefit_years() -> None:
    normalized = normalize_job_seniority({
        "job_title": "Specialist",
        "job_description": "Complementary health screening for 35 yrs and above.",
    })

    assert normalized.seniority_level == ""
    assert normalized.min_years_experience is None


def test_normalize_job_seniority_canonicalizes_provider_level() -> None:
    normalized = normalize_job_seniority({
        "job_title": "People Operations Specialist",
        "seniority_level": "Junior",
        "min_years_experience": "1.0",
    })

    assert normalized.seniority_level == "entry"
    assert normalized.min_years_experience == 1


def test_normalize_job_seniority_does_not_invent_a_level() -> None:
    normalized = normalize_job_seniority({
        "job_title": "Researcher",
        "job_description": "Work with a collaborative team.",
    })

    assert normalized.seniority_level == ""
    assert normalized.min_years_experience is None
    assert normalized.max_years_experience is None


def test_canonical_writer_publishes_normalized_source_fields() -> None:
    row = to_canonical({
        "job_id": "policy-1",
        "title": "Vice President, Public Policy",
        "raw_jd_text": "Requires 12+ years of public-policy experience.",
    }, "Example Org")

    assert row["seniority_level"] == "executive"
    assert row["min_years_experience"] == 12
