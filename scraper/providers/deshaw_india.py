from __future__ import annotations

"""D. E. Shaw India Next.js careers provider.

Pattern validated on deshawindia.com/careers:
  - Public jobs are embedded in __NEXT_DATA__.props.pageProps.regularJobs
  - Full JD text is in data.jobDescription fields
  - Candidate apply URL redirects through /recruit/jobs/Ads/Link/{jobUrl}
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


class DEShawIndiaProvider:
    key = "deshaw_india"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_deshaw_india(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.fallback(
                policy=FALLBACK_FIRECRAWL_EXTRACT,
                reason="deshaw_next_data_unreachable_or_parse_failed",
                portal=portal,
            )
        return ProviderResult.success(jobs)


def _clean_text(value) -> str:
    if isinstance(value, list):
        value = " ".join(_clean_text(item) for item in value)
    elif isinstance(value, dict):
        value = " ".join(_clean_text(item) for item in value.values())
    elif value is None:
        value = ""
    else:
        value = str(value)
    return re.sub(r"\s+", " ", strip_html(value)).strip()


def _extract_next_data(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return {}
    try:
        return json.loads(script.string)
    except Exception:
        return {}


def _location_names(job: dict) -> list[str]:
    metadata = job.get("jobMetadata") if isinstance(job.get("jobMetadata"), dict) else {}
    raw_locations = metadata.get("jobLocations") if isinstance(metadata, dict) else []
    locations: list[str] = []
    if isinstance(raw_locations, list):
        for loc in raw_locations:
            if isinstance(loc, dict) and loc.get("name"):
                locations.append(str(loc["name"]).strip())
    return [loc for loc in locations if loc]


def _description_text(job: dict) -> str:
    jd = job.get("jobDescription") if isinstance(job.get("jobDescription"), dict) else {}
    parts: list[str] = []
    for key in (
        "websiteDescription",
        "responsibilities",
        "responsibilitiesHtml",
        "peopleWeAreLookingFor",
        "peopleWeAreLookingForStr",
        "peopleWeAreLookingForHtml",
    ):
        text = _clean_text(jd.get(key) or "")
        if text:
            parts.append(text)
    return "\n\n".join(parts).strip()


def _apply_url(source_url: str, job_url_slug: str) -> str:
    if not job_url_slug:
        return source_url
    return urljoin(source_url, f"/recruit/jobs/Ads/Link/{job_url_slug}")


def parse_deshaw_next_data(html: str, portal: Portal, source_url: str, max_jobs: int | None = None) -> list[dict]:
    data = _extract_next_data(html)
    page_props = data.get("props", {}).get("pageProps", {})
    regular_jobs = page_props.get("regularJobs", [])
    if not isinstance(regular_jobs, list):
        return []

    india_only = portal.get("india_only", True)
    industry = portal.get("industry", "")
    jobs: list[dict] = []
    seen_ids: set[str] = set()

    for wrapper in regular_jobs:
        job = wrapper.get("data") if isinstance(wrapper, dict) else None
        if not isinstance(job, dict):
            continue
        metadata = job.get("jobMetadata") if isinstance(job.get("jobMetadata"), dict) else {}
        if job.get("isActive") is False or metadata.get("activeOnWebsite") is False:
            continue

        title = (job.get("displayName") or job.get("positionNameForCandidateCommunication") or "").strip()
        if not title:
            continue

        locations = _location_names(job)
        location_text = " | ".join(locations)
        if india_only and not is_india(location_text):
            continue

        job_url_slug = (job.get("jobUrl") or "").strip()
        url = _apply_url(source_url, job_url_slug)
        jid = str(job.get("id") or job_url_slug or job_hash(title, url))
        if jid in seen_ids:
            continue
        seen_ids.add(jid)

        department = job.get("department") if isinstance(job.get("department"), dict) else {}
        business_unit = department.get("name") or ", ".join(job.get("jobHeaders") or [])

        jobs.append(
            {
                "job_id": jid,
                "title": title,
                "job_url": url,
                "source_api_url": source_url,
                "business_unit": business_unit,
                "raw_jd_text": _description_text(job),
                "location_city": location_text,
                "date_posted": job.get("validFromDate") or "",
                "source_platform": "DEShawNextData",
                "industry": industry,
            }
        )
        if max_jobs and len(jobs) >= max_jobs:
            break

    return jobs


def _scrape_deshaw_india(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    endpoint = (portal.get("endpoint") or "").strip()
    company = portal.get("company", "")
    if not endpoint.startswith("http"):
        _log.error(f"    [ERROR] DE Shaw: invalid endpoint for {company}: {endpoint}")
        return None

    try:
        r = requests.get(endpoint, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            _log.warning(f"    [WARN] DE Shaw listing status={r.status_code}")
            return None
    except Exception as e:
        _log.warning(f"    [WARN] DE Shaw listing fetch failed: {e}")
        return None

    return parse_deshaw_next_data(r.text, portal, endpoint, max_jobs=max_jobs)
