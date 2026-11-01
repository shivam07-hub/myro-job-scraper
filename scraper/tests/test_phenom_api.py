from __future__ import annotations

from providers.base import ScrapeReason
from providers.phenom import PhenomProvider


def _job(req_id: str, city: str, country: str) -> dict:
    return {
        "data": {
            "req_id": req_id,
            "title": f"Role {req_id}",
            "description": "<p>Own the plant energy audit</p>",
            "city": city,
            "country": country,
            "full_location": f"{city}, {country}",
            "apply_url": f"https://careers-se.icims.com/jobs/{req_id}/login",
        }
    }


class _Response:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_paginates_by_total_count_and_keeps_only_india(monkeypatch):
    """careers.se.com reports totalCount (not total) and its location=India
    filter also returns ranked jobs from other countries."""
    pages = {
        1: [_job("1", "Bangalore", "India"), _job("2", "Florence", "Italy")],
        2: [_job("3", "Gurgaon", "India"), _job("4", "Cairo", "Egypt")],
        3: [_job("5", "Mumbai", "India")],
    }
    seen: list[str] = []

    def fake_get(url, **kwargs):
        seen.append(url)
        page = int(url.rsplit("page=", 1)[1])
        return _Response({"jobs": pages.get(page, []), "totalCount": 5})

    monkeypatch.setattr("providers.phenom.requests.get", fake_get)
    portal = {
        "company": "Schneider Electric",
        "endpoint": "https://careers.se.com/api/jobs?location=India&pageSize=2",
        "india_only": True,
        "industry": "Industrial",
    }

    result = PhenomProvider().scrape(portal)

    assert result.reason == ScrapeReason.SUCCESS
    assert [j["job_id"] for j in result.jobs] == ["1", "3", "5"]
    assert len(seen) <= 4  # pages 1-3, plus at most one empty page to confirm the end
    assert result.jobs[0]["raw_jd_text"] == "Own the plant energy audit"
    assert result.jobs[0]["location_city"] == "Bangalore, India"
