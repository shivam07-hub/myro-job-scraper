from __future__ import annotations

"""Microsoft Careers provider via public PCSX search + Eightfold detail API.

Listing:
  GET https://apply.careers.microsoft.com/api/pcsx/search?domain=microsoft.com&query=&location=India&start=0&hl=en

Full JD:
  GET https://apply.careers.microsoft.com/api/apply/v2/jobs/{position_id}?domain=microsoft.com
"""

import logging
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests

from config import REQUEST_TIMEOUT
from job_cap import job_limit
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")

_BASE = "https://apply.careers.microsoft.com"
_DOMAIN = "microsoft.com"
_LANDING_URL = f"{_BASE}/careers?location=India&hl=en"
_SEARCH_URL = f"{_BASE}/api/pcsx/search"
_DETAIL_URL = f"{_BASE}/api/apply/v2/jobs/{{position_id}}"
_PAGE_SIZE = 10

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": _LANDING_URL,
    "X-EF-GROUP-ID": _DOMAIN,
}


class MicrosoftCareersProvider:
    key = "microsoft_careers"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_microsoft(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def _date_from_epoch(value) -> str:
    if value in (None, ""):
        return ""
    try:
        return datetime.fromtimestamp(int(value), timezone.utc).date().isoformat()
    except Exception:
        return str(value)


def _first_location(item: dict) -> str:
    location = item.get("location") or item.get("primaryLocation") or item.get("primary_location")
    if location:
        return str(location).strip()

    locations = item.get("locations") or item.get("standardizedLocations") or []
    if isinstance(locations, list):
        return " | ".join(str(loc).strip() for loc in locations if str(loc).strip())
    if locations:
        return str(locations).strip()
    return ""


def _is_india_position(item: dict, location: str) -> bool:
    standardized = item.get("standardizedLocations") or item.get("standardized_locations") or []
    if isinstance(standardized, list) and any(str(loc).upper() == "IN" for loc in standardized):
        return True
    return is_india(location)


def _msft_job_id(item: dict, title: str = "", url: str = "") -> str:
    native = (
        item.get("display_job_id")
        or item.get("displayJobId")
        or item.get("ats_job_id")
        or item.get("atsJobId")
        or item.get("jobId")
        or item.get("id")
    )
    if native:
        native_s = str(native).strip()
        if native_s.startswith("microsoft-"):
            return native_s
        return f"microsoft-{native_s}"
    return job_hash(title, url)


def _absolute_job_url(position_id: str, position_url: str = "") -> str:
    url = urljoin(_BASE, position_url or f"/careers/job/{position_id}")
    parts = urlsplit(url)
    if not parts.query:
        return urlunsplit((parts.scheme, parts.netloc, parts.path, "hl=en", parts.fragment))
    return url


def parse_microsoft_search_payload(
    payload: dict,
    portal: Portal,
    max_jobs: int | None = None,
) -> list[dict]:
    """Map Microsoft PCSX search JSON into raw scraper rows."""
    if not isinstance(payload, dict):
        return []

    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    positions = data.get("positions") if isinstance(data, dict) else []
    if not isinstance(positions, list):
        return []

    cap = job_limit(max_jobs)
    india_only = portal.get("india_only", True)
    source_url = portal.get("endpoint") or _SEARCH_URL
    industry = portal.get("industry", "")

    jobs: list[dict] = []
    seen_ids: set[str] = set()
    for item in positions:
        if not isinstance(item, dict):
            continue

        title = str(item.get("name") or item.get("posting_name") or item.get("postingName") or "").strip()
        position_id = str(item.get("id") or "").strip()
        if not title or not position_id:
            continue

        location = _first_location(item)
        if india_only and not _is_india_position(item, location):
            continue

        apply_url = _absolute_job_url(position_id, str(item.get("positionUrl") or ""))
        job_id = _msft_job_id(item, title, apply_url)
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        jobs.append(
            {
                "job_id": job_id,
                "title": title,
                "job_url": apply_url,
                "source_api_url": source_url,
                "business_unit": item.get("department") or item.get("business_unit") or "",
                "raw_jd_text": "",
                "location_city": location,
                "date_posted": _date_from_epoch(item.get("postedTs") or item.get("posted_ts") or item.get("t_update") or item.get("creationTs")),
                "source_platform": "MicrosoftPCSX",
                "industry": industry,
                "microsoft_position_id": position_id,
            }
        )
        if len(jobs) >= cap:
            break

    return jobs


def _detail_object(payload: dict) -> dict:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("position", "job"):
            if isinstance(data.get(key), dict):
                return data[key]
        if data.get("id") or data.get("job_description"):
            return data
    positions = payload.get("positions")
    if isinstance(positions, list) and positions and isinstance(positions[0], dict):
        return positions[0]
    return payload


def parse_microsoft_detail_payload(payload: dict) -> dict:
    """Map Microsoft detail API JSON into raw scraper fields."""
    item = _detail_object(payload)
    if not item:
        return {}

    title = str(item.get("name") or item.get("posting_name") or item.get("postingName") or "").strip()
    location = _first_location(item)
    position_url = str(item.get("positionUrl") or item.get("canonicalPositionUrl") or item.get("canonical_position_url") or "")
    position_id = str(item.get("id") or "").strip()
    apply_url = _absolute_job_url(position_id, position_url) if position_id else position_url

    return {
        "job_id": _msft_job_id(item, title, apply_url),
        "title": title,
        "job_url": apply_url,
        "business_unit": item.get("business_unit") or item.get("businessUnit") or item.get("department") or "",
        "raw_jd_text": strip_html(item.get("job_description") or item.get("description") or ""),
        "location_city": location,
        "date_posted": _date_from_epoch(
            item.get("t_update")
            or item.get("postedTs")
            or item.get("posted_ts")
            or item.get("t_create")
            or item.get("creationTs")
        ),
    }


def _fetch_detail(session: requests.Session, position_id: str) -> dict:
    try:
        r = session.get(
            _DETAIL_URL.format(position_id=position_id),
            params={"domain": _DOMAIN},
            timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        return parse_microsoft_detail_payload(r.json())
    except Exception as e:
        _log.warning(f"    [WARN] Microsoft detail fetch failed {position_id}: {e}")
        return {}


def _scrape_microsoft(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    company = portal.get("company", "Microsoft")
    cap = job_limit(max_jobs)
    session = requests.Session()
    session.headers.update(_HEADERS)

    try:
        session.get(_LANDING_URL, headers={**_HEADERS, "Accept": "text/html,*/*"}, timeout=REQUEST_TIMEOUT)
    except Exception:
        # The search endpoint is still the source of truth; the warmup just sets
        # normal PCSX session cookies when the frontend wants them.
        pass

    jobs: list[dict] = []
    seen_ids: set[str] = set()
    start = 0
    total = None

    while len(jobs) < cap:
        try:
            r = session.get(
                _SEARCH_URL,
                params={
                    "domain": _DOMAIN,
                    "query": "",
                    "location": "India",
                    "start": start,
                    "hl": "en",
                },
                timeout=REQUEST_TIMEOUT,
            )
            r.raise_for_status()
            payload = r.json()
        except Exception as e:
            _log.error(f"    [ERROR] Microsoft PCSX search {company} start={start}: {e}")
            return jobs or None

        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        positions = data.get("positions") if isinstance(data, dict) else []
        if not positions:
            break
        if isinstance(data.get("count"), int):
            total = data["count"]

        page_jobs = parse_microsoft_search_payload(payload, portal, max_jobs=cap - len(jobs))
        for job in page_jobs:
            if job["job_id"] in seen_ids:
                continue
            seen_ids.add(job["job_id"])
            jobs.append(job)
            if len(jobs) >= cap:
                break

        start += _PAGE_SIZE
        if total is not None and start >= total:
            break

    for job in jobs:
        position_id = job.get("microsoft_position_id") or ""
        if not position_id:
            continue
        detail = _fetch_detail(session, str(position_id))
        if not detail:
            continue
        for key in ("job_id", "title", "job_url", "business_unit", "raw_jd_text", "location_city", "date_posted"):
            if detail.get(key):
                job[key] = detail[key]

    with_jd = sum(1 for job in jobs if job.get("raw_jd_text"))
    _log.info(f"    {len(jobs)} India jobs fetched via Microsoft PCSX; {with_jd} with JD")
    return jobs
