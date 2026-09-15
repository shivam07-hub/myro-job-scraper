from __future__ import annotations

from schema import Portal

import logging
import re

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class SkimaCareersProvider:
    key = "skima_careers"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_skima_careers(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED, "skima_listing_fetch_failed")
        return ProviderResult.success(jobs)


def _page_url(base: str, page: int) -> str:
    if page <= 1:
        return base
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}page={page}"


def _extract_last_page(listing_html: str) -> int:
    soup = BeautifulSoup(listing_html, "html.parser")
    node = soup.select_one("[data-pagination-container]")
    if not node:
        return 1
    try:
        return max(1, int(node.get("data-last-page") or "1"))
    except Exception:
        return 1


def _extract_listing_rows(listing_html: str, base: str) -> list[dict]:
    soup = BeautifulSoup(listing_html, "html.parser")
    rows: list[dict] = []
    seen: set[str] = set()

    # Title links are the stable anchors for each job card.
    for a in soup.select("a.text-lg.font-semibold.text-primary"):
        href = (a.get("href") or "").strip()
        if not href.startswith("/"):
            continue
        jid = href[1:]
        if not _UUID_RE.fullmatch(jid) or jid in seen:
            continue
        seen.add(jid)

        title = strip_html(a.get_text(" ", strip=True))
        if not title:
            continue

        card = a.find_parent("div", class_=lambda c: isinstance(c, str) and "p-5" in c and "flex-col" in c)
        location = ""
        if card:
            spans = card.select("span.break-all.text-sm")
            if spans:
                location = strip_html(spans[0].get_text(" ", strip=True))

        rows.append(
            {
                "job_id": jid,
                "title": title,
                "location": location,
                "detail_url": f"{base.rstrip('/')}/{jid}",
            }
        )
    return rows


def _extract_detail(detail_html: str, fallback_title: str, fallback_loc: str) -> tuple[str, str, str]:
    soup = BeautifulSoup(detail_html, "html.parser")

    title = fallback_title
    h1 = soup.find("h1")
    if h1:
        parsed_title = strip_html(h1.get_text(" ", strip=True))
        if parsed_title:
            title = parsed_title

    location = fallback_loc
    if not location:
        for p in soup.find_all("p"):
            txt = strip_html(p.get_text(" ", strip=True))
            if not txt:
                continue
            if "Exp." in txt or "Posted on" in txt:
                continue
            if txt in {"In Office", "Remote", "Hybrid"}:
                continue
            if "," in txt or "India" in txt:
                location = txt
                break

    jd = ""
    panel = soup.select_one(".job-description-panel")
    if panel:
        jd = strip_html(panel.get_text(" ", strip=True))

    return title, location, jd


def _scrape_skima_careers(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    base = (portal.get("endpoint") or "").strip().rstrip("/")
    if not base.startswith("http"):
        _log.error(f"    [ERROR] SkimaCareers invalid endpoint for {portal.get('company')}")
        return None

    company = portal.get("company", "")
    industry = portal.get("industry", "")

    s = requests.Session()
    s.headers.update(_HEADERS)

    try:
        r0 = s.get(_page_url(base, 1), timeout=REQUEST_TIMEOUT)
        r0.raise_for_status()
    except Exception as e:
        _log.error(f"    [ERROR] SkimaCareers listing fetch failed for {company}: {e}")
        return None

    total_pages = _extract_last_page(r0.text)
    jobs: list[dict] = []
    seen_ids: set[str] = set()

    for page in range(1, total_pages + 1):
        page_url = _page_url(base, page)
        try:
            rp = r0 if page == 1 else s.get(page_url, timeout=REQUEST_TIMEOUT)
            if page != 1:
                rp.raise_for_status()
        except Exception as e:
            _log.warning(f"    [WARN] SkimaCareers page fetch failed for {company} page {page}: {e}")
            continue

        rows = _extract_listing_rows(rp.text, base)
        if not rows and page > 1:
            break

        new_on_page = 0
        for row in rows:
            jid = row["job_id"]
            if jid in seen_ids:
                continue
            seen_ids.add(jid)
            new_on_page += 1

            detail_url = row["detail_url"]
            title = row["title"]
            loc = row.get("location", "")
            jd = ""

            try:
                rd = s.get(detail_url, timeout=REQUEST_TIMEOUT)
                if rd.status_code == 200:
                    title, loc, jd = _extract_detail(rd.text, title, loc)
            except Exception as e:
                _log.warning(f"    [WARN] SkimaCareers detail fetch failed for {company} {jid}: {e}")

            if portal.get("india_only", True) and not is_india(loc):
                continue

            jobs.append(
                {
                    "job_id": jid or job_hash(title, detail_url),
                    "title": title,
                    "job_url": detail_url,
                    "source_api_url": page_url,
                    "business_unit": None,
                    "raw_jd_text": jd,
                    "location_city": loc or "India",
                    "date_posted": None,
                    "source_platform": "SkimaCareers",
                    "industry": industry,
                }
            )

            if max_jobs and len(jobs) >= max_jobs:
                _log.info(f"    {len(jobs)} India jobs fetched via SkimaCareers ({company}) [max_jobs reached]")
                return jobs

        if page > 1 and new_on_page == 0:
            break

    _log.info(f"    {len(jobs)} India jobs fetched via SkimaCareers ({company})")
    return jobs
