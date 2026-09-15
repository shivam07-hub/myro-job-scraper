from __future__ import annotations

import math
from collections import Counter

from postgrest.exceptions import APIError

from csv_importer import _normalize_location, _upsert_jobs


def test_missing_location_uses_non_null_unknown_placeholder() -> None:
    normalized = _normalize_location(None, None)

    assert normalized.location == "Unknown"
    assert normalized.location_quality == "unknown"
    assert normalized.location_mode == "unknown"


class FakeTable:
    def __init__(self) -> None:
        self.batches: list[list[dict]] = []

    def upsert(self, rows, on_conflict=None, ignore_duplicates=False):
        self.batches.append(rows)
        return self

    def execute(self):
        return type("Response", (), {"data": []})()


class FakeSupabase:
    def __init__(self) -> None:
        self.jobs = FakeTable()

    def table(self, name: str) -> FakeTable:
        assert name == "jobs"
        return self.jobs


class TimeoutThenSplitTable:
    def __init__(self) -> None:
        self.attempt_sizes: list[int] = []
        self._current_rows: list[dict] = []

    def upsert(self, rows, on_conflict=None, ignore_duplicates=False):
        self._current_rows = rows
        return self

    def execute(self):
        size = len(self._current_rows)
        self.attempt_sizes.append(size)
        if size > 1:
            raise APIError({
                "message": "canceling statement due to statement timeout",
                "code": "57014",
                "hint": None,
                "details": None,
            })
        return type("Response", (), {"data": []})()


class TimeoutThenSplitSupabase:
    def __init__(self) -> None:
        self.jobs = TimeoutThenSplitTable()

    def table(self, name: str) -> TimeoutThenSplitTable:
        assert name == "jobs"
        return self.jobs


def test_upsert_jobs_sends_non_null_quality_status_for_every_row(monkeypatch) -> None:
    monkeypatch.setattr("csv_importer._jobs_has_job_content_hash_column", lambda: False)
    fake = FakeSupabase()

    written, _ = _upsert_jobs(
        fake,
        [
            {
                "job_id": "job-1",
                "job_title": "Role One",
                "job_description": "Description",
                "company_name": "Acme",
                "industry": "Technology",
                "location": "Bengaluru, India",
                "quality_status": "ok",
                "min_years_experience": 6.0,
                "max_years_experience": 12.0,
            },
            {
                "job_id": "job-2",
                "job_title": None,
                "job_description": None,
                "company_name": "Acme",
                "industry": None,
                "location": "Bengaluru, India",
                "ingestion_source": None,
                "quality_status": None,
                "min_years_experience": math.nan,
                "max_years_experience": math.nan,
            },
        ],
        batch_date=20260707,
        location_alias_counter=Counter(),
    )

    assert written == 2
    by_id = {row["job_id"]: row for batch in fake.jobs.batches for row in batch}
    assert by_id["job-1"]["min_years_experience"] == 6
    assert isinstance(by_id["job-1"]["min_years_experience"], int)
    assert by_id["job-1"]["max_years_experience"] == 12
    assert isinstance(by_id["job-1"]["max_years_experience"], int)
    assert by_id["job-2"]["job_title"] == ""
    assert by_id["job-2"]["job_description"] == ""
    assert by_id["job-2"]["industry"] == "unknown"
    assert by_id["job-2"]["ingestion_source"] == "scraper"
    assert "min_years_experience" not in by_id["job-2"]
    assert "max_years_experience" not in by_id["job-2"]
    assert by_id["job-1"]["quality_status"] == "ok"
    assert by_id["job-2"]["quality_status"] == "auto_extracted"
    for batch in fake.jobs.batches:
        assert len({frozenset(row.keys()) for row in batch}) == 1


def test_upsert_jobs_persists_an_unclassified_band_as_null(monkeypatch) -> None:
    monkeypatch.setattr("csv_importer._jobs_has_job_content_hash_column", lambda: False)
    fake = FakeSupabase()

    _upsert_jobs(
        fake,
        [{
            "job_id": "associate-1",
            "job_title": "Associate",
            "job_description": "Support a documented source function.",
            "company_name": "Acme",
            "location": "Bengaluru, India",
            "career_band": "",
        }],
        batch_date=20260808,
        location_alias_counter=Counter(),
    )

    assert fake.jobs.batches[0][0]["career_band"] is None


def test_upsert_jobs_splits_batch_after_statement_timeout(monkeypatch) -> None:
    monkeypatch.setattr("csv_importer._jobs_has_job_content_hash_column", lambda: False)
    fake = TimeoutThenSplitSupabase()

    written, _ = _upsert_jobs(
        fake,
        [
            {
                "job_id": "job-1",
                "job_title": "Role One",
                "job_description": "Description",
                "company_name": "Acme",
                "industry": "Technology",
                "location": "Bengaluru, India",
            },
            {
                "job_id": "job-2",
                "job_title": "Role Two",
                "job_description": "Description",
                "company_name": "Acme",
                "industry": "Technology",
                "location": "Bengaluru, India",
            },
        ],
        batch_date=20260707,
        location_alias_counter=Counter(),
    )

    assert written == 2
    assert fake.jobs.attempt_sizes == [2, 1, 1]
