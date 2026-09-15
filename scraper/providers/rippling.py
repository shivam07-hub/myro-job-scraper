from __future__ import annotations

import json
import logging
import re

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_NEXT_DATA_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(?P<json>.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


class RipplingProvider:
    key = "rippling"

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
        except Exception as e:
            _log.error(f"    [ERROR] Rippling listing {portal['company']}: {e}")
            return ProviderResult.error(ScrapeReason.API_BLOCKED)

        jobs = parse_rippling_listing_page(r.text, portal)
        if max_jobs:
            jobs = jobs[:max_jobs]

        enriched: list[dict] = []
        for job in jobs:
            detail = _fetch_detail(job.get("job_url", ""), portal)
            if detail:
                job.update(detail)
            enriched.append(job)
        return ProviderResult.success(enriched)


def _next_data(html: str) -> dict:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return {}
    try:
        return json.loads(m.group("json"))
    except Exception:
        return {}


def _locations_text(locations) -> str:
    parts: list[str] = []
    for loc in locations or []:
        if isinstance(loc, str):
            parts.append(loc)
        elif isinstance(loc, dict):
            name = loc.get("name") or ", ".join(
                p for p in [loc.get("city"), loc.get("state"), loc.get("country")] if p
            )
            if name:
                parts.append(str(name))
    return " | ".join(dict.fromkeys(parts))


def _is_india_locations(locations) -> bool:
    for loc in locations or []:
        if isinstance(loc, dict) and (loc.get("countryCode") == "IN" or loc.get("country") == "India"):
            return True
    return is_india(_locations_text(locations))


def parse_rippling_listing_page(html: str, portal: Portal, max_jobs: int | None = None) -> list[dict]:
    data = _next_data(html)
    page_props = data.get("props", {}).get("pageProps", {})
    items = list(page_props.get("jobs", {}).get("items", []))
    for query in page_props.get("dehydratedState", {}).get("queries", []):
        query_data = query.get("state", {}).get("data", {})
        query_items = query_data.get("items", []) if isinstance(query_data, dict) else []
        if isinstance(query_items, list):
            items.extend(query_items)
    out: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        locations = item.get("locations") or []
        if portal.get("india_only", True) and not _is_india_locations(locations):
            continue
        title = (item.get("name") or "").strip()
        if not title:
            continue
        url = item.get("url") or ""
        jid = str(item.get("id") or job_hash(title, url))
        if jid in seen:
            continue
        seen.add(jid)
        dept = item.get("department") if isinstance(item.get("department"), dict) else {}
        out.append({
            "job_id": jid,
            "title": title,
            "job_url": url,
            "source_api_url": portal.get("endpoint", ""),
            "business_unit": dept.get("name"),
            "raw_jd_text": "",
            "location_city": _locations_text(locations),
            "date_posted": None,
            "source_platform": "Rippling",
            "industry": portal.get("industry", ""),
        })
        if max_jobs and len(out) >= max_jobs:
            break
    return out


def _description_text(description) -> str:
    if isinstance(description, str):
        return strip_html(description)
    if isinstance(description, dict):
        return "\n\n".join(
            part for part in (strip_html(str(v)) for v in description.values()) if part
        )
    return ""


def parse_rippling_detail_page(html: str, url: str, portal: Portal) -> dict:
    data = _next_data(html)
    job = (
        data.get("props", {})
        .get("pageProps", {})
        .get("apiData", {})
        .get("jobPost", {})
    )
    if not isinstance(job, dict) or not job:
        return {}
    dept = job.get("department") if isinstance(job.get("department"), dict) else {}
    locations = job.get("workLocations") or []
    title = (job.get("name") or "").strip()
    return {
        "job_id": str(job.get("uuid") or job_hash(title, url)),
        "title": title,
        "job_url": job.get("url") or url,
        "business_unit": dept.get("name"),
        "raw_jd_text": _description_text(job.get("description")),
        "location_city": _locations_text(locations),
        "date_posted": job.get("createdOn"),
        "source_platform": "Rippling",
        "industry": portal.get("industry", ""),
    }


def _fetch_detail(url: str, portal: Portal) -> dict:
    if not url:
        return {}
    try:
        r = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return {}
        return parse_rippling_detail_page(r.text, url, portal)
    except Exception:
        return {}
