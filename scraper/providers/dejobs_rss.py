from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


class DejobsRSSProvider:
    key = "dejobs_rss"

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
            _log.error(f"    [ERROR] DirectEmployers RSS {portal['company']}: {e}")
            return ProviderResult.error(ScrapeReason.API_BLOCKED)

        return ProviderResult.success(parse_dejobs_rss(r.text, portal, max_jobs=max_jobs))


def _prefix_location(title: str) -> str:
    m = re.match(r"\((?:IND|IN)-([^)]+)\)", title.strip(), flags=re.IGNORECASE)
    if not m:
        return ""
    city = re.sub(r"\s+", " ", m.group(1)).strip()
    return f"{city}, India" if city else "India"


def _clean_title(title: str) -> str:
    return re.sub(r"^\((?:IND|IN)-[^)]+\)\s*", "", title.strip(), flags=re.IGNORECASE)


def parse_dejobs_rss(rss_text: str, portal: Portal, max_jobs: int | None = None) -> list[dict]:
    try:
        root = ET.fromstring(rss_text)
    except ET.ParseError:
        return []

    out: list[dict] = []
    seen: set[str] = set()
    for item in root.findall("./channel/item"):
        raw_title = item.findtext("title") or ""
        title = _clean_title(raw_title)
        link = item.findtext("link") or item.findtext("guid") or ""
        loc = _prefix_location(raw_title)
        desc = strip_html(item.findtext("description") or "")
        if portal.get("india_only", True) and not is_india(" ".join([raw_title, loc, desc])):
            continue
        jid = (item.findtext("guid") or link or job_hash(title, link)).strip()
        if jid in seen:
            continue
        seen.add(jid)
        out.append({
            "job_id": jid,
            "title": title,
            "job_url": link,
            "source_api_url": portal.get("endpoint", ""),
            "business_unit": None,
            "raw_jd_text": desc,
            "location_city": loc or "India",
            "date_posted": item.findtext("pubDate") or "",
            "source_platform": "DirectEmployers",
            "industry": portal.get("industry", ""),
        })
        if max_jobs and len(out) >= max_jobs:
            break
    return out
