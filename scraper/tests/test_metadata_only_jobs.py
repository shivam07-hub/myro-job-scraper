from __future__ import annotations

from main import _needs_enrichment
from schema import MISSING_JD_NOTE


def test_missing_jd_note_does_not_need_enrichment() -> None:
    assert _needs_enrichment({
        "job_description": MISSING_JD_NOTE,
        "main_skills": [],
        "skills": [],
    }) is False


def test_real_jd_without_skills_still_needs_enrichment() -> None:
    assert _needs_enrichment({
        "job_description": "This role owns manufacturing quality systems, supplier coordination, and audit readiness.",
        "main_skills": [],
        "skills": [],
    }) is True


def test_profile_only_gap_does_not_need_core_enrichment() -> None:
    assert _needs_enrichment({
        "job_description": "Build reliable data systems with Python and SQL.",
        "job_summary": "Build and maintain reliable data systems with Python and SQL.",
        "role_domain": "Data & Analytics",
        "main_skills": ["Python (Programming Language)"],
        "skills": [{"name": "Python (Programming Language)", "required_level": 2}],
        "candidate_profile": {},
    }) is False


def test_summary_and_domain_without_skills_is_terminal_enrichment() -> None:
    assert _needs_enrichment({
        "job_description": "Supports customers, stakeholders, and internal operations.",
        "job_summary": "Supports operational workflows and stakeholder coordination.",
        "role_domain": "Operations",
        "skills": [],
        "main_skills": [],
    }) is False
