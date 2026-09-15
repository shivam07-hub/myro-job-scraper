from __future__ import annotations

import logging

import main
from providers.base import ProviderResult


class _Checkpoint:
    run_id = "partial-test"

    def __init__(self):
        self.failed = []

    def start(self, company, ats):
        return None

    def mark_failed(self, company, reason):
        self.failed.append((company, reason))


def test_partial_snapshot_never_reaches_save(monkeypatch, tmp_path):
    monkeypatch.setattr(
        main,
        "scrape_portal",
        lambda *args, **kwargs: ProviderResult.partial([{"job_id": "unsafe"}], "page 2 failed"),
    )
    monkeypatch.setattr(main, "save_jobs", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not save")))
    monkeypatch.setattr(main.time, "sleep", lambda _: None)
    checkpoint = _Checkpoint()

    summary = main.run(
        [{"company": "Micron", "ats": "pcsx"}],
        skip_enrich=True,
        log=logging.getLogger("test"),
        output_base=str(tmp_path),
        checkpoint=checkpoint,
    )

    assert summary["processed"] == 0
    assert summary["skipped"] == 1
    assert summary["company_stats"][0]["status"] == "partial"
    assert summary["unresolved"][0]["reason"] == "partial_snapshot"
    assert checkpoint.failed == [("Micron", "partial_snapshot: page 2 failed")]
