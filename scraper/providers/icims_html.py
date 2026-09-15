from __future__ import annotations
from job_cap import job_limit

import logging
import re
from html import unescape as _unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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


class IcimsHTMLProvider:
    """Classic iCIMS iframe listings with server-rendered job cards."""

    key = "icims_html"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        try:
            r = requests.get(_iframe_url(portal["endpoint"]), headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
        except Exception as e:
            _log.error(f"    [ERROR] iCIMS HTML {portal['company']}: {e}")
            return ProviderResult.error(ScrapeReason.API_BLOCKED)

        return ProviderResult.success(parse_icims_html_listing(r.text, portal, max_jobs=max_jobs))


def _iframe_url(url: str) -> str:
    parts = urlsplit(url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    q["in_iframe"] = "1"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q, doseq=True), parts.fragment))


def _field_map(card) -> dict[str, str]:
    fields: dict[str, str] = {}
    for tag in card.select(".iCIMS_JobHeaderTag"):
        key_node = tag.select_one(".iCIMS_JobHeaderField")
        value_node = tag.select_one(".iCIMS_JobHeaderData")
        if not key_node or not value_node:
            continue
        key = strip_html(_unescape(key_node.get_text(" ", strip=True)))
        value = strip_html(_unescape(value_node.decode_contents()))
        if key:
            fields[key] = value
    return fields


def _card_location(card) -> str:
    header = card.select_one(".header.left")
    if not header:
        return ""
    bits = [
        strip_html(_unescape(node.get_text(" ", strip=True)))
        for node in header.find_all("span")
        if "field-label" not in (node.get("class") or [])
    ]
    return " ".join(bit for bit in bits if bit).strip()


def parse_icims_html_listing(listing_html: str, portal: Portal, max_jobs: int | None = None) -> list[dict]:
    soup = BeautifulSoup(listing_html, "html.parser")
    jobs: list[dict] = []
    seen: set[str] = set()
    cap = job_limit(max_jobs)

    for card in soup.select("li.iCIMS_JobCardItem"):
        link = card.select_one(".title a[href]") or card.select_one("a.iCIMS_Anchor[href]")
        if not link:
            continue
        href = (link.get("href") or "").strip()
        title_node = link.select_one("h3")
        title = strip_html(_unescape(title_node.get_text(" ", strip=True) if title_node else link.get_text(" ", strip=True)))
        if not title:
            continue

        loc = _card_location(card)
        if portal.get("india_only", True) and not is_india(loc):
            continue

        fields = _field_map(card)
        jid = fields.get("Job ID") or ""
        if not jid:
            m = re.search(r"/jobs/(\d+)/", href)
            jid = m.group(1) if m else job_hash(title, href)
        if jid in seen:
            continue
        seen.add(jid)

        raw_jd = fields.get("Overview") or ""
        jobs.append({
            "job_id": jid,
            "title": title,
            "job_url": href,
            "source_api_url": _iframe_url(portal.get("endpoint", "")),
            "business_unit": fields.get("Category"),
            "raw_jd_text": raw_jd,
            "location_city": loc,
            "date_posted": "",
            "source_platform": "iCIMS",
            "industry": portal.get("industry", ""),
        })
        if len(jobs) >= cap:
            break

    return jobs
