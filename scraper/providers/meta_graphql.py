from __future__ import annotations
from job_cap import job_limit

from schema import Portal

import json
import logging
import re

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")

# Meta careers runs a public Relay GraphQL backend (no auth, no login).
#   1. GET /jobs            -> page embeds the per-session `lsd` token
#   2. POST /api/graphql/   -> doc_id=29615178951461218, variables={"search_input":{}}
#                              returns data.job_search_with_featured_jobs.all_jobs[]
#                              (full global list in one response, no pagination)
#   3. GET /jobs/{id}/      -> JobPosting JSON-LD carries the full JD
# India is filtered in Python because search_input.offices=["India"] returns 0
# (offices expects internal office ids), while the listing already enumerates
# every job's locations[] (e.g. "Mumbai, India").
_BOOTSTRAP_URL = "https://www.metacareers.com/jobs"
_GRAPHQL_URL = "https://www.metacareers.com/api/graphql/"
_DETAIL_URL = "https://www.metacareers.com/jobs/{job_id}/"
_LIST_DOC_ID = "29615178951461218"

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-Dest": "document",
    "Upgrade-Insecure-Requests": "1",
}

_LSD_RE = re.compile(r'"LSD",\[\],\{"token":"([^"]+)"')
_LDJSON_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


class MetaGraphQLProvider:
    """Meta (metacareers.com) public Relay GraphQL backend."""

    key = "meta_graphql"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_meta(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def _new_session() -> tuple[requests.Session, str] | None:
    """Bootstrap a session: fetch the careers page and pull the `lsd` token."""
    s = requests.Session()
    s.headers.update(_HEADERS)
    html = ""
    for _ in range(5):
        try:
            html = s.get(_BOOTSTRAP_URL, timeout=REQUEST_TIMEOUT).text
        except Exception:
            continue
        if '"LSD",[],{"token"' in html:
            break
    m = _LSD_RE.search(html)
    if not m:
        return None
    return s, m.group(1)


def _fetch_all_jobs(session: requests.Session, lsd: str) -> list[dict] | None:
    data = {
        "lsd": lsd,
        "doc_id": _LIST_DOC_ID,
        "variables": json.dumps({"search_input": {}}),
    }
    headers = {
        "User-Agent": _HEADERS["User-Agent"],
        "X-FB-LSD": lsd,
        "Content-Type": "application/x-www-form-urlencoded",
        "Origin": "https://www.metacareers.com",
        "Referer": _BOOTSTRAP_URL,
        "Accept": "*/*",
        "X-FB-Friendly-Name": "CareersJobSearchResultsDataQuery",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Dest": "empty",
    }
    # The full-list response is ~100KB and Meta is occasionally slow; one retry
    # absorbs transient read timeouts on this single critical call.
    resp = None
    for attempt in range(2):
        try:
            resp = session.post(
                _GRAPHQL_URL, data=data, headers=headers, timeout=REQUEST_TIMEOUT
            )
            break
        except Exception as e:
            if attempt == 1:
                _log.error(f"    [ERROR] Meta GraphQL POST failed: {e}")
                return None
    if resp is None or resp.status_code != 200:
        _log.error(f"    [ERROR] Meta GraphQL status={getattr(resp, 'status_code', 'n/a')}")
        return None
    try:
        payload = resp.json()
    except Exception:
        _log.error("    [ERROR] Meta GraphQL: response not JSON")
        return None
    node = (payload.get("data") or {}).get("job_search_with_featured_jobs")
    if not node:
        return None
    return node.get("all_jobs") or []


def _extract_jd(html: str) -> tuple[str, str, str]:
    """Return (jd_text, date_posted, apply_url) from a job detail page JSON-LD."""
    for m in _LDJSON_RE.finditer(html):
        raw = (m.group(1) or "").strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        candidates = obj if isinstance(obj, list) else [obj]
        for entry in candidates:
            if isinstance(entry, dict) and entry.get("@type") == "JobPosting":
                return (
                    strip_html(entry.get("description", "")),
                    entry.get("datePosted", "") or "",
                    entry.get("url", "") or "",
                )
    return "", "", ""


def _fetch_detail(session: requests.Session, job_id: str) -> tuple[str, str, str]:
    url = _DETAIL_URL.format(job_id=job_id)
    try:
        r = session.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return "", "", ""
        return _extract_jd(r.text)
    except Exception:
        return "", "", ""


def _scrape_meta(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    company = portal["company"]
    india_only = portal.get("india_only", True)
    cap = job_limit(max_jobs)

    boot = _new_session()
    if not boot:
        _log.error(f"    [ERROR] Meta {company}: could not obtain lsd token")
        return None
    session, lsd = boot

    all_jobs = _fetch_all_jobs(session, lsd)
    if all_jobs is None:
        return None

    jobs: list[dict] = []
    seen_ids: set[str] = set()

    for item in all_jobs:
        title = (item.get("title") or "").strip()
        if not title:
            continue

        locations = [loc for loc in (item.get("locations") or []) if loc]
        if india_only and not any(is_india(loc) for loc in locations):
            continue

        job_id = str(item.get("id") or "").strip() or job_hash(title, "")
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)

        detail_url = _DETAIL_URL.format(job_id=job_id)
        raw_jd, date_posted, apply_url = _fetch_detail(session, job_id)

        india_locations = [loc for loc in locations if is_india(loc)] or locations
        primary_city = india_locations[0] if india_locations else "India"

        jobs.append(
            {
                "job_id": job_id,
                "title": title,
                "job_url": apply_url or detail_url,
                "source_api_url": _GRAPHQL_URL,
                "business_unit": ", ".join(item.get("teams") or []),
                "raw_jd_text": raw_jd,
                "location_city": primary_city,
                "locations": india_locations,
                "date_posted": date_posted,
                "source_platform": "MetaGraphQL",
                "industry": portal.get("industry", ""),
            }
        )

        if len(jobs) >= cap:
            break

    _log.info(f"    {len(jobs)} India jobs fetched via Meta GraphQL ({company})")
    return jobs
