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


# Real JD phrasings from the 2026-09-09 publication that the parser missed:
# the label comes first, then a separator, then the years.
import pytest


@pytest.mark.parametrize(
    ("description", "level", "minimum", "maximum"),
    [
        ("Experience: 8-10 Years", "lead", 8, 10),
        ("Qualifications: BCom Years of Experience: 7 to 11 years About Accenture", "senior", 7, 11),
        ("Title: SCCM Total Years of Experience: 6 years to 10 years Location: Bengaluru", "senior", 6, 10),
        ("Aruba, cisco routing, Architect, SDVAN Exp - 10 - 15 years C1 Immediate only", "lead", 10, 15),
        ("Location: Bangalore Experience:- 7-12yrs", "senior", 7, 12),
        ("Work Experience (Range of years): 10-12 Years Preferred Industry", "lead", 10, 12),
        ("Pharma Experience Tenure : 3-5 Yrs Your Success Matters to Us", "mid", 3, 5),
        ("Location: Hyderabad Experience Range: 3–15 Years Qualification: B.Tech", "mid", 3, 15),
        ("Industry Background: Banking • Overall experience: More than 1 year", "entry", 1, None),
    ],
)
def test_normalize_job_seniority_reads_labelled_experience(description, level, minimum, maximum) -> None:
    normalized = normalize_job_seniority({
        "job_title": "Delivery Operations Specialist",
        "job_description": description,
    })

    assert normalized.seniority_level == level
    assert normalized.min_years_experience == minimum
    assert normalized.max_years_experience == maximum


def test_normalize_job_seniority_reads_year_s_unit() -> None:
    normalized = normalize_job_seniority({
        "job_title": "Automotive ECU Software",
        "job_description": "Minimum 2 year(s) of experience is required.",
    })

    assert normalized.seniority_level == "mid"
    assert normalized.min_years_experience == 2


@pytest.mark.parametrize(
    "description",
    [
        "Experience matters. 35 years of legacy in retail.",
        "Experience with 3D modelling tools.",
        "Experience: see the list below.\nFounded 40 years ago.",
    ],
)
def test_normalize_job_seniority_labelled_experience_stays_in_its_clause(description) -> None:
    normalized = normalize_job_seniority({
        "job_title": "Specialist",
        "job_description": description,
    })

    assert normalized.seniority_level == ""
    assert normalized.min_years_experience is None


@pytest.mark.parametrize("level", ["intern", "entry", "mid", "senior", "lead", "executive"])
def test_normalize_job_seniority_is_idempotent_on_canonical_levels(level) -> None:
    # source_matching_facts re-normalizes rows the writer already stamped; a
    # provider-only level must survive that second pass.
    normalized = normalize_job_seniority({
        "job_title": "Researcher",
        "seniority_level": level,
    })

    assert normalized.seniority_level == level


def test_normalize_job_seniority_drops_a_maximum_below_the_minimum() -> None:
    normalized = normalize_job_seniority({
        "job_title": "Application Support Engineer",
        "job_description": (
            "Minimum 5 year(s) of experience is required. "
            "1-2 years of relevant experience in enterprise support will be considered."
        ),
    })

    assert normalized.seniority_level == "senior"
    assert normalized.min_years_experience == 5
    assert normalized.max_years_experience is None
