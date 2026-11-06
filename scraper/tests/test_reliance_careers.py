from __future__ import annotations

import providers.reliance_careers as rel
from portal_reader import parse_portals
from providers.base import ScrapeReason

_HIDDEN = '<input type="hidden" name="__VIEWSTATE" value="vs" /><input type="hidden" name="__EVENTTARGET" value="" />'


def _next(enabled: bool, prefix: str = "ctl00$MainContent$rgJobs$ctl13") -> str:
    disabled = "" if enabled else ' disabled="disabled"'
    return f'<input type="submit" name="{prefix}$lnkNext" value="Next" id="x_lnkNext"{disabled} />'


def _search_page(*jobs: tuple[str, str, str], more: bool = False) -> str:
    rows = "".join(
        f'<tr><td><span>{i}</span></td><td><a id="MainContent_rgJobs_hylUser_{i}" '
        f'href="frmJobSearch.aspx?JBTITLE=t{req}&amp;jbID=j{req}" href="{title}%20(%20{req}%20)">'
        f"{title} ( {req} )</a></td><td>Manufacturing</td><td>{city}</td><td>06 Nov 2026</td></tr>"
        for i, (req, title, city) in enumerate(jobs)
    )
    return f'{_HIDDEN}<table id="MainContent_rgJobs"><tbody>{rows}</tbody></table>{_next(more)}'


def _category_list(*cats: tuple[str, int]) -> str:
    links = "".join(
        f'<a href="frmfuncwisejob.aspx?func={i}&amp;flag=x">{name}       {count}  jobs</a>'
        for i, (name, count) in enumerate(cats)
    )
    return f"{_HIDDEN}{links}"


def _category_page(*jobs: tuple[str, str], more: bool = False) -> str:
    items = "".join(
        f'<h2><a id="MainContent_lstJoblist_hylUser_{i}" href="frmjobdescription.aspx?jbID=j{req}">'
        f"{title} ( {req} )</a></h2><p><span id=\"MainContent_lstJoblist_Label2_{i}\"> Mumbai</span> |&nbsp;"
        f'<span id="MainContent_lstJoblist_lblfunctional_{i}">IT &amp; Systems</span> |&nbsp;Posted '
        f'<span id="MainContent_lstJoblist_Label1_{i}">04 Nov 2026</span></p>'
        for i, (req, title) in enumerate(jobs)
    )
    return f"{_HIDDEN}{items}{_next(more, 'ctl00$MainContent$lstJoblist$DataPager1$ctl00')}"


_JOB_PAGE = (
    '<span id="MainContent_lblJobTitle">Manager Operations and Support ( 87543536 )</span>'
    '<span id="MainContent_lblSummRole">1. Provide technical support<br/>2. Supervise</span>'
    '<span id="MainContent_lblEduReq">B.E/B.Tech/MCA</span>'
    '<span id="MainContent_lblExpReq">Minimum 8 years</span>'
    '<span id="MainContent_lblSkill"></span>'
)


class _Resp:
    def __init__(self, text: str, url: str) -> None:
        self.text = text
        self.url = url

    def raise_for_status(self) -> None:
        return None


class _Session:
    """Serves GETs from ``pages`` and answers each POST with ``post(url, data)``."""

    def __init__(self, pages: dict[str, str], post) -> None:
        self.headers: dict = {}
        self.pages = pages
        self.post_fn = post
        self.gets: list[str] = []
        self.posts: list[tuple[str, dict]] = []

    def get(self, url, timeout=None):
        self.gets.append(url)
        return _Resp(self.pages[url], url)

    def post(self, url, data=None, timeout=None):
        self.posts.append((url, dict(data)))
        return self.post_fn(url, data)


def test_search_rows_read_the_first_href_and_the_requisition_number() -> None:
    rows = rel.parse_search_rows(_search_page(("83078686", "Lab Analyst", "Surat")))
    assert rows == [{
        "job_id": "83078686",
        "title": "Lab Analyst",
        "href": "frmJobSearch.aspx?JBTITLE=t83078686&jbID=j83078686",
        "function": "Manufacturing",
        "location": "Surat",
        "posted": "06 Nov 2026",
    }]


def test_category_rows_read_the_numbered_spans() -> None:
    [row] = rel.parse_category_rows(_category_page(("87543536", "Manager Operations and Support")))
    assert row["job_id"] == "87543536"
    assert row["title"] == "Manager Operations and Support"
    assert (row["location"], row["function"], row["posted"]) == ("Mumbai", "IT & Systems", "04 Nov 2026")


def test_categories_carry_their_job_counts() -> None:
    cats = rel.parse_categories(_category_list(("Freelancer - Sales Associate", 7730), ("Legal", 0)))
    assert cats == [
        ("Freelancer - Sales Associate", "frmfuncwisejob.aspx?func=0&flag=x", 7730),
        ("Legal", "frmfuncwisejob.aspx?func=1&flag=x", 0),
    ]


def test_next_button_only_when_enabled() -> None:
    assert rel.next_button(_search_page(more=True)) == "ctl00$MainContent$rgJobs$ctl13$lnkNext"
    assert rel.next_button(_search_page(more=False)) is None
    assert rel.next_button("<div></div>") is None


def test_store_and_call_centre_titles_are_frontline() -> None:
    for title in (
        "JC Manager C",
        "JC FC&A Lead C",
        "JP oDSS - Part time",
        "Jio Point Assistant Manager",
        "Regional Jio Point Service Coordinator",
        "Jio Digital Repair Intern",
        "Jio Home Service Intern",
        "Home Connect Master Supervisor Trainer",
        "Customer Care Executive Voice_B",
        "Vistaar oDSS",
    ):
        assert rel.is_frontline(title), title
    for title in (
        "Software Development Engineer II",
        "Enterprise Sales Officer T2",
        "Product Manager",
        "MCPE SDWAN Service Desk Engineer",
        "Graduate Engineer Trainee",
        "Lab Analyst",
    ):
        assert not rel.is_frontline(title), title


def test_job_page_keeps_each_section_with_its_label() -> None:
    assert rel.parse_job_page(_JOB_PAGE) == (
        "Job Responsibilities:\n1. Provide technical support\n2. Supervise\n\n"
        "Education Requirement:\nB.E/B.Tech/MCA\n\n"
        "Experience Requirement:\nMinimum 8 years"
    )


def test_jio_skips_mass_categories_and_store_titles(monkeypatch) -> None:
    base = "https://careers.jio.com/"
    it_url = base + "frmfuncwisejob.aspx?func=3&flag=x"
    pages = {
        base + "frmJobCategories.aspx": _category_list(
            ("Freelancer", 7816), ("Business Operations", 5949), ("Legal", 0), ("IT & Systems", 3)
        ),
        it_url: _category_page(("1", "Software Development Engineer I")),
        base + "frmjobdescription.aspx?jbID=j1": _JOB_PAGE,
        base + "frmjobdescription.aspx?jbID=j3": _JOB_PAGE,
    }

    def post(url, data):
        assert url == it_url
        if data.get("__EVENTTARGET") == rel._PAGE_SIZE_FIELD:
            html = _category_page(("1", "Software Development Engineer I"), ("2", "JC Field Engineer"), more=True)
        else:
            assert data["ctl00$MainContent$lstJoblist$DataPager1$ctl00$lnkNext"] == "Next"
            html = _category_page(("3", "Product Manager"))
        return _Resp(html, url)

    session = _Session(pages, post)
    monkeypatch.setattr(rel.requests, "Session", lambda: session)
    portal = {"endpoint": base + "frmJobCategories.aspx", "company": "Reliance Jio", "industry": "Telecommunications"}
    result = rel.RelianceCareersProvider().scrape(portal)

    assert result.reason == ScrapeReason.SUCCESS
    assert [j["job_id"] for j in result.jobs] == ["1", "3"]
    # Freelancer, Business Operations and the empty Legal list are never opened.
    assert session.gets == [
        base + "frmJobCategories.aspx",
        it_url,
        base + "frmjobdescription.aspx?jbID=j1",
        base + "frmjobdescription.aspx?jbID=j3",
    ]
    job = result.jobs[0]
    assert job["title"] == "Software Development Engineer I"
    assert job["job_url"] == base + "frmjobdescription.aspx?jbID=j1"
    assert job["location_city"] == "Mumbai"
    assert job["business_unit"] == "IT & Systems"
    assert job["industry"] == "Telecommunications"
    assert job["raw_jd_text"].startswith("Job Responsibilities:\n1. Provide technical support")


def _ril_session(results_url: str) -> _Session:
    base = "https://careers.ril.com/rilcareers/"
    pages = {
        base + "index.aspx": _HIDDEN,
        base + "frmJobSearch.aspx?JBTITLE=t11&jbID=j11": _JOB_PAGE,
        base + "frmJobSearch.aspx?JBTITLE=t12&jbID=j12": _JOB_PAGE,
    }

    def post(url, data):
        if data.get("__EVENTTARGET") == rel._RIL_SEARCH_BUTTON:
            return _Resp(_search_page(("11", "Lab Analyst", "Surat")), results_url)
        assert url == results_url
        if data.get("__EVENTTARGET") == rel._PAGE_SIZE_FIELD:
            return _Resp(_search_page(("11", "Lab Analyst", "Surat"), more=True), url)
        return _Resp(_search_page(("12", "Sr. Const Engr - CHO Projects MEP", "Jamnagar")), url)

    return _Session(pages, post)


def test_ril_searches_then_pages_the_results(monkeypatch) -> None:
    results_url = "https://careers.ril.com/rilcareers/frmJobSearch.aspx?func=x&loc=x"
    session = _ril_session(results_url)
    monkeypatch.setattr(rel.requests, "Session", lambda: session)
    portal = {"endpoint": "https://careers.ril.com/rilcareers/index.aspx", "company": "Reliance Industries"}
    result = rel.RelianceCareersProvider().scrape(portal)

    assert result.reason == ScrapeReason.SUCCESS
    assert [(j["job_id"], j["location_city"]) for j in result.jobs] == [("11", "Surat"), ("12", "Jamnagar")]
    assert [url for url, _ in session.posts] == [portal["endpoint"], results_url, results_url]


def test_a_search_that_never_opens_results_is_a_layout_change(monkeypatch) -> None:
    session = _ril_session("https://careers.ril.com/rilcareers/index.aspx")
    monkeypatch.setattr(rel.requests, "Session", lambda: session)
    result = rel.RelianceCareersProvider().scrape({"endpoint": "https://careers.ril.com/rilcareers/index.aspx"})
    assert result.reason == ScrapeReason.PARSE_ERROR


def test_portals_route_to_the_provider() -> None:
    portals = {p["company"]: p for p in parse_portals()}
    for company, endpoint in (
        ("Reliance Industries", "https://careers.ril.com/rilcareers/index.aspx"),
        ("Reliance Jio", "https://careers.jio.com/frmJobCategories.aspx"),
        ("Reliance New Energy", "https://careers.ril.com/newenergy/frmJobCategories.aspx"),
    ):
        assert portals[company]["ats"] == "reliance_careers"
        assert portals[company]["endpoint"] == endpoint
        assert not portals[company].get("js_required")
    assert "Reliance Retail" not in portals
