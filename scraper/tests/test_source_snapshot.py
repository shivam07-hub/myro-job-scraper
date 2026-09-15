from __future__ import annotations

from collections import Counter

from postgrest.exceptions import APIError

from csv_importer import _upsert_jobs
from source_snapshot import (
    fill_blank_summaries,
    finalize_source_snapshot,
    upsert_rows,
)


class PostgrestTable:
    """Simulates PostgREST: omitted keys in a mixed batch become NULL."""

    def __init__(self) -> None:
        self.requests: list[list[dict]] = []
        self.stored: list[dict] = []
        self.updates: list[tuple[dict, str]] = []
        self.select_data: list[dict] = []

    def select(self, *args, **kwargs):
        return self

    def eq(self, *args, **kwargs):
        return self

    def in_(self, *args, **kwargs):
        return self

    def upsert(self, rows, on_conflict=None, ignore_duplicates=False):
        union: set[str] = set()
        for row in rows:
            union |= set(row.keys())
        materialized = []
        for row in rows:
            materialized.append({key: row[key] if key in row else None for key in union})
        self.requests.append(list(rows))
        self.stored.extend(materialized)
        return self

    def update(self, payload):
        self._pending_update = payload
        return self

    def execute(self):
        if getattr(self, "_pending_update", None) is not None:
            self.updates.append(self._pending_update)
            self._pending_update = None
            return type("Response", (), {"data": []})()
        return type("Response", (), {"data": list(self.select_data)})()


class PostgrestSb:
    def __init__(self) -> None:
        self.jobs = PostgrestTable()
        self.rpc_calls: list[tuple[str, dict]] = []
        self.rpc_pages: list[list[dict]] = []

    def table(self, name: str) -> PostgrestTable:
        assert name == "jobs"
        return self.jobs

    def rpc(self, name: str, params: dict):
        self.rpc_calls.append((name, params))
        page = self.rpc_pages.pop(0) if self.rpc_pages else []
        return type("Rpc", (), {"execute": lambda self: type("Response", (), {"data": page})()})()


def _job(job_id: str, **overrides) -> dict:
    row = {
        "job_id": job_id,
        "job_title": "Data Engineer",
        "job_description": (
            "Build reliable data platforms using Python and SQL for analytics workloads. "
            "Own Airflow DAGs for daily loads."
        ),
        "job_summary": "",
        "company_name": "Acme",
        "industry": "Technology",
        "location": "Bengaluru, India",
        "quality_status": "auto_extracted",
    }
    row.update(overrides)
    return row


def test_upsert_rows_splits_mixed_keysets_so_omit_cannot_null() -> None:
    sb = PostgrestSb()
    upsert_rows(
        sb,
        "jobs",
        [
            {"job_id": "keep", "title": "A", "job_summary": "LLM body"},
            {"job_id": "omit", "title": "B"},
        ],
        on_conflict="job_id",
    )

    assert len(sb.jobs.requests) == 2
    for request in sb.jobs.requests:
        keys = {frozenset(row.keys()) for row in request}
        assert len(keys) == 1
    stored = {row["job_id"]: row for row in sb.jobs.stored}
    assert stored["keep"]["job_summary"] == "LLM body"
    assert "job_summary" not in stored["omit"]


def test_mixed_batch_without_split_would_null_omitted_summary() -> None:
    """Documents the PostgREST hazard the writer exists to hide."""
    table = PostgrestTable()
    table.upsert(
        [
            {"job_id": "keep", "job_summary": "LLM body"},
            {"job_id": "fill", "job_summary": "Extractive"},
            {"job_id": "omit", "title": "no summary key"},
        ]
    )
    stored = {row["job_id"]: row for row in table.stored}
    assert stored["omit"]["job_summary"] is None
    assert stored["keep"]["job_summary"] == "LLM body"


def test_source_only_mixed_fill_and_preserve_does_not_null_llm_summary() -> None:
    sb = PostgrestSb()
    sb.jobs.select_data = [{"job_id": "keep", "job_summary": "LLM card body already present."}]

    _upsert_jobs(
        sb,
        [
            _job("keep", job_summary="Extractive replacement must not win."),
            _job("fresh", job_summary=""),
        ],
        20260907,
        Counter(),
        source_only=True,
        supports_forward_enrichment=True,
    )

    assert len(sb.jobs.requests) >= 2
    for request in sb.jobs.requests:
        assert len({frozenset(row.keys()) for row in request}) == 1
    keep_row = next(r for req in sb.jobs.requests for r in req if r["job_id"] == "keep")
    fresh_row = next(r for req in sb.jobs.requests for r in req if r["job_id"] == "fresh")
    assert "job_summary" not in keep_row
    assert fresh_row["job_summary"]
    preserve_batch = next(req for req in sb.jobs.requests if any(r["job_id"] == "keep" for r in req))
    assert all("job_summary" not in row for row in preserve_batch)


def test_finalize_never_calls_retire_rpc(monkeypatch) -> None:
    """Physical delete is True_Yodha's archive-then-retire. Publish must not delete."""
    sb = PostgrestSb()
    monkeypatch.setattr(
        "source_snapshot.sync_import_run",
        lambda *args, **kwargs: {"complete": 1, "partial": 0, "failed": 0},
    )
    monkeypatch.setattr(
        "source_snapshot.delist_stale_jobs",
        lambda *args, **kwargs: {"cutoff": 1, "candidates": 0, "changed": 0},
    )

    summary = finalize_source_snapshot(
        sb,
        feed_run_id="run-1",
        json_files=[],
        skill_id_map={},
        eligible_companies={"Stripe"},
        quality_status="ok",
        dry_run=False,
        company_scope=None,
    )

    assert sb.rpc_calls == []
    assert "retired" not in summary


def test_finalize_company_scope_skips_age_delist(monkeypatch) -> None:
    sb = PostgrestSb()
    monkeypatch.setattr(
        "source_snapshot.sync_import_run",
        lambda *args, **kwargs: {"complete": 1, "partial": 0, "failed": 0},
    )
    age_calls = []
    monkeypatch.setattr(
        "source_snapshot.delist_stale_jobs",
        lambda *args, **kwargs: age_calls.append(kwargs) or {"cutoff": 1, "candidates": 0, "changed": 0},
    )

    summary = finalize_source_snapshot(
        sb,
        feed_run_id="run-1",
        json_files=[],
        skill_id_map={},
        eligible_companies={"Stripe"},
        quality_status="ok",
        dry_run=False,
        company_scope="Stripe",
    )

    assert summary["age_delist"]["skipped"] is True
    assert age_calls == []
    assert sb.rpc_calls == []
    assert "retired" not in summary


def test_finalize_full_scope_runs_age_delist(monkeypatch) -> None:
    sb = PostgrestSb()
    sb.rpc_pages = [[]]
    monkeypatch.setattr(
        "source_snapshot.sync_import_run",
        lambda *args, **kwargs: {"complete": 1, "partial": 0, "failed": 0},
    )
    monkeypatch.setattr(
        "source_snapshot.delist_stale_jobs",
        lambda *args, **kwargs: {"cutoff": 20260808, "candidates": 3, "changed": 3},
    )

    summary = finalize_source_snapshot(
        sb,
        feed_run_id="run-1",
        json_files=[],
        skill_id_map={},
        eligible_companies={"Stripe"},
        quality_status="ok",
        dry_run=False,
        company_scope=None,
    )

    assert summary["age_delist"]["changed"] == 3
    assert summary["age_delist"].get("skipped") is not True


def test_finalize_dry_run_does_not_delete(monkeypatch) -> None:
    sb = PostgrestSb()
    monkeypatch.setattr(
        "source_snapshot.sync_import_run",
        lambda *args, **kwargs: {"complete": 1, "partial": 0, "failed": 0},
    )
    monkeypatch.setattr(
        "source_snapshot.delist_stale_jobs",
        lambda *args, **kwargs: {"cutoff": 1, "candidates": 0, "changed": 0},
    )

    summary = finalize_source_snapshot(
        sb,
        feed_run_id="run-1",
        json_files=[],
        skill_id_map={},
        eligible_companies=set(),
        quality_status="ok",
        dry_run=True,
        company_scope=None,
    )

    assert sb.rpc_calls == []
    assert "retired" not in summary


def test_fill_blank_summaries_skips_existing_and_writes_extractive() -> None:
    sb = PostgrestSb()
    sb.jobs.select_data = [
        {
            "job_id": "empty-1",
            "job_title": "Staff Engineer",
            "job_description": (
                "Build reliable data platforms using Python and SQL. "
                "Own Airflow DAGs for daily loads across the analytics warehouse."
            ),
            "job_summary": "",
        },
        {
            "job_id": "keep-1",
            "job_title": "Staff Engineer",
            "job_description": "Build reliable data platforms using Python and SQL.",
            "job_summary": "LLM card body already present.",
        },
    ]

    changed = fill_blank_summaries(sb, company="Stripe", job_ids=["empty-1", "keep-1"])

    assert changed == 1
    assert sb.jobs.updates[0]["job_summary"]
    assert "Python" in sb.jobs.updates[0]["job_summary"]
    assert "LLM" not in sb.jobs.updates[0]["job_summary"]


def test_upsert_rows_still_splits_on_statement_timeout() -> None:
    class TimeoutTable:
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

    class TimeoutSb:
        def __init__(self) -> None:
            self.jobs = TimeoutTable()

        def table(self, name: str) -> TimeoutTable:
            return self.jobs

    sb = TimeoutSb()
    upsert_rows(
        sb,
        "jobs",
        [{"job_id": "a", "title": "A"}, {"job_id": "b", "title": "B"}],
        on_conflict="job_id",
    )
    assert sb.jobs.attempt_sizes == [2, 1, 1]
