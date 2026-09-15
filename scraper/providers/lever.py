from __future__ import annotations

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

_INDIA_KEYWORDS = {'india', 'bangalore', 'bengaluru', 'hyderabad', 'mumbai',
                   'pune', 'chennai', 'noida', 'gurgaon', 'gurugram', 'delhi'}


class LeverProvider:
    key = "lever"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = scrape_lever(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def scrape_lever(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    """Lever ATS: GET https://api.lever.co/v0/postings/{slug}?mode=json"""
    slug       = portal['lever_slug']
    company    = portal['company']
    india_only = portal.get('india_only', True)
    url        = f"https://api.lever.co/v0/postings/{slug}?mode=json"

    try:
        r = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        postings = r.json()
    except Exception as e:
        _log.error(f"    [ERROR] Lever {company}: {e}")
        return None

    if not isinstance(postings, list):
        _log.warning(f"    [WARN] Lever {company}: unexpected response type")
        return None

    jobs = []
    for p in postings:
        cats = p.get('categories') or {}
        location = cats.get('location') or ''
        if india_only and not any(kw in location.lower() for kw in _INDIA_KEYWORDS):
            continue
        # Lever exposes every city for multi-location postings in allLocations (firecrawl #6)
        all_locs = [l for l in (cats.get('allLocations') or [location]) if isinstance(l, str) and l.strip()]

        jd_plain = p.get('descriptionPlain') or strip_html(p.get('description') or '')
        for lst in (p.get('lists') or []):
            content = strip_html(lst.get('content', ''))
            if content:
                jd_plain = f"{jd_plain}\n\n{lst.get('text', '')}\n{content}"

        jid = p.get('id') or job_hash(p.get('text', ''), p.get('hostedUrl', ''))
        jobs.append({
            'job_id':          jid,
            'title':           p.get('text', '').strip(),
            'job_url':         p.get('hostedUrl') or p.get('applyUrl') or '',
            'source_api_url':  url,
            'business_unit':   (p.get('categories') or {}).get('team'),
            'raw_jd_text':     jd_plain.strip(),
            'location_city':   location,
            'locations':       all_locs,
            'date_posted':     None,
            'source_platform': 'Lever',
            'industry':        portal.get('industry', ''),
        })
        if max_jobs and len(jobs) >= max_jobs:
            break

    _log.info(f"    {len(jobs)} jobs fetched via Lever ({slug})")
    return jobs
