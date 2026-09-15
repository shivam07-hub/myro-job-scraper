from __future__ import annotations

"""Darwinbox ATS provider.

API endpoint: POST https://{tenant}.darwinbox.in/ms/candidateapi/job/alljobs?companyId=main
Field map: data[].id, data[].title, data[].jd (HTML-escaped), data[].locations, data[].country
Total count: top-level job_counts field.

CF Turnstile requirement:
  Darwinbox is behind Cloudflare Bot Management. Direct requests 403 without a valid
  __cf_bm cookie. The cookie is IP+UA bound and expires in 30 minutes.

  To enable: set DARWINBOX_CF_BM and DARWINBOX_SESSION env vars (from browser devtools).
  Fallback: if cookies absent or 403, provider returns API_BLOCKED -> Firecrawl fallback.
"""

import html as html_lib
import logging
import os

import requests

from config import REQUEST_TIMEOUT
from providers.base import FALLBACK_FIRECRAWL_EXTRACT, ProviderResult, ScrapeReason
from schema import Portal
from utils import strip_html

_log = logging.getLogger("mirror")
_PAGE_SIZE = 50


def _cf_cookies() -> dict[str, str] | None:
    cf_bm = os.environ.get("DARWINBOX_CF_BM", "").strip()
    session = os.environ.get("DARWINBOX_SESSION", "").strip()
    if cf_bm and session:
        return {"__cf_bm": cf_bm, "session": session}
    return None


class DarwinboxProvider:
    key = "darwinbox"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        cookies = _cf_cookies()
        if not cookies:
            _log.warning(f"    [Darwinbox] {portal['company']}: no CF cookies — set DARWINBOX_CF_BM + DARWINBOX_SESSION")
            return ProviderResult.fallback(
                policy=FALLBACK_FIRECRAWL_EXTRACT,
                reason="darwinbox_no_cf_cookies",
            )

        jobs = _scrape_darwinbox(portal, cookies, max_jobs=max_jobs)
        if jobs is None:
            _log.warning(f"    [Darwinbox] {portal['company']}: CF blocked — cookies expired?")
            return ProviderResult.fallback(
                policy=FALLBACK_FIRECRAWL_EXTRACT,
                reason="darwinbox_cf_blocked",
            )
        return ProviderResult.success(jobs)


def _scrape_darwinbox(
    portal: Portal,
    cookies: dict[str, str],
    max_jobs: int | None = None,
) -> list[dict] | None:
    from urllib.parse import urlparse

    careers_url = portal.get("careers_url", portal.get("endpoint", ""))
    parsed = urlparse(careers_url)
    api_url = f"{parsed.scheme}://{parsed.netloc}/ms/candidateapi/job/alljobs?companyId=main"

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": f"{parsed.scheme}://{parsed.netloc}",
        "Referer": careers_url,
    }

    jobs: list[dict] = []
    page = 1

    while True:
        payload = {"companyId": "main", "page": page, "sort_option": "new", "limit": _PAGE_SIZE}
        try:
            r = requests.post(api_url, json=payload, headers=headers, cookies=cookies, timeout=REQUEST_TIMEOUT)
            if r.status_code in (403, 429):
                return None  # CF blocked
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            _log.error(f"    [ERROR] Darwinbox {portal['company']} page={page}: {e}")
            return jobs or None

        if data.get("status") != "success":
            break

        items = data.get("data", [])
        if not items:
            break

        for j in items:
            title = (j.get("title") or j.get("designation_name") or "").strip()
            if not title:
                continue

            loc = j.get("locations") or j.get("officelocations_area") or j.get("country") or ""
            raw_jd = strip_html(html_lib.unescape(j.get("jd") or ""))
            jid = str(j.get("id") or j.get("_id") or "")
            apply_url = f"{parsed.scheme}://{parsed.netloc}/ms/candidatev2/main/careers/jobDetails/{jid}"

            jobs.append({
                "job_id":          jid,
                "title":           title,
                "job_url":         apply_url,
                "source_api_url":  api_url,
                "business_unit":   j.get("department_name_only") or j.get("department_name"),
                "raw_jd_text":     raw_jd,
                "location_city":   loc,
                "date_posted":     j.get("posted_on"),
                "source_platform": "Darwinbox",
                "industry":        portal.get("industry", ""),
            })

            if max_jobs and len(jobs) >= max_jobs:
                return jobs

        total = data.get("job_counts", 0)
        if len(jobs) >= total or len(items) < _PAGE_SIZE:
            break
        page += 1

    _log.info(f"    {len(jobs)} jobs fetched via Darwinbox ({portal['company']})")
    return jobs
