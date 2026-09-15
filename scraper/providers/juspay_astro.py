from __future__ import annotations

"""Juspay careers provider.

Juspay's public careers page is server-rendered with Astro island props. The
payload is not a conventional ATS API, but it contains stable job objects with
IDs, locations, and JD text.
"""

import html
import json
import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class JuspayAstroProvider:
    key = "juspay_astro"

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
            r = requests.get(endpoint, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                return ProviderResult.error(ScrapeReason.API_BLOCKED, f"status_{r.status_code}")
            r.encoding = r.apparent_encoding or "utf-8"
        except Exception as e:
            _log.warning(f"    [WARN] JuspayAstro fetch failed: {e}")
            return ProviderResult.error(ScrapeReason.TIMEOUT, str(e))

        jobs = parse_juspay_careers_html(r.text, portal)
        if max_jobs:
            jobs = jobs[:max_jobs]
        return ProviderResult.success(jobs)


def _astro_unwrap(value):
    """Decode Astro serialized `[type, value]` wrappers recursively."""
    if isinstance(value, list):
        if len(value) == 2 and isinstance(value[0], int):
            return _astro_unwrap(value[1])
        return [_astro_unwrap(v) for v in value]
    if isinstance(value, dict):
        return {k: _astro_unwrap(v) for k, v in value.items()}
    return value


def _walk_dicts(value):
    value = _astro_unwrap(value)
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_dicts(child)


def _json_payloads(page_html: str) -> list:
    soup = BeautifulSoup(page_html, "html.parser")
    payloads = []
    for island in soup.find_all("astro-island"):
        raw = island.get("props") or ""
        if not raw:
            continue
        try:
            payloads.append(json.loads(html.unescape(raw)))
        except json.JSONDecodeError:
            continue
    for script in soup.find_all("script", type="application/json"):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            payloads.append(json.loads(html.unescape(raw)))
        except json.JSONDecodeError:
            continue
    return payloads


def _field(obj: dict, *names: str) -> str:
    for name in names:
        value = obj.get(name)
        if isinstance(value, (str, int)):
            return str(value).strip()
    return ""


def parse_juspay_careers_html(page_html: str, portal: Portal) -> list[dict]:
    endpoint = portal.get("endpoint") or "https://juspay.io/careers"
    industry = portal.get("industry", "")
    india_only = portal.get("india_only", True)
    jobs: list[dict] = []
    seen: set[str] = set()

    for payload in _json_payloads(page_html):
        for obj in _walk_dicts(payload):
            job_id = _field(obj, "job_id", "jobId", "job_code", "jobCode", "code", "id")
            title = _field(obj, "job_title", "jobTitle", "title", "name")
            loc = _field(obj, "job_location", "jobLocation", "location", "locations")
            jd = _field(
                obj,
                "job_description_career",
                "job_description",
                "jobDescription",
                "description",
                "descriptionPlain",
                "body",
            )
            if not (job_id and title and loc):
                continue
            if india_only and not is_india(loc):
                continue
            if job_id in seen:
                continue
            seen.add(job_id)

            jobs.append(
                {
                    "job_id": job_id,
                    "title": title,
                    "job_url": urljoin(endpoint.rstrip("/") + "/", job_id),
                    "source_api_url": endpoint,
                    "business_unit": _field(obj, "department", "team", "category"),
                    "raw_jd_text": strip_html(jd),
                    "location_city": loc,
                    "date_posted": _field(obj, "postedDate", "createdAt", "updatedAt"),
                    "source_platform": "JuspayAstro",
                    "industry": industry,
                }
            )
    return jobs
