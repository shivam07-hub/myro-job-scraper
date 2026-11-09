from __future__ import annotations

import pytest
import requests

import providers.darwinbox as db
from providers.base import FALLBACK_FIRECRAWL_EXTRACT, ScrapeReason

_CAREERS = "https://nsehrms.darwinbox.in/ms/candidatev2/main/careers/allJobs"
_API = "https://nsehrms.darwinbox.in/ms/candidateapi/job/alljobs?companyId=main"
_PORTAL = {"company": "National Stock Exchange (NSE)", "careers_url": _CAREERS, "endpoint": _CAREERS, "industry": "BFSI"}


def _job(jid: str, **fields) -> dict:
    job = {
        "id": jid,
        "title": "Systems Analyst",
        "jd": "&lt;p&gt;Build trading surveillance systems.&lt;/p&gt;",
        "country": "India",
        "locations": "Inspire, BKC, Mumbai, Maharashtra\r, India",
        "tool_tip_locations": ["Inspire, BKC, Mumbai, Maharashtra, India"],
        "department_name_only": "Technology - Application Development",
        "experience_from": "2",
        "experience_to": "5",
        "posted_on": 1793644200,
    }
    job.update(fields)
    return job


class _Resp:
    def __init__(self, payload: object = None, status: int = 200, text: str = "") -> None:
        self._payload = payload
        self.status_code = status
        self.text = text

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("not JSON")
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


def _page(jobs: list[dict], total: int | None = None) -> _Resp:
    return _Resp({"status": "success", "data": jobs, "job_counts": len(jobs) if total is None else total})


def _serve(monkeypatch, answers: list[_Resp]) -> list[dict]:
    """Answer each POST in order; record what was sent."""
    sent: list[dict] = []

    def post(url, json=None, headers=None, timeout=None, **kwargs):
        assert url == _API
        sent.append({"payload": json, "headers": headers, "kwargs": kwargs})
        return answers.pop(0)

    monkeypatch.setattr(db.requests, "post", post)
    monkeypatch.setattr(db.time, "sleep", lambda seconds: None)
    return sent


def test_reads_every_page_without_cookies(monkeypatch) -> None:
    first = [_job(f"a{i}") for i in range(db._PAGE_SIZE)]
    sent = _serve(monkeypatch, [_page(first, total=51), _page([_job("b1")], total=51)])

    result = db.DarwinboxProvider().scrape(_PORTAL)

    assert result.reason == ScrapeReason.SUCCESS
    assert len(result.jobs) == 51
    assert [s["payload"]["page"] for s in sent] == [1, 2]
    assert all("cookies" not in s["kwargs"] for s in sent)
    assert sent[0]["headers"]["Origin"] == "https://nsehrms.darwinbox.in"
    job = result.jobs[-1]
    assert job["job_id"] == "b1"
    assert job["job_url"] == "https://nsehrms.darwinbox.in/ms/candidatev2/main/careers/jobDetails/b1"
    assert job["source_api_url"] == _API
    assert job["business_unit"] == "Technology - Application Development"
    assert job["raw_jd_text"] == "Build trading surveillance systems."
    assert job["location_city"] == "Inspire, BKC, Mumbai, Maharashtra, India"
    assert job["locations"] == ["Inspire, BKC, Mumbai, Maharashtra, India"]
    assert (job["min_years_experience"], job["max_years_experience"]) == ("2", "5")
    # 1793644200 is 2026-11-03 00:00 IST, still 2026-11-02 in UTC; NSE's
    # page shows this job's date as 03-11-2026.
    assert job["date_posted"] == "2026-11-03"
    assert job["source_platform"] == "Darwinbox"
    assert job["industry"] == "BFSI"


def test_an_empty_description_stays_empty(monkeypatch) -> None:
    # NSE's own page reads "No job description at the moment!"; the writer
    # turns "" into its No-JD note and skips matching for the role.
    _serve(monkeypatch, [_page([_job("a1", jd="")])])

    result = db.DarwinboxProvider().scrape(_PORTAL)

    assert result.jobs[0]["raw_jd_text"] == ""


def test_multiple_locations_list_every_office_once(monkeypatch) -> None:
    chennai = "Ambattur, Kallikuppam, Chennai, Tamil Nadu, India"
    _serve(
        monkeypatch,
        [
            _page(
                [
                    _job("a1", locations="Multiple Locations", tool_tip_locations=[chennai, chennai, "Imphal, Manipur, India"]),
                    _job("a2", locations="Multiple Locations", tool_tip_locations=[]),
                    _job("a3", tool_tip_locations=None),
                ]
            )
        ],
    )

    jobs = db.DarwinboxProvider().scrape(_PORTAL).jobs

    assert jobs[0]["locations"] == [chennai, "Imphal, Manipur, India"]
    assert jobs[0]["location_city"] == f"{chennai} | Imphal, Manipur, India"
    assert (jobs[1]["location_city"], jobs[1]["locations"]) == ("India", [])
    assert jobs[2]["location_city"] == "Inspire, BKC, Mumbai, Maharashtra, India"


def test_skips_postings_outside_india(monkeypatch) -> None:
    _serve(monkeypatch, [_page([_job("a1"), _job("a2", country="United Arab Emirates")])])

    result = db.DarwinboxProvider().scrape(_PORTAL)

    assert [j["job_id"] for j in result.jobs] == ["a1"]


def test_a_cloudflare_block_is_retried(monkeypatch) -> None:
    sent = _serve(monkeypatch, [_Resp(status=403, text="Attention Required! | Cloudflare"), _page([_job("a1")])])

    result = db.DarwinboxProvider().scrape(_PORTAL)

    assert result.reason == ScrapeReason.SUCCESS
    assert len(sent) == 2


def test_a_tenant_that_stays_blocked_goes_to_firecrawl(monkeypatch) -> None:
    sent = _serve(monkeypatch, [_Resp(status=403) for _ in range(db._ATTEMPTS)])

    result = db.DarwinboxProvider().scrape(_PORTAL)

    assert result.fallback_policy == FALLBACK_FIRECRAWL_EXTRACT
    assert result.fallback_reason == "darwinbox_cf_blocked"
    assert len(sent) == db._ATTEMPTS


def test_an_unknown_tenant_is_a_config_error_not_a_fallback(monkeypatch) -> None:
    gone = {"status": "error", "data": {"message": "Internal Server Error - Invalid subdomain: flipkart"}}
    _serve(monkeypatch, [_Resp(gone, status=500) for _ in range(db._ATTEMPTS)])

    result = db.DarwinboxProvider().scrape(_PORTAL)

    assert result.reason == ScrapeReason.CONFIG_ERROR
    assert result.fallback_policy is None
    assert "Invalid subdomain" in (result.fallback_reason or "")


def test_a_failed_later_page_is_partial(monkeypatch) -> None:
    first = [_job(f"a{i}") for i in range(db._PAGE_SIZE)]
    _serve(monkeypatch, [_page(first, total=60)] + [_Resp(status=502) for _ in range(db._ATTEMPTS)])

    result = db.DarwinboxProvider().scrape(_PORTAL)

    assert result.reason == ScrapeReason.PARTIAL
    assert len(result.jobs) == db._PAGE_SIZE


def test_a_non_json_answer_is_a_parse_error(monkeypatch) -> None:
    _serve(monkeypatch, [_Resp(None, status=200, text="<html>maintenance</html>")])

    result = db.DarwinboxProvider().scrape(_PORTAL)

    assert result.reason == ScrapeReason.PARSE_ERROR


@pytest.mark.parametrize(
    ("value", "expected"),
    [(1793644200, "2026-11-03"), (1793644200000, "2026-11-03"), ("1793644200", "2026-11-03"), (None, ""), (0, "")],
)
def test_posted_on_becomes_an_ist_date(value, expected) -> None:
    assert db._posted(value) == expected
