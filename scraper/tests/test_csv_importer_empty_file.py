import json

from csv_importer import import_file


def test_empty_jobs_file_returns_complete_zero_result(tmp_path) -> None:
    json_path = tmp_path / "Visa" / "Outputs" / "2026_06_04" / "jobs.json"
    json_path.parent.mkdir(parents=True)
    json_path.write_text(json.dumps([]), encoding="utf-8")

    result = import_file(
        sb=None,
        json_path=json_path,
        skill_id_map={},
        drift_counter={},
        unknown_location_counter={},
        dry_run=True,
    )

    assert result == {
        "path": str(json_path),
        "company": "Visa",
        "date": "2026_06_04",
        "batch_date": 20260604,
        "job_ids": set(),
        "jobs": 0,
        "withheld": 0,
        "unclassified": 0,
        "duplicates": 0,
        "profile_rows": 0,
        "drift": 0,
        "enriched": 0,
        "unknown_location_rows": 0,
    }
