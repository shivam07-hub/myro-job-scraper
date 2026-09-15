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
