"""Jibe/iCIMS-style public jobs API provider.

The listing contract is ``GET /api/jobs?page=N&location=India`` and returns
``jobs[].data`` plus ``totalCount``.  Unlike the older iCIMS adapter, Jibe's
page size is controlled by the service (currently 10), so pagination advances
until the API's total is exhausted rather than assuming a 100-row page.
"""

from __future__ import annotations

import logging

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


class JibeProvider:
    key = "jibe"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        endpoint = (portal.get("endpoint") or "").strip()
        if not endpoint.startswith("http"):
            return ProviderResult.error(ScrapeReason.CONFIG_ERROR, "bad_jibe_endpoint")

        company = portal.get("company", "")
        cap = max_jobs or 2000
        jobs: list[dict] = []
        seen_ids: set[str] = set()
        fetched = 0
        page = 1
        total = 0

        while len(jobs) < cap:
            params = {
                "location": "India",
                "page": page,
                "sortBy": "relevance",
                "descending": "false",
                "internal": "false",
            }
            try:
                response = requests.get(
                    endpoint,
                    params=params,
                    headers={**_HEADERS, "Referer": portal.get("careers_url") or endpoint},
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                _log.error("    [ERROR] Jibe %s page=%s: %s", company, page, exc)
                if jobs:
                    return ProviderResult.partial(jobs, f"jibe_listing_failed_at_page_{page}: {exc}")
                return ProviderResult.error(ScrapeReason.API_BLOCKED, str(exc))

            batch = payload.get("jobs") or []
            total = int(payload.get("totalCount") or payload.get("count") or total or 0)
            if not batch:
                break
            fetched += len(batch)

            for item in batch:
                data = item.get("data", item) if isinstance(item, dict) else {}
                if not isinstance(data, dict):
                    continue
                title = (data.get("title") or "").strip()
                location = (
                    data.get("full_location")
                    or data.get("location_name")
                    or ", ".join(
                        value
                        for value in (data.get("city") or "", data.get("country") or "")
                        if value
                    )
                )
                if not title or not is_india(location):
                    continue

                apply_url = (data.get("apply_url") or "").strip()
                job_id = str(data.get("req_id") or data.get("slug") or "").strip()
                if not job_id:
                    job_id = job_hash(title, apply_url or endpoint)
                if job_id in seen_ids:
                    continue
                seen_ids.add(job_id)

                categories = data.get("categories") or []
                business_unit = (
                    categories[0].get("name")
                    if categories and isinstance(categories[0], dict)
                    else data.get("department")
                )
                jobs.append(
                    {
                        "job_id": job_id,
                        "title": title,
                        "job_url": apply_url,
                        "source_api_url": endpoint,
                        "business_unit": business_unit,
                        "raw_jd_text": strip_html(
                            data.get("description")
                            or data.get("responsibilities")
                            or data.get("qualifications")
                            or ""
                        ),
                        "location_city": location,
                        "date_posted": data.get("posted_date") or "",
                        "source_platform": "Jibe",
                        "industry": portal.get("industry", ""),
                    }
                )
                if len(jobs) >= cap:
                    break

            if (total and fetched >= total) or len(jobs) >= cap:
                break
            page += 1

        _log.info("    %s India jobs via Jibe (%s); listing total=%s", len(jobs), company, total)
        return ProviderResult.success(jobs)
