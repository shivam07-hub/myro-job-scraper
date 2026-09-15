from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import strip_html

_log = logging.getLogger("mirror")

_JOB_ID_RE = re.compile(r"^(?:creq\d+|job-\d+)$", re.IGNORECASE)


def _title_from_map(title: str, slug: str, job_id: str) -> str:
    clean = title.strip()
    clean = re.sub(r"\s*-\s*Virtusa\s*$", "", clean, flags=re.IGNORECASE)
    clean = re.sub(
        rf"^{re.escape(job_id)}\s*-\s*",
        "",
        clean,
        flags=re.IGNORECASE,
    )
    if not clean or clean.lower() == job_id.lower():
        clean = slug.replace("-", " ").title()
    return clean


def parse_virtusa_map_links(links: list[dict], portal: Portal) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for item in links:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        parts = [part for part in urlsplit(url).path.split("/") if part]
        if "careers" not in parts or "in" not in parts:
            continue
        job_id = parts[-1] if parts else ""
        if not _JOB_ID_RE.fullmatch(job_id) or job_id.lower() in seen:
            continue
        india_index = parts.index("in")
        if len(parts) < india_index + 5:
            continue
        city = parts[india_index + 1].replace("-", " ").title()
        business_unit = parts[india_index + 2].replace("-", " ").title()
        slug = parts[-2]
        seen.add(job_id.lower())
        out.append({
            "job_id": job_id,
            "title": _title_from_map(str(item.get("title") or ""), slug, job_id),
            "job_url": url,
            "source_api_url": portal.get("endpoint", ""),
            "business_unit": business_unit,
            "raw_jd_text": strip_html(str(item.get("description") or "")),
            "location_city": f"{city}, India",
            "date_posted": None,
            "source_platform": "Virtusa CMS via Firecrawl Cloud",
            "industry": portal.get("industry", ""),
        })
    return out


def merge_virtusa_markdown(job: dict, markdown: str) -> dict:
    merged = dict(job)
    title = re.search(r"(?m)^[ \t]*#[ \t]+(.+?)[ \t]*$", markdown)
    location = re.search(r"(?mi)^[ \t]*Location:[ \t]*(.+?)[ \t]*$", markdown)
    date_posted = re.search(r"(?mi)^[ \t]*Date Posted:[ \t]*(.+?)[ \t]*$", markdown)
    body = re.search(
        (
            r"(?is)^[ \t]*##[ \t]+Job description[ \t]*\n"
            r"(.+?)(?=^[ \t]*##[ \t]+Join us|^[ \t]*ABOUT VIRTUSA|\Z)"
        ),
        markdown,
        re.MULTILINE,
    )
    if title:
        merged["title"] = title.group(1).strip()
    if location:
        merged["location_city"] = location.group(1).strip()
    if date_posted:
        merged["date_posted"] = date_posted.group(1).strip()
    if body:
        merged["raw_jd_text"] = strip_html(body.group(1))
    return merged


class VirtusaFirecrawlProvider:
    key = "virtusa_firecrawl"

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
        try:
            import firecrawl_client as fc

            links = fc.cloud_map_site(
                endpoint,
                search="jobs india careers",
                include_subdomains=True,
                ignore_query_parameters=False,
                limit=max(max_jobs or 200, 200),
                sitemap="include",
            )
        except Exception as exc:
            _log.warning("    [Virtusa] Firecrawl cloud map failed: %s", exc)
            return ProviderResult.error(ScrapeReason.API_BLOCKED, str(exc))

        jobs = parse_virtusa_map_links(links, portal)
        if max_jobs:
            jobs = jobs[:max_jobs]
        if not jobs:
            return ProviderResult.error(ScrapeReason.PARSE_ERROR, "no_virtusa_detail_links")
        if validate_mode:
            return ProviderResult.success(jobs)

        pages = fc.cloud_batch_scrape([job["job_url"] for job in jobs])
        jobs = [
            merge_virtusa_markdown(job, pages.get(job["job_url"], ""))
            for job in jobs
        ]
        return ProviderResult.success(jobs)
