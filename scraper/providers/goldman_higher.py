from __future__ import annotations
from job_cap import job_limit

import logging
import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class GoldmanHigherProvider:
    """Goldman Sachs jobs on higher.gs.com, backed by api-higher.gs.com GraphQL."""

    key = "goldman_higher"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        try:
            jobs = _scrape_higher(portal, max_jobs=max_jobs or (200 if validate_mode else None))
        except requests.RequestException as e:
            _log.error(f"    [ERROR] Goldman Higher: {e}")
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def _scrape_higher(portal: Portal, *, max_jobs: int | None) -> list[dict]:
    company = portal.get("company", "Goldman Sachs")
    start_url = portal.get("endpoint") or portal.get("careers_url") or "https://higher.gs.com/roles/"
    cap = job_limit(max_jobs)

    api_url = "https://api-higher.gs.com/gateway/api/v1/graphql"

    query = (
        "query RoleSearch($input: RoleSearchQueryInput!) {"
        "  roleSearch(searchQueryInput: $input) {"
        "    totalCount"
        "    items {"
        "      roleId"
        "      jobTitle"
        "      corporateTitle"
        "      division"
        "      shortDescription"
        "      descriptionHtml"
        "      lastPostedDate"
        "      locations { city state country }"
        "    }"
        "  }"
        "}"
    )

    sess = requests.Session()
    sess.headers.update({**_HEADERS, "Content-Type": "application/json", "Origin": "https://higher.gs.com"})

    page_size = 25
    page_num = 1
    jobs: list[dict] = []

    while True:
        variables = {
            "input": {
                "page": {"pageSize": page_size, "pageNumber": page_num},
                "searchTerm": "",
                "experiences": ["PROFESSIONAL", "EARLY_CAREER", "CAMPUS", "INTERNAL_MOBILITY"],
            }
        }
        r = sess.post(api_url, json={"query": query, "variables": variables}, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        payload = r.json()
        items = (((payload.get("data") or {}).get("roleSearch") or {}).get("items")) or []
        if not items:
            break

        for it in items:
            title = (it.get("jobTitle") or "").strip()
            rid = str(it.get("roleId") or "").strip()
            if not title or not rid:
                continue

            locs = it.get("locations") or []
            loc_strs = []
            for loc in locs:
                if not isinstance(loc, dict):
                    continue
                loc_strs.append(" ".join([str(loc.get("city") or ""), str(loc.get("state") or ""), str(loc.get("country") or "")]).strip())
            loc_join = " | ".join([s for s in loc_strs if s])

            # Keep India roles only. (The portal returns global roles.)
            if loc_join and not is_india(loc_join):
                continue

            desc = strip_html(it.get("descriptionHtml") or it.get("shortDescription") or "")

            jobs.append({
                "job_id": rid,
                "title": title,
                "job_url": f"https://higher.gs.com/roles/{rid}",
                "source_api_url": api_url,
                "raw_jd_text": desc,
                "location_city": loc_join or "India",
                "business_unit": (it.get("division") or "").strip(),
                "date_posted": it.get("lastPostedDate"),
                "source_platform": "api-higher.gs.com (GraphQL)",
                "industry": portal.get("industry", ""),
            })
            if len(jobs) >= cap:
                break

        if len(jobs) >= cap:
            break
        page_num += 1

    _log.info(f"    {company}: {len(jobs)} roles scraped via api-higher.gs.com GraphQL")
    return jobs
