"""One company's failure must not strand the rest of a publish.

The 2026-10-21 publish died inside Axis Bank's upsert. Everything after the
company loop (run audit, lifecycle, Stage A) belongs to the whole run, so one
company took all of it down and left the rows already written unlifecycled.
"""
import sys

import pytest

import csv_importer

COMPANIES = ("Apple", "Axis Bank", "Bosch")


def _result(path, company):
    return {
        "path": str(path),
        "company": company,
        "date": "2026_10_21",
        "batch_date": 20261021,
        "job_ids": {f"{company}-1"},
        "jobs": 1,
        "withheld": 0,
        "unclassified": 0,
        "duplicates": 0,
        "profile_rows": 0,
        "drift": 0,
        "enriched": 0,
        "unknown_location_rows": 0,
    }


@pytest.fixture
def publish(monkeypatch, tmp_path):
    """A real publish over three companies with every external seam stubbed."""
    paths = []
    for company in COMPANIES:
        path = tmp_path / company / "Outputs" / "2026_10_21" / "jobs.json"
        path.parent.mkdir(parents=True)
        path.write_text("[]", encoding="utf-8")
        path.with_name("jobs.complete").touch()
        paths.append(path)

    calls = {"imported": [], "finalize": None, "landed": [], "audited": 0}

    def fake_import_file(_sb, json_path, *_args, **_kwargs):
        company = json_path.parent.parent.parent.name
        calls["imported"].append(company)
        return _result(json_path, company)

    def fake_finalize(_sb, **kwargs):
        calls["finalize"] = kwargs
        return {"complete": 2, "partial": 0, "failed": 0, "age_delist": {"skipped": True}}

    def fake_audit(*_args, **_kwargs):
        calls["audited"] += 1

    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
    monkeypatch.setenv("MYRO_BACKEND_URL", "http://backend.test")
    monkeypatch.setenv("SCRAPE_WEBHOOK_TOKEN", "shared-secret")
    monkeypatch.setattr(csv_importer, "_stage_a_reachable", lambda: None)
    monkeypatch.setattr(csv_importer, "_supabase", lambda: object())
    monkeypatch.setattr(csv_importer, "_find_json_files", lambda *a, **k: paths)
    monkeypatch.setattr(
        csv_importer, "_validate_source_matching_facts", lambda *a, **k: (3, 3, 0, 0)
    )
    monkeypatch.setattr(csv_importer, "_assert_location_audit_contract", lambda *_: None)
    monkeypatch.setattr(csv_importer, "_jobs_missing_forward_enrichment_columns", lambda: [])
    monkeypatch.setattr(csv_importer, "_jobs_has_locations_column", lambda: True)
    monkeypatch.setattr(csv_importer, "_jobs_missing_card_columns", lambda: [])
    monkeypatch.setattr(csv_importer, "_write_location_audit", fake_audit)
    monkeypatch.setattr(csv_importer, "_refresh_analytics_snapshot", lambda: None)
    monkeypatch.setattr(csv_importer, "_notify_scrape_landed", calls["landed"].append)
    monkeypatch.setattr(csv_importer, "import_file", fake_import_file)
    monkeypatch.setattr(csv_importer, "finalize_source_snapshot", fake_finalize)
    monkeypatch.setattr(
        sys, "argv",
        [
            "csv_importer.py", "--source-only", "--publish-unclassified",
            "--run-date", "20261021",
        ],
    )
    return calls


def test_clean_publish_reports_no_failed_imports(publish):
    csv_importer.main()

    assert publish["imported"] == list(COMPANIES)
    assert publish["finalize"]["failed_imports"] == []
    assert len(publish["landed"]) == 1


def test_a_company_crash_leaves_the_rest_of_the_run_intact(publish, monkeypatch):
    real_import = csv_importer.import_file

    def crash_on_axis(sb, json_path, *args, **kwargs):
        if "Axis Bank" in str(json_path):
            raise RuntimeError("Server disconnected")
        return real_import(sb, json_path, *args, **kwargs)

    monkeypatch.setattr(csv_importer, "import_file", crash_on_axis)

    with pytest.raises(SystemExit) as excinfo:
        csv_importer.main()

    assert excinfo.value.code == 1
    assert publish["imported"] == ["Apple", "Bosch"]
    assert publish["audited"] == 1
    # Lifecycle never sees the failed company, so none of its listings close.
    assert publish["finalize"]["eligible_companies"] == {"Apple", "Bosch"}
    assert len(publish["finalize"]["failed_imports"]) == 1
    assert "Axis Bank" in publish["finalize"]["failed_imports"][0]
    # Apple and Bosch did land, so Stage A still gets the run.
    assert len(publish["landed"]) == 1


def test_an_unreadable_company_file_counts_as_a_failed_import(publish, monkeypatch):
    real_import = csv_importer.import_file

    def unreadable_axis(sb, json_path, *args, **kwargs):
        if "Axis Bank" in str(json_path):
            return {"path": str(json_path), "error": "Expecting value"}
        return real_import(sb, json_path, *args, **kwargs)

    monkeypatch.setattr(csv_importer, "import_file", unreadable_axis)

    with pytest.raises(SystemExit) as excinfo:
        csv_importer.main()

    assert excinfo.value.code == 1
    assert publish["finalize"]["eligible_companies"] == {"Apple", "Bosch"}
    assert len(publish["finalize"]["failed_imports"]) == 1
