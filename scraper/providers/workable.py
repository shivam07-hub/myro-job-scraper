"""Workable public job-board provider.

Workable exposes a public account listing API and a per-shortcode detail API.
The detail request is required: listing rows do not contain a job description.
Any torn detail pass is returned as PARTIAL so publication remains fail-closed.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, strip_html

_log = logging.getLogger("mirror")
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
}


def _account_slug(endpoint: str) -> str:
    api_match = re.search(r"/accounts/([^/]+)/jobs", endpoint)
    if api_match:
        return api_match.group(1)
    parts = [part for part in urlsplit(endpoint).path.split("/") if part]
    return parts[0] if parts else ""


class WorkableProvider:
    key = "workable"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        endpoint = (portal.get("endpoint") or "").strip()
        slug = str(portal.get("workable_account") or _account_slug(endpoint)).strip()
        if not slug:
            return ProviderResult.error(ScrapeReason.CONFIG_ERROR, "missing_workable_account")

        list_url = f"https://apply.workable.com/api/v3/accounts/{slug}/jobs"
        try:
            response = requests.post(
                list_url,
                json={},
                headers={**_HEADERS, "Content-Type": "application/json", "Referer": endpoint},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            _log.error("    [ERROR] Workable %s listing: %s", portal.get("company", ""), exc)
            return ProviderResult.error(ScrapeReason.API_BLOCKED, str(exc))

        candidates = []
        for item in payload.get("results") or []:
            location = item.get("location") or {}
            location_text = ", ".join(
                value for value in (location.get("city") or "", location.get("region") or "", location.get("country") or "") if value
            )
            if item.get("state") != "published" or item.get("isInternal"):
                continue
            if location.get("countryCode") != "IN" and not is_india(location_text):
                continue
            candidates.append(item)

        cap = max_jobs or 2000
        jobs: list[dict] = []
        failed_details: list[str] = []
        for item in candidates[:cap]:
            shortcode = str(item.get("shortcode") or "").strip()
            if not shortcode:
                failed_details.append("missing_shortcode")
                continue
            detail_url = f"https://apply.workable.com/api/v2/accounts/{slug}/jobs/{shortcode}"
            try:
                detail_response = requests.get(
                    detail_url,
                    headers={**_HEADERS, "Referer": endpoint},
                    timeout=REQUEST_TIMEOUT,
                )
                detail_response.raise_for_status()
                detail = detail_response.json()
            except Exception as exc:
                failed_details.append(f"{shortcode}: {exc}")
                continue

            location = detail.get("location") or item.get("location") or {}
            location_text = ", ".join(
                value for value in (location.get("city") or "", location.get("region") or "", location.get("country") or "") if value
            )
            departments = detail.get("department") or item.get("department") or []
            department = departments[0] if departments and isinstance(departments[0], str) else ""
            jobs.append(
                {
                    "job_id": str(detail.get("id") or item.get("id") or shortcode),
                    "title": (detail.get("title") or item.get("title") or "").strip(),
                    "job_url": f"https://apply.workable.com/{slug}/j/{shortcode}/",
                    "source_api_url": detail_url,
                    "business_unit": department,
                    "raw_jd_text": strip_html(detail.get("description") or ""),
                    "location_city": location_text,
                    "date_posted": detail.get("published") or item.get("published") or "",
                    "work_mode": detail.get("workplace") or item.get("workplace") or "",
                    "source_platform": "Workable",
                    "industry": portal.get("industry", ""),
                }
            )

        if failed_details:
            return ProviderResult.partial(
                jobs,
                f"workable_detail_failures={len(failed_details)}; first={failed_details[0]}",
            )
        _log.info(
            "    %s India jobs via Workable (%s); listing total=%s",
            len(jobs),
            portal.get("company", ""),
            payload.get("total", 0),
        )
        return ProviderResult.success(jobs)
