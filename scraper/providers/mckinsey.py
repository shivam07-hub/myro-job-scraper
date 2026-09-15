from __future__ import annotations

from schema import Portal

import logging
import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from utils import strip_html

_log = logging.getLogger("mirror")

_API_URL = "https://gateway.mckinsey.com/apigw-x0cceuow60/v1/api/jobs/search"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.mckinsey.com",
    "Referer": "https://www.mckinsey.com/careers/search-jobs?countries=India",
}


class McKinseyProvider:
    key = "mckinsey"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_mckinsey(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def _scrape_mckinsey(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    params = {"pageSize": 200, "start": 1, "countries": "India", "lang": "en"}
    try:
        r = requests.get(_API_URL, params=params, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        _log.error(f"    [ERROR] McKinsey: {e}")
        return None

    docs = data.get("docs", [])
    jobs = []
    for j in docs:
        title = (j.get("title") or "").strip()
        if not title:
            continue

        jd_parts = [
            j.get("whoYouWillWorkWith") or "",
            j.get("whatYouWillDo") or "",
            j.get("yourBackground") or "",
        ]
        raw_jd = strip_html("\n".join(p for p in jd_parts if p))
        job_id = str(j.get("jobID") or j.get("friendlyURL") or "")
        apply_url = j.get("jobApplyURL") or f"https://www.mckinsey.com/careers/search-jobs/{j.get('friendlyURL','')}"

        jobs.append({
            "job_id":          job_id,
            "title":           title,
            "job_url":         apply_url,
            "source_api_url":  _API_URL,
            "business_unit":   (j.get("functions") or [None])[0],
            "raw_jd_text":     raw_jd,
            "location_city":   "India",
            "date_posted":     None,
            "source_platform": "McKinsey",
            "industry":        portal.get("industry", ""),
        })
        if max_jobs and len(jobs) >= max_jobs:
            break

    _log.info(f"    {len(jobs)} India jobs fetched via McKinsey API")
    return jobs
