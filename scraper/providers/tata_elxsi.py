from __future__ import annotations
from job_cap import job_limit

"""Tata Elxsi careers HTML provider.

Pattern validated on tataelxsi.com:
  - Listing: /careers/job-openings?page=N, cards in .jjbcdeo1
  - Detail: /careers/job-openings/{slug}, full JD in #japlicatn .jbpam1
  - Apply URL: Tata Elxsi Ramco link in a.japlynw
"""

import logging
import re
from html import unescape as _unescape
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT
from providers.base import FALLBACK_FIRECRAWL_EXTRACT, ProviderResult
from schema import Portal
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class TataElxsiProvider:
    key = "tata_elxsi"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_tata_elxsi(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.fallback(
                policy=FALLBACK_FIRECRAWL_EXTRACT,
                reason="tata_elxsi_html_unreachable_or_parse_failed",
                portal=portal,
            )
        return ProviderResult.success(jobs)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", strip_html(_unescape(value or ""))).strip()


def _build_listing_url(endpoint: str, page: int) -> str:
    parts = urlsplit(endpoint)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    if page > 1:
        q["page"] = str(page)
    else:
        q.pop("page", None)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q, doseq=True), parts.fragment))


def extract_tata_elxsi_listing_items(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    seen: set[str] = set()

    for card in soup.select("#job_listing .jjbcdeo1, .jjbcdeo1"):
        link = card.select_one("a.jknmre[href]")
        title_node = card.select_one(".jjbcdeo11 h3")
        if not link or not title_node:
            continue

        detail_url = urljoin(base_url, link.get("href") or "").strip()
        title = _clean_text(title_node.get_text(" ", strip=True))
        if not detail_url or not title or detail_url in seen:
            continue
        seen.add(detail_url)

        code_node = card.select_one(".jjbcdeo11 h5")
        meta_node = card.select_one(".jjbcdeo11 p")
        date_node = card.select_one(".jjbcdeo12 p")

        meta_parts = []
        if meta_node:
            meta_parts = [_clean_text(part) for part in meta_node.get_text(" ", strip=True).split("|")]
            meta_parts = [part for part in meta_parts if part]

        out.append(
            {
                "job_code": _clean_text(code_node.get_text(" ", strip=True)) if code_node else "",
                "title": title,
                "location": meta_parts[0] if meta_parts else "",
                "experience": meta_parts[1] if len(meta_parts) > 1 else "",
                "qualification": meta_parts[2] if len(meta_parts) > 2 else "",
                "detail_url": detail_url,
                "date_posted": _clean_text(date_node.get_text(" ", strip=True)) if date_node else "",
            }
        )

    return out


def extract_tata_elxsi_detail(html: str, detail_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one("#japlicatn") or soup

    title_node = root.select_one(".jbpam h2") or root.select_one("h2")
    apply_node = root.select_one("a.japlynw[href]")
    jd_node = root.select_one(".jbpam1")

    return {
        "title": _clean_text(title_node.get_text(" ", strip=True)) if title_node else "",
        "apply_url": urljoin(detail_url, apply_node.get("href") or "") if apply_node else detail_url,
        "raw_jd_text": strip_html(str(jd_node)) if jd_node else "",
    }


def _extract_last_page(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    pages = [1]
    for a in soup.select('a[href*="page="]'):
        href = a.get("href") or ""
        q = dict(parse_qsl(urlsplit(href).query, keep_blank_values=True))
        raw_page = q.get("page")
        if raw_page and raw_page.isdigit():
            pages.append(int(raw_page))
    return max(pages)


def _job_id_from_row(row: dict) -> str:
    code = (row.get("job_code") or "").strip()
    title = (row.get("title") or "").strip()
    detail_url = (row.get("detail_url") or "").rstrip("/")
    if code and code != title and "/" in code:
        return code
    slug = detail_url.rsplit("/", 1)[-1] if detail_url else ""
    return slug or job_hash(title, detail_url)


def _scrape_tata_elxsi(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    endpoint = (portal.get("endpoint") or "").strip()
    company = portal.get("company", "")
    industry = portal.get("industry", "")
    india_only = portal.get("india_only", True)
    cap = job_limit(max_jobs)

    if not endpoint.startswith("http"):
        _log.error(f"    [ERROR] Tata Elxsi: invalid endpoint for {company}: {endpoint}")
        return None

    session = requests.Session()
    session.headers.update(_HEADERS)

    jobs: list[dict] = []
    seen_ids: set[str] = set()
    page = 1
    max_pages = 200
    last_page = 1

    while page <= max_pages and page <= last_page and len(jobs) < cap:
        listing_url = _build_listing_url(endpoint, page)
        try:
            r = session.get(listing_url, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                _log.warning(f"    [WARN] Tata Elxsi listing status={r.status_code} page={page}")
                return None if page == 1 else jobs
            list_html = r.text
        except Exception as e:
            _log.warning(f"    [WARN] Tata Elxsi listing fetch failed page={page}: {e}")
            return None if page == 1 else jobs

        rows = extract_tata_elxsi_listing_items(list_html, listing_url)
        if not rows:
            break
        last_page = max(last_page, _extract_last_page(list_html))

        for row in rows:
            location = (row.get("location") or "").strip()
            if india_only and not is_india(location):
                continue

            jid = _job_id_from_row(row)
            if jid in seen_ids:
                continue
            seen_ids.add(jid)

            detail_url = row["detail_url"]
            detail = {"title": "", "apply_url": detail_url, "raw_jd_text": ""}
            try:
                detail_resp = session.get(detail_url, headers={"Referer": listing_url}, timeout=REQUEST_TIMEOUT)
                if detail_resp.status_code == 200:
                    detail = extract_tata_elxsi_detail(detail_resp.text, detail_url)
            except Exception:
                pass

            jobs.append(
                {
                    "job_id": jid,
                    "title": detail.get("title") or row["title"],
                    "job_url": detail.get("apply_url") or detail_url,
                    "source_api_url": listing_url,
                    "business_unit": None,
                    "raw_jd_text": detail.get("raw_jd_text") or "",
                    "location_city": location,
                    "date_posted": row.get("date_posted", ""),
                    "source_platform": "TataElxsiHTML",
                    "industry": industry,
                }
            )
            if len(jobs) >= cap:
                break

        page += 1

    return jobs
