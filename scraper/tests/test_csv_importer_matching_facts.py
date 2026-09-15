from __future__ import annotations

import json
from collections import Counter

import pytest

import csv_importer
from csv_importer import (
    _find_json_files,
    _source_row_is_publishable,
    _source_matching_facts_are_publishable,
    _validate_source_matching_facts,
    import_file,
)
from enrichment_state import source_content_hash


def _write_jobs(path, jobs) -> None:
    path.write_text(json.dumps(jobs), encoding="utf-8")


def test_targeted_run_date_is_found_even_when_a_newer_folder_exists(
    tmp_path, monkeypatch
) -> None:
    target = tmp_path / "Example_Co" / "Outputs" / "2026_08_07"
    newer = tmp_path / "Example_Co" / "Outputs" / "2026_08_08"
    target.mkdir(parents=True)
    newer.mkdir(parents=True)
    _write_jobs(target / "jobs.json", [])
    _write_jobs(newer / "jobs.json", [])
    monkeypatch.setattr(csv_importer, "OUTPUT_BASE", str(tmp_path))

    assert _find_json_files(
        company_filter=None,
        all_dates=False,
        batch_date=20260807,
    ) == [target / "jobs.json"]


def test_matching_fact_preflight_accepts_valid_band_and_unknown_seniority(tmp_path) -> None:
    jobs_path = tmp_path / "jobs.json"
    job = {
        "job_id": "engineer-1",
        "job_title": "Software Engineer",
        "job_description": "Build reliable data services.",
        "career_band": "engineering_data",
        "career_band_source": "deterministic_title_or_role_domain",
        "seniority_level": "",
    }
    job["career_band_source_hash"] = source_content_hash(job)
    _write_jobs(jobs_path, [job])

    assert _validate_source_matching_facts([jobs_path]) == (1, 1, 0, 0)


def test_matching_fact_preflight_rejects_unresolved_band_before_upload(tmp_path) -> None:
    jobs_path = tmp_path / "jobs.json"
    _write_jobs(jobs_path, [{
        "job_id": "associate-1",
        "job_title": "Associate",
        "career_band": "",
        "seniority_level": "entry",
    }])

    with pytest.raises(ValueError, match="1 invalid/unresolved career bands"):
        _validate_source_matching_facts([jobs_path])


def test_matching_fact_preflight_rejects_invalid_seniority(tmp_path) -> None:
    jobs_path = tmp_path / "jobs.json"
    job = {
        "job_id": "engineer-1",
        "job_title": "Software Engineer",
        "job_description": "Build reliable data services.",
        "career_band": "engineering_data",
        "career_band_source": "deterministic_title_or_role_domain",
        "seniority_level": "experienced",
    }
    job["career_band_source_hash"] = source_content_hash(job)
    _write_jobs(jobs_path, [job])

    with pytest.raises(ValueError, match="1 invalid seniority levels"):
        _validate_source_matching_facts([jobs_path])


def test_matching_fact_preflight_rejects_unprovenanced_fallback(tmp_path) -> None:
    jobs_path = tmp_path / "jobs.json"
    _write_jobs(jobs_path, [{
        "job_id": "associate-1",
        "job_title": "Associate",
        "job_description": "Support business operations.",
        "career_band": "business_product_operations",
        "seniority_level": "entry",
    }])

    with pytest.raises(
        ValueError,
        match="1 invalid/stale career-band provenance",
    ):
        _validate_source_matching_facts([jobs_path])


def test_matching_fact_preflight_requires_model_audit_fields(tmp_path) -> None:
    jobs_path = tmp_path / "jobs.json"
    job = {
        "job_id": "associate-1",
        "job_title": "Associate",
        "job_description": "Prepare financial reports.",
        "career_band": "business_product_operations",
        "career_band_source": "model_grounded",
        "seniority_level": "entry",
    }
    job["career_band_source_hash"] = source_content_hash(job)
    _write_jobs(jobs_path, [job])

    with pytest.raises(
        ValueError,
        match="1 invalid/stale career-band provenance",
    ):
        _validate_source_matching_facts([jobs_path])


def test_publication_safe_preflight_keeps_truthful_unclassified_rows(tmp_path) -> None:
    jobs_path = tmp_path / "jobs.json"
    proven = {
        "job_id": "engineer-1",
        "job_title": "Software Engineer",
        "job_description": "Build reliable data services.",
        "career_band": "engineering_data",
        "career_band_source": "deterministic_title_or_role_domain",
        "seniority_level": "",
    }
    proven["career_band_source_hash"] = source_content_hash(proven)
    unresolved = {
        "job_id": "associate-1",
        "job_title": "Associate",
        "job_description": "Support the team.",
        "career_band": "",
        "seniority_level": "entry",
    }
    _write_jobs(jobs_path, [proven, unresolved])

    assert _validate_source_matching_facts(
        [jobs_path],
        publish_unclassified=True,
    ) == (2, 2, 0, 1)
    assert _source_matching_facts_are_publishable(proven)
    assert not _source_matching_facts_are_publishable(unresolved)
    assert _source_row_is_publishable(unresolved, publish_unclassified=True)


def test_publication_safe_preflight_withholds_missing_job_id(tmp_path) -> None:
    jobs_path = tmp_path / "jobs.json"
    job = {
        "job_title": "Software Engineer",
        "job_description": "Build reliable data services.",
        "career_band": "engineering_data",
        "career_band_source": "deterministic_title_or_role_domain",
        "seniority_level": "",
    }
    job["career_band_source_hash"] = source_content_hash(job)
    _write_jobs(jobs_path, [job])

    assert _validate_source_matching_facts(
        [jobs_path],
        publish_unclassified=True,
    ) == (1, 0, 0, 0)


def test_publication_safe_preflight_counts_duplicate_source_rows(tmp_path) -> None:
    jobs_path = tmp_path / "jobs.json"
    job = {
        "job_id": "engineer-1",
        "company_name": "Example Co",
        "job_title": "Software Engineer",
        "job_description": "Build reliable data services.",
        "career_band": "engineering_data",
        "career_band_source": "deterministic_title_or_role_domain",
        "seniority_level": "",
    }
    job["career_band_source_hash"] = source_content_hash(job)
    _write_jobs(jobs_path, [job, dict(job)])

    assert _validate_source_matching_facts(
        [jobs_path],
        publish_unclassified=True,
    ) == (2, 1, 1, 0)


def test_unclassified_row_with_stale_claim_is_not_publication_safe() -> None:
    row = {
        "job_id": "associate-1",
        "job_title": "Associate",
        "career_band": "",
        "career_band_source": "model_grounded",
        "seniority_level": "entry",
    }

    assert not _source_row_is_publishable(row, publish_unclassified=True)


def test_import_file_publishes_unclassified_for_browse_without_a_band(tmp_path) -> None:
    jobs_path = tmp_path / "Example" / "Outputs" / "2026_08_08" / "jobs.json"
    jobs_path.parent.mkdir(parents=True)
    _write_jobs(jobs_path, [{
        "job_id": "associate-1",
        "company_name": "Example",
        "job_title": "Associate",
        "job_description": "Support the documented source team.",
        "career_band": "",
        "seniority_level": "entry",
        "location": "Bengaluru, India",
    }])

    result = import_file(
        object(),  # unused by a dry run
        jobs_path,
        {},
        Counter(),
        Counter(),
        True,
        source_only=True,
        publish_unclassified=True,
    )

    assert result["jobs"] == 1
    assert result["unclassified"] == 1
    assert result["withheld"] == 0
    assert result["duplicates"] == 0


def test_import_file_does_not_report_duplicates_as_withheld(tmp_path) -> None:
    jobs_path = tmp_path / "Example" / "Outputs" / "2026_08_08" / "jobs.json"
    jobs_path.parent.mkdir(parents=True)
    row = {
        "job_id": "associate-1",
        "company_name": "Example",
        "job_title": "Associate",
        "job_description": "Support the documented source team.",
        "career_band": "",
        "seniority_level": "entry",
        "location": "Bengaluru, India",
    }
    _write_jobs(jobs_path, [row, dict(row)])

    result = import_file(
        object(),
        jobs_path,
        {},
        Counter(),
        Counter(),
        True,
        source_only=True,
        publish_unclassified=True,
    )

    assert result["jobs"] == 1
    assert result["duplicates"] == 1
    assert result["withheld"] == 0
    assert result["unclassified"] == 1
