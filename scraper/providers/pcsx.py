"""Phenom CX (pcsx) ATS provider.

Two-step fetch:
  1. GET {base}/api/pcsx/search?domain={domain}&query=&location=india&start={N}
     Returns {data: {positions: [...], count: N}} — 10 jobs/page
  2. GET {base}/careers/job/{id} → parse JSON-LD <script type="application/ld+json">
     Extracts full JD (~6000 chars) server-side rendered, no JS needed

Portal config keys:
  endpoint     str   base URL e.g. https://careers.haleon.com
  pcsx_domain  str   domain param e.g. haleon.com
"""

from __future__ import annotations
from job_cap import job_limit

import json
import logging
import re
import time

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import strip_html

_log = logging.getLogger("mirror")
_PAGE_SIZE = 10

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


class PCSXProvider:
    """Phenom CX (pcsx) — paginated list API + per-job HTML JSON-LD for full JD."""
    key = "pcsx"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        return _scrape_pcsx(portal, max_jobs=max_jobs)


def _careers_url(base: str, domain: str) -> str:
    return f"{base}/careers?domain={domain}&location=India"


def _bootstrap_session(
    session: requests.Session,
    base: str,
    domain: str,
) -> bool:
    """Load the public board once so PCSX/CloudFront can issue visitor cookies."""
    try:
        response = session.get(
            _careers_url(base, domain),
            headers={**_HEADERS, "Accept": "text/html,application/xhtml+xml"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return True
    except Exception as exc:
        _log.warning("    [WARN] PCSX session bootstrap failed (%s): %s", base, exc)
        return False


def _session_get(
    session: requests.Session,
    url: str,
    *,
    base: str,
    domain: str,
    params: dict | None = None,
    accept: str = "application/json",
) -> requests.Response:
    """GET with one fresh visitor-session recovery for auth-like PCSX blocks."""
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = session.get(
                url,
                params=params,
                headers={
                    **_HEADERS,
                    "Accept": accept,
                    "Referer": _careers_url(base, domain),
                },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_error = exc
            status = getattr(exc.response, "status_code", None)
            if attempt == 0 and status in {401, 403}:
                _bootstrap_session(session, base, domain)
                time.sleep(0.25)
                continue
            raise
    assert last_error is not None
    raise last_error


def _fetch_jd(
    session: requests.Session,
    base: str,
    domain: str,
    job_id: str,
) -> str:
    """Fetch job HTML page and extract JD from JSON-LD JobPosting schema."""
    url = f"{base}/careers/job/{job_id}"
    try:
        r = _session_get(
            session,
            url,
            base=base,
            domain=domain,
            accept="text/html",
        )
        m = re.search(
            r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>',
            r.text, re.DOTALL
        )
        if not m:
            return ""
        ld = json.loads(m.group(1))
        return strip_html(ld.get("description", ""))
    except Exception:
        return ""


def _scrape_pcsx(portal: Portal, max_jobs: int | None = None) -> ProviderResult:
    base = portal.get("endpoint", "").rstrip("/")
    domain = portal.get("pcsx_domain", "")
    company = portal["company"]
    cap = job_limit(max_jobs)

    jobs: list[dict] = []
    seen_job_ids: set[str] = set()
    start = 0
    session = requests.Session()
    if not _bootstrap_session(session, base, domain):
        return ProviderResult.error(
            ScrapeReason.API_BLOCKED,
            "pcsx_career_page_bootstrap_failed",
        )

    while True:
        params = {
            "domain": domain,
            "query": "",
            "location": "india",
            "start": start,
        }
        try:
            r = _session_get(
                session,
                f"{base}/api/pcsx/search",
                base=base,
                domain=domain,
                params=params,
            )
            data = r.json()
        except Exception as e:
            _log.error(f"    [ERROR] PCSX {company} start={start}: {e}")
            if jobs:
                return ProviderResult.partial(
                    jobs,
                    f"pcsx_listing_failed_at_start_{start}: {e}",
                )
            return ProviderResult.error(ScrapeReason.API_BLOCKED, str(e))

        positions = data.get("data", {}).get("positions", [])
        total = data.get("data", {}).get("count", 0)

        if not positions:
            break

        for p in positions:
            job_id = str(p.get("id") or "")
            if not job_id or job_id in seen_job_ids:
                continue
            title = (p.get("name") or "").strip()
            if not title:
                continue

            locs = p.get("locations") or p.get("standardizedLocations") or []
            locs = [location for location in locs if isinstance(location, str) and location.strip()]
            loc = locs[0] if locs else ""
            if isinstance(loc, str):
                # strip ATS prefix e.g. "Field Worker- IND Cx_MumbaiRSO, Mumbai, ..."
                loc = loc.split(",")[-3].strip() if loc.count(",") >= 2 else loc

            jd = _fetch_jd(session, base, domain, job_id)
            apply_url = f"{base}{p.get('positionUrl', f'/careers/job/{job_id}')}"

            jobs.append({
                "job_id":          job_id,
                "title":           title,
                "job_url":         apply_url,
                "source_api_url":  f"{base}/api/pcsx/search",
                "business_unit":   p.get("department"),
                "raw_jd_text":     jd,
                "location_city":   loc,
                "locations":       locs,
                "date_posted":     str(p.get("postedTs", "")),
                "source_platform": "PhenomCX",
                "industry":        portal.get("industry", ""),
            })
            seen_job_ids.add(job_id)

            if len(jobs) >= cap:
                break

        if len(jobs) >= cap or start + _PAGE_SIZE >= total:
            break
        start += _PAGE_SIZE

    _log.info(f"    {len(jobs)} India jobs fetched via PCSX ({company})")
    return ProviderResult.success(jobs)
