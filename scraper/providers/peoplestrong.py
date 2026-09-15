from __future__ import annotations
from job_cap import job_limit

import logging
from urllib.parse import quote

import requests

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
    "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    "Content-Type": "application/json",
}


def _base_url(portal: Portal) -> str:
    return (portal.get("endpoint") or "").strip().rstrip("/")


def _location(item: dict) -> str:
    hierarchy = str(
        item.get("locationHierarchyComplete")
        or item.get("locationHierarchy")
        or item.get("joiningLocation")
        or ""
    ).strip()
    parts = [part.strip() for part in hierarchy.split(">") if part.strip()]
    return parts[-1] if parts else hierarchy


def parse_peoplestrong_listing_payload(payload: dict, portal: Portal) -> list[dict]:
    items = payload.get("response", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        hierarchy = str(item.get("locationHierarchyComplete") or "")
        if portal.get("india_only", True) and not is_india(hierarchy):
            continue
        title = str(item.get("jobTitle") or item.get("designation") or "").strip()
        job_id = str(item.get("requisitionId") or item.get("jobCode") or "").strip()
        if not title or not job_id or job_id in seen:
            continue
        seen.add(job_id)
        skills = item.get("skills") if isinstance(item.get("skills"), dict) else {}
        skill_text = list(skills.get("mustTohave") or []) + list(skills.get("goodtohave") or [])
        out.append({
            "job_id": job_id,
            "title": title,
            "job_url": str(item.get("jobDetailUrl") or "").strip(),
            "source_api_url": (
                f"{_base_url(portal)}/api/cp/rest/altone/cp/jobs/v1"
            ),
            "business_unit": item.get("organizationUnit"),
            "raw_jd_text": "\n".join(str(skill) for skill in skill_text if skill),
            "location_city": _location(item),
            "date_posted": item.get("jobPostedDate"),
            "source_platform": "PeopleStrong",
            "industry": portal.get("industry", ""),
            "_job_code": item.get("jobCode"),
        })
    return out


def _detail_api_url(portal: Portal, job: dict) -> str:
    job_code = str(job.get("_job_code") or job.get("job_id") or "").replace("/", "_")
    return (
        f"{_base_url(portal)}/api/cp/rest/altone/cp/job/"
        f"{quote(job_code)}/v2?part=basic&isReqId=false"
    )


def _merge_basic_detail(job: dict, payload: dict) -> None:
    detail = payload.get("response", {}) if isinstance(payload, dict) else {}
    if not isinstance(detail, dict):
        return
    job["title"] = str(detail.get("jobTitle") or job.get("title") or "").strip()
    job["business_unit"] = detail.get("departmentHierarchy") or job.get("business_unit")
    job["location_city"] = _location(detail) or job.get("location_city")
    job["date_posted"] = detail.get("CandidatePortalStartDate") or job.get("date_posted")
    role = strip_html(str(detail.get("jobRole") or ""))
    if role and len(job.get("raw_jd_text", "")) < 80:
        job["raw_jd_text"] = "\n".join(p for p in [role, job.get("raw_jd_text", "")] if p)


class PeopleStrongProvider:
    key = "peoplestrong"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        base = _base_url(portal)
        if not base.startswith("http"):
            return ProviderResult.error(ScrapeReason.CONFIG_ERROR, "bad_endpoint")
        limit = job_limit(max_jobs)
        listing_url = f"{base}/api/cp/rest/altone/cp/jobs/v1?offset=0&limit={limit}"
        try:
            response = requests.post(
                listing_url,
                headers=_HEADERS,
                json={},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            jobs = parse_peoplestrong_listing_payload(response.json(), portal)
        except requests.Timeout as exc:
            return ProviderResult.error(ScrapeReason.TIMEOUT, str(exc))
        except Exception as exc:
            _log.warning("    [PeopleStrong] listing failed for %s: %s", portal.get("company"), exc)
            return ProviderResult.error(ScrapeReason.API_BLOCKED, str(exc))

        if max_jobs:
            jobs = jobs[:max_jobs]
        for job in jobs:
            try:
                detail = requests.get(
                    _detail_api_url(portal, job),
                    headers=_HEADERS,
                    timeout=REQUEST_TIMEOUT,
                )
                if detail.status_code == 200:
                    _merge_basic_detail(job, detail.json())
            except requests.RequestException:
                pass
            job.pop("_job_code", None)

        if not validate_mode:
            render_jobs = [
                job
                for job in jobs
                if job.get("job_url") and len(job.get("raw_jd_text", "")) < 120
            ]
            if render_jobs:
                try:
                    import firecrawl_client as fc

                    urls = [job["job_url"] for job in render_jobs]
                    pages = fc.batch_scrape(urls)
                    missing = [url for url in urls if not pages.get(url)]
                    if missing:
                        pages.update(fc.cloud_batch_scrape(missing))
                    for job in render_jobs:
                        markdown = pages.get(job["job_url"], "")
                        if markdown:
                            job["raw_jd_text"] = strip_html(markdown)
                except Exception as exc:
                    _log.debug("    [PeopleStrong] detail render failed: %s", exc)
        return ProviderResult.success(jobs)
