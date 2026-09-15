from __future__ import annotations
from job_cap import job_limit

from schema import Portal

import logging
import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent":  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept":      "application/json, text/plain, */*",
    "Referer":     "",  # set per-request from careers_url
}

_PAGE_SIZE = 100


class IcimsCustomProvider:
    """iCIMS Career Sites custom JSON API.
    Pattern: GET {careers_domain}/api/jobs?country=India&page=N
    Response: {"jobs": [{"data": {...}}], "totalCount": N}
    """
    key = "icims_custom"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_icims(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def _scrape_icims(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    careers_url = portal.get("careers_url", portal.get("endpoint", ""))
    # Derive API base from careers URL: https://careers.amd.com/... -> https://careers.amd.com
    from urllib.parse import urlparse
    parsed = urlparse(careers_url)
    api_base = f"{parsed.scheme}://{parsed.netloc}/api/jobs"

    company    = portal["company"]
    india_only = portal.get("india_only", True)
    cap        = job_limit(max_jobs)

    headers = {**_HEADERS, "Referer": careers_url}
    jobs: list[dict] = []
    page = 1

    while True:
        params = {
            "page":       page,
            "sortBy":     "relevance",
            "descending": "false",
            "internal":   "false",
            "limit":      _PAGE_SIZE,
        }
        if india_only:
            location_param = portal.get("icims_location_param", "country")
            params[location_param] = "India" if location_param == "country" else "india"

        try:
            r = requests.get(api_base, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            _log.error(f"    [ERROR] iCIMS {company} page={page}: {e}")
            break

        raw = data.get("jobs", [])
        if not raw:
            break

        for item in raw:
            j = item.get("data", item)
            title = (j.get("title") or "").strip()
            if not title:
                continue

            loc = j.get("full_location") or j.get("city") or j.get("country") or ""
            if india_only and not is_india(loc):
                continue

            jid = str(j.get("req_id") or j.get("slug") or job_hash(title, j.get("apply_url", "")))
            raw_jd = strip_html(j.get("description") or j.get("responsibilities") or "")

            jobs.append({
                "job_id":          jid,
                "title":           title,
                "job_url":         j.get("apply_url") or f"{parsed.scheme}://{parsed.netloc}/careers-home/jobs/{jid}",
                "source_api_url":  api_base,
                "business_unit":   (j.get("categories") or [{}])[0].get("name") if j.get("categories") else j.get("department"),
                "raw_jd_text":     raw_jd,
                "location_city":   loc,
                "date_posted":     j.get("posted_date"),
                "source_platform": "iCIMS",
                "industry":        portal.get("industry", ""),
            })

            if len(jobs) >= cap:
                break

        total = data.get("totalCount", 0)
        if len(jobs) >= cap or page * _PAGE_SIZE >= total:
            break
        page += 1

    _log.info(f"    {len(jobs)} India jobs fetched via iCIMS Custom API")
    return jobs
