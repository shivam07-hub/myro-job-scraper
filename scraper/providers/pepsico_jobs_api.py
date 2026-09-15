from __future__ import annotations
from job_cap import job_limit

from schema import Portal

import logging
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.pepsicojobs.com/india/jobs",
}


class PepsiCoJobsAPIProvider:
    key = "pepsico_jobs_api"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_pepsico_api(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        if not jobs:
            return ProviderResult.no_jobs()
        return ProviderResult.success(jobs)


def _with_page(base_url: str, page_num: int) -> str:
    parts = urlsplit(base_url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    q["page"] = str(page_num)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q, doseq=True), parts.fragment))


def _scrape_pepsico_api(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    endpoint = (portal.get("endpoint") or "").strip()
    company = portal.get("company", "")
    industry = portal.get("industry", "")
    india_only = portal.get("india_only", True)
    cap = job_limit(max_jobs)

    if not endpoint.startswith("http"):
        _log.error(f"    [ERROR] PepsiCo API: invalid endpoint for {company}: {endpoint}")
        return None

    page = 1
    jobs: list[dict] = []
    seen_ids: set[str] = set()
    total_count = 0
    max_pages = 1000

    while page <= max_pages and len(jobs) < cap:
        page_url = _with_page(endpoint, page)
        try:
            r = requests.get(page_url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            _log.error(f"    [ERROR] PepsiCo API page {page} failed ({company}): {e}")
            return None if page == 1 else jobs

        batch = payload.get("jobs") or []
        total_count = int(payload.get("count") or payload.get("totalCount") or total_count or 0)
        if not batch:
            break

        added_on_page = 0
        for item in batch:
            data = item.get("data") if isinstance(item, dict) else None
            if not isinstance(data, dict):
                continue

            title = (data.get("title") or "").strip()
            if not title:
                continue

            location = (
                (data.get("full_location") or "").strip()
                or (data.get("location_name") or "").strip()
                or ", ".join(
                    [x for x in ((data.get("city") or "").strip(), (data.get("country") or "").strip()) if x]
                )
                or "India"
            )
            country = (data.get("country") or data.get("country_code") or "").strip()
            if india_only and not (is_india(location) or is_india(country)):
                continue

            job_id = str(data.get("req_id") or data.get("slug") or "").strip()
            apply_url = (data.get("apply_url") or "").strip()
            if not job_id:
                job_id = job_hash(title, apply_url or page_url)
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            description_parts = [
                data.get("description") or "",
                data.get("responsibilities") or "",
                data.get("qualifications") or "",
            ]
            raw_jd = strip_html("\n".join([p for p in description_parts if p]))

            jobs.append(
                {
                    "job_id": job_id,
                    "title": title,
                    "job_url": apply_url,
                    "source_api_url": page_url,
                    "business_unit": data.get("category") or data.get("employment_type"),
                    "raw_jd_text": raw_jd,
                    "location_city": location,
                    "date_posted": data.get("posted_date") or data.get("create_date") or "",
                    "source_platform": "PepsiCoJobsAPI",
                    "industry": industry,
                }
            )
            added_on_page += 1
            if len(jobs) >= cap:
                break

        if added_on_page == 0:
            break

        # API returns 10/page today; this ends pagination deterministically.
        if total_count and len(jobs) >= total_count:
            break

        page += 1

    _log.info(f"    {len(jobs)} India jobs via PepsiCo Jobs API ({company}); listing total={total_count}")
    return jobs

