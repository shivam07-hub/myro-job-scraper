"""Yubi's public careers page plus Zoho Recruit detail pages.

The Zoho board's hidden ``jobs`` payload contains historical records that are
not all visible on Yubi's official careers page.  The official page is therefore
the listing source of truth; Zoho is used only to fetch each linked full JD.
"""

from __future__ import annotations

import html
import logging
import re

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from providers.zoho_recruit import _parse_detail_job
from schema import Portal
from utils import is_india, strip_html

_log = logging.getLogger("mirror")
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}
_LINK_RE = re.compile(
    r"https://go-yubi\.zohorecruit\.in/jobs/(?:Careers|careers)/(\d+)/([^\"'<> ]+)",
    re.IGNORECASE,
)


def extract_yubi_links(page_html: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    seen_ids: set[str] = set()
    for match in _LINK_RE.finditer(page_html):
        job_id = match.group(1)
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)
        links.append((job_id, html.unescape(match.group(0))))
    return links


class YubiCareersProvider:
    key = "yubi_careers"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        endpoint = (portal.get("endpoint") or "").strip()
        if not endpoint.startswith("http"):
            return ProviderResult.error(ScrapeReason.CONFIG_ERROR, "bad_yubi_endpoint")
        try:
            listing_response = requests.get(endpoint, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            listing_response.raise_for_status()
        except Exception as exc:
            return ProviderResult.error(ScrapeReason.API_BLOCKED, str(exc))

        links = extract_yubi_links(listing_response.text)
        if not links:
            return ProviderResult.error(ScrapeReason.PARSE_ERROR, "no_official_yubi_job_links")

        cap = max_jobs or 2000
        jobs: list[dict] = []
        failures: list[str] = []
        stale_links: list[str] = []
        for expected_id, job_url in links[:cap]:
            try:
                detail_response = requests.get(
                    job_url,
                    headers={**_HEADERS, "Referer": endpoint},
                    timeout=REQUEST_TIMEOUT,
                )
                detail_response.raise_for_status()
                detail = _parse_detail_job(detail_response.text)
            except Exception as exc:
                failures.append(f"{expected_id}: {exc}")
                continue
            if not detail or not detail.get("Job_Description"):
                # Yubi's official page can briefly retain links after Zoho has
                # withdrawn the record. Zoho answers those with a tiny generic
                # 200 page titled only "Yubi". That is explicit inactive-row
                # evidence, not a torn fetch; omit it from the current snapshot.
                if len(detail_response.text) < 5_000 and re.search(
                    r"<title>\s*Yubi\s*</title>", detail_response.text, re.IGNORECASE
                ):
                    stale_links.append(expected_id)
                    continue
                failures.append(f"{expected_id}: missing_embedded_detail")
                continue

            job_id = str(detail.get("id") or expected_id).strip()
            if job_id != expected_id:
                failures.append(f"{expected_id}: detail_id_mismatch_{job_id}")
                continue
            title = (detail.get("Posting_Title") or detail.get("Job_Opening_Name") or "").strip()
            location = ", ".join(
                value
                for value in (detail.get("City") or "", detail.get("State") or "", detail.get("Country") or "")
                if value
            )
            if not title or not is_india(location):
                failures.append(f"{expected_id}: missing_title_or_india_location")
                continue
            jobs.append(
                {
                    "job_id": job_id,
                    "title": title,
                    "job_url": job_url,
                    "source_api_url": endpoint,
                    "business_unit": detail.get("Company") or "",
                    "raw_jd_text": strip_html(detail.get("Job_Description") or ""),
                    "location_city": location,
                    "date_posted": detail.get("Date_Opened") or "",
                    "source_platform": "ZohoRecruit",
                    "industry": portal.get("industry", ""),
                }
            )

        if failures:
            return ProviderResult.partial(
                jobs,
                f"yubi_detail_failures={len(failures)}; first={failures[0]}",
            )
        if stale_links:
            _log.warning("    omitted %s withdrawn Yubi links still present upstream", len(stale_links))
        _log.info("    %s current India jobs via Yubi official links", len(jobs))
        return ProviderResult.success(jobs)
