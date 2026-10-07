"""Bain & Company careers (careers.bain.com, ExternalJobs HTML).

  - Listing: GET /jobs/SearchJobs/india/?folderRecordsPerPage=10&folderOffset=N
    is server-rendered. Each result names its cities under the title
    ("Bengaluru, Mumbai, New Delhi").
  - Detail:  /jobs/FolderDetail/{slug}/{id} rejects plain HTTP, so descriptions
    keep the Scrapling-then-Firecrawl path the generic firecrawl_js route used.

The generic route read only page text, so every Bain job was "India" with no
city (CEO decision record 2026-10-04, Q7). job_id stays ``job_hash(title, url)``
— the id the generic route wrote — so no live Bain row churns.
"""
from __future__ import annotations

import html as _html
import logging
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

import firecrawl_client as fc
import scrapling_client as scrapling
from config import REQUEST_TIMEOUT
from location_vocab import india_city
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import job_hash, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_ARTICLE_RE = re.compile(
    r'<article\s+class="article\s+article--result[^"]*"[^>]*>(?P<body>.*?)</article>',
    re.IGNORECASE | re.DOTALL,
)
_TITLE_RE = re.compile(
    r'<h3[^>]*>\s*<a\s+href="(?P<url>https://careers\.bain\.com/jobs/FolderDetail/[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_CITIES_RE = re.compile(
    r'<div class="article__header__text__subtitle">\s*<span>(?P<cities>.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)
_MIN_JD_CHARS = 100
_BATCH = 20


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", strip_html(_html.unescape(value or ""))).strip()


def parse_bain_listing(listing_html: str) -> list[dict]:
    """[{title, job_url, cities}] for each result on one listing page."""
    rows: list[dict] = []
    for article in _ARTICLE_RE.finditer(listing_html):
        body = article.group("body")
        title_m = _TITLE_RE.search(body)
        if not title_m:
            continue
        title = _clean(title_m.group("title"))
        job_url = _html.unescape(title_m.group("url")).strip()
        if not title or not job_url:
            continue
        cities_m = _CITIES_RE.search(body)
        cities = [c.strip() for c in _clean(cities_m.group("cities")).split(",")] if cities_m else []
        rows.append({"title": title, "job_url": job_url, "cities": [c for c in cities if c]})
    return rows


def _page_url(base_url: str, offset: int) -> str:
    parts = urlsplit(base_url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params["folderOffset"] = str(offset)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


def _india_cities(cities: list[str]) -> list[str]:
    out: list[str] = []
    for city in cities:
        known = india_city(city)
        if known and known[0] not in out:
            out.append(known[0])
    return out


def _scrape_bain(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    base = (portal.get("endpoint") or "").strip()
    page_size = int(dict(parse_qsl(urlsplit(base).query)).get("folderRecordsPerPage", "10") or "10")
    session = requests.Session()
    session.headers.update(_HEADERS)

    listed: list[dict] = []
    seen: set[str] = set()
    for page in range(200):  # safety cap; 106 results today
        try:
            response = session.get(_page_url(base, page * page_size), timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except Exception as exc:
            _log.warning(f"    [WARN] Bain listing page {page} failed: {exc}")
            if page == 0:
                return None
            break
        rows = [row for row in parse_bain_listing(response.text) if row["job_url"] not in seen]
        if not rows:
            break
        for row in rows:
            seen.add(row["job_url"])
            row["india_cities"] = _india_cities(row["cities"])
            # The search matches "india" anywhere, so it also returns Mexico City
            # and Warsaw roles. Myro is India-only (Q4): skip those before paying
            # for their pages.
            if not row["india_cities"]:
                continue
            listed.append(row)
    if max_jobs:
        listed = listed[:max_jobs]

    descriptions: dict[str, str] = {}
    pending: list[str] = []
    for row in listed:
        text = scrapling.fetch_text(row["job_url"]) or ""
        if len(text) >= _MIN_JD_CHARS:
            descriptions[row["job_url"]] = text
        else:
            pending.append(row["job_url"])
    for i in range(0, len(pending), _BATCH):
        for url, markdown in fc.batch_scrape(pending[i:i + _BATCH]).items():
            if markdown and len(markdown) >= _MIN_JD_CHARS:
                descriptions[url] = markdown

    jobs: list[dict] = []
    for row in listed:
        cities = row["india_cities"]
        jobs.append({
            "job_id": job_hash(row["title"], row["job_url"]),
            "title": row["title"],
            "job_url": row["job_url"],
            "source_api_url": base,
            "business_unit": None,
            "raw_jd_text": descriptions.get(row["job_url"], ""),
            "location_city": f"{cities[0]}, India",
            "locations": cities,
            "date_posted": None,
            "source_platform": "BainCareersHTML",
            "industry": portal.get("industry", ""),
        })
    _log.info(f"    {len(jobs)} India jobs via Bain careers listing ({len(seen)} listed)")
    return jobs


class BainCareersProvider:
    key = "bain_careers"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_bain(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED, "bain_listing_unreachable")
        return ProviderResult.success(jobs)
