from __future__ import annotations
from job_cap import job_limit

"""IntouchCX jobs provider via WordPress feed + detail pages.

Listing API:
  GET https://www.intouchcx.com/wp-json/intouchcx/v1/jobs?country=India

The feed returns title/link/location only. Full JDs live on one of two detail
hosts:
  - https://apply.intouchcx.com/{id} legacy HTML with .application-body
  - https://jobs.dayforcehcm.com/.../jobs/{id} SSR __NEXT_DATA__ JSON
"""

import html
import json
import logging
import re
from urllib.parse import urlsplit

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")

_JSON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.intouchcx.com/careers/",
}

_HTML_HEADERS = {
    "User-Agent": _JSON_HEADERS["User-Agent"],
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": _JSON_HEADERS["Accept-Language"],
}


class IntouchCXProvider:
    key = "intouchcx"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_intouchcx(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def _job_id_from_url(title: str, url: str) -> str:
    parts = urlsplit(url)
    host = parts.netloc.lower()
    segments = [s for s in parts.path.split("/") if s]
    native_id = segments[-1] if segments else ""

    if native_id:
        if "jobs.dayforcehcm.com" in host:
            return f"intouchcx-dayforce-{native_id}"
        if "apply.intouchcx.com" in host:
            return f"intouchcx-apply-{native_id}"

    return job_hash(title, url)


def parse_intouchcx_feed(data: dict, portal: Portal, max_jobs: int | None = None) -> list[dict]:
    """Map the WordPress feed shape into raw scraper rows."""
    items = data.get("jobs") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []

    source_url = portal.get("endpoint", "")
    industry = portal.get("industry", "")
    india_only = portal.get("india_only", True)
    cap = job_limit(max_jobs)

    jobs: list[dict] = []
    seen_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue

        title = str(item.get("job") or item.get("title") or "").strip()
        apply_url = str(item.get("link") or item.get("url") or item.get("job_url") or "").strip()
        location = str(item.get("location") or "").strip()
        if not title or not apply_url:
            continue
        if india_only and not is_india(location):
            continue

        job_id = _job_id_from_url(title, apply_url)
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        jobs.append(
            {
                "job_id": job_id,
                "title": title,
                "job_url": apply_url,
                "source_api_url": source_url,
                "business_unit": "",
                "raw_jd_text": "",
                "location_city": location,
                "date_posted": "",
                "source_platform": "IntouchCX",
                "industry": industry,
            }
        )
        if len(jobs) >= cap:
            break

    return jobs


def parse_legacy_intouchcx_detail(html_text: str) -> str:
    """Extract full JD text from apply.intouchcx.com legacy application pages."""
    if not html_text:
        return ""

    m = re.search(
        r'<div[^>]+class="[^"]*\bapplication-body\b[^"]*"[^>]*>(.*?)'
        r'<div[^>]+class="[^"]*\bapplication-buttons\b',
        html_text,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return ""

    return strip_html(m.group(1))


def _find_dayforce_job_data(obj):
    if isinstance(obj, dict):
        content = obj.get("jobPostingContent")
        if isinstance(content, dict) and obj.get("jobTitle"):
            return obj
        for value in obj.values():
            found = _find_dayforce_job_data(value)
            if found:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find_dayforce_job_data(value)
            if found:
                return found
    return None


def parse_dayforce_next_data(html_text: str) -> dict:
    """Extract title/JD/location/date from Dayforce SSR __NEXT_DATA__."""
    if not html_text:
        return {}

    m = re.search(
        r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
        html_text,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return {}

    try:
        payload = json.loads(html.unescape(m.group(1)).strip())
    except Exception:
        return {}

    job_data = _find_dayforce_job_data(payload)
    if not isinstance(job_data, dict):
        return {}

    content = job_data.get("jobPostingContent") or {}
    if not isinstance(content, dict):
        content = {}
    jd_parts = [
        content.get("jobDescriptionHeader") or "",
        content.get("jobDescription") or "",
        content.get("jobDescriptionFooter") or "",
    ]

    locations = job_data.get("postingLocations") or []
    location = ""
    if isinstance(locations, list):
        loc_parts: list[str] = []
        for loc in locations:
            if not isinstance(loc, dict):
                continue
            formatted = loc.get("formattedAddress")
            if formatted:
                loc_parts.append(str(formatted).strip())
                continue
            city = str(loc.get("cityName") or "").strip()
            country = str(loc.get("isoCountryCode") or "").strip()
            loc_parts.append(", ".join([x for x in (city, country) if x]))
        location = " | ".join([x for x in loc_parts if x])

    return {
        "title": str(job_data.get("jobTitle") or "").strip(),
        "raw_jd_text": strip_html("\n".join([p for p in jd_parts if p])),
        "location_city": location,
        "date_posted": job_data.get("postingStartTimestampUTC") or job_data.get("createdTimestampUTC") or "",
        "business_unit": "",
    }


def _fetch_detail(session: requests.Session, url: str) -> dict:
    try:
        r = session.get(url, headers=_HTML_HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        _log.warning(f"    [WARN] IntouchCX detail fetch failed {url}: {e}")
        return {}

    host = urlsplit(url).netloc.lower()
    if "jobs.dayforcehcm.com" in host:
        return parse_dayforce_next_data(r.text)

    legacy_jd = parse_legacy_intouchcx_detail(r.text)
    return {"raw_jd_text": legacy_jd} if legacy_jd else {}


def _scrape_intouchcx(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    endpoint = (portal.get("endpoint") or "").strip()
    company = portal.get("company", "")
    if not endpoint.startswith("http"):
        _log.error(f"    [ERROR] IntouchCX provider: invalid endpoint for {company}: {endpoint}")
        return None

    session = requests.Session()
    session.headers.update(_JSON_HEADERS)

    try:
        r = session.get(endpoint, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        _log.error(f"    [ERROR] IntouchCX feed failed ({company}): {e}")
        return None

    jobs = parse_intouchcx_feed(payload, portal, max_jobs=max_jobs)
    for job in jobs:
        detail = _fetch_detail(session, job.get("job_url") or "")
        if not detail:
            continue
        if detail.get("title"):
            job["title"] = str(detail["title"]).strip()
        if detail.get("raw_jd_text"):
            job["raw_jd_text"] = detail["raw_jd_text"]
        if detail.get("location_city"):
            job["location_city"] = detail["location_city"]
        if detail.get("date_posted"):
            job["date_posted"] = detail["date_posted"]
        if detail.get("business_unit"):
            job["business_unit"] = detail["business_unit"]

    with_jd = sum(1 for job in jobs if job.get("raw_jd_text"))
    _log.info(f"    {len(jobs)} India jobs via IntouchCX feed ({company}); {with_jd} with JD")
    return jobs
