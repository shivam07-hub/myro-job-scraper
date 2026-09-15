from __future__ import annotations
from job_cap import job_limit

from schema import Portal

import logging
import requests

from config import REQUEST_TIMEOUT
from providers._paginate import Page, paginate
from providers.base import ProviderResult, ScrapeReason
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent":  "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept":      "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

_PAGE_SIZE = 20


class EightfoldProvider:
    key = "eightfold"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_eightfold(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def _scrape_eightfold(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    tenant     = portal["eightfold_tenant"]   # e.g. "netflix"
    api_domain = portal["eightfold_domain"]   # e.g. "netflix.com"
    company    = portal["company"]
    india_only = portal.get("india_only", True)
    cap        = job_limit(max_jobs)

    base = f"https://{tenant}.eightfold.ai/api/apply/v2/jobs"
    jobs: list[dict] = []

    # Fixed page size (count=_PAGE_SIZE) at a record offset, with a server total;
    # the shared paginator advances by _PAGE_SIZE and stops at the total.
    def fetch_page(offset: int) -> Page | None:
        params = {"query": "", "count": _PAGE_SIZE, "start": offset, "domain": api_domain}
        if india_only:
            params["location"] = "India"
        try:
            r = requests.get(base, params=params, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            _log.error(f"    [ERROR] Eightfold list {company} start={offset}: {e}")
            return None
        return Page(items=data.get("positions", []), total=data.get("count") or None)

    for positions in paginate(fetch_page, step=_PAGE_SIZE):
        for pos in positions:
            loc = pos.get("location", "")
            if india_only and not is_india(loc):
                continue

            jid   = str(pos.get("id", job_hash(pos.get("name", ""), "")))
            title = pos.get("name", "").strip()
            jd    = _fetch_jd(base, jid, api_domain)

            jobs.append({
                "job_id":          jid,
                "title":           title,
                "job_url":         pos.get("canonicalPositionUrl", f"https://{tenant}.eightfold.ai/careers/job/{jid}"),
                "source_api_url":  base,
                "business_unit":   pos.get("department") or pos.get("business_unit"),
                "raw_jd_text":     jd,
                "location_city":   loc,
                "date_posted":     pos.get("t_update"),
                "source_platform": "Eightfold",
                "industry":        portal.get("industry", ""),
            })

            if len(jobs) >= cap:
                _log.info(f"    {len(jobs)} India jobs fetched via Eightfold API")
                return jobs

    _log.info(f"    {len(jobs)} India jobs fetched via Eightfold API")
    return jobs


def _fetch_jd(base_url: str, job_id: str, api_domain: str) -> str:
    try:
        r = requests.get(
            f"{base_url}/{job_id}",
            params={"domain": api_domain},
            headers=_HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        # Single-job response may nest under 'positions' or be flat
        pos = data.get("positions", [data])[0] if data.get("positions") else data
        return strip_html(pos.get("job_description", "") or "")
    except Exception:
        return ""
