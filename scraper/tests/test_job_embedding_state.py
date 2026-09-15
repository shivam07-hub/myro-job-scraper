from __future__ import annotations

from job_embedding_state import (
    JOB_DOCUMENT_PREFIX,
    JOB_QUERY_PREFIX,
    build_job_embedding_text,
    build_job_query_text,
    job_embedding_input_hash,
)


def test_job_document_is_source_first_and_uses_nomic_prefix() -> None:
    job = {
        "job_title": "Product Strategy Manager",
        "company_name": "Myro Labs",
        "industry": "Software",
        "location": "Gurugram, India",
        "location_country": "India",
        "location_mode": "hybrid",
        "job_description": "Own the product roadmap.\n\nWork with analytics and GTM teams.",
        "job_summary": "model-owned summary must not participate",
        "role_domain": "model-owned domain",
        "main_skills": ["model-owned skill"],
    }

    text = build_job_embedding_text(job)

    assert text.startswith(JOB_DOCUMENT_PREFIX)
    assert "Product Strategy Manager" in text
    assert "analytics and GTM" in text
    assert "model-owned" not in text


def test_job_document_truncation_and_hash_are_deterministic() -> None:
    job = {"job_title": "Engineer", "job_description": "x" * 40}
    text = build_job_embedding_text(job, description_chars=12)

    assert text.endswith("x" * 12)
    assert job_embedding_input_hash(text) == job_embedding_input_hash(text)
    assert job_embedding_input_hash(text) != job_embedding_input_hash(text + " changed")


def test_query_uses_compatible_nomic_prefix() -> None:
    assert build_job_query_text("  B2B product role  ") == (
        f"{JOB_QUERY_PREFIX}B2B product role"
    )
