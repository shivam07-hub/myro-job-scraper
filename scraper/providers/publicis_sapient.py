from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}
_DETAIL_HEADERS = {
    **_HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_DETAIL_BODY_RE = re.compile(
    r'<div[^>]+class="[^"]*\bjob-details-content\b[^"]*"[^>]*>(?P<body>.*?)'
    r'(?:<div[^>]+class="[^"]*\bjob-detail-share\b|<footer|</main>|$)',
    re.IGNORECASE | re.DOTALL,
)


class PublicisSapientProvider:
    key = "publicis_sapient"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = scrape_publicis_sapient(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def _docs_from_payload(payload: dict) -> list[dict]:
    response = payload.get("response")
    if isinstance(response, dict) and isinstance(response.get("docs"), list):
        return [x for x in response["docs"] if isinstance(x, dict)]
    docs = payload.get("docs")
    if isinstance(docs, list):
        return [x for x in docs if isinstance(x, dict)]
    return []


def _doc_location(doc: dict) -> str:
    parts = [
        doc.get("city") or "",
        doc.get("region") or doc.get("state") or "",
        doc.get("countryName") or doc.get("country") or "",
    ]
    return ", ".join([str(p).strip() for p in parts if str(p).strip()])


def _publicis_detail_url(portal: Portal, doc: dict) -> str:
    base = "https://careers.publicissapient.com"
    endpoint = portal.get("endpoint") or ""
    if endpoint.startswith("http"):
        base = endpoint.split("/apps/", 1)[0].rstrip("/")

    detail = doc.get("jobDetailUrl") or doc.get("url") or ""
    if isinstance(detail, str) and detail:
        return urljoin(base + "/", detail.lstrip("/"))
    return str(doc.get("jobUrl") or "")


def parse_publicis_search_payload(payload: dict, portal: Portal, max_jobs: int | None = None) -> list[dict]:
    jobs: list[dict] = []
    india_only = portal.get("india_only", True)
    source_url = portal.get("endpoint", "")

    for doc in _docs_from_payload(payload):
        title = str(doc.get("name") or doc.get("title") or "").strip()
        if not title:
            continue

        location = _doc_location(doc)
        if india_only and not is_india(location):
            continue

        detail_url = _publicis_detail_url(portal, doc)
        job_id = str(doc.get("jobId") or doc.get("id") or job_hash(title, detail_url))
        raw_jd = strip_html(
            doc.get("description")
            or doc.get("jobDescription")
            or doc.get("overview")
            or doc.get("summary")
            or ""
        )

        jobs.append(
            {
                "job_id": job_id,
                "title": title,
                "job_url": detail_url or str(doc.get("jobUrl") or ""),
                "source_api_url": source_url,
                "business_unit": doc.get("teams") or doc.get("team") or doc.get("department"),
                "raw_jd_text": raw_jd,
                "location_city": location,
                "date_posted": doc.get("postedDate") or doc.get("lastModified") or doc.get("date"),
                "source_platform": "PublicisSapientAEM",
                "industry": portal.get("industry", ""),
            }
        )
        if max_jobs and len(jobs) >= max_jobs:
            break

    return jobs


def _fetch_detail_jd(url: str) -> str:
    if not url or "careers.publicissapient.com" not in url:
        return ""
    try:
        r = requests.get(url, headers=_DETAIL_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return ""
        m = _DETAIL_BODY_RE.search(r.text)
        if m:
            return strip_html(m.group("body") or "")
        return ""
    except Exception:
        return ""


def scrape_publicis_sapient(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    url = portal.get("endpoint", "")
    if not url.startswith("http"):
        _log.error(f"    [ERROR] Publicis Sapient: invalid endpoint for {portal.get('company')}")
        return None

    try:
        r = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        payload = r.json()
    except Exception as e:
        _log.error(f"    [ERROR] Publicis Sapient fetch failed: {e}")
        return None

    jobs = parse_publicis_search_payload(payload, portal, max_jobs=max_jobs)
    for job in jobs:
        if len(job.get("raw_jd_text") or "") >= 1200:
            continue
        detail_jd = _fetch_detail_jd(job.get("job_url", ""))
        if detail_jd:
            job["raw_jd_text"] = detail_jd

    _log.info(f"    {len(jobs)} India jobs fetched via Publicis Sapient AEM")
    return jobs
