from __future__ import annotations
from job_cap import job_limit

"""Michelin Astro/CXF careers provider.

The public Michelin India careers site renders listing/detail pages server-side.
India filtering is driven by the criteria JSON used by the search page widgets.
"""

import json
import re
from datetime import datetime
from html import unescape as _unescape
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult
from schema import Portal
from utils import is_india, strip_html

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_BASE_URL = "https://jobs.michelin.in"
_SEARCH_PATH = "/job-offer-result-list"
_INDIA_CRITERIA = json.dumps(
    {
        "jobLocation": {
            "level0": ["clef9npi100080hwi9ulb6phu", "sw4r5llp48tmhadpo1jgn5wf"],
            "level1": [
                "x5ziednftq4lnjnkkg96rlvd",
                "clef9npi100070hwig0b9b78r",
                "a4fj1fimu7m8enbotzwwhzgp",
            ],
        }
    },
    separators=(",", ":"),
)


class MichelinAstroProvider:
    key = "michelin_astro"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_michelin(portal, max_jobs=max_jobs)
        return ProviderResult.success(jobs)


def _page_url(endpoint: str, page: int) -> str:
    endpoint = endpoint.strip() or f"{_BASE_URL}{_SEARCH_PATH}"
    parts = urlsplit(endpoint)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("criteria", _INDIA_CRITERIA)
    query["page"] = str(page)
    path = parts.path or _SEARCH_PATH
    netloc = parts.netloc or urlsplit(_BASE_URL).netloc
    scheme = parts.scheme or "https"
    return urlunsplit((scheme, netloc, path, urlencode(query), parts.fragment))


def _last_page(soup: BeautifulSoup, fallback: int) -> int:
    for island in soup.find_all("astro-island"):
        component = (island.get("component-url") or "").lower()
        if "pagination" not in component:
            continue
        try:
            props = json.loads(island.get("props") or "{}")
            data = props.get("data", [None, {}])[1]
            last = data.get("lastPage", [None, None])[1]
            if last:
                return int(last)
        except Exception:
            continue
    return fallback


def _extract_listing(link) -> dict | None:
    href = (link.get("href") or "").strip()
    if not href or "/job-offer-result-list/" not in href:
        return None

    text = strip_html(_unescape(link.get_text(" ", strip=True)))
    loc_m = re.search(r"Location\s*:\s*(.+?)(?:Sector|Contract type|$)", text, re.IGNORECASE)
    loc = loc_m.group(1).strip() if loc_m else ""
    if not is_india(loc):
        return None

    title_m = re.match(r"^(.+?)Offer published", text)
    title = title_m.group(1).strip() if title_m else text[:120].strip()
    if not title:
        return None

    date_posted = ""
    date_m = re.search(r"published on (\d{2} \d{2} \d{4})", text, re.IGNORECASE)
    if date_m:
        try:
            date_posted = datetime.strptime(date_m.group(1), "%d %m %Y").strftime("%Y-%m-%d")
        except ValueError:
            date_posted = ""

    sector_m = re.search(r"Sector\s*:\s*(.+?)(?:Contract type|$)", text, re.IGNORECASE)
    sector = sector_m.group(1).strip() if sector_m else ""

    return {
        "slug": href.rstrip("/").split("/")[-1],
        "title": title,
        "location": loc,
        "sector": sector,
        "date_posted": date_posted,
        "detail_url": urljoin(_BASE_URL, href),
    }


def _fetch_detail(session: requests.Session, url: str) -> str:
    try:
        r = session.get(url, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return ""
        r.encoding = r.apparent_encoding or "utf-8"
    except Exception:
        return ""
    soup = BeautifulSoup(r.text, "html.parser")
    main = soup.find("main") or soup.find(id="main-content")
    return strip_html(_unescape(str(main))) if main else strip_html(_unescape(soup.get_text(" ", strip=True)))


def _scrape_michelin(portal: Portal, max_jobs: int | None = None) -> list[dict]:
    session = requests.Session()
    session.headers.update(_HEADERS)

    endpoint = portal.get("endpoint") or f"{_BASE_URL}{_SEARCH_PATH}"
    industry = portal.get("industry", "")
    cap = job_limit(max_jobs)
    jobs: list[dict] = []
    seen: set[str] = set()
    page = 1
    max_pages = 50

    while page <= max_pages and len(jobs) < cap:
        url = _page_url(endpoint, page)
        try:
            r = session.get(url, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                break
            r.encoding = r.apparent_encoding or "utf-8"
        except Exception:
            break

        soup = BeautifulSoup(r.text, "html.parser")
        if page == 1:
            max_pages = min(_last_page(soup, max_pages), max_pages)

        links = soup.find_all("a", href=lambda h: h and "/job-offer-result-list/" in str(h))
        if not links:
            break

        new_on_page = 0
        for link in links:
            item = _extract_listing(link)
            if not item or item["slug"] in seen:
                continue
            seen.add(item["slug"])

            jd = _fetch_detail(session, item["detail_url"])
            jobs.append(
                {
                    "job_id": item["slug"],
                    "title": item["title"],
                    "job_url": item["detail_url"],
                    "source_api_url": url,
                    "business_unit": item["sector"],
                    "raw_jd_text": jd,
                    "location_city": item["location"],
                    "date_posted": item["date_posted"],
                    "source_platform": "MichelinAstro",
                    "industry": industry,
                }
            )
            new_on_page += 1
            if len(jobs) >= cap:
                break

        if new_on_page == 0:
            break
        page += 1

    return jobs
