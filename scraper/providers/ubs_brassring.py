from __future__ import annotations

import html
import json
import logging

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json",
    "Accept-Language": "en-US,en;q=0.9",
}


def _question_map(job: dict) -> dict[str, str]:
    out: dict[str, str] = {}
    for question in job.get("Questions", []):
        if not isinstance(question, dict):
            continue
        name = str(question.get("QuestionName") or "").strip().lower()
        value = question.get("ActualValueFromSolar")
        if value in (None, ""):
            value = question.get("Value")
        if name and value not in (None, ""):
            out[name] = html.unescape(str(value)).strip()
    return out


def _parse_jobs(items: list[dict], portal: Portal) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        questions = _question_map(item)
        location = questions.get("formtext23") or questions.get("location") or ""
        if portal.get("india_only", True) and not is_india(location):
            continue
        title = questions.get("jobtitle", "")
        job_id = questions.get("reqid", "")
        if not title or not job_id or job_id in seen:
            continue
        seen.add(job_id)
        out.append({
            "job_id": job_id,
            "title": title,
            "job_url": html.unescape(str(item.get("Link") or "")).strip(),
            "source_api_url": portal.get("endpoint", ""),
            "business_unit": questions.get("department") or questions.get("formtext21"),
            "raw_jd_text": strip_html(questions.get("jobdescription", "")),
            "location_city": location,
            "date_posted": questions.get("lastupdated"),
            "source_platform": "BrassRing TGNewUI",
            "industry": portal.get("industry", ""),
        })
    return out


def _embedded_search_payload(page_html: str) -> dict:
    soup = BeautifulSoup(page_html, "html.parser")
    node = soup.select_one("#searchResults")
    if not node:
        return {}
    raw = html.unescape(node.get("value") or "")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def parse_ubs_search_html(page_html: str, portal: Portal) -> list[dict]:
    payload = _embedded_search_payload(page_html)
    items = payload.get("HotJobs", {}).get("Job", [])
    return _parse_jobs(items if isinstance(items, list) else [], portal)


def parse_ubs_search_payload(payload: dict, portal: Portal) -> list[dict]:
    items = payload.get("Jobs", {}).get("Job", []) if isinstance(payload, dict) else []
    return _parse_jobs(items if isinstance(items, list) else [], portal)


class UBSBrassRingProvider:
    key = "ubs_brassring"

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
        session = requests.Session()
        session.headers.update(_HEADERS)
        try:
            response = session.get(endpoint, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            token_node = soup.select_one('input[name="__RequestVerificationToken"]')
            cookie_node = soup.select_one("#CookieValue")
            embedded = _embedded_search_payload(response.text)
            if not token_node or not cookie_node or not embedded:
                jobs = parse_ubs_search_html(response.text, portal)
                return ProviderResult.success(jobs[:max_jobs] if max_jobs else jobs)

            payload = {
                "PartnerId": str(portal.get("brassring_partner_id") or "25008"),
                "SiteId": str(portal.get("brassring_site_id") or "5012"),
                "Keyword": "",
                "Location": "India",
                "KeywordCustomSolrFields": embedded.get("KeywordCustomSolrFields"),
                "LocationCustomSolrFields": embedded.get("LocationCustomSolrFields"),
                "TurnOffHttps": False,
                "Latitude": 0,
                "Longitude": 0,
                "FacetFilterFields": {"Facet": []},
                "PowerSearchOptions": {"PowerSearchOption": []},
                "SortType": "",
                "EncryptedSessionValue": cookie_node.get("value") or "",
            }
            search = session.post(
                "https://jobs.ubs.com/TgNewUI/Search/Ajax/PowerSearchJobs",
                json=payload,
                headers={
                    "RFT": token_node.get("value") or "",
                    "Referer": endpoint,
                    "Content-Type": "application/json; charset=utf-8",
                },
                timeout=REQUEST_TIMEOUT,
            )
            search.raise_for_status()
            jobs = parse_ubs_search_payload(search.json(), portal)
        except requests.Timeout as exc:
            return ProviderResult.error(ScrapeReason.TIMEOUT, str(exc))
        except Exception as exc:
            _log.warning("    [UBS BrassRing] request failed: %s", exc)
            return ProviderResult.error(ScrapeReason.API_BLOCKED, str(exc))

        if max_jobs:
            jobs = jobs[:max_jobs]
        return ProviderResult.success(jobs)
