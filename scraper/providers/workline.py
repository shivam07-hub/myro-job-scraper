from __future__ import annotations

import json
import logging
from urllib.parse import quote, urlsplit

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


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _decode_jobs(payload: dict) -> list[dict]:
    data = payload.get("d", payload)
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        return []
    jobs = data.get("obj1", [])
    if isinstance(jobs, str):
        jobs = json.loads(jobs)
    return jobs if isinstance(jobs, list) else []


def parse_workline_listing_payload(payload: dict, portal: Portal) -> list[dict]:
    root = _origin(portal.get("endpoint", ""))
    out: list[dict] = []
    seen: set[str] = set()
    for item in _decode_jobs(payload):
        if not isinstance(item, dict):
            continue
        location = (
            item.get("City_Name")
            or item.get("Field2")
            or item.get("LOCATIONNAME")
            or ""
        ).strip()
        country = (item.get("Country_Name") or "").strip()
        if portal.get("india_only", True) and not (
            country.lower() == "india" or is_india(f"{location}, {country}")
        ):
            continue
        title = (item.get("Position_Name") or item.get("ExternalJobName") or "").strip()
        track_token = str(item.get("TrackToken") or "").strip()
        search_key = str(item.get("SearchKeyWord") or "").strip()
        job_id = str(item.get("Req_No") or item.get("ERFCode") or track_token).strip()
        if not title or not track_token or not job_id or job_id in seen:
            continue
        seen.add(job_id)
        detail_url = f"{root}/CandidatePortal/{quote(track_token)}/{quote(search_key)}"
        out.append({
            "job_id": job_id,
            "title": title,
            "job_url": detail_url,
            "source_api_url": portal.get("endpoint", ""),
            "business_unit": item.get("FunctionName") or item.get("Field1"),
            "raw_jd_text": "",
            "location_city": location,
            "date_posted": item.get("PublishDate"),
            "source_platform": "Workline HR",
            "industry": portal.get("industry", ""),
        })
    return out


def parse_workline_detail_html(html: str, url: str, portal: Portal) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    container = next(
        (
            node
            for node in soup.select(".jobs-wrapper")
            if node.select_one(".description-info, .responsibilities, .requirements")
        ),
        None,
    )
    if container:
        sections = container.select(".description-info, .responsibilities, .requirements")
        raw_jd = "\n\n".join(
            section.get_text("\n", strip=True) for section in sections if section.get_text(strip=True)
        )
    else:
        section = soup.select_one(".job-description")
        raw_jd = section.get_text("\n", strip=True) if section else ""
    return {
        "raw_jd_text": strip_html(raw_jd),
        "job_url": url,
        "source_platform": "Workline HR",
        "industry": portal.get("industry", ""),
    }


class WorklineProvider:
    key = "workline"

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
            page = session.get(endpoint, timeout=REQUEST_TIMEOUT)
            page.raise_for_status()
            api_url = f"{_origin(endpoint)}/CPortal/generalopening.aspx/GetCurrentopening"
            response = session.post(
                api_url,
                json={"JDFileName": "", "OrgCode": "", "KeyName": ""},
                headers={
                    "Content-Type": "application/json; charset=utf-8",
                    "Referer": endpoint,
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.Timeout as exc:
            return ProviderResult.error(ScrapeReason.TIMEOUT, str(exc))
        except Exception as exc:
            _log.warning("    [Workline] listing failed for %s: %s", portal.get("company"), exc)
            return ProviderResult.error(ScrapeReason.API_BLOCKED, str(exc))

        jobs = parse_workline_listing_payload(payload, portal)
        if max_jobs:
            jobs = jobs[:max_jobs]
        for job in jobs:
            try:
                detail = session.get(job["job_url"], timeout=REQUEST_TIMEOUT)
                if detail.status_code == 200:
                    job.update(parse_workline_detail_html(detail.text, job["job_url"], portal))
            except requests.RequestException:
                continue
        return ProviderResult.success(jobs)
