"""Oracle CE stops returning rows at offset 10,000.

Kotak reported 11,871 open postings but only the newest 10,000 were readable,
so every complete run closed the oldest ~1,900 listings while they were still
open. A site over the ceiling is now read in posting-date windows that each
fit under it; a single day still over the ceiling is a truncated read.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

import pytest

import providers.generic_json as generic_json
from providers.base import PartialSnapshot

ENDPOINT = (
    "https://hcbt.fa.em2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
    "?onlyData=true&finder=findReqs;siteNumber=CX_1001,limit=25,sortBy=POSTING_DATES_DESC"
)
PORTAL = {"company": "Kotak Mahindra Bank", "ats": "oracle", "oracle_nested": True,
          "india_only": True, "industry": "BFSI", "endpoint": ENDPOINT}
CEILING = 50


class _Response:
    headers = {"Content-Type": "application/json"}

    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Status403(_Response):
    def __init__(self):
        super().__init__({})

    def raise_for_status(self):
        raise generic_json.requests.HTTPError("403 Forbidden")


class _HtmlPage(_Response):
    headers = {"Content-Type": "text/html"}
    text = "<html>Access denied</html>"

    def __init__(self):
        super().__init__({})


class _BadJson(_Response):
    def json(self):
        raise ValueError("Expecting value")


def _fake_oracle(postings: list[tuple[int, date]], calls: list[str], ceiling: int = CEILING,
                 location=lambda pid: "Mumbai, India", overcount: int = 0):
    """Serve findReqs like Oracle: date windows, newest first, nothing past the ceiling."""
    def fake_get(url, headers=None, timeout=None):
        calls.append(url)
        window = re.search(r"postingStartDate=([\d-]+),postingEndDate=([\d-]+)", url)
        rows = postings
        if window:
            start, end = (date.fromisoformat(d) for d in window.groups())
            rows = [p for p in postings if start <= p[1] <= end]
        rows = sorted(rows, key=lambda p: p[1], reverse=True)
        limit = int(re.search(r"limit=(\d+)", url).group(1))
        offset_match = re.search(r"offset=(\d+)", url)
        offset = int(offset_match.group(1)) if offset_match else 0
        page = rows[offset:offset + limit] if offset < ceiling else []
        return _Response({"items": [{"TotalJobsCount": len(rows) + overcount, "requisitionList": [
            {"Id": pid, "Title": f"Personal Banker {pid}", "PrimaryLocation": location(pid),
             "PostedDate": posted.isoformat(), "ExternalDescriptionStr": "x" * 1300}
            for pid, posted in page
        ]}]})
    return fake_get


def test_site_over_the_ceiling_is_read_completely_in_date_windows(monkeypatch):
    today = date.today()
    postings = [(1000 + i, today - timedelta(days=i % 40)) for i in range(120)]
    calls: list[str] = []
    monkeypatch.setattr(generic_json, "ORACLE_OFFSET_CEILING", CEILING)
    monkeypatch.setattr(generic_json.requests, "get", _fake_oracle(postings, calls))

    jobs = generic_json.scrape_get(PORTAL)

    assert sorted(int(j["job_id"]) for j in jobs) == list(range(1000, 1120))
    assert any("postingStartDate=" in url for url in calls)


def test_one_day_over_the_ceiling_is_a_partial_snapshot(monkeypatch):
    """Nothing can split a single day, so the read is truncated: publish and close nothing."""
    today = date.today()
    postings = [(1000 + i, today) for i in range(CEILING + 10)]
    monkeypatch.setattr(generic_json, "ORACLE_OFFSET_CEILING", CEILING)
    monkeypatch.setattr(generic_json.requests, "get", _fake_oracle(postings, []))

    with pytest.raises(PartialSnapshot):
        generic_json.scrape_get(PORTAL)


def test_a_slow_page_is_retried_before_the_read_fails(monkeypatch):
    today = date.today()
    postings = [(1000 + i, today - timedelta(days=i % 40)) for i in range(120)]
    serve = _fake_oracle(postings, [])
    timeouts = {"left": 1}

    def flaky_get(url, headers=None, timeout=None):
        if "offset=" in url and "limit=100" in url and timeouts["left"]:
            timeouts["left"] -= 1
            raise generic_json.requests.Timeout("read timed out")
        return serve(url, headers=headers, timeout=timeout)

    monkeypatch.setattr(generic_json, "ORACLE_OFFSET_CEILING", CEILING)
    monkeypatch.setattr(generic_json.requests, "get", flaky_get)
    monkeypatch.setattr(generic_json.time, "sleep", lambda s: None)

    jobs = generic_json.scrape_get(PORTAL)

    assert len(jobs) == 120


def test_site_under_the_ceiling_keeps_the_plain_read(monkeypatch):
    today = date.today()
    postings = [(1000 + i, today - timedelta(days=i)) for i in range(30)]
    calls: list[str] = []
    monkeypatch.setattr(generic_json, "ORACLE_OFFSET_CEILING", CEILING)
    monkeypatch.setattr(generic_json.requests, "get", _fake_oracle(postings, calls))

    jobs = generic_json.scrape_get(PORTAL)

    assert len(jobs) == 30
    assert not any("postingStartDate=" in url for url in calls)


def _plain_site() -> list[tuple[int, date]]:
    today = date.today()
    return [(1000 + i, today - timedelta(days=i % 40)) for i in range(250)]


@pytest.mark.parametrize("failure", [
    pytest.param(lambda: (_ for _ in ()).throw(generic_json.requests.Timeout("read timed out")), id="timeout"),
    pytest.param(_Status403, id="403"),
    pytest.param(_HtmlPage, id="html-block-page"),
    pytest.param(_BadJson, id="bad-json"),
])
def test_plain_read_later_page_failure_is_a_partial_snapshot(monkeypatch, failure):
    """A prefix of the site must never pass for the whole site: one miss closes a listing."""
    serve = _fake_oracle(_plain_site(), [], ceiling=10_000)

    def get(url, headers=None, timeout=None):
        return failure() if "offset=100" in url else serve(url, headers=headers, timeout=timeout)

    monkeypatch.setattr(generic_json.requests, "get", get)
    monkeypatch.setattr(generic_json.time, "sleep", lambda s: None)

    with pytest.raises(PartialSnapshot) as caught:
        generic_json.scrape_get(PORTAL)

    assert len(caught.value.jobs) == 100
    assert "offset 100" in caught.value.note


def test_plain_read_retries_a_slow_later_page(monkeypatch):
    serve = _fake_oracle(_plain_site(), [], ceiling=10_000)
    timeouts = {"left": 1}

    def get(url, headers=None, timeout=None):
        if "offset=100" in url and timeouts["left"]:
            timeouts["left"] -= 1
            raise generic_json.requests.Timeout("read timed out")
        return serve(url, headers=headers, timeout=timeout)

    monkeypatch.setattr(generic_json.requests, "get", get)
    monkeypatch.setattr(generic_json.time, "sleep", lambda s: None)

    assert len(generic_json.scrape_get(PORTAL)) == 250


def test_plain_read_first_page_failure_stays_a_hard_error(monkeypatch):
    """The provider maps None to the careers-page fallback; no rows means no prefix to keep."""
    def get(url, headers=None, timeout=None):
        raise generic_json.requests.Timeout("read timed out")

    monkeypatch.setattr(generic_json.requests, "get", get)
    monkeypatch.setattr(generic_json.time, "sleep", lambda s: None)

    assert generic_json.scrape_get(PORTAL) is None


def test_plain_read_first_page_html_keeps_the_firecrawl_route(monkeypatch):
    monkeypatch.setattr(generic_json.requests, "get", lambda url, headers=None, timeout=None: _HtmlPage())
    monkeypatch.setattr(generic_json.time, "sleep", lambda s: None)

    assert generic_json.scrape_get(PORTAL)[0]["_needs_firecrawl"] is True


def test_a_lost_window_count_is_a_partial_snapshot(monkeypatch):
    today = date.today()
    postings = [(1000 + i, today - timedelta(days=i % 40)) for i in range(120)]
    serve = _fake_oracle(postings, [])

    def get(url, headers=None, timeout=None):
        if re.search(r"limit=1\b", url):
            raise generic_json.requests.Timeout("read timed out")
        return serve(url, headers=headers, timeout=timeout)

    monkeypatch.setattr(generic_json, "ORACLE_OFFSET_CEILING", CEILING)
    monkeypatch.setattr(generic_json.requests, "get", get)
    monkeypatch.setattr(generic_json.time, "sleep", lambda s: None)

    with pytest.raises(PartialSnapshot):
        generic_json.scrape_get(PORTAL)


def test_plain_read_does_not_stop_at_a_page_with_no_india_rows(monkeypatch):
    today = date.today()
    postings = [(1000 + i, today - timedelta(days=i)) for i in range(130)]
    location = lambda pid: "Dubai, UAE" if pid < 1100 else "Mumbai, India"
    monkeypatch.setattr(generic_json.requests, "get",
                        _fake_oracle(postings, [], ceiling=10_000, location=location))

    jobs = generic_json.scrape_get(PORTAL)

    assert sorted(int(j["job_id"]) for j in jobs) == list(range(1100, 1130))


def test_plain_read_tolerates_a_count_one_above_the_rows_served(monkeypatch):
    """Oracle's own site reported 319 and served 318 on one read of 2026-10-30; not a lost page."""
    today = date.today()
    postings = [(1000 + i, today - timedelta(days=i % 40)) for i in range(300)]
    monkeypatch.setattr(generic_json.requests, "get",
                        _fake_oracle(postings, [], ceiling=10_000, overcount=1))

    assert len(generic_json.scrape_get(PORTAL)) == 300


def test_plain_read_empty_page_with_a_full_page_still_reported_is_partial(monkeypatch):
    serve = _fake_oracle(_plain_site(), [], ceiling=100)
    monkeypatch.setattr(generic_json.requests, "get", serve)

    with pytest.raises(PartialSnapshot) as caught:
        generic_json.scrape_get(PORTAL)

    assert len(caught.value.jobs) == 100
