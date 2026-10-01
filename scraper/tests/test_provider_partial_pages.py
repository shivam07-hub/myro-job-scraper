"""A page that fails after page 1 must yield a PARTIAL result, never success.

On 2026-10-01 PepsiCo's page 8 timed out and the provider returned the 70 jobs
from pages 1-7 as a complete snapshot (the last complete run had 232). The
lifecycle treats anything above 25% coverage as complete, and one complete
miss closes a listing, so that publish would have closed ~160 live jobs.
"""
from __future__ import annotations

from providers import google_careers, pepsico_jobs_api, tata_elxsi
from providers.base import ScrapeReason


class _Response:
    def __init__(self, *, payload=None, text: str = "", status_code: int = 200) -> None:
        self._payload = payload
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _pepsico_page(n: int) -> dict:
    return {
        "count": 30,
        "jobs": [
            {"data": {"req_id": f"r{n}-{i}", "title": f"Analyst {n}-{i}",
                      "full_location": "Hyderabad, India", "description": "Build models."}}
            for i in range(10)
        ],
    }


def test_pepsico_later_page_failure_is_partial(monkeypatch) -> None:
    def get(url, **_kwargs):
        if "page=2" in url:
            raise TimeoutError("Read timed out")
        return _Response(payload=_pepsico_page(1))

    monkeypatch.setattr(pepsico_jobs_api.requests, "get", get)

    result = _scrape(pepsico_jobs_api, {
        "company": "PepsiCo", "endpoint": "https://www.pepsicojobs.com/api/jobs?country=India",
    })

    assert result.reason == ScrapeReason.PARTIAL
    assert len(result.jobs) == 10
    assert "page 2" in result.fallback_reason


def test_pepsico_first_page_failure_stays_an_error(monkeypatch) -> None:
    def get(url, **_kwargs):
        raise TimeoutError("Read timed out")

    monkeypatch.setattr(pepsico_jobs_api.requests, "get", get)

    result = _scrape(pepsico_jobs_api, {
        "company": "PepsiCo", "endpoint": "https://www.pepsicojobs.com/api/jobs?country=India",
    })

    assert result.reason == ScrapeReason.API_BLOCKED
    assert result.jobs == []


class _Session:
    def __init__(self, respond) -> None:
        self.headers: dict = {}
        self.respond = respond

    def get(self, url, **kwargs):
        return self.respond(url)


def test_google_careers_later_page_failure_is_partial(monkeypatch) -> None:
    calls = []

    def respond(url):
        calls.append(url)
        if len(calls) > 1:
            raise ConnectionError("Could not resolve host")
        return _Response(text="<html></html>")

    page_size = google_careers._PAGE_SIZE
    monkeypatch.setattr(google_careers.requests, "Session", lambda: _Session(respond))
    monkeypatch.setattr(
        google_careers, "parse_google_careers_html",
        lambda _html, _portal, source_url: [
            {"job_id": f"g{i}", "title": f"Engineer {i}"} for i in range(page_size)
        ],
    )

    result = _scrape(google_careers, {
        "company": "Google", "endpoint": "https://www.google.com/about/careers/applications/jobs/results/?location=India",
    })

    assert result.reason == ScrapeReason.PARTIAL
    assert len(result.jobs) == page_size


def test_tata_elxsi_later_listing_failure_is_partial(monkeypatch) -> None:
    detail_url = "https://www.tataelxsi.com/careers/job/1"
    listing_calls = []

    def respond(url):
        if url == detail_url:
            return _Response(status_code=404)
        listing_calls.append(url)
        if len(listing_calls) > 1:
            raise ConnectionError("Could not resolve host")
        return _Response(text="<html>page 1</html>")

    monkeypatch.setattr(tata_elxsi.requests, "Session", lambda: _Session(respond))
    monkeypatch.setattr(
        tata_elxsi, "extract_tata_elxsi_listing_items",
        lambda _html, _url: [{"title": "Embedded Engineer", "location": "Bangalore, India",
                              "detail_url": detail_url}],
    )
    monkeypatch.setattr(tata_elxsi, "_extract_last_page", lambda _html: 2)

    result = _scrape(tata_elxsi, {
        "company": "Tata Elxsi", "endpoint": "https://www.tataelxsi.com/careers/jobs",
    })

    assert result.reason == ScrapeReason.PARTIAL
    assert len(result.jobs) == 1


def _scrape(module, portal):
    provider_cls = next(
        value for value in vars(module).values()
        if isinstance(value, type) and getattr(value, "key", None) == module.__name__.split(".")[-1]
    )
    return provider_cls().scrape(portal)



# ── Shared seam: dispatch turns PartialSnapshot into a PARTIAL result ──────────

import logging

import requests

from providers import sap_jobs2web_html, workday
from providers.base import is_transport_failure
from providers.registry import dispatch_scrape_result

LOG = logging.getLogger("test")


def _http_error(status: int) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"HTTP {status}", response=response)


def test_transport_failures_are_timeouts_dns_429_and_5xx_not_4xx() -> None:
    assert is_transport_failure(requests.Timeout("read timed out"))
    assert is_transport_failure(requests.ConnectionError("Could not resolve host"))
    assert is_transport_failure(_http_error(503))
    assert is_transport_failure(_http_error(429))
    assert not is_transport_failure(_http_error(404))
    assert not is_transport_failure(ValueError("bad json"))


def test_workday_later_page_timeout_is_partial_through_dispatch(monkeypatch) -> None:
    page_size = workday.WORKDAY_PAGE_SIZE
    calls = []

    def post(url, **_kwargs):
        calls.append(url)
        if len(calls) > 1:
            raise requests.Timeout("Read timed out")
        postings = [
            {"externalPath": f"/job/Bangalore/Engineer_R{i}", "title": f"Engineer {i}",
             "locationsText": "Bangalore, India", "bulletFields": [f"R{i}"]}
            for i in range(page_size)
        ]
        return _Response(payload={"total": page_size * 3, "jobPostings": postings})

    monkeypatch.setattr(workday.requests, "post", post)
    result = dispatch_scrape_result({
        "company": "Example", "ats": "workday", "india_only": True,
        "endpoint": "https://example.wd1.myworkdayjobs.com/wday/cxs/example/careers/jobs",
        "workday_facet_param": "locations", "workday_india_uuids": ["india"],
    }, LOG)

    assert result.reason == ScrapeReason.PARTIAL
    assert len(result.jobs) == page_size


def _sap(monkeypatch, second_page):
    hint = 25
    listing_calls = []

    def respond(url):
        listing_calls.append(url)
        if len(listing_calls) > 1:
            return second_page()
        return _Response(text="<html>page 1</html>")

    monkeypatch.setattr(sap_jobs2web_html.requests, "Session", lambda: _Session(respond))
    monkeypatch.setattr(
        sap_jobs2web_html, "_extract_rows",
        lambda _html: [{"href": f"/job/{len(listing_calls)}-{i}", "title": f"Officer {i}",
                        "listing_location": "Mumbai, IN"} for i in range(hint)],
    )
    monkeypatch.setattr(
        sap_jobs2web_html, "_extract_detail",
        lambda _session, url, title, loc: {"job_id": url.rsplit("/", 1)[-1], "title": title,
                                           "raw_jd_text": "Run branch operations.", "location": loc},
    )
    return dispatch_scrape_result({
        "company": "Example Bank", "ats": "sap_jobs2web_html", "india_only": True,
        "endpoint": "https://careers.example.com/search/?q=&locationsearch=india",
    }, LOG)


def test_sap_later_page_5xx_is_partial_through_dispatch(monkeypatch) -> None:
    result = _sap(monkeypatch, lambda: _Response(status_code=503))

    assert result.reason == ScrapeReason.PARTIAL
    assert len(result.jobs) == 25


def test_sap_later_page_dns_failure_is_partial_through_dispatch(monkeypatch) -> None:
    def fail():
        raise requests.ConnectionError("Could not resolve host")

    result = _sap(monkeypatch, fail)

    assert result.reason == ScrapeReason.PARTIAL


def test_sap_404_past_the_last_page_still_ends_normally(monkeypatch) -> None:
    result = _sap(monkeypatch, lambda: _Response(status_code=404))

    assert result.reason == ScrapeReason.SUCCESS
    assert len(result.jobs) == 25
