from __future__ import annotations

"""Waaree careers provider.

The Waaree careers page currently renders a small static list of jobs but the
site's TLS/browser behavior is brittle from local Python. Use the Firecrawl
scrape cache as the rendered source and parse the on-page roles directly.
"""

import logging
import re

import firecrawl_client as fc
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import company_slug, job_hash, strip_html

_log = logging.getLogger("mirror")

_STOP_TITLES = ("frequently asked", "ready to start", "what types of roles")
_NOISE_LINES = {
    "apply now",
    "view more",
    "all locationchikhlidelhimumbai",
    "all departmentdevitqcui",
    "all work typefreelancerfull timepart time",
    "all workspace typeworkspace1",
}


class WaareeStaticProvider:
    key = "waaree_static"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        endpoint = (portal.get("endpoint") or portal.get("careers_url") or "").strip()
        if not endpoint.startswith("http"):
            return ProviderResult.error(ScrapeReason.CONFIG_ERROR, "bad_endpoint")
        markdown = fc.scrape(endpoint)
        if not markdown:
            return ProviderResult.error(ScrapeReason.API_BLOCKED, "waaree_firecrawl_empty")
        jobs = parse_waaree_markdown(markdown, portal)
        if max_jobs:
            jobs = jobs[:max_jobs]
        return ProviderResult.success(jobs)


def _clean_lines(block: str) -> list[str]:
    lines: list[str] = []
    for raw in block.splitlines():
        line = strip_html(raw).strip()
        if not line:
            continue
        lower = line.lower()
        if lower in _NOISE_LINES or lower.startswith("![") or lower.startswith("- !["):
            continue
        if "icon]" in lower or "cookie" in lower:
            continue
        lines.append(line)
    return lines


def parse_waaree_markdown(markdown: str, portal: Portal) -> list[dict]:
    endpoint = portal.get("endpoint") or "https://www.waaree.com/careers/"
    company = portal.get("company", "Waaree Group")
    industry = portal.get("industry", "")
    slug = company_slug(company).lower()

    headings = list(re.finditer(r"^\s*#{3,6}\s+(.+?)\s*$", markdown, flags=re.MULTILINE))
    jobs: list[dict] = []
    seen: set[str] = set()

    for i, match in enumerate(headings):
        title = strip_html(match.group(1)).strip()
        if not title:
            continue
        lower_title = title.lower()
        if any(stop in lower_title for stop in _STOP_TITLES):
            break
        if lower_title in ("come build the future with us",):
            continue

        end = headings[i + 1].start() if i + 1 < len(headings) else len(markdown)
        lines = _clean_lines(markdown[match.end():end])
        if len(lines) < 3:
            continue

        location = lines[0]
        work_type = lines[1] if len(lines) > 1 else ""
        department = lines[2] if len(lines) > 2 else ""
        jd = " ".join(lines[3:]).strip() or f"{title} at {company}"
        jid = f"{slug}_{job_hash(title, location)}"
        if jid in seen:
            continue
        seen.add(jid)

        jobs.append(
            {
                "job_id": jid,
                "title": title,
                "job_url": endpoint,
                "source_api_url": endpoint,
                "business_unit": department or work_type,
                "raw_jd_text": jd,
                "location_city": location,
                "date_posted": "",
                "source_platform": "WaareeStatic",
                "industry": industry,
            }
        )

    _log.info(f"    [WaareeStatic] {len(jobs)} jobs parsed from rendered careers page")
    return jobs
