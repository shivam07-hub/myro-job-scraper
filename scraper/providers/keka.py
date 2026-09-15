"""Keka Hire public career-board provider."""

from __future__ import annotations

import logging

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, strip_html

_log = logging.getLogger("mirror")
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


class KekaProvider:
    key = "keka"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        endpoint = str(portal.get("endpoint") or "").strip()
        if not endpoint.startswith("http"):
            return ProviderResult.error(ScrapeReason.CONFIG_ERROR, "bad_keka_endpoint")

        try:
            response = requests.get(endpoint, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout as exc:
            return ProviderResult.error(ScrapeReason.TIMEOUT, str(exc))
        except (requests.RequestException, ValueError, TypeError) as exc:
            _log.error("    [ERROR] Keka %s: %s", portal.get("company"), exc)
            return ProviderResult.error(ScrapeReason.API_BLOCKED, str(exc))

        if not isinstance(payload, list):
            return ProviderResult.error(ScrapeReason.PARSE_ERROR, "keka_payload_not_a_list")

        jobs: list[dict] = []
        seen: set[str] = set()
        careers_url = str(portal.get("careers_url") or endpoint).rstrip("/")
        if careers_url.endswith("/api/jobs/default/active"):
            careers_url = careers_url.removesuffix("/api/jobs/default/active")

        for item in payload:
            if not isinstance(item, dict):
                continue
            job_id = str(item.get("id") or item.get("jobNumber") or "").strip()
            title = str(item.get("title") or "").strip()
            if not job_id or not title or job_id in seen:
                continue

            locations = item.get("jobLocations") or []
            location_labels: list[str] = []
            for location in locations:
                if not isinstance(location, dict):
                    continue
                label = ", ".join(
                    dict.fromkeys(
                        str(location.get(key) or "").strip()
                        for key in ("city", "state", "countryName")
                        if str(location.get(key) or "").strip()
                    )
                )
                if label:
                    location_labels.append(label)

            location_text = " | ".join(dict.fromkeys(location_labels))
            if portal.get("india_only", True) and not is_india(location_text):
                continue

            seen.add(job_id)
            jobs.append({
                "job_id": job_id,
                "title": title,
                "job_url": f"{careers_url}/jobdetails/{job_id}",
                "source_api_url": endpoint,
                "business_unit": item.get("departmentName"),
                "raw_jd_text": strip_html(str(item.get("description") or "")),
                "location_city": location_text,
                "locations": location_labels,
                "date_posted": item.get("publishedOn"),
                "source_platform": "Keka Hire",
                "industry": portal.get("industry", ""),
            })
            if max_jobs and len(jobs) >= max_jobs:
                break

        return ProviderResult.success(jobs)
