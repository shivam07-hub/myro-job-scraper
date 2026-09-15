from __future__ import annotations

from jd_skill_evidence import extract_skill_evidence


def test_extracts_explicit_required_and_preferred_skill_evidence() -> None:
    jd = """
    Required Skills
    Must have 5+ years of Python and SQL experience.

    Preferred Qualifications
    Exposure to Kubernetes is preferred.

    Responsibilities
    Partner with product teams and own stakeholder management.
    """

    evidence = extract_skill_evidence(
        jd,
        candidates=[
            "Python (Programming Language)",
            "SQL (Programming Language)",
            "Kubernetes",
            "Stakeholder Management",
        ],
    )

    by_name = {item["name"]: item for item in evidence}

    assert by_name["Python (Programming Language)"]["zone"] == "mandatory"
    assert by_name["Python (Programming Language)"]["required_level"] == 4
    assert by_name["SQL (Programming Language)"]["required_level"] == 4
    assert by_name["Kubernetes"]["zone"] == "preferred"
    assert by_name["Kubernetes"]["required_level"] == 1
    assert by_name["Stakeholder Management"]["zone"] == "responsibilities"
    assert by_name["Stakeholder Management"]["required_level"] == 2


def test_skill_matching_respects_word_boundaries() -> None:
    jd = """
    Required qualifications
    Own governance dashboards and improve go-to-market reporting.
    """

    evidence = extract_skill_evidence(
        jd,
        candidates=["Go (Programming Language)", "Governance"],
    )

    names = [item["name"] for item in evidence]
    assert "Governance" in names
    assert "Go (Programming Language)" not in names


def test_keeps_strongest_evidence_for_duplicate_skill() -> None:
    jd = """
    Preferred
    Exposure to Python is a plus.

    Minimum Qualifications
    Strong Python experience building production services.
    """

    evidence = extract_skill_evidence(jd, candidates=["Python (Programming Language)"])

    assert evidence == [
        {
            "name": "Python (Programming Language)",
            "required_level": 3,
            "zone": "mandatory",
            "evidence": "Strong Python experience building production services.",
        }
    ]
