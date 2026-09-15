from __future__ import annotations

import logging
import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


class AshbyProvider:
    key = "ashby"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        try:
            r = requests.get(portal["endpoint"], headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            _log.error(f"    [ERROR] Ashby {portal['company']}: {e}")
            return ProviderResult.error(ScrapeReason.API_BLOCKED)

        return ProviderResult.success(parse_ashby_job_board(payload, portal, max_jobs=max_jobs))


def _location_text(job: dict) -> str:
    locs: list[str] = []
    primary = job.get("location")
    if isinstance(primary, str) and primary:
        locs.append(primary)
    for item in job.get("secondaryLocations") or []:
        if isinstance(item, str) and item:
            locs.append(item)
        elif isinstance(item, dict):
            name = item.get("name") or item.get("location")
            if name:
                locs.append(str(name))
    return " | ".join(dict.fromkeys(locs))


def parse_ashby_job_board(payload: dict, portal: Portal, max_jobs: int | None = None) -> list[dict]:
    jobs: list[dict] = []
    seen: set[str] = set()
    for item in payload.get("jobs") or []:
        if not isinstance(item, dict):
            continue

        title = (item.get("title") or "").strip()
        if not title:
            continue

        loc = _location_text(item)
        # Some Ashby boards use a broad region (for example "APAC | Remote")
        # as the structured location and put the authoritative country in the
        # role title ("... - India").  Include the title in the India check, but
        # never infer India from the JD body where incidental mentions are common.
        if portal.get("india_only", True) and not is_india(f"{loc} {title}"):
            continue
        if not is_india(loc) and is_india(title):
            loc = f"{loc} | India" if loc else "India"

        jid = str(item.get("id") or job_hash(title, item.get("jobUrl") or item.get("applyUrl") or ""))
        if jid in seen:
            continue
        seen.add(jid)

        jd = item.get("descriptionPlain") or strip_html(item.get("descriptionHtml") or "")
        jobs.append({
            "job_id": jid,
            "title": title,
            "job_url": item.get("applyUrl") or item.get("jobUrl") or "",
            "source_api_url": portal.get("endpoint", ""),
            "business_unit": item.get("department") or item.get("team"),
            "raw_jd_text": jd.strip(),
            "location_city": loc,
            "date_posted": item.get("publishedAt"),
            "source_platform": "Ashby",
            "industry": portal.get("industry", ""),
        })
        if max_jobs and len(jobs) >= max_jobs:
            break
    return jobs
