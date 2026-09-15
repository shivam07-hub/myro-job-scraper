from __future__ import annotations

import logging
import re

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, strip_html, job_hash

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_POST_ID_RE = re.compile(r"(\d+)$")
_BODY_POST_RE = re.compile(r"\bpostid-(\d+)\b")


class BlackBrixJobsProvider:
    key = "blackbrix_jobs"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_blackbrix(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def parse_blackbrix_listing_items(html: str, source_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    for card in soup.select(".awsm-job-listing-item"):
        link = card.select_one("a.awsm-job-item[href]")
        title_node = card.select_one(".awsm-job-post-title")
        location_node = card.select_one(".awsm-job-specification-job-location .awsm-job-specification-term")
        if not link or not title_node:
            continue
        href = (link.get("href") or "").strip()
        title = strip_html(title_node.get_text(" ", strip=True))
        location = strip_html(location_node.get_text(" ", strip=True)) if location_node else ""
        card_id = card.get("id") or ""
        tail = card_id.rsplit("-", 1)[-1]
        job_id = tail if tail.isdigit() else (href.rstrip("/").rsplit("/", 1)[-1] or job_hash(title, href))
        items.append(
            {
                "job_id": job_id,
                "title": title,
                "job_url": href,
                "source_api_url": source_url,
                "location_city": location,
            }
        )
    return items


def parse_blackbrix_detail(html: str, detail_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one("body")
    body_classes = " ".join(body.get("class", [])) if body else ""
    body_match = _BODY_POST_RE.search(body_classes)

    title_node = soup.select_one(".wp-block-post-title a") or soup.select_one(".wp-block-post-title")
    title = strip_html(title_node.get_text(" ", strip=True)) if title_node else ""

    location_node = soup.select_one(".awsm-job-specification-job-location .awsm-job-specification-term")
    location = strip_html(location_node.get_text(" ", strip=True)) if location_node else ""

    content_node = soup.select_one(".awsm-job-entry-content")
    raw_jd = strip_html(str(content_node)).strip() if content_node else ""

    category_node = soup.select_one(".awsm-job-specification-job-category .awsm-job-specification-term")
    business_unit = strip_html(category_node.get_text(" ", strip=True)) if category_node else ""
    if not title:
        title = business_unit

    url_tail = detail_url.rstrip("/").rsplit("/", 1)[-1]
    tail_match = _POST_ID_RE.search(url_tail)
    job_id = body_match.group(1) if body_match else (tail_match.group(1) if tail_match else job_hash(title, detail_url))

    return {
        "job_id": job_id,
        "title": title,
        "job_url": detail_url,
        "source_api_url": detail_url,
        "business_unit": business_unit,
        "raw_jd_text": raw_jd,
        "location_city": location,
        "date_posted": "",
        "source_platform": "BlackBrixJobs",
    }


def _scrape_blackbrix(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    url = portal.get("endpoint", "")
    try:
        listing_response = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        listing_response.raise_for_status()
    except Exception as exc:
        _log.error(f"    [ERROR] Black Brix listing fetch failed: {exc}")
        return None

    listing_items = parse_blackbrix_listing_items(listing_response.text, url)
    if max_jobs:
        listing_items = listing_items[:max_jobs]

    jobs: list[dict] = []
    for item in listing_items:
        if portal.get("india_only", True) and not is_india(item.get("location_city", "")):
            continue
        try:
            detail_response = requests.get(item["job_url"], headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            detail_response.raise_for_status()
        except Exception as exc:
            _log.warning(f"    [WARN] Black Brix detail fetch failed {item['job_url']}: {exc}")
            continue
        detail = parse_blackbrix_detail(detail_response.text, item["job_url"])
        detail["industry"] = portal.get("industry", "")
        jobs.append(detail)

    _log.info(f"    {len(jobs)} jobs via Black Brix HTML")
    return jobs
