"""BNP Paribas India job offers (group.bnpparibas, applications on bwelcome.hr.bnpparibas).

The group careers site lists every offer but answers plain requests with an
Akamai 403. The Avature applicant site behind it has its search and feed
switched off, though its job pages are plain HTML.

So one Firecrawl cloud render (1 credit, cached 7 days) opens the India list and
runs ``bnp_paribas_listing.js`` in the page. The script reads every list page and
every offer page, then writes each offer's Avature job id into
``<pre id="myro-bnp">``. The JDs are then read from Avature over ordinary HTTP.
On 2026-11-06: 340 offers, 34 list pages, 56 s inside the render.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import strip_html

_log = logging.getLogger("mirror")

_LISTING_SCRIPT = Path(__file__).with_name("bnp_paribas_listing.js").read_text(encoding="utf-8")
_RESULT_ID = "myro-bnp"
_CARD = 'a.card-link[href*="/careers/job-offer/"]'
_JOB_URL = "https://bwelcome.hr.bnpparibas/en_US/externalcareers/JobDetails?jobId={job_id}"
_RENDER_TIMEOUT_MS = 180_000
# Avature takes ~3 s a page; four at a time read 340 JDs in about four minutes.
_WORKERS = 4
_FACTS = ("Contract type", "Professional Family", "Required experience in the field")
_FAMILY_CODE_RE = re.compile(r"^F\d+\s*-\s*")
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def listing_actions() -> list[dict]:
    return [
        {"type": "wait", "selector": _CARD},
        {"type": "executeJavascript", "script": _LISTING_SCRIPT},
        # The script writes the <pre> only once every list page loaded; without
        # it this wait fails the render, so a partial list is never cached.
        {"type": "wait", "selector": f"#{_RESULT_ID}"},
        {"type": "scrape"},
    ]


def parse_listing(html: str) -> list[dict]:
    node = BeautifulSoup(html or "", "html.parser").find(id=_RESULT_ID)
    if node is None:
        return []
    return list(json.loads(node.get_text()).get("offers") or [])


def parse_job_page(html: str) -> tuple[dict[str, str], str]:
    """The "General Information" fields and the Description of an Avature job page."""
    soup = BeautifulSoup(html or "", "html.parser")
    fields: dict[str, str] = {}
    for field in soup.select(".article__content__view__field"):
        label = field.select_one(".article__content__view__field__label")
        value = field.select_one(".article__content__view__field__value")
        if label and value:
            fields[label.get_text(" ", strip=True)] = value.get_text(" ", strip=True)
    description = ""
    for article in soup.select("article.article--details"):
        heading = article.select_one(".article__header__text__title")
        content = article.select_one(".article__content")
        if heading and content and heading.get_text(strip=True) == "Description":
            description = strip_html(str(content)).strip()
    return fields, description


def jd_text(fields: dict[str, str], description: str) -> str:
    facts = [f"{name}: {fields[name]}" for name in _FACTS if fields.get(name)]
    return "\n".join(facts + ([description] if description else []))


def _job_record(offer: dict, html: str, endpoint: str, portal: Portal) -> dict | None:
    fields, description = parse_job_page(html)
    if not fields:
        # Avature drops the fields once an offer closes.
        return None
    family = fields.get("Professional Family", "")
    return {
        "job_id": offer.get("ref") or fields.get("Ref #") or offer["jobId"],
        "title": offer.get("title") or "",
        "job_url": _JOB_URL.format(job_id=offer["jobId"]),
        "source_api_url": endpoint,
        "business_unit": _FAMILY_CODE_RE.sub("", family) or None,
        "raw_jd_text": jd_text(fields, description),
        "location_city": offer.get("location") or fields.get("City") or "India",
        "date_posted": offer.get("datePosted"),
        "source_platform": "BNP Paribas Careers via Firecrawl Cloud",
        "industry": portal.get("industry", ""),
    }


class BnpParibasProvider:
    key = "bnp_paribas"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        endpoint = (portal.get("endpoint") or "").strip()
        if not endpoint.startswith("http"):
            return ProviderResult.error(ScrapeReason.CONFIG_ERROR, "bad_endpoint")

        import firecrawl_client as fc

        pages = fc.cloud_scrape_action_pages(endpoint, listing_actions(), timeout_ms=_RENDER_TIMEOUT_MS)
        try:
            offers = parse_listing(pages[-1]) if pages else []
        except json.JSONDecodeError as exc:
            return ProviderResult.error(ScrapeReason.PARSE_ERROR, f"bnp_listing_json: {exc}")
        if not offers:
            return ProviderResult.error(ScrapeReason.PARSE_ERROR, "no_bnp_listing")
        resolved = [offer for offer in offers if offer.get("jobId")]
        if len(resolved) < len(offers):
            _log.warning("    [BNP] %d offer pages did not load in the render", len(offers) - len(resolved))
        if max_jobs:
            resolved = resolved[:max_jobs]

        def fetch(offer: dict) -> dict | None:
            url = _JOB_URL.format(job_id=offer["jobId"])
            try:
                response = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
            except requests.RequestException as exc:
                _log.warning("    [BNP] JD %s unavailable: %s", offer["jobId"], exc)
                return None
            return _job_record(offer, response.text, endpoint, portal)

        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            jobs = [job for job in pool.map(fetch, resolved) if job]
        _log.info("    %d BNP Paribas jobs from %d listed", len(jobs), len(offers))
        return ProviderResult.success(jobs)
