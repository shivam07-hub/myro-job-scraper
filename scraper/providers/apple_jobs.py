from __future__ import annotations
from job_cap import job_limit

"""Apple Jobs direct API provider.

Apple's public careers app uses:
  - POST /api/v1/search
  - GET  /api/v1/jobDetails/{positionId}

The public location filter is not accepted as a simple ID payload, so the
provider uses direct API search queries and filters India locations in Python.
"""

import logging
from typing import Any

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, strip_html

_log = logging.getLogger("mirror")

_BASE = "https://jobs.apple.com"
_SEARCH_URL = f"{_BASE}/api/v1/search"
_CSRF_URL = f"{_BASE}/api/v1/CSRFToken"
_DETAIL_URL = f"{_BASE}/api/v1/jobDetails/{{job_id}}"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Content-Type": "application/json",
    "Origin": _BASE,
    "Referer": "https://jobs.apple.com/en-in/search?location=india-INDC",
    "locale": "en-in",
}

_QUERIES = ("", "India", "Bengaluru", "Hyderabad", "Mumbai", "Pune", "Chennai")


class AppleJobsProvider:
    key = "apple_jobs"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        try:
            jobs = _scrape_apple_jobs(portal, max_jobs=max_jobs)
        except Exception as exc:
            _log.error(f"    [ERROR] Apple Jobs API failed: {exc}")
            return ProviderResult.error(ScrapeReason.API_BLOCKED, "apple_jobs_api_failed")
        return ProviderResult.success(jobs)


def _search_body(query: str, page: int) -> dict[str, Any]:
    return {
        "query": query,
        "filters": {},
        "page": page,
        "locale": "en-in",
        "sort": "newest",
        "format": {
            "longDate": "MMMM D, YYYY",
            "mediumDate": "MMM D, YYYY",
        },
    }


def _location_text(locations: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for loc in locations:
        if not isinstance(loc, dict):
            continue
        name = loc.get("name") or loc.get("city") or ""
        country = loc.get("countryName") or ""
        text = ", ".join([x for x in (name, country) if x])
        if text:
            parts.append(text)
    return " | ".join(parts)


def parse_apple_search_result(item: dict[str, Any], portal: Portal) -> dict | None:
    locations = item.get("locations") if isinstance(item.get("locations"), list) else []
    location = _location_text(locations)
    if not is_india(location):
        return None

    position_id = str(item.get("positionId") or item.get("jobPositionId") or item.get("id") or "").replace("PIPE-", "")
    title = (item.get("postingTitle") or item.get("transformedPostingTitle") or "").strip()
    if not position_id or not title:
        return None

    slug = (item.get("transformedPostingTitle") or title).lower().replace(" ", "-")
    return {
        "job_id": position_id,
        "title": title,
        "job_url": f"https://jobs.apple.com/en-in/details/{position_id}/{slug}",
        "source_api_url": portal.get("endpoint", _SEARCH_URL),
        "business_unit": item.get("team") or "",
        "raw_jd_text": strip_html(item.get("jobSummary") or ""),
        "location_city": location,
        "date_posted": item.get("postingDate") or item.get("postDateInGMT") or "",
        "source_platform": "AppleJobsAPI",
        "industry": portal.get("industry", ""),
    }


def _fetch_detail(session: requests.Session, job_id: str) -> dict[str, Any]:
    resp = session.get(_DETAIL_URL.format(job_id=job_id), params={"locale": "en-in"}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return data.get("res", data) if isinstance(data, dict) else {}


def _detail_text(detail: dict[str, Any], fallback: str) -> str:
    parts = [
        detail.get("jobSummary") or fallback,
        detail.get("description") or "",
        detail.get("keyQualifications") or "",
        detail.get("preferredQualifications") or "",
        detail.get("educationExperience") or "",
        detail.get("additionalRequirements") or "",
    ]
    return strip_html("\n\n".join(str(p) for p in parts if p))[:12000]


def _scrape_apple_jobs(portal: Portal, max_jobs: int | None = None) -> list[dict]:
    cap = job_limit(max_jobs)
    session = requests.Session()
    session.headers.update(_HEADERS)
    session.get(_CSRF_URL, timeout=REQUEST_TIMEOUT)

    jobs: list[dict] = []
    seen: set[str] = set()

    for query in _QUERIES:
        page = 1
        while page <= 10:
            resp = session.post(_SEARCH_URL, json=_search_body(query, page), timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            payload = resp.json().get("res", {})
            results = payload.get("searchResults") or []
            if not results:
                break

            for item in results:
                job = parse_apple_search_result(item, portal)
                if not job or job["job_id"] in seen:
                    continue
                seen.add(job["job_id"])
                detail = _fetch_detail(session, job["job_id"])
                if detail:
                    job["title"] = detail.get("postingTitle") or job["title"]
                    job["raw_jd_text"] = _detail_text(detail, job["raw_jd_text"])
                    job["business_unit"] = detail.get("team") or job["business_unit"]
                jobs.append(job)
                if len(jobs) >= cap:
                    _log.info(f"    {len(jobs)} India jobs via Apple Jobs API [max_jobs reached]")
                    return jobs

            total = int(payload.get("totalRecords") or 0)
            if page * 20 >= total:
                break
            # Empty-query search is global; page 1 carries the India retail roles seen
            # from the India landing page, but full pagination would walk thousands.
            if not query:
                break
            page += 1

    _log.info(f"    {len(jobs)} India jobs via Apple Jobs API")
    return jobs
