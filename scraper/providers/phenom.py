from __future__ import annotations
from job_cap import job_limit

from schema import Portal

import logging
import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from utils import job_hash, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type":    "application/json",
}


class PhenomProvider:
    key = "phenom_api"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = scrape_phenom_api(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def scrape_phenom_api(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    """Phenom/iCIMS paginated REST API with full JDs per page."""
    base_url   = portal['endpoint']
    company    = portal['company']
    india_only = portal.get('india_only', True)
    jobs       = []
    page       = 1
    _GLOBAL_CAP = job_limit(max_jobs)

    while True:
        url = f"{base_url}&page={page}"
        try:
            r = requests.get(url, headers={**_HEADERS, "Accept": "application/json"}, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            _log.error(f"    [ERROR] Phenom API {company} page={page}: {e}")
            break

        raw_jobs = data.get('jobs', [])
        if not raw_jobs:
            break

        for item in raw_jobs:
            job_data = item.get('data') or item
            title    = job_data.get('title', '').strip()
            if not title:
                continue

            jd_parts = [
                job_data.get('description', '') or '',
                job_data.get('responsibilities', '') or '',
                job_data.get('qualifications', '') or '',
            ]
            raw_jd = strip_html('\n\n'.join(p for p in jd_parts if p).strip())

            loc_raw = job_data.get('location_name') or job_data.get('full_location') or job_data.get('location') or {}
            if isinstance(loc_raw, dict):
                city = loc_raw.get('city') or loc_raw.get('name') or ''
            else:
                city = str(loc_raw)

            job_url = (job_data.get('apply_url') or job_data.get('jobUrl') or
                       job_data.get('applyUrl') or '')
            jid     = str(job_data.get('req_id') or job_data.get('jobId') or
                          job_data.get('id') or job_hash(title, job_url))

            jobs.append({
                'job_id':          jid,
                'title':           title,
                'job_url':         job_url,
                'source_api_url':  base_url,
                'business_unit':   job_data.get('department') or job_data.get('category'),
                'raw_jd_text':     raw_jd,
                'location_city':   city,
                'date_posted':     job_data.get('publishedDate') or job_data.get('datePosted'),
                'source_platform': 'Phenom',
                'industry':        portal.get('industry', ''),
            })

        total = data.get('total', 0)
        page_size = len(raw_jobs)
        if not total or page * page_size >= total:
            break
        if not india_only and len(jobs) >= _GLOBAL_CAP:
            break
        page += 1

    scope_label = "India" if india_only else "global"
    _log.info(f"    {len(jobs)} {scope_label} jobs fetched via Phenom API")
    return jobs
