from __future__ import annotations

"""Vector Consulting Group SSR/Next.js careers provider.

Pattern validated on vectorconsulting.in:
  - Listing: /careers/career-listings/
  - Jobs: embedded in __NEXT_DATA__.props.pageProps.jobsData.dataset
  - Full JD: description + body section content in that embedded payload
"""

import json
import logging
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT
from providers.base import FALLBACK_FIRECRAWL_EXTRACT, ProviderResult
from schema import Portal
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class VectorConsultingProvider:
    key = "vector_consulting"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_vector_consulting(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.fallback(
                policy=FALLBACK_FIRECRAWL_EXTRACT,
                reason="vector_next_data_unreachable_or_parse_failed",
                portal=portal,
            )
        return ProviderResult.success(jobs)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", strip_html(value or "")).strip()


def _extract_next_data(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return {}
    try:
        return json.loads(script.string)
    except Exception:
        return {}


def _normalise_body_sections(body) -> list[dict]:
    if isinstance(body, str):
        try:
            body = json.loads(body)
        except Exception:
            return []
    return body if isinstance(body, list) else []


def _job_description(item: dict) -> str:
    parts: list[str] = []
    description = _clean_text(item.get("description") or "")
    if description:
        parts.append(description)

    for section in _normalise_body_sections(item.get("body")):
        if not isinstance(section, dict):
            continue
        title = _clean_text(section.get("title") or "")
        content = _clean_text(section.get("content") or "")
        if title and content:
            parts.append(f"{title} {content}")
        elif content:
            parts.append(content)

    return "\n\n".join(parts).strip()


def _job_url(source_url: str, slug: str) -> str:
    if not slug:
        return source_url
    base = source_url.rstrip("/") + "/"
    return urljoin(base, slug).rstrip("/")


def parse_vector_next_data(html: str, portal: Portal, source_url: str, max_jobs: int | None = None) -> list[dict]:
    data = _extract_next_data(html)
    page_props = data.get("props", {}).get("pageProps", {})
    jobs_data = page_props.get("jobsData", {})
    dataset = jobs_data.get("dataset", [])
    if not isinstance(dataset, list):
        return []

    india_only = portal.get("india_only", True)
    industry = portal.get("industry", "")
    jobs: list[dict] = []
    seen_ids: set[str] = set()

    for item in dataset:
        if not isinstance(item, dict):
            continue
        title = (item.get("job_title") or item.get("job_role") or "").strip()
        slug = (item.get("slug") or "").strip()
        location = (item.get("location") or "").strip()
        if not title:
            continue
        if india_only and not is_india(location):
            continue

        url = _job_url(source_url, slug)
        jid = str(item.get("id") or slug or job_hash(title, url))
        if jid in seen_ids:
            continue
        seen_ids.add(jid)

        jobs.append(
            {
                "job_id": jid,
                "title": title,
                "job_url": url,
                "source_api_url": source_url,
                "business_unit": item.get("job_role") or item.get("employment_type"),
                "raw_jd_text": _job_description(item),
                "location_city": location,
                "date_posted": item.get("updated_at") or item.get("created_at") or "",
                "source_platform": "VectorNextData",
                "industry": industry,
            }
        )
        if max_jobs and len(jobs) >= max_jobs:
            break

    return jobs


def _scrape_vector_consulting(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    endpoint = (portal.get("endpoint") or "").strip()
    company = portal.get("company", "")
    if not endpoint.startswith("http"):
        _log.error(f"    [ERROR] Vector Consulting: invalid endpoint for {company}: {endpoint}")
        return None

    try:
        r = requests.get(endpoint, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            _log.warning(f"    [WARN] Vector Consulting listing status={r.status_code}")
            return None
    except Exception as e:
        _log.warning(f"    [WARN] Vector Consulting listing fetch failed: {e}")
        return None

    return parse_vector_next_data(r.text, portal, endpoint, max_jobs=max_jobs)
