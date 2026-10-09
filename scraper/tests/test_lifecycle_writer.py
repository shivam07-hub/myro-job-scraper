from datetime import datetime, timezone

from lifecycle_writer import apply_missing, apply_seen


class Query:
    def __init__(self, db, table):
        self.db = db
        self.table = table
        self.payload = None
        self.ids = []

    def update(self, payload):
        self.payload = payload
        return self

    def insert(self, payload):
        self.payload = payload
        return self

    def in_(self, _column, values):
        self.ids = values
        return self

    def execute(self):
        self.db.calls.append((self.table, self.payload, self.ids))
        return type("Response", (), {"data": []})()


class DB:
    def __init__(self):
        self.calls = []

    def table(self, name):
        return Query(self, name)


def test_seen_jobs_reactivate_and_reset_misses() -> None:
    db = DB()
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)

    apply_seen(
        db,
        [{"job_id": "j1", "listing_confidence": "closed"}],
        {"j1"},
        company_id="company-1",
        source_run_id="run-1",
        now=now,
    )

    job_updates = [call for call in db.calls if call[0] == "jobs"]
    assert job_updates[0][1]["listing_confidence"] == "active"
    assert job_updates[0][1]["consecutive_complete_misses"] == 0
    assert job_updates[0][1]["company_id"] == "company-1"
    assert job_updates[1][1]["reactivated_at"] == now.isoformat()
    assert all(call[0] != "job_listing_observations" for call in db.calls)


def test_first_missing_run_sets_fixed_deletion_eligibility() -> None:
    db = DB()
    now = datetime(2026, 7, 11, tzinfo=timezone.utc)

    apply_missing(
        db,
        [{"job_id": "j1", "consecutive_complete_misses": 0}],
        set(),
        source_run_id="run-1",
        now=now,
    )

    update = next(call[1] for call in db.calls if call[0] == "jobs")
    assert update["listing_confidence"] == "closed"
    assert update["is_active"] is False
    assert update["last_source_run_id"] == "run-1"
    assert update["deletion_eligible_at"] == "2026-07-11T01:00:00+00:00"
    missing = next(call for call in db.calls if call[0] == "job_listing_observations")
    assert missing[1][0]["result"] == "source_missing"


def test_later_missing_run_does_not_extend_deletion_clock() -> None:
    db = DB()

    apply_missing(
        db,
        [{"job_id": "j1", "consecutive_complete_misses": 3}],
        set(),
        source_run_id="run-1",
        now=datetime(2026, 7, 18, tzinfo=timezone.utc),
    )

    update = next(call[1] for call in db.calls if call[0] == "jobs")
    assert update["last_source_run_id"] == "run-1"
    assert "deletion_eligible_at" not in update
    assert all(call[0] != "job_listing_observations" for call in db.calls)


# ── Statement timeouts under contention (2026-10-01) ──────────────────────────
# Republishing EY India Experienced while another importer and both inference
# workers were writing to jobs made a 200-id lifecycle UPDATE hit the statement
# timeout. The source upsert had already landed, so the run stopped half
# written: rows active again but still marked closed, and no source run row.

import pytest

import lifecycle_writer


class StatementTimeout(Exception):
    code = "57014"


class SlowDB(DB):
    """Times out any jobs UPDATE over `limit` ids, plus `extra` more times."""

    def __init__(self, limit: int, extra: int = 0):
        super().__init__()
        self.limit = limit
        self.extra = extra

    def table(self, name):
        db = self

        class SlowQuery(Query):
            def execute(self):
                if self.table == "jobs" and isinstance(self.payload, dict) and self.ids:
                    if len(self.ids) > db.limit:
                        raise StatementTimeout("canceling statement due to statement timeout")
                    if db.extra:
                        db.extra -= 1
                        raise StatementTimeout("canceling statement due to statement timeout")
                return super().execute()

        return SlowQuery(self, name)


def _updated_ids(db):
    return sorted(i for table, payload, ids in db.calls if table == "jobs" and "listing_confidence" in payload for i in ids)


def test_timed_out_chunks_are_split_until_they_fit(monkeypatch) -> None:
    monkeypatch.setattr(lifecycle_writer, "_sleep", lambda _: None)
    db = SlowDB(limit=30)
    ids = {f"j{i:03d}" for i in range(200)}

    apply_seen(db, [], ids, company_id="c", source_run_id="r", now=datetime(2026, 10, 1, tzinfo=timezone.utc))

    assert _updated_ids(db) == sorted(ids)


def test_small_chunk_timeouts_back_off_and_retry(monkeypatch) -> None:
    sleeps = []
    monkeypatch.setattr(lifecycle_writer, "_sleep", sleeps.append)
    db = SlowDB(limit=1000, extra=2)

    apply_seen(db, [], {"a", "b"}, company_id="c", source_run_id="r", now=datetime(2026, 10, 1, tzinfo=timezone.utc))

    assert _updated_ids(db) == ["a", "b"]
    assert len(sleeps) == 2


def test_persistent_timeouts_still_raise(monkeypatch) -> None:
    monkeypatch.setattr(lifecycle_writer, "_sleep", lambda _: None)
    db = SlowDB(limit=0)

    with pytest.raises(StatementTimeout):
        apply_seen(db, [], {"a"}, company_id="c", source_run_id="r", now=datetime(2026, 10, 1, tzinfo=timezone.utc))


def test_other_errors_are_not_retried(monkeypatch) -> None:
    monkeypatch.setattr(lifecycle_writer, "_sleep", lambda _: (_ for _ in ()).throw(AssertionError("no retry")))

    class Broken(DB):
        def table(self, name):
            class Q(Query):
                def execute(self):
                    raise PermissionError("permission denied for table jobs")
            return Q(self, name)

    with pytest.raises(PermissionError):
        apply_seen(Broken(), [], {"a"}, company_id="c", source_run_id="r", now=datetime(2026, 10, 1, tzinfo=timezone.utc))
