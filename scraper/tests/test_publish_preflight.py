"""Publication must refuse a run it cannot finish, before it writes anything.

The Stage A hand-off used to be the first thing that read its own config, at
the very end of publish — so a missing key surfaced only after every source row
was already committed.
"""
import sys

import pytest

import csv_importer


def _stub_supabase(*_args, **_kwargs):
    raise AssertionError("Supabase was reached before the preflight ran")


def test_real_publish_without_stage_a_config_exits_before_any_write(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
    monkeypatch.delenv("MYRO_BACKEND_URL", raising=False)
    monkeypatch.delenv("SCRAPE_WEBHOOK_TOKEN", raising=False)
    monkeypatch.setattr(csv_importer, "_supabase", _stub_supabase)
    monkeypatch.setattr(
        sys, "argv",
        [
            "csv_importer.py", "--source-only", "--publish-unclassified",
            "--run-date", "20260808",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        csv_importer.main()

    assert excinfo.value.code == 2


def test_missing_supabase_config_also_stops_the_run(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    monkeypatch.setattr(csv_importer, "_supabase", _stub_supabase)
    monkeypatch.setattr(
        sys, "argv",
        [
            "csv_importer.py", "--source-only", "--publish-unclassified",
            "--run-date", "20260808", "--dry-run",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        csv_importer.main()

    assert excinfo.value.code == 2


def test_unreachable_stage_a_backend_stops_the_run_before_any_write(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
    monkeypatch.setenv("MYRO_BACKEND_URL", "http://localhost:8000")
    monkeypatch.setenv("SCRAPE_WEBHOOK_TOKEN", "shared-secret")
    monkeypatch.setattr(csv_importer, "_supabase", _stub_supabase)
    monkeypatch.setattr(
        csv_importer, "_stage_a_reachable", lambda: "http://localhost:8000 did not answer"
    )
    monkeypatch.setattr(
        sys, "argv",
        [
            "csv_importer.py", "--source-only", "--publish-unclassified",
            "--run-date", "20260808",
        ],
    )

    with pytest.raises(SystemExit) as excinfo:
        csv_importer.main()

    assert excinfo.value.code == 2


def test_reachability_probe_treats_any_http_status_as_reachable(monkeypatch):
    class _Response:
        status_code = 404

    monkeypatch.setenv("MYRO_BACKEND_URL", "http://backend.test/")
    monkeypatch.setattr(csv_importer.requests, "get", lambda *a, **k: _Response())
    assert csv_importer._stage_a_reachable() is None


def test_reachability_probe_reports_a_connection_failure(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise csv_importer.requests.ConnectionError("refused")

    monkeypatch.setenv("MYRO_BACKEND_URL", "http://backend.test")
    monkeypatch.setattr(csv_importer.requests, "get", _boom)
    reason = csv_importer._stage_a_reachable()
    assert reason is not None and "ConnectionError" in reason
