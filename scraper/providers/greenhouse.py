from __future__ import annotations

from schema import Portal

import logging
import re
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


class GreenhouseProvider:
    key = "greenhouse"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = scrape_greenhouse(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


_INDIA_LOCATION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("Bengaluru, India", r"\b(?:bengaluru|bangalore)\b"),
    ("Hyderabad, India", r"\bhyderabad\b"),
    ("Pune, India", r"\bpune\b"),
    ("Gurugram, India", r"\b(?:gurugram|gurgaon)\b"),
    ("Mumbai, India", r"\bmumbai\b"),
    ("Delhi NCR, India", r"\b(?:delhi|new delhi|ncr)\b"),
    ("Chennai, India", r"\bchennai\b"),
    ("Noida, India", r"\bnoida\b"),
    ("India", r"\bindia\b"),
)


def _infer_india_location(text: str) -> str:
    for label, pattern in _INDIA_LOCATION_PATTERNS:
        if re.search(pattern, text, flags=re.IGNORECASE):
            return label
    return ""


def scrape_greenhouse(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    url = portal['endpoint']
    try:
        r = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        _log.error(f"    [ERROR] Greenhouse {portal['company']}: {e}")
        return None

    india_only = portal.get('india_only', True)
    match_content = portal.get('greenhouse_match_content', False)
    listings = data.get('jobs', [])
    jobs = []
    for p in listings:
        loc = (p.get('location') or {}).get('name', '')
        raw_jd = strip_html(p.get('content', ''))
        match_text = loc
        if match_content:
            match_text = " ".join([loc, p.get('title', ''), raw_jd])
        if india_only and not is_india(match_text):
            continue
        depts  = p.get('departments') or []
        loc_out = loc
        if match_content and not is_india(loc_out):
            loc_out = _infer_india_location(" ".join([p.get('title', ''), raw_jd])) or loc_out
        jobs.append({
            'job_id':          str(p.get('id', job_hash(p.get('title', ''), p.get('absolute_url', '')))),
            'title':           p.get('title', ''),
            'job_url':         p.get('absolute_url', ''),
            'source_api_url':  url,
            'business_unit':   depts[0]['name'] if depts else None,
            'raw_jd_text':     raw_jd,
            'location_city':   loc_out,
            'date_posted':     p.get('updated_at'),
            'source_platform': 'Greenhouse',
            'industry':        portal.get('industry', ''),
        })
        if max_jobs and len(jobs) >= max_jobs:
            break
    return jobs
