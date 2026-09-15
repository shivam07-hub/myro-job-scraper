from datetime import datetime, timezone
import json

import trusted_job_lifecycle as lifecycle
from trusted_job_lifecycle import assess_source_run, missing_transition


def test_complete_run_requires_safe_coverage() -> None:
    healthy = assess_source_run(current_count=80, prior_good_count=100)
    collapsed = assess_source_run(current_count=20, prior_good_count=100)

    assert healthy.status == "complete"
    assert healthy.coverage_ratio == 0.8
    assert collapsed.status == "partial"
    assert "coverage" in (collapsed.failure_reason or "")


def test_zero_first_run_is_failed_not_complete() -> None:
    result = assess_source_run(current_count=0, prior_good_count=None)

    assert result.status == "failed"


def test_growth_is_complete_and_coverage_is_capped_for_storage() -> None:
    result = assess_source_run(current_count=37, prior_good_count=36)

    assert result.status == "complete"
    assert result.coverage_ratio == 1.0


def test_one_complete_miss_closes_then_quarantines_the_listing() -> None:
    now = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)

    first = missing_transition(0, now=now)
    second = missing_transition(1, now=now)

    assert first.listing_confidence == "closed"
    assert first.is_active is False
    assert first.quarantine_until is not None
    assert (first.quarantine_until - now).total_seconds() == 3600
    assert second.listing_confidence == "closed"
    assert second.quarantine_until is None


def test_additional_misses_do_not_extend_quarantine() -> None:
    now = datetime(2026, 7, 11, 12, tzinfo=timezone.utc)

    transition = missing_transition(3, now=now)

    assert transition.listing_confidence == "closed"
    assert transition.quarantine_until is None


def test_source_only_lifecycle_promotes_seen_without_writing_skill_facts(monkeypatch):
    calls = []
    monkeypatch.setattr(lifecycle, "_resolve_company", lambda sb, company: "company-1")
    monkeypatch.setattr(lifecycle, "_fetch_company_jobs", lambda sb, company_id: [])
    monkeypatch.setattr(lifecycle, "_prior_good_count", lambda sb, company_id: None)
    monkeypatch.setattr(lifecycle, "_write_source_run", lambda *args, **kwargs: "source-run-1")
    monkeypatch.setattr(lifecycle, "_apply_seen", lambda *args, **kwargs: calls.append("seen"))
    monkeypatch.setattr(lifecycle, "_apply_missing", lambda *args, **kwargs: calls.append("missing"))
    monkeypatch.setattr(
        lifecycle,
        "build_company_skill_facts",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not write skill facts")),
    )

    result = lifecycle.sync_company_run(
        object(),
        feed_run_id="feed-run-1",
        company="Example",
        jobs=[{"job_id": "one"}],
        skill_id_map={},
        quality_status="ok",
        dry_run=False,
        write_skill_facts=False,
    )

    assert result.status == "complete"
    assert calls == ["seen", "missing"]


def test_import_run_excludes_rows_not_accepted_by_importer(monkeypatch, tmp_path):
    output = tmp_path / "Example" / "Outputs" / "2026_08_13"
    output.mkdir(parents=True)
    path = output / "jobs.json"
    path.write_text(
        json.dumps([
            {"job_id": "published", "company_name": "Example"},
            {"job_id": "withheld", "company_name": "Example"},
        ]),
        encoding="utf-8",
    )
    seen = []
    monkeypatch.setattr(
        lifecycle,
        "sync_company_run",
        lambda sb, **kwargs: seen.extend(job["job_id"] for job in kwargs["jobs"])
        or lifecycle.SourceRunAssessment("complete", None),
    )

    lifecycle.sync_import_run(
        object(),
        feed_run_id="feed-run-1",
        json_files=[path],
        skill_id_map={},
        eligible_companies={"Example"},
        quality_status="ok",
        dry_run=True,
        eligible_job_ids={"Example": {"published"}},
    )

    assert seen == ["published"]


def test_sync_import_run_does_not_call_retire_rpc(monkeypatch, tmp_path) -> None:
    output = tmp_path / "Example" / "Outputs" / "2026_09_07"
    output.mkdir(parents=True)
    path = output / "jobs.json"
    path.write_text('[{"job_id": "published", "company_name": "Example"}]', encoding="utf-8")

    class _Sb:
        def rpc(self, *args, **kwargs):
            raise AssertionError("physical delete is True_Yodha archive-then-retire")

    monkeypatch.setattr(
        lifecycle,
        "sync_company_run",
        lambda sb, **kwargs: lifecycle.SourceRunAssessment("complete", None),
    )
    summary = lifecycle.sync_import_run(
        _Sb(),
        feed_run_id="feed-run-1",
        json_files=[path],
        skill_id_map={},
        eligible_companies={"Example"},
        quality_status="ok",
        dry_run=False,
        eligible_job_ids={"Example": {"published"}},
    )
    assert summary["complete"] == 1
    assert "retired" not in summary
