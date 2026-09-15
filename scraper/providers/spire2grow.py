from __future__ import annotations

"""Spire2Grow / IES ATS provider (used by Myntra and others).

Pattern: GET https://io.spire2grow.com/ies/v1/p/requisition/_search?page=N&size=100
Required headers: workspaceid, workflowid, origin
Response: {"entities": [...], "total": N}
Fields: id, jobTitle, jobLocation[0].country/city, jobDescription, departmentName
"""

import logging
import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, strip_html

_log = logging.getLogger("mirror")
_API_URL = "https://io.spire2grow.com/ies/v1/p/requisition/_search"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "*/*",
    "Language": "en",
}


class Spire2GrowProvider:
    key = "spire2grow"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_spire2grow(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def _scrape_spire2grow(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    workspace_id = portal.get("spire2grow_workspace_id", "")
    workflow_id = portal.get("spire2grow_workflow_id", "")
    careers_url = portal.get("careers_url", portal.get("endpoint", ""))
    india_only = portal.get("india_only", True)

    if not workspace_id:
        _log.error(f"    [Spire2Grow] {portal['company']}: missing spire2grow_workspace_id")
        return None

    headers = {
        **_HEADERS,
        "Origin": careers_url.rstrip("/"),
        "Referer": careers_url.rstrip("/") + "/",
        "Workspaceid": workspace_id,
        "Workflowid": workflow_id or f"WFU_{portal['company'].upper()}",
    }

    jobs: list[dict] = []
    page = 1

    while True:
        params = {"page": page, "size": 100, "selectedSortOrder": "desc", "selectedSortField": "postedOn"}
        try:
            r = requests.get(_API_URL, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            _log.error(f"    [ERROR] Spire2Grow {portal['company']} page={page}: {e}")
            return jobs or None

        entities = data.get("entities", [])
        total = data.get("total", 0)

        if not entities:
            break

        for e in entities:
            title = (e.get("jobTitle") or "").strip()
            if not title:
                continue

            locs = e.get("jobLocation") or []
            loc = ""
            if locs and isinstance(locs[0], dict):
                loc = locs[0].get("fqLocationName") or f"{locs[0].get('city','')}, {locs[0].get('country','')}".strip(", ")

            if india_only and not is_india(loc):
                continue

            jid = str(e.get("id") or "")
            raw_jd = strip_html(e.get("jobDescription") or e.get("aboutCompany") or "")
            apply_url = f"{careers_url.rstrip('/')}/job/{jid}" if jid else careers_url

            jobs.append({
                "job_id":          jid,
                "title":           title,
                "job_url":         apply_url,
                "source_api_url":  _API_URL,
                "business_unit":   e.get("departmentName"),
                "raw_jd_text":     raw_jd,
                "location_city":   loc,
                "date_posted":     e.get("createdOn") or e.get("updatedOn"),
                "source_platform": "Spire2Grow",
                "industry":        portal.get("industry", ""),
            })

            if max_jobs and len(jobs) >= max_jobs:
                return jobs

        if len(jobs) >= total or len(entities) < 100:
            break
        page += 1

    _log.info(f"    {len(jobs)} jobs via Spire2Grow ({portal['company']})")
    return jobs
