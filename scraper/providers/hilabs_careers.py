from __future__ import annotations

import json
import logging
import re

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_RSC_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,"(.*)"\]\)', re.DOTALL)


class HiLabsCareersProvider:
    key = "hilabs_careers"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_hilabs(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def parse_hilabs_html(html: str, portal: Portal) -> list[dict]:
    payload = _extract_jobs_payload(html)
    if not payload:
        return []

    groups = payload.get("groupedByPlaceAndDepartments") or {}
    places = ["india"] if portal.get("india_only", True) else list(groups.keys())
    jobs: list[dict] = []
    seen: set[str] = set()

    for place in places:
        by_department = groups.get(place) or {}
        items = by_department.get("All Job Listing") or _flatten_department_lists(by_department)
        for item in items:
            title = (item.get("Job_Title") or "").strip()
            location = (item.get("Job_Location") or "").strip()
            if not title:
                continue
            if portal.get("india_only", True) and not is_india(location):
                continue

            document_id = str(item.get("documentId") or "").strip()
            job_id = str(item.get("Job_Id") or "").strip() or (f"hilabs-{document_id}" if document_id else "")
            if not job_id or job_id in seen:
                continue
            seen.add(job_id)

            jobs.append(
                {
                    "job_id": job_id,
                    "title": title,
                    "job_url": _job_url(portal.get("endpoint", ""), title, document_id),
                    "source_api_url": portal.get("endpoint", ""),
                    "business_unit": (item.get("Category") or "").strip(),
                    "raw_jd_text": _build_job_description(item),
                    "location_city": location,
                    "date_posted": _date_only(item.get("updatedAt") or item.get("publishedAt") or item.get("createdAt") or ""),
                    "source_platform": "HiLabsCareers",
                    "industry": portal.get("industry", ""),
                }
            )
    return jobs


def _scrape_hilabs(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    url = portal.get("endpoint", "")
    try:
        response = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except Exception as exc:
        _log.error(f"    [ERROR] HiLabs careers fetch failed: {exc}")
        return None

    jobs = parse_hilabs_html(response.text, portal)
    if max_jobs:
        jobs = jobs[:max_jobs]

    _log.info(f"    {len(jobs)} jobs via HiLabs careers payload")
    return jobs


def _extract_jobs_payload(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        text = script.string or script.get_text()
        if "groupedByPlaceAndDepartments" not in text or "self.__next_f.push" not in text:
            continue
        match = _RSC_PUSH_RE.search(text)
        if not match:
            continue
        decoded = json.loads(f'"{match.group(1)}"')
        _, _, raw = decoded.partition(":")
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        found = _find_grouped_payload(payload)
        if found:
            return found
    return {}


def _find_grouped_payload(node):
    if isinstance(node, dict):
        if "groupedByPlaceAndDepartments" in node:
            return node
        for value in node.values():
            found = _find_grouped_payload(value)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_grouped_payload(value)
            if found:
                return found
    return None


def _flatten_department_lists(grouped: dict) -> list[dict]:
    out: list[dict] = []
    for value in grouped.values():
        if isinstance(value, list):
            out.extend(item for item in value if isinstance(item, dict))
    return out


def _build_job_description(item: dict) -> str:
    parts: list[str] = []
    intro = strip_html(item.get("Add_description_to_Hilabs_Team") or "").strip()
    if intro:
        parts.append(intro)

    for section in item.get("Job_Description") or []:
        heading = strip_html(section.get("Heading") or "").strip()
        bullets: list[str] = []
        for block in section.get("Add_bullet_points_with_heading") or []:
            block_heading = strip_html(block.get("Heading") or "").strip()
            if block_heading:
                bullets.append(block_heading)
            for point in block.get("Points") or []:
                text = strip_html(point.get("Point") or "").strip()
                if text:
                    bullets.append(text)
        if heading:
            parts.append(heading)
        if bullets:
            parts.append("\n".join(bullets))

    return "\n\n".join(part for part in parts if part).strip()


def _slugify_title(title: str) -> str:
    return title.replace("/", "").replace(" ", "-")


def _job_url(endpoint: str, title: str, document_id: str) -> str:
    base = endpoint.split("?", 1)[0].rstrip("/")
    if not document_id:
        return base
    return f"{base}/{_slugify_title(title)}/{document_id}"


def _date_only(value: str) -> str:
    return value[:10] if value else ""
