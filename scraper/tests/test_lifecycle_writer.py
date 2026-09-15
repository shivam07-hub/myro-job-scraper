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
