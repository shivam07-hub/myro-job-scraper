from __future__ import annotations

import json

import providers.icici_careers as icici
from providers.base import ScrapeReason
from portal_reader import parse_portals

_PORTAL = {
    "company": "ICICI Bank",
    "endpoint": "https://careers.icici.bank.in/CareerApplicant/career/job-listing/",
    "industry": "BFSI",
    "india_only": True,
}


def _page(*ids: str, next_enabled: bool = False) -> str:
    links = "".join(
        f'<a href="/CareerApplicant/Career/job-details/{i}">Role {i}</a>' for i in ids
    )
    flag = "false" if next_enabled else "true"
    return (
        f"<div>{links}</div><ul class=\"cust-pagination\">"
        f'<li class="cust-pagin-btn paginnext"><a aria-disabled="{flag}" aria-label="Next page"></a></li></ul>'
    )


def _jd(job_id: str, **over) -> dict:
    row = {
        "JobID": job_id,
        "JobTitle": "Credit Manager",
        "Location": "Across India",
        "Function": "Credit",
        "JD": "<p><b>Role</b> &amp; responsibilities</p><p>Assess credit.</p>",
        "MobileJD": json.dumps([
            {"type": "category", "title": "Category", "list": [
                {"title": "Job level", "description": "Mid - Level Managerial"},
                {"title": "Experience", "description": "3-6 Years"},
            ]},
            {"type": "swipper", "title": "Key Responsibilities", "list": [
                {"title": "Market understanding", "description": "<p>Scope the market.</p>"},
            ]},
            {"type": "Gallery", "title": "About the Business group", "list": [{"title": "API Banking"}]},
        ]),
        "EndDate": "2032-12-30T00:00:00.000Z",
        "f_isDelete": 0,
        "f_createdDate": "2024-08-20T00:00:00.000Z",
    }
    row.update(over)
    return {"Data": [row]}


def test_listing_ids_keep_page_order_and_drop_repeats() -> None:
    pages = [_page("11", "12"), _page("13", "11"), _page("13")]
    assert icici.parse_listing_ids(pages) == ["11", "12", "13"]


def test_more_pages_is_read_from_the_last_snapshot() -> None:
    assert icici.has_next_page(_page("1", next_enabled=True))
    assert not icici.has_next_page(_page("1"))


def test_listing_actions_click_next_with_javascript() -> None:
    # A disabled Next link fails a real click; a scripted click is a no-op instead.
    actions = icici.listing_actions(3)
    assert actions[0] == {"type": "wait", "selector": 'a[href*="job-details"]'}
    assert [a["type"] for a in actions].count("scrape") == 3
    assert not any(a["type"] == "click" for a in actions)
    assert all("paginnext" in a["script"] for a in actions if a["type"] == "executeJavascript")


def test_jd_maps_to_a_job_record() -> None:
    job = icici.parse_icici_jd(_jd("2524737"), "2524737", _PORTAL)
    assert job is not None
    assert job["job_id"] == "2524737"
    assert job["title"] == "Credit Manager"
    assert job["location_city"] == "Across India"
    assert job["business_unit"] == "Credit"
    assert job["job_url"] == "https://careers.icici.bank.in/CareerApplicant/Career/job-details/2524737"
    assert "Role & responsibilities" in job["raw_jd_text"]
    assert "<p>" not in job["raw_jd_text"]
    assert job["date_posted"] == "2024-08-20T00:00:00.000Z"


def test_title_is_the_one_the_listing_shows() -> None:
    job = icici.parse_icici_jd(
        _jd("1", JobTitle="RM - Business Banking,", f_title="Relationship Manager - Business Banking"),
        "1",
        _PORTAL,
    )
    assert job["title"] == "Relationship Manager - Business Banking"


def test_jd_text_leads_with_level_and_experience() -> None:
    job = icici.parse_icici_jd(_jd("1"), "1", _PORTAL)
    assert job["raw_jd_text"].startswith("Job level: Mid - Level Managerial\nExperience: 3-6 Years\n")


def test_empty_jd_falls_back_to_the_mobile_sections() -> None:
    job = icici.parse_icici_jd(_jd("1", JD=""), "1", _PORTAL)
    assert "Key Responsibilities" in job["raw_jd_text"]
    assert "Market understanding: Scope the market." in job["raw_jd_text"]
    assert "API Banking" not in job["raw_jd_text"]


def test_a_listed_posting_is_kept_whatever_its_delete_flag() -> None:
    # 16 of the 25 postings listed live on 2026-11-06 carried f_isDelete=1.
    assert icici.parse_icici_jd(_jd("1", f_isDelete=1), "1", _PORTAL) is not None


def test_a_jd_with_no_data_is_skipped() -> None:
    assert icici.parse_icici_jd({"Data": []}, "3", _PORTAL) is None


def test_scrape_renders_once_then_reads_each_jd(monkeypatch) -> None:
    import firecrawl_client as fc

    renders: list[str] = []

    def fake_render(url, actions):
        renders.append(url)
        return [_page("11", "12"), _page("13")]

    fetched: list[str] = []

    class _Resp:
        def __init__(self, job_id: str) -> None:
            self.job_id = job_id

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            if self.job_id == "12":
                return {"Data": []}
            return _jd(self.job_id)

    class _Session:
        def __init__(self) -> None:
            self.headers: dict = {}

        def get(self, url, timeout=None):
            job_id = url.rsplit("/", 1)[-1]
            fetched.append(job_id)
            return _Resp(job_id)

    monkeypatch.setattr(fc, "cloud_scrape_action_pages", fake_render)
    monkeypatch.setattr(icici.requests, "Session", _Session)

    result = icici.IciciCareersProvider().scrape(_PORTAL)
    assert result.reason == ScrapeReason.SUCCESS
    assert renders == [_PORTAL["endpoint"]]
    assert fetched == ["11", "12", "13"]
    assert [j["job_id"] for j in result.jobs] == ["11", "13"]


def test_scrape_reports_an_empty_render(monkeypatch) -> None:
    import firecrawl_client as fc

    monkeypatch.setattr(fc, "cloud_scrape_action_pages", lambda url, actions: [])
    result = icici.IciciCareersProvider().scrape(_PORTAL)
    assert result.reason == ScrapeReason.PARSE_ERROR


def test_icici_portal_routes_to_the_provider() -> None:
    portal = [p for p in parse_portals() if p.get("company") == "ICICI Bank"]
    assert portal and portal[0]["ats"] == "icici_careers"
    assert not portal[0].get("js_required")
