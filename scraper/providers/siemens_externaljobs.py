from __future__ import annotations
from job_cap import job_limit

"""Siemens Careers Marketplace provider (jobs.siemens.com externaljobs).

Pattern confirmed via browser capture:
  - Listing: GET /en_US/externaljobs/SearchJobs/?42386=[812053]&42386_format=17546&listFilterMode=1&folderRecordsPerPage=6&folderOffset=N
  - Detail:  GET /en_US/externaljobs/JobDetail/{job_id}
  - Apply:   /en_US/externaljobs/ApplicationMethods?folderId={job_id}

The listing page is server-rendered HTML (not Workday CXS). Full JD text is
in the job detail page under article content field-value blocks.
"""

import html as _html
import logging
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from config import REQUEST_TIMEOUT
from providers.base import FALLBACK_FIRECRAWL_EXTRACT, ProviderResult, ScrapeReason
from schema import Portal
from utils import is_india, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_ARTICLE_RE = re.compile(
    r"<article\s+class=\"article\s+article--result[^\"]*\"[^>]*>(?P<body>.*?)</article>",
    re.IGNORECASE | re.DOTALL,
)
_DETAIL_LINK_RE = re.compile(
    r'<a\s+class="link"\s+href="(?P<url>https://jobs\.siemens\.com/en_US/externaljobs/JobDetail/(?P<id>\d+))"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_CITY_RE = re.compile(r'<span class="list-item-jobCity">(?P<v>.*?)</span>', re.IGNORECASE | re.DOTALL)
_STATE_RE = re.compile(r'<span class="list-item-jobState">(?P<v>.*?)</span>', re.IGNORECASE | re.DOTALL)
_COUNTRY_RE = re.compile(r'<span class="list-item-jobCountry">(?P<v>.*?)</span>', re.IGNORECASE | re.DOTALL)
_FAMILY_RE = re.compile(r'<span class="list-item-family">(?P<v>.*?)</span>', re.IGNORECASE | re.DOTALL)
_TOTAL_RE = re.compile(r"\bof\s+(?P<n>\d+)\s+results\b", re.IGNORECASE)
_APPLY_RE = re.compile(
    r'<a class="button button--hero" href="(?P<url>https://jobs\.siemens\.com/en_US/externaljobs/ApplicationMethods\?folderId=\d+)"[^>]*>\s*Apply\s*</a>',
    re.IGNORECASE | re.DOTALL,
)
_OG_TITLE_RE = re.compile(
    r'<meta property="og:title" content="(?P<title>[^"]+)"',
    re.IGNORECASE,
)


class SiemensExternalJobsProvider:
    key = "siemens_externaljobs"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_siemens_externaljobs(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.fallback(
                policy=FALLBACK_FIRECRAWL_EXTRACT,
                reason="siemens_externaljobs_blocked_or_parse_failed",
                portal=portal,
            )
        return ProviderResult.success(jobs)


def _clean_text(raw: str) -> str:
    return re.sub(r"\s+", " ", strip_html(raw or "")).strip()


def _extract_div_class_blocks(html: str, class_name: str) -> list[str]:
    """Extract full inner HTML for <div class='... class_name ...'> blocks.

    Uses a lightweight depth counter to handle nested <div> elements.
    """
    pat = re.compile(
        rf'<div[^>]*class="[^"]*\b{re.escape(class_name)}\b[^"]*"[^>]*>',
        re.IGNORECASE,
    )
    out: list[str] = []

    for m in pat.finditer(html):
        start = m.end()
        pos = start
        depth = 1

        while depth > 0 and pos < len(html):
            next_open = html.find("<div", pos)
            next_close = html.find("</div>", pos)
            if next_close == -1:
                break
            if next_open != -1 and next_open < next_close:
                depth += 1
                pos = next_open + 4
            else:
                depth -= 1
                pos = next_close + 6

        if depth == 0:
            out.append(html[start:pos - 6])

    return out


def _build_page_url(base_url: str, offset: int, page_size: int) -> str:
    parts = urlsplit(base_url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params["folderRecordsPerPage"] = str(page_size)
    params["folderOffset"] = str(offset)
    q = urlencode(params, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, q, parts.fragment))


def _parse_total_results(listing_html: str) -> int | None:
    m = _TOTAL_RE.search(listing_html)
    if not m:
        return None
    try:
        return int(m.group("n"))
    except Exception:
        return None


def _parse_listing_page(listing_html: str) -> list[dict]:
    rows: list[dict] = []

    for art in _ARTICLE_RE.finditer(listing_html):
        body = art.group("body")
        link_m = _DETAIL_LINK_RE.search(body)
        if not link_m:
            continue

        job_id = (link_m.group("id") or "").strip()
        job_url = (link_m.group("url") or "").strip()
        title = _clean_text(_html.unescape(link_m.group("title") or ""))
        if not job_id or not title:
            continue

        city_m = _CITY_RE.search(body)
        state_m = _STATE_RE.search(body)
        country_m = _COUNTRY_RE.search(body)
        family_m = _FAMILY_RE.search(body)

        parts = []
        for m in (city_m, state_m, country_m):
            if m:
                t = _clean_text(_html.unescape(m.group("v") or ""))
                if t:
                    parts.append(t)
        location = ", ".join(parts)
        family = _clean_text(_html.unescape(family_m.group("v") or "")) if family_m else ""

        rows.append(
            {
                "job_id": job_id,
                "title": title,
                "job_url": job_url,
                "listing_location": location,
                "family": family,
            }
        )

    return rows


def _fetch_detail(session: requests.Session, job_url: str) -> dict:
    out = {
        "title": "",
        "location": "",
        "date_posted": "",
        "business_unit": "",
        "apply_url": job_url,
        "raw_jd_text": "",
    }
    try:
        r = session.get(job_url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
    except Exception:
        return out

    html = r.text

    # Preferred title from OG metadata.
    og_title_m = _OG_TITLE_RE.search(html)
    if og_title_m:
        out["title"] = _clean_text(_html.unescape(og_title_m.group("title") or ""))

    # Apply URL in right-side action card.
    apply_m = _APPLY_RE.search(html)
    if apply_m:
        out["apply_url"] = _html.unescape(apply_m.group("url") or out["apply_url"])

    # Metadata fields rendered as label/value blocks.
    labels = [_clean_text(x).lower() for x in _extract_div_class_blocks(html, "article__content__view__field__label")]
    values = [_clean_text(x) for x in _extract_div_class_blocks(html, "article__content__view__field__value")]
    field_map: dict[str, str] = {}
    for i, label in enumerate(labels):
        if i < len(values):
            field_map[label] = values[i]

    out["location"] = field_map.get("location(s)", "")
    out["date_posted"] = field_map.get("posted since", "")
    out["business_unit"] = field_map.get("field of work", "")

    # JD text is the extra (unlabeled) field-value block and is typically the longest one.
    if len(values) > len(labels):
        extra_values = values[len(labels):]
        out["raw_jd_text"] = max(extra_values, key=len)
    elif values:
        out["raw_jd_text"] = max(values, key=len)

    return out


def _scrape_siemens_externaljobs(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    base_url = (portal.get("endpoint") or "").strip()
    company = portal.get("company", "")
    industry = portal.get("industry", "")
    india_only = portal.get("india_only", True)
    cap = job_limit(max_jobs)

    if not base_url.startswith("http") or "/externaljobs/SearchJobs" not in base_url:
        _log.error(f"    [ERROR] SiemensExternalJobs: invalid endpoint for {company}: {base_url}")
        return None

    # Filter is captured from browser: Country India -> 42386=[812053].
    # Keep any supplied query params from endpoint and only control pagination.
    qs = dict(parse_qsl(urlsplit(base_url).query, keep_blank_values=True))
    page_size = int(qs.get("folderRecordsPerPage", "6") or "6")
    if page_size <= 0:
        page_size = 6

    session = requests.Session()
    session.headers.update(_HEADERS)

    jobs: list[dict] = []
    seen_ids: set[str] = set()
    offset = int(qs.get("folderOffset", "0") or "0")
    total_results: int | None = None
    page_num = 0
    max_pages = 1500  # safety cap

    while page_num < max_pages:
        page_url = _build_page_url(base_url, offset=offset, page_size=page_size)
        page_num += 1
        try:
            r = session.get(page_url, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
        except Exception as e:
            _log.warning(f"    [WARN] SiemensExternalJobs page fetch failed (offset={offset}): {e}")
            break

        listing_html = r.text
        if total_results is None:
            total_results = _parse_total_results(listing_html)

        rows = _parse_listing_page(listing_html)
        if not rows:
            break

        new_count = 0
        for row in rows:
            job_id = row["job_id"]
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            new_count += 1

            detail = _fetch_detail(session, row["job_url"])
            title = detail["title"] or row["title"]
            location = detail["location"] or row["listing_location"] or "India"
            business_unit = detail["business_unit"] or row["family"]
            apply_url = detail["apply_url"] or row["job_url"]
            raw_jd = detail["raw_jd_text"] or ""
            date_posted = detail["date_posted"] or ""

            if india_only and not is_india(location):
                continue

            jobs.append(
                {
                    "job_id": job_id,
                    "title": title,
                    "job_url": apply_url,
                    "source_api_url": page_url,
                    "business_unit": business_unit,
                    "raw_jd_text": raw_jd,
                    "location_city": location,
                    "date_posted": date_posted,
                    "source_platform": "SiemensExternalJobs",
                    "industry": industry,
                }
            )

            if len(jobs) >= cap:
                _log.info(f"    {len(jobs)} India jobs via SiemensExternalJobs ({company}) [max_jobs reached]")
                return jobs

        if new_count == 0:
            break

        offset += page_size
        if total_results is not None and offset >= total_results:
            break

    _log.info(
        f"    {len(jobs)} India jobs via SiemensExternalJobs ({company}); "
        f"total={total_results if total_results is not None else 'unknown'} pages={page_num}"
    )
    return jobs
