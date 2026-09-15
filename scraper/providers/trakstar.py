from __future__ import annotations
from job_cap import job_limit

import logging
import re
from html import unescape as _unescape
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class TrakstarProvider:
    """Trakstar Hire / Recruiterbox server-rendered careers pages."""

    key = "trakstar"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        try:
            r = requests.get(portal["endpoint"], headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
        except Exception as e:
            _log.error(f"    [ERROR] Trakstar listing {portal['company']}: {e}")
            return ProviderResult.error(ScrapeReason.API_BLOCKED)

        jobs = parse_trakstar_listing(r.text, portal, max_jobs=max_jobs)
        return ProviderResult.success(jobs)


def _field_text(node, selector: str) -> str:
    found = node.select_one(selector)
    return strip_html(_unescape(found.get_text(" ", strip=True))) if found else ""


def parse_trakstar_listing(listing_html: str, portal: Portal, max_jobs: int | None = None) -> list[dict]:
    soup = BeautifulSoup(listing_html, "html.parser")
    base_url = portal.get("endpoint", "")
    jobs: list[dict] = []
    seen: set[str] = set()
    cap = job_limit(max_jobs)

    for card in soup.select(".js-careers-page-job-list-item"):
        href = (card.get("data-href") or "").strip()
        link = card.select_one("a[href]")
        if not href and link:
            href = (link.get("href") or "").strip()
        if not href:
            continue

        title = _field_text(card, ".js-job-list-opening-name")
        loc = _field_text(card, ".js-job-list-opening-loc")
        if portal.get("india_only", True) and not is_india(loc):
            continue

        detail_url = urljoin(base_url, href)
        jid = _job_id_from_url(href) or job_hash(title, detail_url)
        if jid in seen:
            continue
        seen.add(jid)

        detail = parse_trakstar_detail(_fetch_detail(detail_url), detail_url) if detail_url else {}
        jobs.append({
            "job_id": jid,
            "title": detail.get("title") or title,
            "job_url": detail_url,
            "source_api_url": base_url,
            "business_unit": detail.get("business_unit") or _field_text(card, ".col-md-4 .rb-text-4"),
            "raw_jd_text": detail.get("raw_jd_text", ""),
            "location_city": detail.get("location_city") or loc,
            "date_posted": "",
            "source_platform": "Trakstar",
            "industry": portal.get("industry", ""),
        })
        if len(jobs) >= cap:
            break
    return jobs


def _job_id_from_url(href: str) -> str:
    m = re.search(r"/jobs/([^/?#]+)/?", href)
    return m.group(1) if m else ""


def _fetch_detail(url: str) -> str:
    try:
        r = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""


def parse_trakstar_detail(detail_html: str, detail_url: str) -> dict:
    soup = BeautifulSoup(detail_html, "html.parser")
    text = soup.get_text("\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]

    title = _field_text(soup, ".js-job-title")
    loc = ""
    business_unit = ""
    for idx, line in enumerate(lines):
        if not title and line == "Back to all openings":
            for candidate in lines[idx + 1:idx + 8]:
                if (
                    candidate.startswith("http")
                    or candidate.lower().startswith("see all")
                    or candidate.lower() in {"website", "careers"}
                ):
                    continue
                title = candidate
                break
        if line == "|" and idx > 0 and idx + 1 < len(lines):
            loc = lines[idx - 1]
            business_unit = lines[idx + 1]
            break
    if not title:
        h1 = soup.find(["h1", "h2", "h3"])
        title = strip_html(_unescape(h1.get_text(" ", strip=True))) if h1 else ""

    start = 0
    for marker in ("Who are we?", "About", "Role", "What will you"):
        for idx, line in enumerate(lines):
            if line.lower().startswith(marker.lower()):
                start = idx
                break
        if start:
            break
    end = len(lines)
    for marker in ("Apply with Linkedin", "Apply with Indeed", "Apply", "Powered by"):
        for idx in range(start or 0, len(lines)):
            if lines[idx] == marker:
                end = idx
                break
        if end != len(lines):
            break

    raw_jd = "\n".join(lines[start:end]).strip() if start else ""
    return {
        "title": title,
        "location_city": loc,
        "business_unit": business_unit,
        "raw_jd_text": raw_jd,
        "job_url": detail_url,
    }
