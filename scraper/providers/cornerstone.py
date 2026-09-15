from __future__ import annotations
from job_cap import job_limit

import json
import logging
import re
from urllib.parse import parse_qs, urlsplit

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json",
    "Accept-Language": "en-US,en;q=0.9",
}


def _location_text(location: dict) -> str:
    country = str(location.get("country") or "").strip()
    if country.lower() == "in":
        country = "India"
    parts = [
        str(location.get("city") or "").strip(),
        str(location.get("state") or "").strip(),
        country,
    ]
    return ", ".join(part for part in parts if part)


def parse_cornerstone_search_payload(payload: dict, portal: Portal) -> list[dict]:
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    items = data.get("requisitions", []) if isinstance(data, dict) else []
    out: list[dict] = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        locations = item.get("locations") or []
        location_texts = [
            _location_text(location)
            for location in locations
            if isinstance(location, dict)
        ]
        if portal.get("india_only", True):
            india_locations = [
                location
                for location in location_texts
                if "india" in location.lower()
            ]
            if not india_locations:
                continue
            location_texts = india_locations
        requisition_id = str(item.get("requisitionId") or "").strip()
        title = str(item.get("displayJobTitle") or "").strip()
        if not requisition_id or not title:
            continue
        base = (portal.get("endpoint") or "").split("/home", 1)[0]
        query_corp = parse_qs(urlsplit(portal.get("endpoint", "")).query).get("c", [""])[0]
        corp = str(portal.get("cornerstone_corp") or query_corp).strip()
        query = f"?c={corp}" if corp else ""
        out.append({
            "job_id": requisition_id,
            "title": title,
            "job_url": f"{base}/home/requisition/{requisition_id}{query}",
            "source_api_url": portal.get("endpoint", ""),
            "business_unit": None,
            "raw_jd_text": "",
            "location_city": "; ".join(location_texts),
            "date_posted": item.get("postingEffectiveDate"),
            "source_platform": "Cornerstone OnDemand",
            "industry": portal.get("industry", ""),
            "_cornerstone_requisition_id": requisition_id,
        })
    return out


def merge_cornerstone_detail(job: dict, payload: dict) -> dict:
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        return job
    merged = dict(job)
    reference = str(data.get("ref") or "").strip()
    if reference:
        merged["job_id"] = reference
    title = str(data.get("displayTitle") or "").strip()
    if title:
        merged["title"] = title
    description = strip_html(str(data.get("externalDescription") or ""))
    if description:
        merged["raw_jd_text"] = description
    locations = [data.get("primaryLocation"), *(data.get("additionalLocations") or [])]
    location_texts = [
        _location_text(location)
        for location in locations
        if isinstance(location, dict)
    ]
    if location_texts:
        merged["location_city"] = "; ".join(dict.fromkeys(location_texts))
    merged["date_posted"] = data.get("openDate") or merged.get("date_posted")
    merged.pop("_cornerstone_requisition_id", None)
    return merged


def _bootstrap_context(page_html: str) -> dict:
    match = re.search(r"csod\.context\s*=\s*(\{.*?\});", page_html, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return {}


class CornerstoneProvider:
    key = "cornerstone"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        endpoint = (portal.get("endpoint") or "").strip()
        site_match = re.search(r"/careersite/(\d+)", endpoint, re.IGNORECASE)
        if not endpoint.startswith("http") or not site_match:
            return ProviderResult.error(ScrapeReason.CONFIG_ERROR, "bad_endpoint")

        session = requests.Session()
        session.headers.update(_HEADERS)
        try:
            page = session.get(endpoint, timeout=REQUEST_TIMEOUT)
            page.raise_for_status()
            context = _bootstrap_context(page.text)
            token = str(context.get("token") or "")
            culture_id = context.get("cultureID")
            if not token or culture_id is None:
                return ProviderResult.error(ScrapeReason.PARSE_ERROR, "missing_csod_context")

            origin = f"{urlsplit(endpoint).scheme}://{urlsplit(endpoint).netloc}"
            site_id = int(site_match.group(1))
            cap = job_limit(max_jobs)
            page_size = min(cap, 100)
            search_payload = {
                "careerSiteId": site_id,
                "careerSitePageId": site_id,
                "pageNumber": 1,
                "pageSize": page_size,
                "cultureId": culture_id,
                "searchText": "",
                "cultureName": context.get("cultureName") or "en-US",
                "states": [],
                "countryCodes": ["in"] if portal.get("india_only", True) else [],
                "cities": [],
                "placeID": "",
                "radius": None,
                "postingsWithinDays": None,
                "customFieldCheckboxKeys": [],
                "customFieldDropdowns": [],
                "customFieldRadios": [],
            }
            api_headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Referer": endpoint,
            }
            jobs: list[dict] = []
            page_number = 1
            while len(jobs) < cap:
                search_payload["pageNumber"] = page_number
                response = session.post(
                    f"{origin}/services/x/career-site/v1/search",
                    json=search_payload,
                    headers=api_headers,
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                payload = response.json()
                page_jobs = parse_cornerstone_search_payload(payload, portal)
                jobs.extend(page_jobs)
                data = payload.get("data", {}) if isinstance(payload, dict) else {}
                requisitions = data.get("requisitions", []) if isinstance(data, dict) else []
                total_count = int(data.get("totalCount") or 0) if isinstance(data, dict) else 0
                if not requisitions or page_number * page_size >= total_count:
                    break
                page_number += 1

            detailed: list[dict] = []
            for job in jobs[:cap]:
                requisition_id = job.get("_cornerstone_requisition_id")
                detail = session.get(
                    (
                        f"{origin}/services/x/job-requisition/v2/requisitions/"
                        f"{requisition_id}/jobDetails?cultureId={culture_id}"
                    ),
                    headers=api_headers,
                    timeout=REQUEST_TIMEOUT,
                )
                detail.raise_for_status()
                detailed.append(merge_cornerstone_detail(job, detail.json()))
        except requests.Timeout as exc:
            return ProviderResult.error(ScrapeReason.TIMEOUT, str(exc))
        except Exception as exc:
            _log.warning("    [Cornerstone] request failed: %s", exc)
            return ProviderResult.error(ScrapeReason.API_BLOCKED, str(exc))

        return ProviderResult.success(detailed)
