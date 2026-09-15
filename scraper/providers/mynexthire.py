from __future__ import annotations

"""MyNextHire ATS provider.

Pattern: POST https://{company}.mynexthire.com/employer/careers/reqlist/get
Body: {"source":"careers","code":"","filterByBuId":-1,"filterByCustomField":{"career_page_category":"{cat}"}}
Response: {"reqDetailsBOList": [...]}
Fields: reqId, reqTitle, jdDisplay, locationList[0].address, location[0].office
Apply URL: https://{tenant}.mynexthire.com/employer/jobs/{reqId}

No auth required. Categories must be iterated — empty filterByCustomField returns 0.
Known categories: Technology, Business (others return 0 for Swiggy).
"""

import logging
from urllib.parse import urlparse

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, strip_html

_log = logging.getLogger("mirror")

_CATEGORIES = [
    "Technology", "Business", "Operations", "Sales", "Marketing",
    "Finance", "HR", "Supply Chain", "Design", "Data Science",
    "Product", "Customer Experience", "Engineering", "Analytics",
]

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json;charset=UTF-8",
}


class MyNextHireProvider:
    key = "mynexthire"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_mynexthire(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def _scrape_mynexthire(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    careers_url = portal.get("careers_url", portal.get("endpoint", ""))
    parsed = urlparse(careers_url)

    # Derive MyNextHire tenant domain from careers URL
    # careers.swiggy.com -> swiggy.mynexthire.com (from referer in XHR)
    # OR the tenant is directly {company}.mynexthire.com
    tenant_domain = portal.get("mynexthire_tenant") or f"{parsed.netloc.split('.')[0]}.mynexthire.com"
    api_url = f"https://{tenant_domain}/employer/careers/reqlist/get"

    headers = {**_HEADERS, "Origin": f"https://{tenant_domain}", "Referer": f"https://{tenant_domain}/employer/jobs/careers"}
    india_only = portal.get("india_only", True)
    seen: set[str] = set()
    jobs: list[dict] = []

    for cat in _CATEGORIES:
        payload = {
            "source": "careers",
            "code": "",
            "filterByBuId": -1,
            "filterByCustomField": {"career_page_category": cat},
        }
        try:
            r = requests.post(api_url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            _log.debug(f"    [MyNextHire] {portal['company']} cat={cat}: {e}")
            continue

        items = data.get("reqDetailsBOList") or []
        if not items:
            continue

        for j in items:
            jid = str(j.get("reqId") or "")
            if not jid or jid in seen:
                continue
            seen.add(jid)

            title = (j.get("reqTitle") or j.get("designation") or "").strip()
            if not title:
                continue

            # Location: prefer locationList, fall back to location array
            loc_list = j.get("locationList") or j.get("location") or []
            loc = ""
            if loc_list and isinstance(loc_list[0], dict):
                loc = loc_list[0].get("address") or loc_list[0].get("office") or ""
            elif isinstance(loc_list, str):
                loc = loc_list

            if india_only and not is_india(loc):
                continue

            raw_jd = strip_html(j.get("jdDisplay") or j.get("buDescription") or "")
            apply_url = f"https://{tenant_domain}/employer/jobs/{jid}"

            jobs.append({
                "job_id":          jid,
                "title":           title,
                "job_url":         apply_url,
                "source_api_url":  api_url,
                "business_unit":   j.get("buName") or j.get("careerStream"),
                "raw_jd_text":     raw_jd,
                "location_city":   loc,
                "date_posted":     j.get("approvedOn"),
                "source_platform": "MyNextHire",
                "industry":        portal.get("industry", ""),
            })

            if max_jobs and len(jobs) >= max_jobs:
                return jobs

    _log.info(f"    {len(jobs)} jobs via MyNextHire ({portal['company']})")
    return jobs
