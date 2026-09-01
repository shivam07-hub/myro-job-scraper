from __future__ import annotations

import json

from providers.base import ScrapeReason
from providers.jibe import JibeProvider
from providers.workable import WorkableProvider
from providers.yubi_careers import YubiCareersProvider
from providers.zoho_recruit import _parse_detail_job


class _JsonResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_jibe_paginates_service_page_size_and_maps_full_jd(monkeypatch):
    calls = []

    def fake_get(url, params, **kwargs):
        calls.append(params["page"])
        rows = {
            1: [
                {"data": {"req_id": "1", "title": "Engineer", "full_location": "Hyderabad, India", "description": "<p>Build APIs</p>", "apply_url": "https://apply/1"}},
                {"data": {"req_id": "x", "title": "US role", "full_location": "Boston, United States", "description": "Not India"}},
            ],
            2: [
                {"data": {"req_id": "2", "title": "Analyst", "full_location": "Gurugram, India", "description": "<p>Analyse data</p>", "apply_url": "https://apply/2"}},
            ],
        }
        return _JsonResponse({"jobs": rows.get(params["page"], []), "totalCount": 3})

    monkeypatch.setattr("providers.jibe.requests.get", fake_get)
    result = JibeProvider().scrape(
        {"company": "S&P Global", "endpoint": "https://careers.spglobal.com/api/jobs", "industry": "BFSI"}
    )

    assert result.reason == ScrapeReason.SUCCESS
    assert calls == [1, 2]
    assert [job["job_id"] for job in result.jobs] == ["1", "2"]
    assert result.jobs[0]["raw_jd_text"] == "Build APIs"


def test_workable_fetches_details_and_filters_non_india(monkeypatch):
    listing = {
        "total": 2,
        "results": [
            {"id": 10, "shortcode": "INDIA1", "title": "Operator", "state": "published", "isInternal": False,
             "location": {"country": "India", "countryCode": "IN", "city": "Bengaluru"}},
            {"id": 11, "shortcode": "US1", "title": "US role", "state": "published", "isInternal": False,
             "location": {"country": "United States", "countryCode": "US", "city": "Austin"}},
        ],
    }
    detail = {
        **listing["results"][0],
        "description": "<p>Own reliable operations</p>",
        "published": "2026-08-11",
        "workplace": "on_site",
    }
    monkeypatch.setattr("providers.workable.requests.post", lambda *args, **kwargs: _JsonResponse(listing))
    monkeypatch.setattr("providers.workable.requests.get", lambda *args, **kwargs: _JsonResponse(detail))

    result = WorkableProvider().scrape(
        {"company": "Elevation Capital", "endpoint": "https://apply.workable.com/elevation-capital-3/", "industry": "BFSI"}
    )

    assert result.reason == ScrapeReason.SUCCESS
    assert len(result.jobs) == 1
    assert result.jobs[0]["raw_jd_text"] == "Own reliable operations"
    assert result.jobs[0]["job_url"].endswith("/elevation-capital-3/j/INDIA1/")


def test_workable_detail_failure_is_partial_and_not_publishable(monkeypatch):
    listing = {
        "total": 1,
        "results": [{"id": 10, "shortcode": "FAIL", "title": "Operator", "state": "published", "isInternal": False,
                     "location": {"country": "India", "countryCode": "IN", "city": "Bengaluru"}}],
    }
    monkeypatch.setattr("providers.workable.requests.post", lambda *args, **kwargs: _JsonResponse(listing))
    monkeypatch.setattr("providers.workable.requests.get", lambda *args, **kwargs: _JsonResponse({}, status_code=503))

    result = WorkableProvider().scrape(
        {"company": "Elevation Capital", "endpoint": "https://apply.workable.com/elevation-capital-3/"}
    )
    assert result.reason == ScrapeReason.PARTIAL


def _zoho_detail_script(job: dict) -> str:
    encoded = json.dumps([job], separators=(",", ":"))
    encoded = encoded.replace('"', r"\x22")
    return f"<script>jobs = JSON.parse('{encoded}')</script>"


def test_yubi_uses_official_links_then_fetches_zoho_detail(monkeypatch):
    listing_html = (
        '<a href="https://go-yubi.zohorecruit.in/jobs/Careers/123/Backend-Engineer?source=CareerSite">Job</a>'
    )
    detail_html = _zoho_detail_script(
        {"id": "123", "Job_Opening_Name": "Backend Engineer", "Job_Description": "<p>Build debt-market APIs</p>",
         "Country": "India", "State": "Tamil Nadu", "City": "Chennai"}
    )
    responses = iter([_JsonResponse({}, text=listing_html), _JsonResponse({}, text=detail_html)])
    monkeypatch.setattr("providers.zoho_recruit.requests.get", lambda *args, **kwargs: next(responses))

    result = YubiCareersProvider().scrape(
        {
            "company": "Yubi",
            "endpoint": "https://go-yubi.com/careers",
            "industry": "Fintech",
        }
    )

    assert result.reason == ScrapeReason.SUCCESS
    assert len(result.jobs) == 1
    assert result.jobs[0]["raw_jd_text"] == "Build debt-market APIs"
    assert "/jobs/Careers/123/Backend-Engineer" in result.jobs[0]["job_url"]


def test_yubi_omits_explicit_withdrawn_generic_detail_page(monkeypatch):
    listing_html = (
        '<a href="https://go-yubi.zohorecruit.in/jobs/Careers/123/Backend-Engineer?source=CareerSite">Live</a>'
        '<a href="https://go-yubi.zohorecruit.in/jobs/Careers/456/Withdrawn?source=CareerSite">Withdrawn</a>'
    )
    detail_html = _zoho_detail_script(
        {"id": "123", "Job_Opening_Name": "Backend Engineer", "Job_Description": "<p>Build APIs</p>",
         "Country": "India", "City": "Chennai"}
    )
    withdrawn_html = "<html><head><title>Yubi</title></head><body></body></html>"
    responses = iter(
        [_JsonResponse({}, text=listing_html), _JsonResponse({}, text=detail_html), _JsonResponse({}, text=withdrawn_html)]
    )
    monkeypatch.setattr("providers.yubi_careers.requests.get", lambda *args, **kwargs: next(responses))

    result = YubiCareersProvider().scrape({"company": "Yubi", "endpoint": "https://go-yubi.com/careers"})

    assert result.reason == ScrapeReason.SUCCESS
    assert [job["job_id"] for job in result.jobs] == ["123"]


def test_zoho_detail_parser_does_not_execute_page_javascript():
    parsed = _parse_detail_job(_zoho_detail_script({"Job_Description": "<p>Safe JSON only</p>"}))
    assert parsed["Job_Description"] == "<p>Safe JSON only</p>"
