"""
Zoho Recruit career portal provider.

Targets: ITC Limited (recruitment.itcportal.com/jobs/Careers)

All jobs are SSR-embedded as an HTML-entity-encoded JSON array in the page.
No pagination needed; one GET returns all India jobs.
"""

from __future__ import annotations
from job_cap import job_limit

import html
import json
import logging
import re
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup

from schema import Portal
from providers.base import FALLBACK_FIRECRAWL_EXTRACT, ProviderResult, ScrapeReason

_log = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

_PAGE_ID = "48611000000181149"
_JOBS_ARRAY_START = "[{&#34;Remote_Job&#34;"


def _parse_embedded_jobs(page_html: str) -> list[dict]:
    soup = BeautifulSoup(page_html, "html.parser")
    for node in soup.find_all("input", {"type": "hidden"}):
        value = node.get("value") or ""
        if not value or "Posting_Title" not in value or "Job_Description" not in value:
            continue
        try:
            data = json.loads(html.unescape(value))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            continue

    idx = page_html.find(_JOBS_ARRAY_START)
    if idx < 0:
        idx = page_html.find("[{&#34;")
    if idx < 0:
        return []
    chunk = page_html[idx : idx + 500_000]
    decoded = html.unescape(chunk)
    end = decoded.rfind("}]")
    if end < 0:
        return []
    try:
        return json.loads(decoded[: end + 2])
    except json.JSONDecodeError:
        return []


def _build_apply_url(portal: Portal, job_id: str) -> str:
    page_id = str(portal.get("zoho_page_id") or _PAGE_ID).strip()
    endpoint = (portal.get("endpoint") or "").strip()
    parts = urlsplit(endpoint)
    root = f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else "https://recruitment.itcportal.com"
    return f"{root}/recruit/SingleJobDetail.na?sys_id={job_id}&page_id={page_id}"


class ZohoRecruitProvider:
    key = "zoho_recruit"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        endpoint = (portal.get("endpoint") or "").strip()
        company = portal.get("company", "")
        industry = portal.get("industry", "")

        if not endpoint.startswith("http"):
            _log.error(f"    [ERROR] ZohoRecruit: invalid endpoint for {company}: {endpoint}")
            return ProviderResult.error(ScrapeReason.CONFIG_ERROR, "bad_endpoint")

        try:
            r = requests.get(endpoint, headers=_HEADERS, timeout=30)
        except Exception as e:
            _log.warning(f"    [WARN] ZohoRecruit: fetch failed for {company}: {e}")
            return ProviderResult.error(ScrapeReason.TIMEOUT, str(e))

        if r.status_code != 200:
            _log.warning(f"    [WARN] ZohoRecruit: status={r.status_code} for {company}")
            return ProviderResult.fallback(
                policy=FALLBACK_FIRECRAWL_EXTRACT,
                reason=f"zoho_recruit_status_{r.status_code}",
                portal=portal,
            )

        all_jobs = _parse_embedded_jobs(r.text)
        if not all_jobs:
            _log.warning(f"    [WARN] ZohoRecruit: no embedded jobs found for {company}")
            return ProviderResult.error(ScrapeReason.PARSE_ERROR, "no_embedded_json")

        india_jobs = [j for j in all_jobs if (j.get("Country") or "").strip() == "India"]
        if not india_jobs:
            india_jobs = all_jobs  # India-only portal fallback

        cap = job_limit(max_jobs)
        results = []
        for job in india_jobs[:cap]:
            job_id = str(job.get("id", "")).strip()
            if not job_id:
                continue

            title = (job.get("Posting_Title") or job.get("Job_Opening_Name") or "").strip()
            city = (job.get("City") or "").strip()
            state = (job.get("State") or "").strip()
            country = (job.get("Country") or "India").strip()
            location_raw = ", ".join(p for p in [city, state, country] if p)
            raw_jd = (job.get("Job_Description") or "").strip()

            results.append({
                "job_id": job_id,
                "job_title": title,
                "job_description": raw_jd,
                "company_name": company,
                "industry": industry,
                "location_raw": location_raw,
                "apply_url": _build_apply_url(portal, job_id),
                "source_api_url": endpoint,
            })

        _log.info(f"    [ZohoRecruit] {company}: {len(results)} India jobs")
        return ProviderResult.success(results)
