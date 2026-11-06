"""ICICI Bank careers (careers.icici.bank.in).

The listing API (``POST CareerApplicantApi/Career/Search/1``) is encrypted in the
browser, so the listing is read from the rendered page instead: one Firecrawl
cloud scrape loads the job list, clicks Next, and snapshots the HTML of every
page. Job IDs come from the ``job-details/{id}`` links. Each JD is then read from
the plain JSON endpoint ``Career/getMobileJd/{id}`` with ordinary HTTP.
"""

from __future__ import annotations

import json
import logging
import re

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import strip_html

_log = logging.getLogger("mirror")

_BASE = "https://careers.icici.bank.in"
_JD_URL = _BASE + "/CareerApplicantApi/Career/getMobileJd/{job_id}"
_DETAIL_URL = _BASE + "/CareerApplicant/Career/job-details/{job_id}"
# 12 postings a page; 3 pages on 2026-11-06. Six leaves room to grow.
_MAX_PAGES = 6
_DETAIL_RE = re.compile(r"/job-details/(\d+)")
_JOB_LINK = 'a[href*="job-details"]'
_NEXT_ENABLED_RE = re.compile(r'paginnext[^>]*>\s*<a[^>]*aria-disabled="false"')
# A scripted click on a disabled Next link does nothing; a real click on it fails.
_CLICK_NEXT = "document.querySelector('li.paginnext a')?.click();"

# The page's own static request headers: binfo/platform are double-base64 of the
# browser name and "web"; the bearer value is the literal word "token".
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "authorization": "Bearer token",
    "binfo": "UTJoeWIyMWxJREUxTWc9PQ==",
    "platform": "ZDJWaQ==",
}


def listing_actions(pages: int = _MAX_PAGES) -> list[dict]:
    # Wait for the links, not a fixed time: a render where the search never
    # answers ("No Jobs Available!") then fails instead of caching an empty list.
    actions: list[dict] = [{"type": "wait", "selector": _JOB_LINK}, {"type": "scrape"}]
    for _ in range(pages - 1):
        actions += [
            {"type": "executeJavascript", "script": _CLICK_NEXT},
            {"type": "wait", "milliseconds": 3000},
            {"type": "scrape"},
        ]
    return actions


def parse_listing_ids(html_pages: list[str]) -> list[str]:
    ids: list[str] = []
    for html in html_pages:
        for job_id in _DETAIL_RE.findall(html or ""):
            if job_id not in ids:
                ids.append(job_id)
    return ids


def has_next_page(html: str) -> bool:
    return bool(_NEXT_ENABLED_RE.search(html or ""))


def _jd_text(row: dict) -> str:
    """``JD`` is HTML; when it is empty the page renders ``MobileJD`` sections instead.

    The "category" section holds the facts (job level, experience range, cities)
    and leads either way; "Gallery" sections are product videos, not the role.
    """
    sections = [s for s in json.loads(row.get("MobileJD") or "[]") if isinstance(s, dict)]
    lines: list[str] = []
    for section in sections:
        if str(section.get("type") or "").lower() != "category":
            continue
        for item in section.get("list") or []:
            if item.get("title") and item.get("description"):
                lines.append(f"{item['title']}: {strip_html(str(item['description']))}")
    body = strip_html(str(row.get("JD") or ""))
    if body:
        return "\n".join(lines + [body])
    for section in sections:
        if str(section.get("type") or "").lower() in ("category", "gallery"):
            continue
        lines += [str(section.get("title") or ""), strip_html(str(section.get("description") or ""))]
        for item in section.get("list") or []:
            text = strip_html(str(item.get("description") or ""))
            lines.append(f"{item.get('title') or ''}: {text}" if text else str(item.get("title") or ""))
    return "\n".join(line for line in lines if line.strip())


def parse_icici_jd(payload: dict, job_id: str, portal: Portal) -> dict | None:
    # No delete/expiry filter: the rendered listing is what is live. 16 of the 25
    # postings listed on 2026-11-06 carried f_isDelete=1.
    rows = payload.get("Data") if isinstance(payload, dict) else None
    row = rows[0] if isinstance(rows, list) and rows and isinstance(rows[0], dict) else None
    if row is None:
        return None
    # f_title is what the listing shows; JobTitle is the internal name ("RM - Business Banking,").
    title = str(row.get("f_title") or row.get("JobTitle") or "").strip()
    if not title:
        return None
    return {
        "job_id": job_id,
        "title": title,
        "job_url": _DETAIL_URL.format(job_id=job_id),
        "source_api_url": _JD_URL.format(job_id=job_id),
        "business_unit": (row.get("Function") or None),
        "raw_jd_text": _jd_text(row),
        "location_city": str(row.get("Location") or "India").strip(),
        "date_posted": row.get("f_createdDate"),
        "source_platform": "ICICI Careers via Firecrawl Cloud",
        "industry": portal.get("industry", ""),
    }


class IciciCareersProvider:
    key = "icici_careers"

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

        import firecrawl_client as fc

        pages = fc.cloud_scrape_action_pages(endpoint, listing_actions())
        ids = parse_listing_ids(pages)
        if not ids:
            return ProviderResult.error(ScrapeReason.PARSE_ERROR, "no_icici_job_links")
        if has_next_page(pages[-1]):
            _log.warning("    [ICICI] listing runs past %d pages; raise _MAX_PAGES", _MAX_PAGES)
        if max_jobs:
            ids = ids[:max_jobs]

        session = requests.Session()
        session.headers.update(_HEADERS)
        jobs: list[dict] = []
        for job_id in ids:
            try:
                response = session.get(_JD_URL.format(job_id=job_id), timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                job = parse_icici_jd(response.json(), job_id, portal)
            except (requests.RequestException, ValueError) as exc:
                _log.warning("    [ICICI] JD %s unavailable: %s", job_id, exc)
                continue
            if job:
                jobs.append(job)
        _log.info("    %d ICICI jobs from %d listed", len(jobs), len(ids))
        return ProviderResult.success(jobs)
