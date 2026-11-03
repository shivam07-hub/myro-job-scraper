from __future__ import annotations

from csv_importer import (
    _collision_safe_job_id,
    _namespace_cross_company_collisions,
)


class Query:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def select(self, columns: str):
        return self

    def in_(self, column: str, values: list[str]):
        self.values = values
        return self

    def execute(self):
        rows = [row for row in self.rows if row["job_id"] in self.values]
        return type("Response", (), {"data": rows})()


class FakeSupabase:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def table(self, name: str) -> Query:
        assert name == "jobs"
        return Query(self.rows)


def test_cross_company_collision_gets_stable_namespaced_id() -> None:
    jobs = [
        {"job_id": "29401", "company_name": "Nokia"},
        {"job_id": "100", "company_name": "Nokia"},
    ]
    sb = FakeSupabase([
        {"job_id": "29401", "company_name": "WESCO"},
        {"job_id": "100", "company_name": "Nokia"},
    ])

    changed = _namespace_cross_company_collisions(sb, jobs)

    assert changed == 1
    assert jobs[0]["job_id"] == "nokia::29401"
    assert jobs[1]["job_id"] == "100"
    assert _collision_safe_job_id("Adani Thermal Power", "32568") == (
        "adani_thermal_power::32568"
    )


class RecordingSupabase(FakeSupabase):
    def __init__(self, rows: list[dict]) -> None:
        super().__init__(rows)
        self.lookups: list[str] = []

    def table(self, name: str) -> Query:
        query = super().table(name)
        lookup = query.in_

        def in_(column: str, values: list[str]):
            self.lookups.extend(values)
            return lookup(column, values)

        query.in_ = in_
        return query


def test_job_keeps_its_safe_id_after_the_raw_owner_is_deleted() -> None:
    jobs = [{"job_id": "29401", "company_name": "Nokia"}]
    sb = FakeSupabase([{"job_id": "nokia::29401", "company_name": "Nokia"}])

    _namespace_cross_company_collisions(sb, jobs)

    assert jobs[0]["job_id"] == "nokia::29401"


def test_new_job_with_no_safe_row_keeps_its_source_id() -> None:
    jobs = [{"job_id": "29401", "company_name": "Nokia"}]

    assert _namespace_cross_company_collisions(FakeSupabase([]), jobs) == 0
    assert jobs[0]["job_id"] == "29401"


def test_own_raw_row_wins_over_a_leftover_safe_row() -> None:
    jobs = [{"job_id": "29401", "company_name": "Nokia"}]
    sb = FakeSupabase([
        {"job_id": "29401", "company_name": "Nokia"},
        {"job_id": "nokia::29401", "company_name": "Nokia"},
    ])

    _namespace_cross_company_collisions(sb, jobs)

    assert jobs[0]["job_id"] == "29401"


def test_safe_ids_are_looked_up_only_for_unowned_jobs() -> None:
    jobs = [
        {"job_id": "100", "company_name": "Nokia"},
        {"job_id": "new", "company_name": "Nokia"},
    ]
    sb = RecordingSupabase([{"job_id": "100", "company_name": "Nokia"}])

    _namespace_cross_company_collisions(sb, jobs)

    assert sb.lookups == ["100", "new", "nokia::new"]
