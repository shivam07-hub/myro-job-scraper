from __future__ import annotations

from collections import Counter

from csv_importer import _upsert_jobs
from enrichment_state import source_content_hash


class FakeTable:
    def __init__(self, select_data: list[dict] | None = None) -> None:
        self.batches: list[list[dict]] = []
        self.select_data = select_data or []
        self.updates: list[dict] = []

    def select(self, *args, **kwargs):
        return self

    def in_(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    @property
    def not_(self):
        return self

    def is_(self, *args, **kwargs):
        return self

    def lt(self, *args, **kwargs):
        return self

    def range(self, *args, **kwargs):
        return self

    def upsert(self, rows, on_conflict=None, ignore_duplicates=False):
        self.batches.append(rows)
        return self

    def update(self, payload):
        self.updates.append(payload)
        return self

    def execute(self):
        return type("Response", (), {"data": list(self.select_data)})()


class FakeSupabase:
    def __init__(self) -> None:
        self.jobs = FakeTable()

    def table(self, name: str) -> FakeTable:
        assert name == "jobs"
        return self.jobs


def _job(**overrides) -> dict:
    row = {
        "job_id": "job-1",
        "job_title": "Data Engineer",
        "job_description": "Build reliable data platforms using Python and SQL for analytics workloads.",
        "job_summary": "Builds reliable analytics data platforms.",
        "role_domain": "Data & Analytics",
        "skills": [{"name": "Python (Programming Language)", "required_level": 3}],
        "main_skills": ["Python (Programming Language)"],
        "side_skills": [],
        "company_name": "Acme",
        "industry": "Technology",
        "location": "Bengaluru, India",
        "quality_status": "auto_extracted",
        "job_content_hash": "enriched-hash",
    }
    row.update(overrides)
    return row


def test_source_hash_uses_only_title_and_description() -> None:
    original = _job()
    different_enrichment = _job(
        job_summary="Different model summary",
        role_domain="Software Engineering",
        main_skills=["SQL (Programming Language)"],
    )
    changed_jd = _job(job_description=original["job_description"] + " Own Airflow operations.")

    assert source_content_hash(original) == source_content_hash(different_enrichment)
    assert source_content_hash(original) != source_content_hash(changed_jd)


def test_source_only_upsert_never_sends_model_owned_fields() -> None:
    fake = FakeSupabase()
    job = _job()

    _upsert_jobs(
        fake,
        [job],
        20260711,
        Counter(),
        source_only=True,
        supports_forward_enrichment=True,
    )

    row = fake.jobs.batches[0][0]
    assert row["source_content_hash"] == source_content_hash(job)
    assert row["job_summary"] == job["job_summary"]
    for field in (
        "role_domain",
        "main_skills",
        "side_skills",
        "job_content_hash",
        "enriched_source_hash",
        "enrichment_status",
    ):
        assert field not in row


def test_source_only_upsert_preserves_existing_model_summary() -> None:
    fake = FakeSupabase()
    fake.jobs.select_data = [{"job_id": "job-1", "job_summary": "LLM card body already present."}]
    job = _job(job_summary="Extractive replacement must not win.")

    _upsert_jobs(
        fake,
        [job],
        20260711,
        Counter(),
        source_only=True,
        supports_forward_enrichment=True,
    )

    row = fake.jobs.batches[0][0]
    assert "job_summary" not in row


def test_source_only_upsert_fills_blank_summary_from_jd() -> None:
    fake = FakeSupabase()
    job = _job(job_summary="")

    _upsert_jobs(
        fake,
        [job],
        20260711,
        Counter(),
        source_only=True,
        supports_forward_enrichment=True,
    )

    row = fake.jobs.batches[0][0]
    assert row["job_summary"]
    assert "Python" in row["job_summary"] or "data" in row["job_summary"].lower()


def test_unenriched_default_upsert_preserves_existing_model_fields(monkeypatch) -> None:
    monkeypatch.setattr("csv_importer._jobs_has_job_content_hash_column", lambda: True)
    fake = FakeSupabase()
    raw = _job(
        job_summary="",
        role_domain="",
        skills=[],
        main_skills=[],
        job_content_hash="raw-hash-must-not-write",
    )

    _upsert_jobs(
        fake,
        [raw],
        20260711,
        Counter(),
        supports_forward_enrichment=True,
    )

    row = fake.jobs.batches[0][0]
    assert row["source_content_hash"] == source_content_hash(raw)
    assert "job_summary" not in row
    assert "role_domain" not in row
    assert "main_skills" not in row
    assert "job_content_hash" not in row


def test_enriched_default_upsert_can_write_model_fields(monkeypatch) -> None:
    monkeypatch.setattr("csv_importer._jobs_has_job_content_hash_column", lambda: True)
    fake = FakeSupabase()
    job = _job()

    _upsert_jobs(
        fake,
        [job],
        20260711,
        Counter(),
        supports_forward_enrichment=True,
    )

    row = fake.jobs.batches[0][0]
    assert row["job_summary"] == job["job_summary"]
    assert row["role_domain"] == job["role_domain"]
    assert row["main_skills"] == job["main_skills"]
    assert row["enrichment_status"] == "complete"
    assert row["enriched_source_hash"] == row["source_content_hash"]
    assert row["job_content_hash"] == "enriched-hash"
