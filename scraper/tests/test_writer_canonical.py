from __future__ import annotations

import json

from schema import CANONICAL_FIELDS, MISSING_JD_NOTE
from pipeline_validator import run_gate
from writer import job_content_hash, save_jobs, to_canonical


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_to_canonical_matches_jobs_table_fields() -> None:
    raw = {
        "job_id": "req-1",
        "title": "Senior Engineer",
        "raw_jd_text": "Build reliable data systems, maintain production pipelines, and collaborate with product teams.",
        "industry": "Technology",
        "job_url": "https://example.com/jobs/req-1",
        "source_api_url": "https://api.example.com/jobs/req-1",
        "source_platform": "greenhouse",
        "candidate_profile": {"ideal_candidate_summary": "Production data systems engineer."},
        "candidate_profile_version": "cv_profile_v1",
        "candidate_profile_hash": "hash-123",
        "location_city": "Bengaluru, India",
    }
    row = to_canonical(raw, "Example Co")

    check("canonical key order", list(row.keys()) == CANONICAL_FIELDS)
    check("title mapped", row["job_title"] == "Senior Engineer")
    check("description mapped", row["job_description"] == "Build reliable data systems, maintain production pipelines, and collaborate with product teams.")
    check("company mapped", row["company_name"] == "Example Co")
    check("location mapped", row["location"] == "Bengaluru, India")
    check("location raw defaults", row["location_raw"] == "Bengaluru, India")
    check("country defaults to India", row["location_country"] == "India")
    check("skill fields default empty", row["skills"] == [] and row["main_skills"] == [] and row["side_skills"] == [])
    check("source_url mapped", row["source_url"] == "https://api.example.com/jobs/req-1")
    check("source_platform mapped", row["source_platform"] == "greenhouse")
    check("ingestion source defaults", row["ingestion_source"] == "scraper")
    check("quality status defaults", row["quality_status"] == "auto_extracted")
    check("candidate profile retained", row["candidate_profile"]["ideal_candidate_summary"] == "Production data systems engineer.")
    check("candidate profile version retained", row["candidate_profile_version"] == "cv_profile_v1")
    check("candidate profile hash retained", row["candidate_profile_hash"] == "hash-123")
    check("content hash populated", bool(row["job_content_hash"]))
    check("extractive summary stamped", bool(row["job_summary"]) and row["job_summary"] != MISSING_JD_NOTE)


def test_job_content_hash_changes_when_embedding_inputs_change() -> None:
    base = {
        "job_title": "Data Engineer",
        "job_description": "Build Python services.",
        "main_skills": ["Python (Programming Language)"],
    }

    changed_description = dict(base, job_description="Build Python and SQL services.")
    changed_skills = dict(base, main_skills=["Python (Programming Language)", "SQL (Programming Language)"])

    check("hash stable for same content", job_content_hash(base) == job_content_hash(dict(base)))
    check("hash changes with JD", job_content_hash(base) != job_content_hash(changed_description))
    check("hash changes with skills", job_content_hash(base) != job_content_hash(changed_skills))


def test_metadata_only_jobs_are_retained_with_no_jd_note() -> None:
    raw = {
        "job_id": "job-2922",
        "title": "Line Incharge",
        "raw_jd_text": "",
        "industry": "Industrial",
        "job_url": "https://example.com/jobs/job-2922",
        "location_city": "Hisar, Haryana, India",
    }
    row = to_canonical(raw, "Jindal Stainless")

    check("missing JD note applied", row["job_description"] == MISSING_JD_NOTE)
    check("summary mirrors missing JD note", row["job_summary"] == MISSING_JD_NOTE)
    check("metadata-only row passes pre-enrich gate", run_gate([row], "pre_enrich").passed == [row])
    check("metadata-only row passes post-enrich gate", run_gate([row], "post_enrich").passed == [row])


def test_too_short_descriptions_are_marked_metadata_only() -> None:
    raw = {
        "job_id": "job-qa",
        "title": "Executive Engineer - QA",
        "raw_jd_text": "Central QA-SMS Lab",
        "industry": "Industrial",
        "job_url": "https://example.com/jobs/job-qa",
        "location_city": "Jajpur, Odisha, India",
    }
    row = to_canonical(raw, "Jindal Stainless")

    check("too-short JD note applied", row["job_description"] == MISSING_JD_NOTE)
    check("too-short row passes pre-enrich gate", run_gate([row], "pre_enrich").drop_count == 0)


def test_save_jobs_keeps_a_midnight_spanning_run_in_its_start_date(tmp_path) -> None:
    first_job = to_canonical(
        {
            "job_id": "req-1",
            "title": "Software Engineer",
            "raw_jd_text": "Build reliable software systems for production users.",
        },
        "Example Co",
    )
    second_job = to_canonical(
        {
            "job_id": "req-2",
            "title": "Data Engineer",
            "raw_jd_text": "Build reliable data systems for production users.",
        },
        "Example Co",
    )

    save_jobs(
        "Example Co",
        [first_job],
        output_base=str(tmp_path),
        write_marker=False,
        run_date="2026_08_07",
    )
    path = tmp_path / "Example_Co" / "Outputs" / "2026_08_07"
    assert not (path / "jobs.complete").exists()

    json_path, _ = save_jobs(
        "Example Co",
        [first_job, second_job],
        output_base=str(tmp_path),
        run_date="2026_08_07",
    )

    assert json_path == str(path / "jobs.json")
    assert (path / "jobs.complete").exists()
    jobs = json.loads((path / "jobs.json").read_text(encoding="utf-8"))
    assert len(jobs) == 2
    assert {job["batch_date"] for job in jobs} == {20260807}


def main() -> None:
    test_to_canonical_matches_jobs_table_fields()
    test_metadata_only_jobs_are_retained_with_no_jd_note()
    test_too_short_descriptions_are_marked_metadata_only()
    print("All writer canonical tests passed.")


if __name__ == "__main__":
    main()
