from __future__ import annotations

"""Cognizant careers XML feed provider.

The India careers page exposes a public XML feed with full descriptions:
https://careers.cognizant.com/india-en/jobs/xml/?rss=true
"""

import logging
import xml.etree.ElementTree as ET

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "application/xml,text/xml,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


class CognizantXMLProvider:
    key = "cognizant_xml"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        endpoint = portal.get("endpoint", "").strip()
        if not endpoint:
            return ProviderResult.error(ScrapeReason.CONFIG_ERROR, "missing_cognizant_xml_endpoint")
        try:
            resp = requests.get(endpoint, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except Exception as exc:
            _log.error(f"    [ERROR] Cognizant XML fetch failed: {exc}")
            return ProviderResult.error(ScrapeReason.API_BLOCKED, "cognizant_xml_fetch_failed")

        try:
            jobs = parse_cognizant_xml(resp.text, portal)
        except Exception as exc:
            _log.error(f"    [ERROR] Cognizant XML parse failed: {exc}")
            return ProviderResult.error(ScrapeReason.PARSE_ERROR, "cognizant_xml_parse_failed")

        if max_jobs:
            jobs = jobs[:max_jobs]
        _log.info(f"    {len(jobs)} India jobs via Cognizant XML")
        return ProviderResult.success(jobs)


def _text(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    return (child.text or "").strip() if child is not None else ""


def _clean_text(value: str) -> str:
    value = value or ""
    # Some feed entries contain mojibake for punctuation. Repair when possible.
    if "â" in value:
        try:
            value = value.encode("latin1").decode("utf-8")
        except Exception:
            pass
    return value.strip()


def parse_cognizant_xml(xml_text: str, portal: Portal) -> list[dict]:
    root = ET.fromstring(xml_text)
    india_only = portal.get("india_only", True)
    jobs: list[dict] = []
    seen: set[str] = set()

    for item in root.findall("job"):
        title = _clean_text(_text(item, "title"))
        if not title:
            continue

        jid = _text(item, "requisitionid") or _text(item, "referencenumber") or _text(item, "apijobid")
        job_url = _text(item, "url")
        city = _clean_text(_text(item, "city"))
        state = _clean_text(_text(item, "state"))
        country = _clean_text(_text(item, "country"))
        location = ", ".join([part for part in (city, state, country) if part])
        if india_only and not is_india(location):
            continue

        jid = jid or job_hash(title, job_url)
        if jid in seen:
            continue
        seen.add(jid)

        jobs.append(
            {
                "job_id": jid,
                "title": title,
                "job_url": job_url,
                "source_api_url": portal.get("endpoint", ""),
                "business_unit": _clean_text(_text(item, "category")),
                "raw_jd_text": strip_html(_clean_text(_text(item, "description"))),
                "location_city": location or "India",
                "date_posted": _text(item, "date") or _text(item, "lastactivitydate"),
                "source_platform": "CognizantXML",
                "industry": portal.get("industry", ""),
            }
        )

    return jobs
