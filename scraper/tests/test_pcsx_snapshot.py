from __future__ import annotations

import requests

import providers.pcsx as pcsx
from providers.base import ScrapeReason


class _Response:
    def __init__(self, payload=None, *, status=200, text=""):
        self._payload = payload
        self.status_code = status
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(str(self.status_code))
            error.response = self
            raise error

    def json(self):
        return self._payload


class _Session:
    def __init__(self, api_responses):
        self.api_responses = iter(api_responses)
        self.bootstrap_count = 0

    def get(self, url, **kwargs):
        if "/careers?" in url:
            self.bootstrap_count += 1
            return _Response(text="career board")
        assert url.endswith("/api/pcsx/search")
        return next(self.api_responses)


def _portal():
    return {
        "company": "Micron",
        "ats": "pcsx",
        "endpoint": "https://careers.micron.com",
        "pcsx_domain": "micron.com",
    }


def _listing(job_id="one", total=20):
    return {"data": {"count": total, "positions": [{"id": job_id, "name": "Engineer", "locations": ["Bengaluru, India"]}]}}


def test_later_page_failure_returns_quarantined_partial(monkeypatch):
    session = _Session([
        _Response(_listing()),
        _Response(status=403),
        _Response(status=403),
    ])
    monkeypatch.setattr(pcsx.requests, "Session", lambda: session)
    monkeypatch.setattr(pcsx, "_fetch_jd", lambda *args: "complete description")
    monkeypatch.setattr(pcsx.time, "sleep", lambda _: None)

    result = pcsx._scrape_pcsx(_portal())

    assert result.reason == ScrapeReason.PARTIAL
    assert len(result.jobs) == 1
    assert "start_10" in (result.fallback_reason or "")
    assert session.bootstrap_count == 2


def test_403_refreshes_visitor_session_once_then_recovers(monkeypatch):
    session = _Session([
        _Response(status=403),
        _Response(_listing(total=1)),
    ])
    monkeypatch.setattr(pcsx.requests, "Session", lambda: session)
    monkeypatch.setattr(pcsx, "_fetch_jd", lambda *args: "complete description")
    monkeypatch.setattr(pcsx.time, "sleep", lambda _: None)

    result = pcsx._scrape_pcsx(_portal())

    assert result.reason == ScrapeReason.SUCCESS
    assert len(result.jobs) == 1
    assert session.bootstrap_count == 2


def test_overlapping_pages_keep_one_row_per_requisition(monkeypatch):
    session = _Session([
        _Response(_listing(job_id="same", total=20)),
        _Response(_listing(job_id="same", total=20)),
    ])
    monkeypatch.setattr(pcsx.requests, "Session", lambda: session)
    monkeypatch.setattr(pcsx, "_fetch_jd", lambda *args: "complete description")

    result = pcsx._scrape_pcsx(_portal())

    assert result.reason == ScrapeReason.SUCCESS
    assert [job["job_id"] for job in result.jobs] == ["same"]
