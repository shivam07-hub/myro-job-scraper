"""CDSL careers page: comments hidden, panel title wins, email decoded."""

from __future__ import annotations

import requests

from providers.base import ScrapeReason
from providers.cdsl_careers import CdslCareersProvider, parse_cdsl_html
from utils import company_slug, job_hash

_CAREERS = "https://www.cdslindia.com/Main/careers.html"
_EMAIL = "careers@cdslindia.com"
_CFEMAIL = "9af9fbe8ffffe8e9daf9fee9f6f3f4fef3fbb4f9f5f7"


def _portal() -> dict:
    return {
        "company": "CDSL",
        "endpoint": _CAREERS,
        "careers_url": _CAREERS,
        "industry": "BFSI",
    }


def _job_panel(
    title: str,
    location: str,
    position: str,
    description: str,
    *,
    qualification: str = "MBA",
    age: str = "35 Years",
    include_data: bool = True,
) -> str:
    data_row = ""
    if include_data:
        data_row = f"""
          <tr>
            <td><b>{position}</b></td>
            <td>{location}</td>
            <td>{qualification}</td>
            <td>{age}</td>
          </tr>
        """
    return f"""
      <div class="panel panel-default">
        <h4 class="panel-title"><a>{title}</a></h4>
        <table>
          <tr class="head">
            <td>Position</td><td>Location</td><td>Qualification</td><td>Age Limit</td>
          </tr>
          {data_row}
          <tr><td colspan="4">{description}</td></tr>
        </table>
      </div>
    """


def _page(*departments: tuple[str, str], commented: str = "") -> str:
    blocks = []
    for name, inner in departments:
        blocks.append(
            f"""
            <div class="panel panel-default">
              <div class="panel-heading">
                <h4 class="panel-title"><a>{name}</a></h4>
              </div>
              <div class="panel-collapse">{commented}{inner}</div>
            </div>
            """
        )
    return f"<html><body><div id=\"accordion10\">{''.join(blocks)}</div></body></html>"


class _Response:
    def __init__(
        self,
        text: str,
        error: Exception | None = None,
        *,
        content: bytes | None = None,
        headers: dict | None = None,
    ):
        self.text = text
        self.content = text.encode("utf-8") if content is None else content
        self.headers = {"Content-Type": "text/html; charset=utf-8"} if headers is None else headers
        self._error = error

    def raise_for_status(self):
        if self._error:
            raise self._error


def test_commented_out_jobs_are_ignored():
    retired = _job_panel(
        "CHIEF TECHNOLOGY OFFICER",
        "Mumbai",
        "CHIEF TECHNOLOGY OFFICER",
        "Retired June 2026 advert",
    )
    live = _job_panel(
        "SOC Manager",
        "Mumbai",
        "SOC Manager",
        "Run the security operations centre",
    )
    jobs = parse_cdsl_html(_page(("Information Security", live), commented=f"<!--{retired}-->"), _portal())

    assert jobs is not None
    assert [job["title"] for job in jobs] == ["SOC Manager"]


def test_title_comes_from_the_panel_heading():
    page = _page(
        (
            "Finance & Accounts",
            _job_panel(
                "Deputy Manager– Financial Reporting",
                "Mumbai",
                "Deputy Manager",
                f'Please email your resume at: <span data-cfemail="{_CFEMAIL}">[email protected]</span>',
                qualification="CA",
                age="40 Years",
            ),
        )
    )
    jobs = parse_cdsl_html(page, _portal())

    assert jobs is not None and len(jobs) == 1
    job = jobs[0]
    assert job["title"] == "Deputy Manager– Financial Reporting"
    assert job["business_unit"] == "Finance & Accounts"
    assert job["location_city"] == "Mumbai"
    assert job["job_url"] == _CAREERS
    assert job["date_posted"] == ""
    assert job["source_platform"] == "CDSL"
    assert job["industry"] == "BFSI"
    assert job["job_id"] == f"{company_slug('CDSL').lower()}_{job_hash(job['title'], 'Mumbai')}"
    assert "Qualification: CA" in job["raw_jd_text"]
    assert "Age Limit: 40 Years" in job["raw_jd_text"]
    assert _EMAIL in job["raw_jd_text"]
    assert "[email" not in job["raw_jd_text"]
    assert "Deputy Manager" != job["title"]


def test_same_title_in_two_cities_is_two_jobs():
    panel = _job_panel("Network Support Engineer", "Mumbai", "Deputy Manager", "Mumbai desk")
    panel += _job_panel("Network Support Engineer", "Hyderabad", "Deputy Manager", "Hyderabad desk")
    jobs = parse_cdsl_html(_page(("Information Technology", panel)), _portal())

    assert jobs is not None and len(jobs) == 2
    assert [job["title"] for job in jobs] == ["Network Support Engineer", "Network Support Engineer"]
    assert [job["location_city"] for job in jobs] == ["Mumbai", "Hyderabad"]
    assert jobs[0]["job_id"] != jobs[1]["job_id"]


def test_header_row_can_use_th_cells():
    panel = """
      <div class="panel panel-default">
        <h4 class="panel-title"><a>Dy. Manager / Manager - Windows System Administrator</a></h4>
        <table>
          <tr class="head">
            <th>Position</th><th>Location</th><th>Qualification</th><th>Age Limit</th>
          </tr>
          <tr>
            <td>Dy. Manager / Manager - Windows System Administrator</td>
            <td>Mumbai</td>
            <td>B. E</td>
            <td>Up to 30 years</td>
          </tr>
          <tr><td colspan="4">DC &amp; DR &amp;nbspoperation</td></tr>
        </table>
      </div>
    """
    jobs = parse_cdsl_html(_page(("Information Technology", panel)), _portal())

    assert jobs is not None and len(jobs) == 1
    assert jobs[0]["location_city"] == "Mumbai"
    assert "Qualification: B. E" in jobs[0]["raw_jd_text"]
    assert "Age Limit: Up to 30 years" in jobs[0]["raw_jd_text"]
    assert jobs[0]["raw_jd_text"].endswith("DC & DR operation")
    assert "&nbsp" not in jobs[0]["raw_jd_text"]


def test_utf8_bom_page_keeps_en_dashes(monkeypatch):
    page = _page(
        (
            "Finance & Accounts",
            _job_panel("Billing Lead", "Mumbai", "Billing Lead", "Experience – 8 years"),
        )
    )
    raw = b"\xef\xbb\xbf" + page.encode("utf-8")
    monkeypatch.setattr(
        "providers.cdsl_careers.requests.get",
        lambda *args, **kwargs: _Response(
            raw.decode("latin-1"),
            content=raw,
            headers={"Content-Type": "text/html"},
        ),
    )

    result = CdslCareersProvider().scrape(_portal())

    assert result.reason == ScrapeReason.SUCCESS
    assert "Experience – 8 years" in result.jobs[0]["raw_jd_text"]
    assert "â" not in result.jobs[0]["raw_jd_text"]


def test_missing_data_row_still_keeps_the_description():
    panel = _job_panel(
        "DevOps Engineer",
        "Mumbai",
        "DevOps Engineer",
        "Experience in depository operations (No of positions - 1)",
        include_data=False,
    )
    jobs = parse_cdsl_html(_page(("Information Technology", panel)), _portal())

    assert jobs is not None and len(jobs) == 1
    assert jobs[0]["title"] == "DevOps Engineer"
    assert jobs[0]["location_city"] == ""
    assert "Experience in depository operations" in jobs[0]["raw_jd_text"]
    assert "Qualification:" not in jobs[0]["raw_jd_text"]


def test_missing_accordion_is_a_parse_error(monkeypatch):
    monkeypatch.setattr(
        "providers.cdsl_careers.requests.get",
        lambda *args, **kwargs: _Response("<html><body><p>Careers</p></body></html>"),
    )

    result = CdslCareersProvider().scrape(_portal())

    assert result.reason == ScrapeReason.PARSE_ERROR
    assert result.jobs == []


def test_accordion_with_no_jobs_is_empty_success():
    jobs = parse_cdsl_html('<div id="accordion10"></div>', _portal())
    assert jobs == []


def test_http_error_is_api_blocked(monkeypatch):
    monkeypatch.setattr(
        "providers.cdsl_careers.requests.get",
        lambda *args, **kwargs: _Response("", error=requests.HTTPError("403 Client Error")),
    )

    result = CdslCareersProvider().scrape(_portal())

    assert result.reason == ScrapeReason.API_BLOCKED
    assert result.jobs == []


def test_timeout_is_timeout(monkeypatch):
    def _timeout(*args, **kwargs):
        raise requests.Timeout("timed out")

    monkeypatch.setattr("providers.cdsl_careers.requests.get", _timeout)

    result = CdslCareersProvider().scrape(_portal())

    assert result.reason == ScrapeReason.TIMEOUT
    assert result.jobs == []


def test_max_jobs_truncates_in_page_order(monkeypatch):
    panel = _job_panel("First Role", "Mumbai", "First Role", "One")
    panel += _job_panel("Second Role", "Mumbai", "Second Role", "Two")
    monkeypatch.setattr(
        "providers.cdsl_careers.requests.get",
        lambda *args, **kwargs: _Response(_page(("Operations", panel))),
    )

    result = CdslCareersProvider().scrape(_portal(), max_jobs=1)

    assert result.reason == ScrapeReason.SUCCESS
    assert [job["title"] for job in result.jobs] == ["First Role"]
