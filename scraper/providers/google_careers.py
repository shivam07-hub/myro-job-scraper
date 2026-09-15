from __future__ import annotations
from job_cap import job_limit

"""Google Careers provider via embedded AF_initDataCallback job data.

Validated endpoint:
  GET https://www.google.com/about/careers/applications/jobs/results/?location=India

The page is HTML, but it embeds full job records in AF_initDataCallback blocks.
Pagination uses `page=N` and returns 20 jobs/page until empty.
"""

import html as html_lib
import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_PAGE_SIZE = 20
_MAX_PAGES = 100


class GoogleCareersProvider:
    key = "google_careers"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_google_careers(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)
        return ProviderResult.success(jobs)


def _with_page(url: str, page: int) -> str:
    parts = urlsplit(url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    if page <= 1:
        q.pop("page", None)
    else:
        q["page"] = str(page)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q, doseq=True), parts.fragment))


def _extract_bracket_value(text: str, start: int) -> str:
    open_char = text[start]
    close_char = "]" if open_char == "[" else "}"
    depth = 0
    in_string = False
    escape = False

    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == open_char:
            depth += 1
        elif ch == close_char:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return ""


def _callback_data_arrays(html_text: str) -> list:
    arrays: list = []
    for match in re.finditer(r"AF_initDataCallback\(", html_text):
        data_pos = html_text.find("data:", match.end())
        if data_pos < 0:
            continue
        bracket_pos = html_text.find("[", data_pos)
        if bracket_pos < 0:
            continue
        raw_array = _extract_bracket_value(html_text, bracket_pos)
        if not raw_array:
            continue
        try:
            arrays.append(json.loads(raw_array))
        except Exception:
            continue
    return arrays


def _find_job_records(value, out: list[list]) -> None:
    if isinstance(value, list):
        if (
            len(value) > 10
            and isinstance(value[0], str)
            and value[0].isdigit()
            and isinstance(value[1], str)
            and isinstance(value[2], str)
        ):
            out.append(value)
            return
        for item in value:
            _find_job_records(item, out)


def _html_section(value) -> str:
    if isinstance(value, list) and len(value) > 1 and isinstance(value[1], str):
        return strip_html(value[1])
    if isinstance(value, str):
        return strip_html(value)
    return ""


def _locations_text(record: list) -> str:
    locations = record[9] if len(record) > 9 else []
    if not isinstance(locations, list):
        return ""

    parts: list[str] = []
    for loc in locations:
        if not isinstance(loc, list) or not loc:
            continue
        formatted = str(loc[0] or "").strip()
        if formatted:
            parts.append(formatted)
    return " | ".join(parts)


def _date_from_timestamp(value) -> str:
    if not isinstance(value, list) or not value:
        return ""
    try:
        return datetime.fromtimestamp(int(value[0]), timezone.utc).date().isoformat()
    except Exception:
        return ""


def _parse_google_job_record(record: list, portal: Portal, source_url: str) -> dict | None:
    title = str(record[1] or "").strip() if len(record) > 1 else ""
    apply_url = str(record[2] or "").strip() if len(record) > 2 else ""
    job_id = str(record[0] or "").strip() if record else ""
    location = _locations_text(record)

    if not job_id or not title:
        return None
    if portal.get("india_only", True) and not is_india(location):
        return None

    sections = [
        _html_section(record[10] if len(record) > 10 else None),
        _html_section(record[3] if len(record) > 3 else None),
        _html_section(record[4] if len(record) > 4 else None),
        _html_section(record[18] if len(record) > 18 else None),
    ]
    raw_jd = "\n\n".join([s for s in sections if s])

    return {
        "job_id": job_id,
        "title": title,
        "job_url": apply_url,
        "source_api_url": source_url,
        "business_unit": "Google",
        "raw_jd_text": raw_jd,
        "location_city": location,
        "date_posted": _date_from_timestamp(record[12] if len(record) > 12 else None),
        "source_platform": "GoogleCareers",
        "industry": portal.get("industry", ""),
    }


def parse_google_careers_html(html_text: str, portal: Portal, source_url: str | None = None) -> list[dict]:
    source = source_url or portal.get("endpoint", "")
    records: list[list] = []
    for data in _callback_data_arrays(html_text):
        _find_job_records(data, records)

    jobs: list[dict] = []
    seen: set[str] = set()
    for record in records:
        job = _parse_google_job_record(record, portal, source)
        if not job or job["job_id"] in seen:
            continue
        seen.add(job["job_id"])
        jobs.append(job)
    return jobs


def _scrape_google_careers(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    endpoint = (portal.get("endpoint") or "").strip()
    company = portal.get("company", "")
    if not endpoint.startswith("http"):
        _log.error(f"    [ERROR] Google Careers provider: invalid endpoint for {company}: {endpoint}")
        return None

    cap = job_limit(max_jobs)
    jobs: list[dict] = []
    seen: set[str] = set()
    session = requests.Session()
    session.headers.update(_HEADERS)

    for page in range(1, _MAX_PAGES + 1):
        page_url = _with_page(endpoint, page)
        try:
            r = session.get(page_url, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
        except Exception as e:
            _log.error(f"    [ERROR] Google Careers page {page} failed ({company}): {e}")
            return None if page == 1 else jobs

        page_jobs = parse_google_careers_html(r.text, portal, source_url=page_url)
        added = 0
        for job in page_jobs:
            if job["job_id"] in seen:
                continue
            seen.add(job["job_id"])
            jobs.append(job)
            added += 1
            if len(jobs) >= cap:
                break

        if not page_jobs or added == 0 or len(page_jobs) < _PAGE_SIZE or len(jobs) >= cap:
            break

    _log.info(f"    {len(jobs)} India jobs via Google Careers embedded HTML ({company})")
    return jobs
