from __future__ import annotations
from job_cap import job_limit

"""Yello (Recsolu) provider.

Validated on EY board:
  - Listing JSON: GET /job_boards/{board_slug}/search?query=&filters={india_id}&page_number=N
  - Response: {"html": "...", "more_requisitions": bool, ...}
  - Detail page: /jobs/{token}?job_board_id={board_slug}
    includes full JD HTML + apply link.
"""

import html as _html
import json
import logging
import re
from urllib.parse import urljoin, urlparse

import requests

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

_SEARCH_URL_RE = re.compile(
    r'data-search-url="(?P<url>https?://[^"]+/job_boards/[^"/]+/search)"',
    re.IGNORECASE,
)
_INDIA_FILTER_ESC_RE = re.compile(r"&quot;id&quot;:(?P<id>\d+),&quot;label&quot;:&quot;India&quot;")
_INDIA_FILTER_RAW_RE = re.compile(r'"id"\s*:\s*(?P<id>\d+)\s*,\s*"label"\s*:\s*"India"', re.IGNORECASE)

_ITEM_RE = re.compile(r'<li class="search-results__item">(?P<body>.*?)</li>', re.IGNORECASE | re.DOTALL)
_ITEM_LINK_RE = re.compile(
    r'<a[^>]*class="[^"]*\bsearch-results__req_title\b[^"]*"[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_ITEM_REQ_ID_RE = re.compile(r"<div>\s*<span>\s*(?P<id>\d{4,})\s*</span>\s*</div>", re.IGNORECASE)

_H1_RE = re.compile(r"<h1[^>]*>(?P<title>.*?)</h1>", re.IGNORECASE | re.DOTALL)
_APPLY_RE = re.compile(r'<a[^>]*id="apply-button"[^>]*href="(?P<href>[^"]+)"', re.IGNORECASE)
_DETAIL_TOP_RE = re.compile(
    r'<div class="details-top__title[^"]*">(?P<body>.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_SPAN_RE = re.compile(r"<span[^>]*>(?P<txt>.*?)</span>", re.IGNORECASE | re.DOTALL)
_DETAIL_KV_RE = re.compile(
    r'<span class="secondary-details__title">(?P<k>.*?)</span>\s*<span class="secondary-details__content">(?P<v>.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)
_JD_RE = re.compile(
    r'<section class="job-details__description[^"]*">\s*<div class="inner[^"]*">(?P<jd>.*?)</div>\s*</section>',
    re.IGNORECASE | re.DOTALL,
)


class YelloProvider:
    key = "yello"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_yello(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.fallback(
                policy=FALLBACK_FIRECRAWL_EXTRACT,
                reason="yello_board_unreachable_or_parse_failed",
                portal=portal,
            )
        return ProviderResult.success(jobs)


def _candidate_board_urls(portal: Portal) -> list[str]:
    out: list[str] = []

    def _add(url: str) -> None:
        u = (url or "").strip()
        if u and u not in out:
            out.append(u)

    endpoint = (portal.get("endpoint") or "").strip()
    careers = (portal.get("careers_url") or "").strip()
    company = (portal.get("company") or "").strip()

    for u in (endpoint, careers):
        if not u.startswith("http"):
            continue
        _add(u)

        p = urlparse(u)
        if "yello.co" in p.netloc and "/job_boards/" not in p.path:
            _add(f"{p.scheme}://{p.netloc}/job_boards/1")

    # EY currently uses a Yello board and no longer serves listing JSON from careers.ey.com.
    if company == "EY India":
        _add("https://eyglobal.yello.co/job_boards/1")
        _add("https://eyglobal.yello.co/job_boards/c1riT--B2O-KySgYWsZO1Q")

    return out


def _discover_board(session: requests.Session, portal: Portal) -> dict | None:
    for board_url in _candidate_board_urls(portal):
        try:
            r = session.get(board_url, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                continue
        except Exception:
            continue

        html = r.text
        search_m = _SEARCH_URL_RE.search(html)
        search_url = (search_m.group("url") if search_m else "").strip()
        if not search_url:
            continue

        india_id = ""
        decoded = _html.unescape(html)
        m1 = _INDIA_FILTER_RAW_RE.search(decoded)
        if m1:
            india_id = m1.group("id")
        if not india_id:
            m2 = _INDIA_FILTER_ESC_RE.search(html)
            if m2:
                india_id = m2.group("id")

        return {
            "board_url": board_url,
            "search_url": search_url,
            "india_filter_id": india_id,
        }

    return None


def _parse_listing_items(list_html: str) -> list[dict]:
    out: list[dict] = []
    for item_m in _ITEM_RE.finditer(list_html or ""):
        body = item_m.group("body") or ""
        link_m = _ITEM_LINK_RE.search(body)
        if not link_m:
            continue

        href = (link_m.group("href") or "").strip()
        title = strip_html(_html.unescape(link_m.group("title") or ""))
        if not href or not title:
            continue

        req_m = _ITEM_REQ_ID_RE.search(body)
        req_id = (req_m.group("id") if req_m else "").strip()

        out.append(
            {
                "href": href,
                "title": title,
                "req_id": req_id,
            }
        )
    return out


def _normalize_location(raw_loc: str, country: str) -> str:
    loc = (raw_loc or "").strip()
    c = (country or "").strip()

    if loc.upper().startswith("IND-") and len(loc) > 4:
        loc = loc[4:].strip()

    if c and c.lower() not in loc.lower():
        if loc:
            return f"{loc}, {c}"
        return c
    return loc or c or "India"


def _extract_detail(session: requests.Session, detail_url: str, listing_title: str, listing_req_id: str) -> dict:
    out = {
        "title": listing_title,
        "job_id": listing_req_id,
        "location": "India",
        "country": "",
        "apply_url": detail_url,
        "raw_jd_text": "",
    }
    try:
        r = session.get(detail_url, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return out
    except Exception:
        return out

    html = r.text

    h1 = _H1_RE.search(html)
    if h1:
        out["title"] = strip_html(_html.unescape(h1.group("title") or "")) or out["title"]

    apply_m = _APPLY_RE.search(html)
    if apply_m:
        out["apply_url"] = urljoin(detail_url, _html.unescape(apply_m.group("href") or ""))

    top_m = _DETAIL_TOP_RE.search(html)
    if top_m:
        spans = [strip_html(_html.unescape(x.group("txt") or "")) for x in _SPAN_RE.finditer(top_m.group("body"))]
        spans = [s for s in spans if s]
        # Expected: [job_id, location]
        for s in spans:
            if not out["job_id"] and re.fullmatch(r"\d{4,}", s):
                out["job_id"] = s
            elif not re.fullmatch(r"\d{4,}", s):
                out["location"] = s
                break

    details_map: dict[str, str] = {}
    for m in _DETAIL_KV_RE.finditer(html):
        k = strip_html(_html.unescape(m.group("k") or ""))
        v = strip_html(_html.unescape(m.group("v") or ""))
        if k and v:
            details_map[k] = v

    out["country"] = details_map.get("Country/Region", "")
    out["location"] = _normalize_location(out.get("location", ""), out["country"])

    jd_m = _JD_RE.search(html)
    if jd_m:
        out["raw_jd_text"] = strip_html(_html.unescape(jd_m.group("jd") or ""))

    return out


def _scrape_yello(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    company = portal.get("company", "")
    industry = portal.get("industry", "")
    india_only = portal.get("india_only", True)
    cap = job_limit(max_jobs)

    session = requests.Session()
    session.headers.update(_HEADERS)

    board = _discover_board(session, portal)
    if not board:
        _log.error(f"    [ERROR] Yello: board discovery failed for {company}")
        return None

    search_url = board["search_url"]
    india_filter_id = board.get("india_filter_id", "")
    origin = "{uri.scheme}://{uri.netloc}".format(uri=urlparse(search_url))

    page = 1
    max_pages = 400
    jobs: list[dict] = []
    seen_ids: set[str] = set()

    while page <= max_pages and len(jobs) < cap:
        params = {
            "query": "",
            "filters": india_filter_id,
            # UI sends a random GUID; any stable string works for backend responses.
            "job_board_tab_identifier": "mirror-scraper",
        }
        if page > 1:
            params["page_number"] = str(page)

        try:
            r = session.get(search_url, params=params, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                _log.warning(f"    [WARN] Yello page {page} status={r.status_code} for {company}")
                break
            payload = r.json()
        except json.JSONDecodeError:
            _log.warning(f"    [WARN] Yello non-JSON response on page {page} for {company}")
            break
        except Exception as e:
            _log.warning(f"    [WARN] Yello listing fetch failed page {page} for {company}: {e}")
            break

        list_html = payload.get("html", "") or ""
        listing_items = _parse_listing_items(list_html)
        if not listing_items:
            break

        new_on_page = 0
        for item in listing_items:
            detail_url = urljoin(origin, item["href"])
            detail = _extract_detail(session, detail_url, item["title"], item.get("req_id", ""))

            title = (detail.get("title") or item["title"]).strip()
            job_id = str(detail.get("job_id") or item.get("req_id") or job_hash(title, detail_url)).strip()
            location = (detail.get("location") or "").strip() or "India"
            raw_jd = (detail.get("raw_jd_text") or "").strip()
            apply_url = (detail.get("apply_url") or detail_url).strip()

            if not job_id or job_id in seen_ids:
                continue
            if india_only and not (is_india(location) or is_india(detail.get("country", ""))):
                continue

            seen_ids.add(job_id)
            new_on_page += 1
            jobs.append(
                {
                    "job_id": job_id,
                    "title": title,
                    "location_city": location,
                    "job_url": apply_url,
                    "raw_jd_text": raw_jd,
                    "company": company,
                    "industry": industry,
                }
            )
            if len(jobs) >= cap:
                break

        more = bool(payload.get("more_requisitions"))
        if not more or new_on_page == 0:
            break
        page += 1

    return jobs

