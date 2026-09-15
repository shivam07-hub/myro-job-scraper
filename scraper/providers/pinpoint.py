from __future__ import annotations
from job_cap import job_limit

from schema import Portal

import logging
import requests
from urllib.parse import urlparse

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from utils import job_hash, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
}


class PinpointProvider:
    """Pinpoint ATS — JSON API at /en/postings.json.

    Portal config keys:
      endpoint       str   base URL e.g. https://jobs.aligntech.com
      pinpoint_india_location_ids  list[str]  location_id values for India
    """
    key = "pinpoint"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_pinpoint(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def _scrape_pinpoint(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    base = portal.get("endpoint", "").rstrip("/")
    parsed = urlparse(base)
    api_url = f"{parsed.scheme}://{parsed.netloc}/en/postings.json"

    india_ids: list[str] = portal.get("pinpoint_india_location_ids", [])
    company = portal["company"]
    cap = job_limit(max_jobs)

    params: list[tuple[str, str]] = []
    for lid in india_ids:
        params.append(("location_id[]", lid))

    # Some Pinpoint installs serve at /postings.json, others at /en/postings.json
    data = None
    for url_candidate in [api_url, f"{parsed.scheme}://{parsed.netloc}/postings.json"]:
        try:
            r = requests.get(url_candidate, params=params, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            api_url = url_candidate
            break
        except Exception as e:
            _log.debug(f"    [Pinpoint] {company} {url_candidate}: {e}")

    if data is None:
        _log.error(f"    [ERROR] Pinpoint {company}: all URL candidates failed")
        return None

    from utils import is_india
    india_only = portal.get("india_only", True)

    raw = data.get("data", [])
    jobs: list[dict] = []

    for item in raw:
        title = (item.get("title") or "").strip()
        if not title:
            continue

        loc_obj = item.get("location") or {}
        loc = loc_obj.get("city") or loc_obj.get("name") or ""

        if india_only and not india_ids and not is_india(loc):
            continue

        jid = str(item.get("id") or job_hash(title, item.get("url", "")))
        raw_jd = strip_html(item.get("description") or item.get("key_responsibilities") or "")

        jobs.append({
            "job_id":          jid,
            "title":           title,
            "job_url":         item.get("url") or f"{parsed.scheme}://{parsed.netloc}/en/postings/{jid}",
            "source_api_url":  api_url,
            "raw_jd_text":     raw_jd,
            "location_city":   loc,
            "date_posted":     item.get("deadline_at"),
            "source_platform": "Pinpoint",
            "industry":        portal.get("industry", ""),
        })

        if len(jobs) >= cap:
            break

    _log.info(f"    {len(jobs)} India jobs fetched via Pinpoint ({company})")
    return jobs
