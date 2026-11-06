from __future__ import annotations

import providers.taleo as taleo
from portal_reader import parse_portals


class _Resp:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"totalJobs": 0, "jobSearchResult": []}


def _captured_body(monkeypatch, portal: dict) -> dict:
    sent: dict = {}

    class _Session:
        def __init__(self) -> None:
            self.headers: dict = {}

        def post(self, url, json=None, timeout=None):
            sent.update(json or {})
            return _Resp()

    monkeypatch.setattr(taleo.requests, "Session", _Session)
    taleo._scrape_taleo_v1(portal)
    return sent


def test_taleo_v1_sends_the_portal_locale(monkeypatch) -> None:
    # Standard Chartered posts in en_GB only: en_US returns totalJobs=0.
    body = _captured_body(monkeypatch, {
        "company": "Standard Chartered Bank",
        "endpoint": "https://jobs.standardchartered.com/services/recruiting/v1/jobs",
        "taleo_v1": True,
        "taleo_locale": "en_GB",
    })
    assert body["locale"] == "en_GB"
    assert body["keywords"] == "india"


def test_taleo_v1_defaults_to_en_us(monkeypatch) -> None:
    body = _captured_body(monkeypatch, {
        "company": "Wipro",
        "endpoint": "https://careers.wipro.com/services/recruiting/v1/jobs",
        "taleo_v1": True,
        "taleo_use_location": True,
    })
    assert body["locale"] == "en_US"
    assert body["location"] == "india"


def test_standard_chartered_portal_carries_en_gb() -> None:
    sc = [p for p in parse_portals() if p.get("company") == "Standard Chartered Bank"]
    assert sc and sc[0].get("taleo_locale") == "en_GB"
