"""Probe verdict logic — probe_scrape stubbed so it's network-free."""

from __future__ import annotations

import providers
from heal.probe import probe_company
from providers.base import ProviderResult


def _stub(jobs):
    def _f(portal, log, max_jobs=None, validate_mode=False, allow_firecrawl=False):
        selected = jobs[:max_jobs] if max_jobs else jobs
        return ProviderResult.success(selected)
    return _f


def test_capped_probe_reads_as_recovered_not_partial(monkeypatch):
    # 30 jobs available, cap 25 -> count==cap -> healthy route, not PARTIAL.
    monkeypatch.setattr(providers, "probe_scrape", _stub([{"job_title": f"r{i}"} for i in range(30)]))
    r = probe_company({"company": "NVIDIA", "ats": "pcsx"}, baseline_count=201, max_jobs=25)
    assert r.verdict == "RECOVERED"
    assert r.this_count == 25


def test_genuine_dry_route_is_coverage_drop_not_torn_partial(monkeypatch):
    monkeypatch.setattr(providers, "probe_scrape", _stub([{"job_title": f"r{i}"} for i in range(3)]))
    r = probe_company({"company": "Qualcomm", "ats": "pcsx"}, baseline_count=709, max_jobs=25)
    assert r.verdict == "COVERAGE_DROP"
    assert r.this_count == 3


def test_zero_is_still_broken(monkeypatch):
    monkeypatch.setattr(providers, "probe_scrape", _stub([]))
    r = probe_company({"company": "HSBC", "ats": "other"}, baseline_count=250, max_jobs=25)
    assert r.verdict == "STILL_BROKEN"


def test_route_raises_is_error(monkeypatch):
    def _boom(portal, log, max_jobs=None, validate_mode=False, allow_firecrawl=False):
        raise RuntimeError("405")
    monkeypatch.setattr(providers, "probe_scrape", _boom)
    r = probe_company({"company": "Persistent Systems", "ats": "custom"}, baseline_count=300, max_jobs=25)
    assert r.verdict == "ERROR"
    assert not r.reachable


def test_torn_snapshot_is_explicitly_unsafe(monkeypatch):
    def _partial(portal, log, max_jobs=None, validate_mode=False, allow_firecrawl=False):
        return ProviderResult.partial([{"title": "one"}], "page 2 returned 403")

    monkeypatch.setattr(providers, "probe_scrape", _partial)
    r = probe_company({"company": "Micron", "ats": "pcsx"}, baseline_count=294, max_jobs=25)
    assert r.verdict == "PARTIAL"
    assert not r.reachable
    assert r.this_count == 1
    assert "do not publish" in r.suggested_fix


def test_firecrawl_route_is_not_spent_during_cheap_probe(monkeypatch):
    def _fallback(portal, log, max_jobs=None, validate_mode=False, allow_firecrawl=False):
        assert allow_firecrawl is False
        return ProviderResult.fallback(
            policy="firecrawl_extract",
            reason="firecrawl_probe_skipped",
        )

    monkeypatch.setattr(providers, "probe_scrape", _fallback)
    r = probe_company({"company": "Opaque Co", "ats": "other"}, baseline_count=None)
    assert r.verdict == "FALLBACK_NEEDED"
    assert not r.reachable
