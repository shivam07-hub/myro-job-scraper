from __future__ import annotations
from job_cap import job_limit

from schema import Portal

import json
import logging
import re
from urllib.parse import urlparse

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Search/results page embeds jobs in phApp.ddo (JSON).
# We intentionally avoid a deep DOTALL brace regex here because some tenants
# embed very large JSON blobs and regex backtracking can become expensive.
_DDO_START = "phApp.ddo = "
_DDO_END = "; phApp.experimentData"
_NEXT_RE = re.compile(r'rel="next"\s+href="([^"]+)"')

# Job page embeds full JD in JobPosting JSON-LD.
_LDJSON_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)


class PhenomSSRProvider:
    """Phenom SSR careers pages.

    Pattern validated on Adobe:
      - Listing/search: jobs are embedded in phApp.ddo.eagerLoadRefineSearch.data.jobs
      - Details: full JD in JobPosting JSON-LD at /us/en/job/{jobSeqNo}
    """

    key = "phenom_ssr"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_phenom_ssr(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def _extract_search_jobs(html: str) -> list[dict]:
    s = html.find(_DDO_START)
    if s == -1:
        return []
    s += len(_DDO_START)
    e = html.find(_DDO_END, s)
    if e == -1:
        return []
    blob = html[s:e].strip()
    if not blob:
        return []
    try:
        ddo = json.loads(blob)
    except Exception:
        return []
    return ddo.get("eagerLoadRefineSearch", {}).get("data", {}).get("jobs", []) or []


def _extract_next_url(html: str) -> str:
    m = _NEXT_RE.search(html)
    return m.group(1).strip() if m else ""


def _extract_jd_from_job_page(html: str) -> str:
    for m in _LDJSON_RE.finditer(html):
        raw = (m.group(1) or "").strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if isinstance(obj, list):
            for entry in obj:
                if isinstance(entry, dict) and entry.get("@type") == "JobPosting":
                    return strip_html(entry.get("description", ""))
            continue
        if isinstance(obj, dict) and obj.get("@type") == "JobPosting":
            return strip_html(obj.get("description", ""))
    return ""


def _slugify_title(title: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", (title or "").strip()).strip("-")
    return slug or "job"


def _locale_prefix_from_endpoint(endpoint: str) -> str:
    """
    Extract locale prefix from search endpoint path.
    Example:
      /global/en/search-results -> /global/en
      /us/en/search-results     -> /us/en
    """
    path = (urlparse(endpoint).path or "").strip("/")
    parts = path.split("/") if path else []
    if "search-results" in parts:
        idx = parts.index("search-results")
        if idx > 0:
            return "/" + "/".join(parts[:idx])
    return ""


def _job_detail_url_candidates(endpoint: str, *, job_seq_no: str, job_id: str, title: str) -> list[str]:
    """
    Generate likely Phenom SSR job detail URLs across tenants.

    Different tenants use different keys in the path:
      - /{locale}/job/{jobSeqNo}
      - /{locale}/job/{jobId}/{title-slug}
    """
    parsed = urlparse(endpoint)
    base = f"{parsed.scheme}://{parsed.netloc}"
    prefix = _locale_prefix_from_endpoint(endpoint)
    slug = _slugify_title(title)

    out: list[str] = []

    def _add(url: str) -> None:
        if url and url not in out:
            out.append(url)

    # ABB-like tenants (global/en) primarily resolve by jobId in the path.
    prefer_job_id = prefix.startswith("/global/")

    if prefer_job_id and job_id:
        _add(f"{base}{prefix}/job/{job_id}/{slug}")
        _add(f"{base}{prefix}/job/{job_id}")

    if job_seq_no:
        _add(f"{base}{prefix}/job/{job_seq_no}")
        _add(f"{base}{prefix}/job/{job_seq_no}/{slug}")
        # Legacy fallback seen on older tenants (e.g., some Adobe routes)
        _add(f"{base}/us/en/job/{job_seq_no}")

    if (not prefer_job_id) and job_id:
        _add(f"{base}{prefix}/job/{job_id}/{slug}")
        _add(f"{base}{prefix}/job/{job_id}")

    return out


def _fetch_jd(detail_url: str, *, referer: str) -> str:
    try:
        r = requests.get(
            detail_url,
            headers={**_HEADERS, "Referer": referer},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code != 200:
            return ""
        return _extract_jd_from_job_page(r.text)
    except Exception:
        return ""


def _scrape_phenom_ssr(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    company = portal["company"]
    search_url = portal.get("endpoint", "").strip() or portal.get("careers_url", "").strip()
    if not search_url:
        _log.error(f"    [ERROR] Phenom SSR {company}: missing endpoint")
        return None

    india_only = portal.get("india_only", True)
    cap = job_limit(max_jobs)

    jobs: list[dict] = []
    seen_ids: set[str] = set()
    seen_pages: set[str] = set()

    url = search_url
    page_count = 0
    max_pages = 300

    while url and page_count < max_pages:
        if url in seen_pages:
            break
        seen_pages.add(url)
        page_count += 1

        try:
            resp = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code != 200:
                _log.error(f"    [ERROR] Phenom SSR {company}: status={resp.status_code} url={url}")
                break
            html = resp.text
        except Exception as e:
            _log.error(f"    [ERROR] Phenom SSR {company}: {e}")
            break

        raw_jobs = _extract_search_jobs(html)
        if not raw_jobs:
            break

        for item in raw_jobs:
            title = (item.get("title") or "").strip()
            if not title:
                continue

            country = item.get("country") or item.get("standardisedCountry") or ""
            location = (
                item.get("location")
                or item.get("cityStateCountry")
                or item.get("cityState")
                or item.get("city")
                or ""
            )
            if india_only and not (is_india(country) or is_india(location)):
                continue

            job_seq_no = str(item.get("jobSeqNo") or "").strip()
            apply_url = item.get("applyUrl") or ""
            raw_job_id = str(item.get("jobId") or item.get("reqId") or "").strip()
            job_id = str(raw_job_id or job_seq_no or job_hash(title, apply_url))
            if not job_id or job_id in seen_ids:
                continue
            seen_ids.add(job_id)

            detail_url = ""
            raw_jd = ""
            for candidate in _job_detail_url_candidates(
                search_url,
                job_seq_no=job_seq_no,
                job_id=raw_job_id,
                title=title,
            ):
                candidate_jd = _fetch_jd(candidate, referer=url)
                if not candidate_jd:
                    continue
                # Prefer fuller descriptions when multiple URL patterns resolve.
                if len(candidate_jd) > len(raw_jd):
                    raw_jd = candidate_jd
                    detail_url = candidate
                # Good-enough full JD found; avoid extra fetch attempts.
                if len(raw_jd) >= 1200:
                    break

            jobs.append(
                {
                    "job_id": job_id,
                    "title": title,
                    "job_url": apply_url or detail_url,
                    "source_api_url": url,
                    "business_unit": item.get("category") or "",
                    "raw_jd_text": raw_jd or strip_html(item.get("descriptionTeaser") or ""),
                    "location_city": location or "India",
                    "locations": [location] if location else [],
                    "date_posted": item.get("postedDate") or "",
                    "source_platform": "PhenomSSR",
                    "industry": portal.get("industry", ""),
                }
            )

            if len(jobs) >= cap:
                break

        if len(jobs) >= cap:
            break

        next_url = _extract_next_url(html)
        if not next_url:
            break
        url = next_url

    _log.info(f"    {len(jobs)} India jobs fetched via Phenom SSR ({company})")
    return jobs
