from datetime import datetime, timezone

from schema import MISSING_JD_NOTE
from job_summary import extractive_job_summary
from trusted_job_lifecycle import AGE_STALE_DAYS, delist_stale_jobs, stale_last_seen_cutoff
from writer import to_canonical


def test_extractive_summary_uses_jd_sentences() -> None:
    summary = extractive_job_summary(
        "Data Engineer",
        "Build reliable data platforms using Python and SQL. Own Airflow DAGs for daily loads. Apply now on the careers site.",
    )
    assert "Python" in summary
    assert "Apply now" not in summary
    assert len(summary.split()) <= 60


def test_extractive_summary_for_missing_jd() -> None:
    assert extractive_job_summary("Guard", "", metadata_only=True) == MISSING_JD_NOTE


def test_to_canonical_always_has_a_summary() -> None:
    row = to_canonical(
        {
            "job_id": "req-1",
            "title": "Senior Engineer",
            "raw_jd_text": "Build reliable data systems and maintain production pipelines with the platform team.",
            "industry": "Technology",
            "job_url": "https://example.com/jobs/req-1",
            "location_city": "Bengaluru, India",
        },
        "Example Co",
    )
    assert row["job_summary"]
    assert row["job_summary"] != MISSING_JD_NOTE


def test_age_cutoff_is_thirty_days() -> None:
    assert AGE_STALE_DAYS == 30
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    assert stale_last_seen_cutoff(today=now) == 20260808


class _FakeQuery:
    def __init__(self, table: "_FakeTable") -> None:
        self.table = table

    def select(self, *args, **kwargs):
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

    def in_(self, column, ids):
        self.table.last_ids = list(ids)
        return self

    def update(self, payload):
        self.table.updates.append(payload)
        return self

    def execute(self):
        return type("Response", (), {"data": list(self.table.rows)})()


class _FakeTable:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows
        self.updates: list[dict] = []
        self.last_ids: list[str] = []

    def select(self, *args, **kwargs):
        return _FakeQuery(self)

    def update(self, payload):
        return _FakeQuery(self).update(payload)


class _FakeSb:
    def __init__(self, rows: list[dict]) -> None:
        self.jobs = _FakeTable(rows)

    def table(self, name: str) -> _FakeTable:
        assert name == "jobs"
        return self.jobs


def test_age_delist_closes_stale_active_rows() -> None:
    sb = _FakeSb([{"job_id": "old-1"}])
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    result = delist_stale_jobs(sb, dry_run=False, today=now)
    assert result["candidates"] == 1
    assert result["changed"] == 1
    assert sb.jobs.updates[0]["is_active"] is False
    assert sb.jobs.updates[0]["listing_confidence"] == "closed"
    assert sb.jobs.updates[0]["deletion_eligible_at"] == "2026-09-07T01:00:00+00:00"
    assert sb.jobs.updates[0]["quarantine_until"] == sb.jobs.updates[0]["deletion_eligible_at"]


def test_age_delist_dry_run_does_not_write() -> None:
    sb = _FakeSb([{"job_id": "old-1"}])
    now = datetime(2026, 9, 7, tzinfo=timezone.utc)
    result = delist_stale_jobs(sb, dry_run=True, today=now)
    assert result["candidates"] == 1
    assert result["changed"] == 0
    assert sb.jobs.updates == []
