"""Darwinbox ATS provider.

API: ``POST https://{tenant}.darwinbox.in/ms/candidateapi/job/alljobs?companyId=main``
with ``{"companyId": "main", "page": N, "sort_option": "new", "limit": 50}``.
Each page carries what the job page shows: ``data[].id``, ``title``, ``jd``
(HTML-escaped; empty when the company wrote none), ``tool_tip_locations``,
``country``, ``department_name_only``, ``experience_from``/``experience_to`` and
``posted_on`` (Unix seconds, midnight IST). ``job_counts`` is the total.

The API answers without cookies (40/40 calls across four tenants, 2026-11-09).
The Cloudflare in front of it blocks the odd request at random, so a blocked or
failed page is retried; a tenant that stays blocked goes to the Firecrawl
fallback.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import requests

from config import REQUEST_TIMEOUT
from providers.base import FALLBACK_FIRECRAWL_EXTRACT, ProviderResult, ScrapeReason
from schema import Portal
from utils import strip_html

_log = logging.getLogger("mirror")
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
}
_PAGE_SIZE = 50
_MAX_PAGES = 100
_RETRY_STATUS = {403, 429, 500, 502, 503, 504}
_BLOCK_STATUS = {403, 429}
_ATTEMPTS = 3
_RETRY_PAUSE_S = 1.0
_IST = timezone(timedelta(hours=5, minutes=30))
_COUNTRY = "India"


class _Blocked(Exception):
    pass


class _TenantError(Exception):
    """The API answered with status "error", e.g. "Invalid subdomain"."""


class _LayoutChanged(Exception):
    pass


def _message(data: object, status: int) -> str:
    if isinstance(data, dict):
        inner = data.get("data")
        if isinstance(inner, dict) and inner.get("message"):
            return str(inner["message"])
        if data.get("message"):
            return str(data["message"])
    return f"HTTP {status}"


def _post(api_url: str, payload: dict, headers: dict[str, str]) -> dict:
    response = None
    for attempt in range(_ATTEMPTS):
        if attempt:
            time.sleep(_RETRY_PAUSE_S * attempt)
        response = requests.post(api_url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
        if response.status_code not in _RETRY_STATUS:
            break
    if response.status_code in _BLOCK_STATUS:
        raise _Blocked(f"HTTP {response.status_code}")
    try:
        data = response.json()
    except ValueError as exc:
        response.raise_for_status()
        raise _LayoutChanged("alljobs response is not JSON") from exc
    if not isinstance(data, dict) or data.get("status") != "success":
        raise _TenantError(_message(data, response.status_code))
    return data


def _clean(text: str) -> str:
    # Darwinbox writes "Mumbai, Maharashtra\r, India".
    return re.sub(r"\s+,", ",", re.sub(r"\s+", " ", text)).strip(" ,")


def _places(job: dict) -> list[str]:
    places = [_clean(p) for p in job.get("tool_tip_locations") or [] if isinstance(p, str)]
    places = [p for p in places if p]
    if not places:
        single = _clean(str(job.get("locations") or ""))
        if single and single.casefold() != "multiple locations":
            places = [single]
    return list(dict.fromkeys(places))


def _posted(value: object) -> str:
    if isinstance(value, str) and value.strip().isdigit():
        value = int(value.strip())
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        return ""
    if value > 10**11:  # milliseconds
        value = value / 1000
    return datetime.fromtimestamp(value, _IST).date().isoformat()


def _years(value: object) -> object:
    return "" if value is None else value


def _in_india(job: dict) -> bool:
    country = str(job.get("country") or "").strip()
    return not country or country.casefold() == _COUNTRY.casefold()


def job_record(job: dict, origin: str, api_url: str, industry: str) -> dict:
    jid = str(job.get("id") or job.get("_id") or "")
    places = _places(job)
    return {
        "job_id": jid,
        "title": _clean(str(job.get("title") or job.get("designation_name") or "")),
        "job_url": f"{origin}/ms/candidatev2/main/careers/jobDetails/{jid}",
        "source_api_url": api_url,
        "business_unit": job.get("department_name_only") or job.get("department_name") or "",
        # Empty when the company wrote no description; the writer then stores
        # its "No JD provided" note and skips matching for the role.
        "raw_jd_text": strip_html(html_lib.unescape(str(job.get("jd") or ""))).strip(),
        "location_city": " | ".join(places) or _COUNTRY,
        "locations": places,
        "min_years_experience": _years(job.get("experience_from")),
        "max_years_experience": _years(job.get("experience_to")),
        "date_posted": _posted(job.get("posted_on")),
        "source_platform": "Darwinbox",
        "industry": industry,
    }


class DarwinboxProvider:
    key = "darwinbox"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        careers_url = (portal.get("careers_url") or portal.get("endpoint") or "").strip()
        parts = urlparse(careers_url)
        if parts.scheme not in ("http", "https") or not parts.netloc:
            return ProviderResult.error(ScrapeReason.CONFIG_ERROR, "bad_darwinbox_careers_url")
        origin = f"{parts.scheme}://{parts.netloc}"
        api_url = f"{origin}/ms/candidateapi/job/alljobs?companyId=main"
        headers = {**_HEADERS, "Origin": origin, "Referer": careers_url}
        industry = portal.get("industry", "")

        jobs: list[dict] = []
        seen: set[str] = set()

        def failed(page: int, reason: ScrapeReason, note: str) -> ProviderResult:
            if page == 1:
                return ProviderResult.error(reason, note)
            return ProviderResult.partial(jobs, f"darwinbox_page_{page}: {note}")

        for page in range(1, _MAX_PAGES + 1):
            payload = {"companyId": "main", "page": page, "sort_option": "new", "limit": _PAGE_SIZE}
            try:
                data = _post(api_url, payload, headers)
            except _Blocked as exc:
                if page == 1:
                    _log.warning(f"    [Darwinbox] {portal['company']}: blocked after {_ATTEMPTS} tries ({exc})")
                    return ProviderResult.fallback(
                        policy=FALLBACK_FIRECRAWL_EXTRACT,
                        reason="darwinbox_cf_blocked",
                    )
                return failed(page, ScrapeReason.API_BLOCKED, str(exc))
            except _TenantError as exc:
                return failed(page, ScrapeReason.CONFIG_ERROR, f"darwinbox_error: {exc}")
            except _LayoutChanged as exc:
                return failed(page, ScrapeReason.PARSE_ERROR, str(exc))
            except requests.Timeout as exc:
                return failed(page, ScrapeReason.TIMEOUT, str(exc))
            except requests.RequestException as exc:
                return failed(page, ScrapeReason.API_BLOCKED, str(exc))

            items = data.get("data")
            if not isinstance(items, list):
                return failed(page, ScrapeReason.PARSE_ERROR, "alljobs response has no data list")
            for item in items:
                jid = str(item.get("id") or item.get("_id") or "")
                if not jid or jid in seen:
                    continue
                seen.add(jid)
                if not _in_india(item):
                    continue
                record = job_record(item, origin, api_url, industry)
                if not record["title"]:
                    continue
                jobs.append(record)
                if max_jobs and len(jobs) >= max_jobs:
                    return ProviderResult.success(jobs)

            total = data.get("job_counts")
            if len(items) < _PAGE_SIZE or (isinstance(total, int) and len(seen) >= total):
                break
        else:
            return ProviderResult.partial(jobs, f"darwinbox_page_limit={_MAX_PAGES}")

        _log.info(f"    {len(jobs)} jobs fetched via Darwinbox ({portal['company']})")
        return ProviderResult.success(jobs)
