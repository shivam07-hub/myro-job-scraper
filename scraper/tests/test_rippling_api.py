from __future__ import annotations

import json

import pytest
import requests

from providers.base import PartialSnapshot, ScrapeReason
from providers.rippling import RipplingProvider

ENDPOINT = "https://ats.rippling.com/api/v2/board/rippling/jobs"
PORTAL = {"company": "Rippling", "endpoint": ENDPOINT, "india_only": True, "industry": "Technology"}


def _item(job_id: str, country_code: str, name: str) -> dict:
    return {
        "id": job_id,
        "name": f"Role {job_id}",
        "url": f"https://ats.rippling.com/rippling/jobs/{job_id}",
        "department": {"name": "Engineering"},
        "locations": [{"name": name, "countryCode": country_code}],
    }


def _detail_html(job_id: str) -> str:
    payload = {"props": {"pageProps": {"apiData": {"jobPost": {
        "uuid": job_id,
        "name": f"Role {job_id}",
        "url": f"https://ats.rippling.com/rippling/jobs/{job_id}",
        "description": {"role": f"<p>Build payroll for {job_id}</p>"},
        "workLocations": [{"name": "Bangalore, India"}],
        "department": {"name": "Engineering"},
    }}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'


class _Response:
    def __init__(self, *, payload=None, text="", status=200):
        self._payload, self.text, self.status_code = payload, text, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)

    def json(self):
        return self._payload


def test_board_api_pages_through_every_job_and_keeps_india(monkeypatch):
    """The careers page stopped embedding its job list; the public board API
    pages through all of it with the same item shape."""
    pages = {
        0: [_item("in-1", "IN", "Bangalore, India"), _item("us-1", "US", "New York, NY")],
        1: [_item("in-2", "IN", "Bangalore, India")],
    }

    def fake_get(url, params=None, **kwargs):
        if url == ENDPOINT:
            page = params["page"]
            return _Response(payload={"items": pages.get(page, []), "page": page, "totalPages": 2})
        return _Response(text=_detail_html(url.rsplit("/", 1)[1]))

    monkeypatch.setattr("providers.rippling.requests.get", fake_get)

    result = RipplingProvider().scrape(PORTAL)

    assert result.reason == ScrapeReason.SUCCESS
    assert [j["job_id"] for j in result.jobs] == ["in-1", "in-2"]
    assert "Build payroll for in-2" in result.jobs[1]["raw_jd_text"]


def test_board_api_failure_after_first_page_is_partial(monkeypatch):
    def fake_get(url, params=None, **kwargs):
        if url == ENDPOINT and params["page"] == 0:
            return _Response(payload={"items": [_item("in-1", "IN", "Bangalore, India")], "totalPages": 2})
        if url == ENDPOINT:
            return _Response(status=503)
        return _Response(text=_detail_html("in-1"))

    monkeypatch.setattr("providers.rippling.requests.get", fake_get)

    with pytest.raises(PartialSnapshot):
        RipplingProvider().scrape(PORTAL)
