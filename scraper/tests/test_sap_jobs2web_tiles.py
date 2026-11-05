from __future__ import annotations

from providers.sap_jobs2web_html import _extract_rows, _is_india_listing_location


def _section(job: str, view: str, field: str, label: str, value: str) -> str:
    return (
        f'<span class="section-label" id="job-{job}-{view}-section-{field}-label">{label}</span>'
        f'<div id="job-{job}-{view}-section-{field}-value">{value}</div>'
    )


def _tile(job: str, title: str, country: str, state: str, city: str) -> str:
    views = ""
    for view in ("desktop", "tablet", "mobile"):
        views += (
            f'<a class="jobTitle-link" href="/job/{city}-{job}/{job}/">{title}</a>'
            + _section(job, view, "date", "Posting Date", "18 Oct 2026")
            + _section(job, view, "customfield4", "Country", country)
            + _section(job, view, "customfield3", "State", state)
            + _section(job, view, "customfield2", "Location", city)
            + _section(job, view, "customfield5", "Req Id", "105828")
        )
    return f'<li class="job-tile job-id-{job}" data-url="/job/{city}-{job}/{job}/">{views}</li>'


def test_career_site_builder_tiles_parse_once_each_with_location() -> None:
    html = (
        '<ul id="job-tile-list">'
        + _tile("1366203266", "Engineer - Mechanical", "India", "Sikkim", "Rangpo")
        + _tile("1369426366", "Junior Officer - Production", "India", "Sikkim", "Rangpo")
        + _tile("1400000001", "QA Compliance Manager", "United States", "Massachusetts", "Fall River")
        + "</ul>"
    )
    rows = _extract_rows(html)

    assert [r["href"] for r in rows] == [
        "/job/Rangpo-1366203266/1366203266/",
        "/job/Rangpo-1369426366/1369426366/",
        "/job/Fall River-1400000001/1400000001/",
    ]
    assert rows[0]["title"] == "Engineer - Mechanical"
    assert rows[0]["listing_location"] == "India, Sikkim, Rangpo"
    assert _is_india_listing_location(rows[0]["listing_location"])
    assert not _is_india_listing_location(rows[2]["listing_location"])


def test_table_layout_still_wins_when_present() -> None:
    html = (
        '<table id="searchresults"><tbody><tr class="data-row">'
        '<td><a class="jobTitle-link" href="/job/Bangalore-X/123456/">X</a></td>'
        '<td><span class="jobLocation">Bangalore, IN</span></td></tr></tbody></table>'
        '<ul id="job-tile-list"><li class="job-tile" data-url="/job/ignored/999999/"></li></ul>'
    )
    rows = _extract_rows(html)
    assert [r["href"] for r in rows] == ["/job/Bangalore-X/123456/"]
    assert rows[0]["listing_location"] == "Bangalore, IN"
