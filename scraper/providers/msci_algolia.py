from __future__ import annotations
from job_cap import job_limit

import logging
import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, strip_html

_log = logging.getLogger("mirror")

_ALGOLIA_URL = "https://RVMOB42DFH.algolia.net/1/indexes/production__mscicare2201__sort-rank/query"
_HEADERS = {
    "X-Algolia-Application-Id": "RVMOB42DFH",
    "X-Algolia-API-Key": "629e647c6a9a8b542fb1022001313a7e",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}


class MsciAlgoliaProvider:
    """MSCI job search via Algolia (appId RVMOB42DFH, index production__mscicare2201__sort-rank).
    Fetches all 156 global jobs in one request; filters India cities via is_india().
    Full JD in hit['description']. Apply URL points to globalcareers-msci.icims.com.
    """

    key = "msci_algolia"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        try:
            jobs = _scrape_msci(portal, max_jobs=max_jobs)
        except requests.RequestException as e:
            _log.error(f"    [ERROR] MSCI Algolia: {e}")
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def _scrape_msci(portal: Portal, *, max_jobs: int | None) -> list[dict]:
    company = portal["company"]
    cap = job_limit(max_jobs)

    # Single request — index has ~156 global jobs total
    payload = {
        "query": "",
        "hitsPerPage": 1000,
        "attributesToRetrieve": [
            "title", "description", "qualifications", "about_company",
            "town_city_country", "location", "apply_url", "jd_url",
            "ats_requisition_id", "objectID", "department", "type",
        ],
    }

    r = requests.post(_ALGOLIA_URL, json=payload, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    hits = r.json().get("hits", [])

    jobs: list[dict] = []
    for h in hits:
        loc = h.get("town_city_country") or h.get("location") or ""
        if not is_india(loc):
            continue

        title = (h.get("title") or "").strip()
        if not title:
            continue

        raw_jd = strip_html(
            h.get("description") or h.get("qualifications") or h.get("about_company") or ""
        )
        apply_url = h.get("apply_url") or h.get("jd_url") or ""
        jid = h.get("ats_requisition_id") or h.get("objectID") or ""

        jobs.append({
            "job_id":          str(jid),
            "title":           title,
            "job_url":         apply_url,
            "source_api_url":  _ALGOLIA_URL,
            "business_unit":   h.get("department"),
            "raw_jd_text":     raw_jd,
            "location_city":   loc,
            "date_posted":     None,
            "source_platform": "MSCI Algolia",
            "industry":        portal.get("industry", ""),
        })

        if len(jobs) >= cap:
            break

    _log.info(f"    [MSCI] {len(jobs)} India jobs from {len(hits)} global hits")
    return jobs
