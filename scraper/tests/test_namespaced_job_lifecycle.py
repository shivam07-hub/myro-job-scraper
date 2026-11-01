"""A job renamed to dodge a cross-company id collision lives like any other row.

These drive the real importer and lifecycle against an in-memory ``jobs`` table,
because the bug sat between them: ``jobs.json`` keeps the source id while the
database holds the published one.
"""
from __future__ import annotations

from collections import Counter
import json

from csv_importer import import_file
from source_snapshot import finalize_source_snapshot


class _Query:
    def __init__(self, db: "_Db", table: str) -> None:
        self.db = db
        self.table = table
        self.rows = list(db.tables[table])
        self.write = None

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.rows = [row for row in self.rows if row.get(column) == value]
        return self

    def in_(self, column, values):
        wanted = set(values)
        self.rows = [row for row in self.rows if row.get(column) in wanted]
        return self

    def gt(self, column, value):
        self.rows = [row for row in self.rows if row.get(column) > value]
        return self

    def order(self, column, desc=False):
        self.rows = sorted(self.rows, key=lambda row: row[column], reverse=desc)
        return self

    def limit(self, count):
        self.rows = self.rows[:count]
        return self

    def upsert(self, rows, on_conflict=None, ignore_duplicates=False):
        self.write = lambda: self.db.upsert(self.table, rows)
        return self

    def update(self, payload):
        self.write = lambda: [row.update(payload) for row in self.rows]
        return self

    def insert(self, rows):
        self.write = lambda: self.db.tables[self.table].extend(rows)
        return self

    def execute(self):
        data = self.write() if self.write else self.rows
        return type("Response", (), {"data": data})()


class _Db:
    """Only what publication touches. Unknown tables fail loudly."""

    def __init__(self, jobs: list[dict]) -> None:
        self.tables = {
            "jobs": [dict(row) for row in jobs],
            "job_source_runs": [],
            "job_listing_observations": [],
        }
        self.writes = 0

    def table(self, name: str) -> _Query:
        return _Query(self, name)

    def rpc(self, name: str, params: dict):
        assert name == "resolve_company_entity"
        company_id = f"{params['p_company_name'].lower()}-id"
        return type(
            "Rpc",
            (),
            {"execute": lambda _self: type("Response", (), {"data": company_id})()},
        )()

    def upsert(self, table: str, rows) -> list[dict]:
        self.writes += 1
        rows = rows if isinstance(rows, list) else [rows]
        if table == "job_source_runs":
            stored = [{**row, "id": f"run-{len(self.tables[table])}"} for row in rows]
            self.tables[table].extend(stored)
            return stored
        for row in rows:
            existing = next(
                (job for job in self.tables[table] if job["job_id"] == row["job_id"]),
                None,
            )
            if existing is None:
                self.tables[table].append(
                    {"company_id": None, "listing_confidence": "uncertain", **row}
                )
            else:
                existing.update(row)
        return []

    def job(self, job_id: str) -> dict:
        return next(row for row in self.tables["jobs"] if row["job_id"] == job_id)


def _wesco_owns(job_id: str) -> _Db:
    return _Db([
        {
            "job_id": job_id,
            "company_name": "WESCO",
            "company_id": "wesco-id",
            "is_active": True,
            "listing_confidence": "active",
        }
    ])


def _source_row(company: str, job_id: str) -> dict:
    return {
        "job_id": job_id,
        "company_name": company,
        "job_title": "Associate",
        "job_description": "Support the documented source team.",
        "career_band": "",
        "seniority_level": "entry",
        "location": "Bengaluru, India",
    }


def _publish(db: _Db, tmp_path, company: str, job_ids: list[str], run_date: str) -> None:
    json_path = tmp_path / company / "Outputs" / run_date / "jobs.json"
    json_path.parent.mkdir(parents=True)
    json_path.write_text(
        json.dumps([_source_row(company, job_id) for job_id in job_ids]),
        encoding="utf-8",
    )
    result = import_file(
        db,
        json_path,
        {},
        Counter(),
        Counter(),
        False,
        source_only=True,
        publish_unclassified=True,
    )
    finalize_source_snapshot(
        db,
        feed_run_id=run_date,
        json_files=[json_path],
        skill_id_map={},
        eligible_companies={company},
        quality_status="ok",
        dry_run=False,
        write_skill_facts=False,
        eligible_job_ids={company: result["job_ids"]},
        company_scope=company,
    )


def test_renamed_job_is_tagged_and_promoted_when_seen(tmp_path) -> None:
    db = _wesco_owns("29401")

    _publish(db, tmp_path, "Nokia", ["29401", "100"], "2026_11_01")

    renamed = db.job("nokia::29401")
    assert renamed["company_id"] == "nokia-id"
    assert renamed["listing_confidence"] == "active"
    assert renamed["confidence_reason"] == "complete_source_seen"
    owner = db.job("29401")
    assert owner["company_name"] == "WESCO"
    assert owner["company_id"] == "wesco-id"


def test_renamed_job_still_listed_stays_open_on_the_next_run(tmp_path) -> None:
    """Tagging the row without matching its id would close it here."""
    db = _wesco_owns("29401")
    _publish(db, tmp_path, "Nokia", ["29401", "100", "200"], "2026_11_01")

    _publish(db, tmp_path, "Nokia", ["29401", "100", "200"], "2026_11_02")

    renamed = db.job("nokia::29401")
    assert renamed["is_active"] is True
    assert renamed["listing_confidence"] == "active"
    assert renamed["consecutive_complete_misses"] == 0
    assert db.tables["job_listing_observations"] == []


def test_renamed_job_closes_when_missing_from_a_complete_run(tmp_path) -> None:
    db = _wesco_owns("29401")
    _publish(db, tmp_path, "Nokia", ["29401", "100", "200"], "2026_11_01")

    _publish(db, tmp_path, "Nokia", ["100", "200"], "2026_11_02")

    renamed = db.job("nokia::29401")
    assert renamed["is_active"] is False
    assert renamed["listing_confidence"] == "closed"
    assert db.job("29401")["is_active"] is True


def test_source_run_counts_the_renamed_job(tmp_path) -> None:
    db = _wesco_owns("29401")

    _publish(db, tmp_path, "Nokia", ["29401", "100"], "2026_11_01")

    assert db.tables["job_source_runs"][-1]["observed_count"] == 2


def test_dry_run_shows_the_rename_without_writing(tmp_path) -> None:
    db = _wesco_owns("29401")
    json_path = tmp_path / "Nokia" / "Outputs" / "2026_11_01" / "jobs.json"
    json_path.parent.mkdir(parents=True)
    json_path.write_text(json.dumps([_source_row("Nokia", "29401")]), encoding="utf-8")

    result = import_file(
        db,
        json_path,
        {},
        Counter(),
        Counter(),
        True,
        source_only=True,
        publish_unclassified=True,
    )

    assert result["job_ids"] == {"29401": "nokia::29401"}
    assert db.writes == 0
    assert [row["job_id"] for row in db.tables["jobs"]] == ["29401"]
