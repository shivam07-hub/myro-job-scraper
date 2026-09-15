from __future__ import annotations

import logging
import requests
from schema import Portal
from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from utils import strip_html, is_india, job_hash

_log = logging.getLogger("mirror")

_TOKEN = "9f12ab0e7c6c9d65e9dc74b44f19a6a4c5c03861df6eb0fbd10ff4f4f9cd0349"
_HEADERS = {
    "Authorization": f"Bearer {_TOKEN}",
    "Accept": "*/*",
    "Referer": "https://careers.adityabirla.com/",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}
_BASE = "https://careers.adityabirla.com/api/v3"
_PAGE = 50


class AdityaBirlaProvider:
    key = "aditya_birla"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = []
        offset = 0
        india_only = portal.get("india_only", True)

        while True:
            try:
                r = requests.get(
                    f"{_BASE}/jobs?sortBy=new&offset={offset}&limit={_PAGE}",
                    headers=_HEADERS,
                    timeout=REQUEST_TIMEOUT,
                )
                r.raise_for_status()
                batch = r.json().get("data", [])
            except Exception as e:
                _log.error(f"    [Aditya Birla] listing error: {e}")
                return ProviderResult.error(ScrapeReason.API_BLOCKED)

            if not batch:
                break

            for item in batch:
                loc = item.get("locationHierarchyComplete", "")
                if india_only and not is_india(loc):
                    continue

                title   = item.get("jobTitle", "")
                jcode   = item.get("jobCode", "")
                jid     = jcode or str(item.get("id", "")) or job_hash(title, "")
                job_url = f"https://careers.adityabirla.com/job-details/{jcode}" if jcode else ""

                jd = _fetch_jd(jcode) if jcode else ""

                jobs.append({
                    "job_id":          jid,
                    "title":           title,
                    "job_url":         job_url,
                    "source_api_url":  f"{_BASE}/jobs",
                    "business_unit":   item.get("organizationUnit"),
                    "raw_jd_text":     jd,
                    "location_city":   loc,
                    "date_posted":     item.get("jobPostedDate", ""),
                    "source_platform": "AdityaBirla",
                    "industry":        portal.get("industry", ""),
                })

                if max_jobs and len(jobs) >= max_jobs:
                    return ProviderResult.success(jobs)

            if len(batch) < _PAGE:
                break
            offset += _PAGE

        return ProviderResult.success(jobs) if jobs else ProviderResult.no_jobs()


def _fetch_jd(jcode: str) -> str:
    try:
        r = requests.get(f"{_BASE}/job/{jcode}", headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code == 200:
            return strip_html(r.json().get("data", {}).get("jobDescription", ""))
    except Exception:
        pass
    return ""
