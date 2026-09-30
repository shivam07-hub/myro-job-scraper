from __future__ import annotations

import logging

import main
import network_guard
from providers.base import ProviderResult, ScrapeReason

LOG = logging.getLogger("test")
# conftest stubs network_available for every test; keep the real one here.
REAL_NETWORK_AVAILABLE = network_guard.network_available


class _Clock:
    """monotonic() that advances only when sleep() is called."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_wait_for_network_returns_immediately_when_up() -> None:
    clock = _Clock()

    assert network_guard.wait_for_network(
        LOG, check=lambda: True, sleep=clock.sleep, monotonic=clock.monotonic,
    )
    assert clock.sleeps == []


def test_wait_for_network_pauses_until_dns_returns() -> None:
    clock = _Clock()
    answers = iter([False, False, True])

    assert network_guard.wait_for_network(
        LOG, check=lambda: next(answers), sleep=clock.sleep, monotonic=clock.monotonic,
        poll_seconds=30,
    )
    assert clock.sleeps == [30, 30]


def test_wait_for_network_gives_up_after_the_awake_budget() -> None:
    clock = _Clock()

    assert not network_guard.wait_for_network(
        LOG, check=lambda: False, sleep=clock.sleep, monotonic=clock.monotonic,
        poll_seconds=30, max_wait_seconds=90,
    )
    assert sum(clock.sleeps) == 90


def test_network_available_needs_one_resolvable_host() -> None:
    def resolver(host, *_args, **_kwargs):
        if host == "b.example":
            return [("ok",)]
        raise OSError("nodename nor servname provided")

    assert REAL_NETWORK_AVAILABLE(("a.example", "b.example"), resolver=resolver)
    assert not REAL_NETWORK_AVAILABLE(("a.example",), resolver=resolver)


class _Checkpoint:
    run_id = "network-test"

    def __init__(self) -> None:
        self.failed: list[tuple[str, str]] = []

    def start(self, company, ats):
        return None

    def mark_failed(self, company, reason):
        self.failed.append((company, reason))


def _run(portals, monkeypatch, tmp_path, *, network, scrape):
    clock = _Clock()
    monkeypatch.setattr(network_guard, "network_available", network)
    monkeypatch.setattr(network_guard, "_sleep", clock.sleep)
    monkeypatch.setattr(network_guard, "_monotonic", clock.monotonic)
    monkeypatch.setattr(main, "scrape_portal", scrape)
    monkeypatch.setattr(main.time, "sleep", lambda _: None)
    checkpoint = _Checkpoint()
    summary = main.run(
        portals, skip_enrich=True, log=LOG, output_base=str(tmp_path), checkpoint=checkpoint,
    )
    return summary, checkpoint


def test_company_that_failed_while_offline_is_retried_once_network_returns(monkeypatch, tmp_path):
    # 2026-09-30: the Mac slept mid-run; each dark wake had no DNS, and 20
    # companies were recorded as empty in milliseconds.
    network = iter([True, False, False, True, True, True])
    calls: list[str] = []

    def scrape(portal, *_args, **_kwargs):
        calls.append(portal["company"])
        if len(calls) == 1:
            return ProviderResult.error(ScrapeReason.NO_JOBS)
        return ProviderResult.partial([{"job_id": "x"}], "stop before save")

    summary, _ = _run(
        [{"company": "Asian Paints", "ats": "sap_jobs2web_html"}],
        monkeypatch, tmp_path, network=lambda: next(network), scrape=scrape,
    )

    assert calls == ["Asian Paints", "Asian Paints"]
    assert summary["company_stats"][0]["status"] == "partial"


def test_genuine_empty_result_with_network_up_is_not_retried(monkeypatch, tmp_path):
    calls: list[str] = []

    def scrape(portal, *_args, **_kwargs):
        calls.append(portal["company"])
        return ProviderResult.error(ScrapeReason.NO_JOBS)

    summary, checkpoint = _run(
        [{"company": "Quiet Co", "ats": "greenhouse"}],
        monkeypatch, tmp_path, network=lambda: True, scrape=scrape,
    )

    assert calls == ["Quiet Co"]
    assert summary["skipped"] == 1
    assert checkpoint.failed[0][0] == "Quiet Co"


def test_run_stops_cleanly_when_network_never_returns(monkeypatch, tmp_path):
    monkeypatch.setattr(network_guard, "MAX_WAIT_SECONDS", 60)
    calls: list[str] = []

    summary, _ = _run(
        [{"company": "A", "ats": "greenhouse"}, {"company": "B", "ats": "greenhouse"}],
        monkeypatch, tmp_path, network=lambda: False,
        scrape=lambda portal, *_a, **_k: calls.append(portal["company"]),
    )

    assert calls == []
    assert summary["processed"] == 0
    assert summary["errors"][0]["stage"] == "network"
