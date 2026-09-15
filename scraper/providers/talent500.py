from __future__ import annotations

import logging

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://talent500.com",
    "Referer": "https://talent500.com/jobs/",
}


class Talent500Provider:
    key = "talent500"

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
            payload = r.json()
        except Exception as e:
            _log.error(f"    [ERROR] Talent500 {portal['company']}: {e}")
            return ProviderResult.error(ScrapeReason.API_BLOCKED)

        return ProviderResult.success(parse_talent500_jobs(payload, portal, max_jobs=max_jobs))


def _company_name(item: dict) -> str:
    company = item.get("company")
    if isinstance(company, dict):
        return company.get("name") or ""
    return str(company or "")


def _detail_url(item: dict, portal: Portal) -> str:
    job_url = item.get("job_url")
    if job_url:
        return str(job_url)
    slug = item.get("slug")
    company_slug = portal.get("talent500_company_slug") or ""
    if slug and company_slug:
        return f"https://talent500.com/jobs/{company_slug}/{slug}/"
    return ""


def _fetch_detail(item: dict) -> dict:
    detail_id = item.get("id") or item.get("slug") or item.get("external_id")
    if not detail_id:
        return {}
    url = f"https://prod-warmachine.talent500.co/api/jobs/{detail_id}/"
    try:
        r = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return {}
        data = r.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def parse_talent500_jobs(payload: dict, portal: Portal, max_jobs: int | None = None) -> list[dict]:
    items = payload.get("data") if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return []

    jobs: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue

        country = item.get("country") if isinstance(item.get("country"), dict) else {}
        loc = ", ".join(p for p in [item.get("location"), country.get("name")] if p)
        if portal.get("india_only", True) and not is_india(loc):
            continue

        detail = _fetch_detail(item)
        merged = {**item, **detail}
        title = merged.get("title_alias_1") or merged.get("title") or ""
        if not title:
            continue

        jid = str(merged.get("job_code") or merged.get("id") or job_hash(title, _detail_url(merged, portal)))
        if jid in seen:
            continue
        seen.add(jid)

        description = "\n\n".join(
            part
            for part in [
                merged.get("role_summary"),
                merged.get("description"),
                merged.get("summary"),
                merged.get("what_you_offer"),
                merged.get("what_you_need_to_succeed"),
                merged.get("responsibilities"),
            ]
            if part
        )
        jobs.append({
            "job_id": jid,
            "title": title,
            "job_url": _detail_url(merged, portal),
            "source_api_url": portal.get("endpoint", ""),
            "business_unit": merged.get("job_category") or merged.get("role_category"),
            "raw_jd_text": strip_html(description),
            "location_city": loc,
            "date_posted": merged.get("published_at") or merged.get("created_at") or merged.get("posted_on"),
            "source_platform": "Talent500",
            "industry": portal.get("industry", ""),
            "company_name": _company_name(merged) or portal.get("company", ""),
        })
        if max_jobs and len(jobs) >= max_jobs:
            break
    return jobs
