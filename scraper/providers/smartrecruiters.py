from __future__ import annotations

from schema import Portal

import logging
import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type":    "application/json",
}


class SmartRecruitersProvider:
    key = "smartrecruiters"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = scrape_smartrecruiters(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def scrape_smartrecruiters(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    """SmartRecruiters: list endpoint + per-posting JD fetch."""
    list_url = portal['endpoint']
    try:
        r = requests.get(list_url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        _log.error(f"    [ERROR] SmartRecruiters {portal['company']}: {e}")
        return None

    listings = data.get('content', [])
    if max_jobs:
        listings = listings[:max_jobs]
    _log.info(f"    {len(listings)} postings listed — fetching JDs...")

    jobs = []
    india_only = portal.get('india_only', True)
    for p in listings:
        loc  = p.get('location') or {}
        city = loc.get('city') or loc.get('country', '')
        if india_only and not is_india(f"{city} {loc.get('country', '')}"):
            continue
        dept = (p.get('department') or {}).get('label')
        ref  = p.get('ref', '')

        raw_jd = ''
        public_url = ref
        if ref:
            try:
                jr = requests.get(ref, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
                jr.raise_for_status()
                jdata    = jr.json()
                sections = (jdata.get('jobAd') or {}).get('sections') or {}
                raw_jd   = strip_html(
                    sections.get('jobDescription', {}).get('text', '') or
                    sections.get('qualifications', {}).get('text', '')
                )
                public_url = jdata.get('postingUrl') or jdata.get('applyUrl') or ref
            except Exception:
                pass

        jobs.append({
            'job_id':          str(p.get('id') or job_hash(p.get('name', ''), ref)),
            'title':           p.get('name', ''),
            'job_url':         public_url,
            'source_api_url':  list_url,
            'business_unit':   dept,
            'raw_jd_text':     raw_jd,
            'location_city':   city,
            'date_posted':     p.get('releasedDate'),
            'source_platform': 'SmartRecruiters',
            'industry':        portal.get('industry', ''),
        })
    return jobs
