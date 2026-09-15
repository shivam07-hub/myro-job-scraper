from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlsplit

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import strip_html

_log = logging.getLogger("mirror")

_DETAIL_PREFIX = "/en-gb/careers/new-job-openings/"
_API_RE = re.compile(r'"apiEndpointName":"(?P<endpoint>Careers/[^"]+/Get)"')


def parse_bdo_api_payload(payload: dict, portal: Portal) -> list[dict]:
    items = payload.get("data", []) if isinstance(payload, dict) else []
    out: list[dict] = []
    seen: set[str] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        reference = str(item.get("reference") or "").strip()
        title = str(item.get("title") or "").strip()
        apply_path = str(item.get("applyURL") or "").strip()
        if not reference or not title or reference in seen:
            continue
        seen.add(reference)
        locations = item.get("locations") or []
        location = ", ".join(str(value) for value in locations if value) or "India"
        metadata = "\n".join(
            value
            for value in [
                title,
                f"Job title: {item.get('jobTitle')}" if item.get("jobTitle") else "",
                f"Level: {item.get('level')}" if item.get("level") else "",
            ]
            if value
        )
        out.append({
            "job_id": reference,
            "title": title,
            "job_url": urljoin(portal.get("endpoint", ""), apply_path),
            "source_api_url": portal.get("endpoint", ""),
            "business_unit": item.get("jobTitle"),
            "raw_jd_text": metadata,
            "location_city": location,
            "date_posted": item.get("publishDate"),
            "source_platform": "BDO Kentico Careers API",
            "industry": portal.get("industry", ""),
        })
    return out


def parse_bdo_map_links(links: list[dict], portal: Portal) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for item in links:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        parts = urlsplit(url)
        if not parts.path.startswith(_DETAIL_PREFIX):
            continue
        slug = parts.path[len(_DETAIL_PREFIX):].strip("/")
        if not slug or "/" in slug or slug in seen:
            continue
        seen.add(slug)
        title = str(item.get("title") or "").strip()
        for suffix in (" - BDO India", " - BDO", " | BDO India"):
            if title.endswith(suffix):
                title = title[: -len(suffix)].strip()
        if not title:
            title = slug.replace("-", " ").title()
        out.append({
            "job_id": slug,
            "title": title,
            "job_url": url,
            "source_api_url": portal.get("endpoint", ""),
            "business_unit": None,
            "raw_jd_text": strip_html(str(item.get("description") or "")),
            "location_city": "India",
            "date_posted": None,
            "source_platform": "BDO CMS via Firecrawl Cloud",
            "industry": portal.get("industry", ""),
        })
    return out


class BDOFirecrawlProvider:
    key = "bdo_firecrawl"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        endpoint = (portal.get("endpoint") or "").strip()
        if not endpoint.startswith("http"):
            return ProviderResult.error(ScrapeReason.CONFIG_ERROR, "bad_endpoint")
        try:
            response = requests.get(
                endpoint,
                headers={
                    "User-Agent": "python-requests/2",
                    "Accept": "text/html,application/json",
                },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            api_match = _API_RE.search(response.text)
            if api_match:
                api_url = urljoin(
                    endpoint,
                    f"/api/en-gb/{api_match.group('endpoint')}",
                )
                listing = requests.get(
                    api_url,
                    params={"currentPage": 1, "pageSize": max_jobs or 200},
                    headers={
                        "User-Agent": "python-requests/2",
                        "Accept": "application/json",
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                listing.raise_for_status()
                jobs = parse_bdo_api_payload(listing.json(), portal)
                if max_jobs:
                    jobs = jobs[:max_jobs]
                if jobs:
                    return ProviderResult.success(jobs)
        except requests.RequestException as exc:
            _log.info("    [BDO] direct careers API unavailable: %s", exc)

        try:
            import firecrawl_client as fc

            links = fc.cloud_map_site(
                endpoint,
                search="new job openings",
                include_subdomains=False,
                ignore_query_parameters=True,
                limit=max_jobs or 200,
                sitemap="include",
            )
        except Exception as exc:
            _log.warning("    [BDO] Firecrawl cloud map failed: %s", exc)
            return ProviderResult.error(ScrapeReason.API_BLOCKED, str(exc))

        jobs = parse_bdo_map_links(links, portal)
        if max_jobs:
            jobs = jobs[:max_jobs]
        if not jobs:
            return ProviderResult.error(ScrapeReason.PARSE_ERROR, "no_bdo_detail_links")
        return ProviderResult.success(jobs)
