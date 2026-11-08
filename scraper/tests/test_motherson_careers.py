from __future__ import annotations

import json
import socket

import pytest
import requests

import providers.motherson_careers as mc
from providers.base import ScrapeReason

_ENDPOINT = "https://careers.motherson.com/en/jobs"
_DATA = "https://careers.motherson.com/_next/data/build-1/en/job/"
_SF_APPLY = (
    "https://career55.sapsf.eu/career?company=smrautomot"
    "&career_ns=job_application&career_job_req_id=7688"
)


def _posting(slug: str, title: str, city: str, country: str) -> dict:
    return {
        "id": f"rec-{slug}",
        "slug": slug,
        "title": title,
        "location": {"name": city, "country": {"name": country}},
    }


def _listing(*postings: dict) -> str:
    data = {
        "page": "/jobs",
        "buildId": "build-1",
        "locale": "en",
        "props": {"pageProps": {"allJobs": list(postings)}},
    }
    return (
        "<html><body><main>Jobs</main>"
        f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
        "</body></html>"
    )


def _job(slug: str, title: str, apply_url: str, *, company: str | None = "Motherson Technology Services Limited (MTSL)") -> dict:
    return {
        "id": f"rec-{slug}",
        "slug": slug,
        "title": title,
        "introduction": "<p>To lead all tooling activities.</p>",
        "tasks": "<ul><li>Lead new mould development.</li></ul>",
        "profile": "<ul><li>-</li></ul>",
        "whatWeOffer": "<p>Health insurance.</p>",
        "hoursPerWeek": "48.0",
        "applyUrl": apply_url,
        "company": {"name": company} if company else None,
        "businessDivision": {"name": "Modules & Polymer Products"},
        "careerLevel": {"name": "Experienced"},
        "location": {"name": "Pune", "country": {"name": "India"}},
    }


class _Resp:
    def __init__(self, text: str = "", payload: dict | None = None, status: int = 200) -> None:
        self.text = text
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def json(self) -> dict:
        return self._payload or {}


def _serve(monkeypatch, pages: dict[str, _Resp | list[_Resp]]) -> list[str]:
    """Answer each URL with its response; a list is answered in order."""
    asked: list[str] = []

    def get(url, headers=None, timeout=None):
        asked.append(url)
        answer = pages[url]
        return answer.pop(0) if isinstance(answer, list) else answer

    monkeypatch.setattr(mc.requests, "get", get)
    monkeypatch.setattr(mc.time, "sleep", lambda seconds: None)
    return asked


def _dns(monkeypatch, errors: dict[str, int]) -> None:
    def getaddrinfo(host, port, *args, **kwargs):
        if host in errors:
            raise socket.gaierror(errors[host], "lookup failed")
        return [("ok",)]

    monkeypatch.setattr(mc.socket, "getaddrinfo", getaddrinfo)


def test_parse_listing_reads_next_data() -> None:
    build_id, locale, jobs = mc.parse_listing(_listing(_posting("engineer-6488", "ENGINEER", "Pune", "India")))
    assert (build_id, locale) == ("build-1", "en")
    assert [j["slug"] for j in jobs] == ["engineer-6488"]


def test_parse_listing_without_next_data_is_a_layout_change() -> None:
    with pytest.raises(mc._LayoutChanged):
        mc.parse_listing("<html>maintenance</html>")


def test_jd_text_uses_page_headings_and_skips_placeholder_sections() -> None:
    text = mc.jd_text(_job("deputy-manager-7688", "DEPUTY MANAGER", _SF_APPLY))
    assert text.startswith("Career level: Experienced\nDivision: Modules & Polymer Products\nHours per week: 48.0")
    assert "To lead all tooling activities." in text
    assert "What you'll do\nLead new mould development." in text
    assert "What we offer\nHealth insurance." in text
    # profile is "<ul><li>-</li></ul>" on this posting: nothing to say, no heading
    assert "What we are looking for" not in text


def test_scrape_keeps_india_jobs_with_a_live_apply_host(monkeypatch) -> None:
    dead = "https://apply.motherson.com/careers/manager-finance?apply=1"
    asked = _serve(
        monkeypatch,
        {
            _ENDPOINT: _Resp(
                _listing(
                    _posting("deputy-manager-7688", "DEPUTY MANAGER", "Pune", "India"),
                    _posting("manager-finance-619724", "Manager Finance", "Noida", "India"),
                    _posting("logistiker-9001", "Logistiker", "Stuttgart", "Germany"),
                )
            ),
            _DATA + "deputy-manager-7688.json": _Resp(
                payload={"pageProps": {"job": _job("deputy-manager-7688", "DEPUTY MANAGER", _SF_APPLY)}}
            ),
            _DATA + "manager-finance-619724.json": _Resp(
                payload={"pageProps": {"job": _job("manager-finance-619724", "Manager Finance", dead, company=None)}}
            ),
        },
    )
    _dns(monkeypatch, {"apply.motherson.com": socket.EAI_NONAME})

    result = mc.MothersonCareersProvider().scrape(
        {"company": "Motherson Group", "endpoint": _ENDPOINT, "industry": "Automotive"}
    )

    assert result.reason == ScrapeReason.SUCCESS
    assert _DATA + "logistiker-9001.json" not in asked
    assert len(result.jobs) == 1
    job = result.jobs[0]
    assert job["job_id"] == "7688"
    assert job["title"] == "DEPUTY MANAGER"
    assert job["job_url"] == "https://careers.motherson.com/en/job/deputy-manager-7688"
    assert job["source_api_url"] == _ENDPOINT
    assert job["business_unit"] == "Motherson Technology Services Limited (MTSL)"
    assert job["location_city"] == "Pune, India"
    assert job["source_platform"] == "Motherson Careers"
    assert job["industry"] == "Automotive"
    assert "Lead new mould development." in job["raw_jd_text"]


def test_scrape_keeps_jobs_when_dns_is_only_temporarily_down(monkeypatch) -> None:
    _serve(
        monkeypatch,
        {
            _ENDPOINT: _Resp(_listing(_posting("deputy-manager-7688", "DEPUTY MANAGER", "Pune", "India"))),
            _DATA + "deputy-manager-7688.json": _Resp(
                payload={"pageProps": {"job": _job("deputy-manager-7688", "DEPUTY MANAGER", _SF_APPLY)}}
            ),
        },
    )
    _dns(monkeypatch, {"career55.sapsf.eu": socket.EAI_AGAIN})

    result = mc.MothersonCareersProvider().scrape({"company": "Motherson Group", "endpoint": _ENDPOINT})

    assert [j["job_id"] for j in result.jobs] == ["7688"]


def test_scrape_with_a_failed_description_is_partial(monkeypatch) -> None:
    _serve(
        monkeypatch,
        {
            _ENDPOINT: _Resp(
                _listing(
                    _posting("deputy-manager-7688", "DEPUTY MANAGER", "Pune", "India"),
                    _posting("engineer-6488", "ENGINEER", "Pune", "India"),
                )
            ),
            _DATA + "deputy-manager-7688.json": _Resp(
                payload={"pageProps": {"job": _job("deputy-manager-7688", "DEPUTY MANAGER", _SF_APPLY)}}
            ),
            _DATA + "engineer-6488.json": _Resp(status=404),
        },
    )
    _dns(monkeypatch, {})

    result = mc.MothersonCareersProvider().scrape({"company": "Motherson Group", "endpoint": _ENDPOINT})

    assert result.reason == ScrapeReason.PARTIAL
    assert [j["job_id"] for j in result.jobs] == ["7688"]
    assert "engineer-6488" in (result.fallback_reason or "")


def test_a_waf_block_on_one_description_is_retried(monkeypatch) -> None:
    detail = _DATA + "deputy-manager-7688.json"
    asked = _serve(
        monkeypatch,
        {
            _ENDPOINT: _Resp(_listing(_posting("deputy-manager-7688", "DEPUTY MANAGER", "Pune", "India"))),
            detail: [
                _Resp("Sorry, you have been blocked", status=403),
                _Resp(payload={"pageProps": {"job": _job("deputy-manager-7688", "DEPUTY MANAGER", _SF_APPLY)}}),
            ],
        },
    )
    _dns(monkeypatch, {})

    result = mc.MothersonCareersProvider().scrape({"company": "Motherson Group", "endpoint": _ENDPOINT})

    assert result.reason == ScrapeReason.SUCCESS
    assert asked.count(detail) == 2


def test_scrape_without_next_data_is_a_parse_error(monkeypatch) -> None:
    _serve(monkeypatch, {_ENDPOINT: _Resp("<html>maintenance</html>")})

    result = mc.MothersonCareersProvider().scrape({"company": "Motherson Group", "endpoint": _ENDPOINT})

    assert result.reason == ScrapeReason.PARSE_ERROR


def test_scrape_with_postings_missing_countries_is_a_parse_error(monkeypatch) -> None:
    # A renamed location field must not read as "Motherson has no India jobs".
    posting = {"id": "rec-1", "slug": "engineer-6488", "title": "ENGINEER", "place": {"name": "Pune"}}
    _serve(monkeypatch, {_ENDPOINT: _Resp(_listing(posting))})

    result = mc.MothersonCareersProvider().scrape({"company": "Motherson Group", "endpoint": _ENDPOINT})

    assert result.reason == ScrapeReason.PARSE_ERROR


def test_listing_fetch_failure_is_api_blocked(monkeypatch) -> None:
    asked = _serve(monkeypatch, {_ENDPOINT: _Resp(status=503)})

    result = mc.MothersonCareersProvider().scrape({"company": "Motherson Group", "endpoint": _ENDPOINT})

    assert result.reason == ScrapeReason.API_BLOCKED
    assert len(asked) == mc._ATTEMPTS
