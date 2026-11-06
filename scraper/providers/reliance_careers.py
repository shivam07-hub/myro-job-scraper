"""Reliance group careers portals (careers.ril.com, careers.jio.com).

RIL, Jio and Reliance New Energy run the same ASP.NET WebForms software with
two listing layouts:

* RIL (``careers.ril.com/rilcareers/index.aspx``): the home page's Search
  button posts back to one results table.
* Jio and New Energy (``.../frmJobCategories.aspx``): one list per function,
  each labelled with its job count.

Both lists switch to 25 rows a page and page with a ``lnkNext`` submit button,
and every job page uses the same ``MainContent_lbl*`` spans for the JD. All of
it is plain HTTP; no Firecrawl.

Myro serves post-MBA and post-engineering job seekers, so Jio's store, gig and
call-centre postings are dropped: whole categories before they are paged, then
store titles inside the rest. On 2026-11-06 that kept 561 of ~30,400 postings.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterator
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_CATEGORY_LIST = "frmJobCategories.aspx"
_RIL_SEARCH_BUTTON = "ctl00$head$Button1"
_PAGE_SIZE_FIELD = "ctl00$MainContent$ddlentries"
_PAGE_SIZE = "25"
# Jio's Sales and Distribution needed 40 pages of 25 on 2026-11-06.
_MAX_PAGES = 80
_REQ_ID_RE = re.compile(r"\s*\(\s*(\d+)\s*\)\s*$")
_CATEGORY_RE = re.compile(r"^(.*?)\s+(\d+)\s+jobs?$", re.IGNORECASE)

# Per-city gig and store categories, skipped before paging (~29,900 postings).
_MASS_CATEGORIES = ("Freelancer", "Jio Sales Associate", "Business Operations", "Apprentice")
# Store staff at Jio Centres (JC) and Jio Points (JP), doorstep installers and
# call-centre agents, who sit inside otherwise office categories.
_FRONTLINE_TITLE_RE = re.compile(
    r"^(?:JC|JP)\b|\bJio Point\b|^Jio Digital|^Jio Home Service"
    r"|Home Connect Master Supervisor|Customer Care Executive|Advisor Voice|\boDSS\b",
    re.IGNORECASE,
)
_JD_SECTIONS = (
    ("lblSummRole", "Job Responsibilities"),
    ("lblEduReq", "Education Requirement"),
    ("lblExpReq", "Experience Requirement"),
    ("lblSkill", "Skills & Competencies"),
)


class _LayoutChanged(Exception):
    """The page answered but not in the shape this provider reads."""


def _soup(html: str) -> BeautifulSoup:
    # RIL's result links carry two href attributes; the first is the link.
    return BeautifulSoup(html or "", "html.parser", on_duplicate_attribute="ignore")


def _form(html: str) -> dict[str, str]:
    return {
        field["name"]: field.get("value", "")
        for field in _soup(html).select("input[type=hidden][name]")
    }


def is_frontline(title: str) -> bool:
    return bool(_FRONTLINE_TITLE_RE.search(title))


def next_button(html: str) -> str | None:
    button = _soup(html).select_one('input[name$="$lnkNext"]')
    if button is None or button.has_attr("disabled"):
        return None
    return button["name"]


def _row(link, function: str, location: str, posted: str) -> dict | None:
    text = link.get_text(" ", strip=True)
    match = _REQ_ID_RE.search(text)
    if not match or not link.get("href"):
        return None
    return {
        "job_id": match.group(1),
        "title": text[: match.start()].strip(),
        "href": link["href"],
        "function": function,
        "location": location,
        "posted": posted,
    }


def parse_search_rows(html: str) -> list[dict]:
    """RIL results table: title link, then function, location and posted cells."""
    rows = []
    for link in _soup(html).select('a[id^="MainContent_rgJobs_hylUser_"]'):
        cells = [td.get_text(" ", strip=True) for td in link.find_parent("td").find_next_siblings("td")]
        row = _row(link, *(cells + ["", "", ""])[:3])
        if row:
            rows.append(row)
    return rows


def parse_category_rows(html: str) -> list[dict]:
    """Jio function list: title link, then numbered location/function/posted spans."""
    soup = _soup(html)
    rows = []
    for link in soup.select('a[id^="MainContent_lstJoblist_hylUser_"]'):
        index = link["id"].rsplit("_", 1)[1]

        def span(name: str) -> str:
            node = soup.find(id=f"MainContent_lstJoblist_{name}_{index}")
            return node.get_text(" ", strip=True) if node else ""

        row = _row(link, span("lblfunctional"), span("Label2"), span("Label1"))
        if row:
            rows.append(row)
    return rows


def parse_categories(html: str) -> list[tuple[str, str, int]]:
    out = []
    for link in _soup(html).select('a[href^="frmfuncwisejob.aspx"]'):
        match = _CATEGORY_RE.match(" ".join(link.get_text(" ", strip=True).split()))
        if match:
            out.append((match.group(1), link["href"], int(match.group(2))))
    return out


def parse_job_page(html: str) -> str:
    soup = _soup(html)
    parts = []
    for span_id, label in _JD_SECTIONS:
        node = soup.find(id=f"MainContent_{span_id}")
        text = node.get_text("\n", strip=True) if node else ""
        if text:
            parts.append(f"{label}:\n{text}")
    return "\n\n".join(parts)


def _get(session: requests.Session, url: str) -> str:
    response = session.get(url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


def _post(session: requests.Session, url: str, data: dict[str, str]) -> requests.Response:
    response = session.post(url, data=data, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response


def _pages(
    session: requests.Session, url: str, html: str, parse_rows: Callable[[str], list[dict]]
) -> Iterator[list[dict]]:
    """Each page's rows: switch the list to 25 a page, then press Next until it is disabled."""
    form = {**_form(html), "__EVENTTARGET": _PAGE_SIZE_FIELD, _PAGE_SIZE_FIELD: _PAGE_SIZE}
    html = _post(session, url, form).text
    for _ in range(_MAX_PAGES):
        rows = parse_rows(html)
        if not rows:
            return
        yield rows
        button = next_button(html)
        if button is None:
            return
        html = _post(session, url, {**_form(html), button: "Next", _PAGE_SIZE_FIELD: _PAGE_SIZE}).text
    _log.warning("    [Reliance] %s runs past %d pages; raise _MAX_PAGES", url, _MAX_PAGES)


def _search_pages(session: requests.Session, endpoint: str) -> Iterator[list[dict]]:
    form = {**_form(_get(session, endpoint)), "__EVENTTARGET": _RIL_SEARCH_BUTTON}
    results = _post(session, endpoint, form)
    if "frmJobSearch.aspx" not in results.url:
        raise _LayoutChanged(f"search did not open the results page ({results.url})")
    yield from _pages(session, results.url, results.text, parse_search_rows)


def _category_pages(session: requests.Session, endpoint: str) -> Iterator[list[dict]]:
    categories = parse_categories(_get(session, endpoint))
    if not categories:
        raise _LayoutChanged("no job categories on the page")
    for name, href, count in categories:
        if not count or name.startswith(_MASS_CATEGORIES):
            continue
        url = urljoin(endpoint, href)
        yield from _pages(session, url, _get(session, url), parse_category_rows)


class RelianceCareersProvider:
    key = "reliance_careers"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        endpoint = (portal.get("endpoint") or "").strip()
        if not endpoint.startswith("http"):
            return ProviderResult.error(ScrapeReason.CONFIG_ERROR, "bad_endpoint")
        pages = _category_pages if endpoint.endswith(_CATEGORY_LIST) else _search_pages

        session = requests.Session()
        session.headers.update(_HEADERS)
        rows: list[dict] = []
        seen: set[str] = set()
        try:
            for page in pages(session, endpoint):
                for row in page:
                    if row["job_id"] not in seen and not is_frontline(row["title"]):
                        seen.add(row["job_id"])
                        rows.append(row)
                if max_jobs and len(rows) >= max_jobs:
                    break
        except _LayoutChanged as exc:
            return ProviderResult.error(ScrapeReason.PARSE_ERROR, str(exc))
        except requests.RequestException as exc:
            return ProviderResult.error(ScrapeReason.API_BLOCKED, f"listing: {exc}")
        if max_jobs:
            rows = rows[:max_jobs]

        jobs: list[dict] = []
        for row in rows:
            job_url = urljoin(endpoint, row["href"])
            try:
                jd = parse_job_page(_get(session, job_url))
            except requests.RequestException as exc:
                _log.warning("    [Reliance] JD %s unavailable: %s", row["job_id"], exc)
                continue
            jobs.append({
                "job_id": row["job_id"],
                "title": row["title"],
                "job_url": job_url,
                "source_api_url": endpoint,
                "business_unit": row["function"] or None,
                "raw_jd_text": jd,
                "location_city": row["location"] or "India",
                "date_posted": row["posted"],
                "source_platform": "Reliance Careers",
                "industry": portal.get("industry", ""),
            })
        _log.info("    %d %s jobs from %d listed", len(jobs), portal.get("company", "Reliance"), len(rows))
        return ProviderResult.success(jobs)
