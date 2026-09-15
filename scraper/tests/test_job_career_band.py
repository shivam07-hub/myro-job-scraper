from __future__ import annotations

from job_career_band import normalize_job_career_band
from writer import to_canonical


def test_product_designer_uses_design_band_over_product_domain() -> None:
    assert normalize_job_career_band({
        "job_title": "Product Designer",
        "role_domain": "Product Management",
    }) == "design_creative"


def test_ui_engineer_uses_engineering_band() -> None:
    assert normalize_job_career_band({
        "job_title": "AI/UI Engineer",
    }) == "engineering_data"


def test_explicit_technical_occupation_beats_employer_function_word() -> None:
    assert normalize_job_career_band({
        "job_title": "Software Engineer, Finance Systems",
    }) == "engineering_data"


def test_sales_engineer_follows_the_customer_facing_path() -> None:
    assert normalize_job_career_band({
        "job_title": "Senior Sales Engineer",
    }) == "business_product_operations"


def test_legal_occupation_beats_incidental_data_word() -> None:
    assert normalize_job_career_band({
        "job_title": "Data Privacy Counsel",
    }) == "research_people_public_impact"


def test_training_role_is_people_impact_not_creative_design() -> None:
    assert normalize_job_career_band({
        "job_title": "Training Design and Delivery Leader",
    }) == "research_people_public_impact"


def test_actuarial_role_uses_finance_path() -> None:
    assert normalize_job_career_band({
        "job_title": "Senior Actuarial Lead",
    }) == "business_product_operations"


def test_role_domain_maps_mba_families_to_business_band() -> None:
    assert normalize_job_career_band({
        "job_title": "Strategy Associate",
        "role_domain": "Strategy & Consulting",
    }) == "business_product_operations"


def test_unknown_titles_do_not_invent_a_band() -> None:
    assert normalize_job_career_band({"job_title": "Associate"}) == ""


def test_employer_industry_does_not_determine_role_function() -> None:
    assert normalize_job_career_band({
        "job_title": "Specialist",
        "industry": "Technology",
    }) == ""


def test_canonical_writer_uses_controlled_business_unit_before_classification() -> None:
    row = to_canonical({
        "job_id": "finance-1",
        "title": "Associate",
        "raw_jd_text": "Prepare monthly financial reports and reconcile accounts.",
        "business_unit": "Finance",
    }, "Example Org")

    assert row["role_domain"] == "Finance"
    assert row["career_band"] == "business_product_operations"


def test_canonical_writer_publishes_career_band() -> None:
    row = to_canonical({
        "job_id": "policy-1",
        "title": "Graduate Policy Research Associate",
        "raw_jd_text": "Support policy research and stakeholder briefs for public programs.",
        "role_domain": "Research & Science",
    }, "Example Org")

    assert row["career_band"] == "research_people_public_impact"


def test_back_office_titles_resolve_without_a_model_call() -> None:
    """Real Stripe titles that reached the model pass unbanded on 2026-08-07.

    An unbanded job is withheld from publication, so a title this plain has to
    resolve deterministically rather than spend an inference call to be guessed.
    """
    for title in (
        "Accounts Receivable Manager",
        "Administrative Coordinator",
        "Social Media, Customer Support Associate",
    ):
        assert normalize_job_career_band({"job_title": title}) == (
            "business_product_operations"
        ), title


def test_administrative_does_not_capture_technical_administrators() -> None:
    for title in ("Database Administrator", "Systems Administrator"):
        assert normalize_job_career_band({"job_title": title}) == "engineering_data", title


def test_generic_business_words_from_the_withheld_set_resolve() -> None:
    """Titles withheld on 2026-08-08 that carry a plain business role word.

    Each resolves on the generic word, never on the employer's private prefix —
    "CBG:Circle Head - Liability" is banded by "circle head", so the same rule
    works for any company that writes the same role.
    """
    for title in (
        "AVC:Virtual Acquisition Manager-NRI",
        "DBAT:Campaign Manager",
        "DBAT:Channel Manager",
        "CBG:Circle Head - Liability",
        "CBG:Geography Head - Liability",
        "WBCG: MEG - State Head",
        "RPMG:Circle Portfolio Manager - CBG - Field - Ninety",
        "RB - Affluent Business:Investment specialist",
        "Manager - DAS/GGN/2546 - Due Diligence",
        "Manager - MS/BLR/4751- Managed Services",
        "Associate Director - DAS/MUM/4498 - Deal Value Creation",
    ):
        assert normalize_job_career_band({"job_title": title}) == (
            "business_product_operations"
        ), title


def test_no_employer_prefix_is_hardcoded() -> None:
    """A bare division code carries no role evidence and must stay unbanded."""
    for title in ("CBG:", "WBCG - Team", "DBAT:Team"):
        assert normalize_job_career_band({"job_title": title}) == "", title


def test_technical_support_stays_engineering() -> None:
    assert normalize_job_career_band({
        "job_title": "Technical Support Engineer",
    }) == "engineering_data"


def test_second_pass_generic_words_resolve() -> None:
    """Withheld titles from the full 2026-08-08 set, banded on generic words."""
    business = (
        "Climate Risk Analyst - ERM",
        "Assistant Vice President, Team Lead, Operational Risk Management",
        "Analyst, Client Services, Small Medium Enterprises",
        "Divisional Vendor Manager Associate (IB DVMO), AS",
        "Global Sourcing & Supply Manager",
        "IB Divisional Control Office - Assurance / CDA, AVP/VP",
        "ALYST, Specialist, Know Your Customer, Small Medium Enterprises",
        "IN-Business Expert",
        "Business Management Analyst, NCT",
    )
    for title in business:
        assert normalize_job_career_band({"job_title": title}) == (
            "business_product_operations"
        ), title

    assert normalize_job_career_band({
        "job_title": "Senior Associate, Specialist, Employee Relations",
    }) == "research_people_public_impact"


def test_risk_does_not_outrank_an_explicit_technical_occupation() -> None:
    for title in ("Risk Engineer", "Risk Data Scientist", "Security Risk Architect"):
        assert normalize_job_career_band({"job_title": title}) == "engineering_data", title


def test_unbandable_non_roles_stay_empty() -> None:
    """Not every posting names a function; these must stay withheld, not guessed."""
    for title in ("Return to Work Fellowship 2026", "Fixed Term Appointment", "IN-Expert"):
        assert normalize_job_career_band({"job_title": title}) == "", title


def test_data_scientist_is_engineering_not_public_impact() -> None:
    """The band guide puts "data, AI" in engineering_data.

    `scientist` lives in _PUBLIC_IMPACT_OCCUPATION and runs before the technical
    check, so these compounds have to be claimed first or every Data Scientist
    lands in research/people/public impact — and drops out of the technical
    keep-set that scrape_select uses when a company is over its cap.
    """
    for title in (
        "Data Scientist",
        "Senior Machine Learning Scientist",
        "Applied Scientist II",
        "Decision Scientist",
        "Research Engineer, Speech",
    ):
        assert normalize_job_career_band({"job_title": title}) == "engineering_data", title


def test_clinical_research_scientist_stays_public_impact() -> None:
    for title in ("Research Scientist, Oncology", "Clinical Scientist"):
        assert normalize_job_career_band({"job_title": title}) == (
            "research_people_public_impact"
        ), title
