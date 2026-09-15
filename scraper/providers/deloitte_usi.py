from __future__ import annotations
from job_cap import job_limit

"""Deloitte USI careers provider (Avature-style server-rendered HTML).

Validated pattern:
  - Listing: GET /en_US/careersUSI/SearchJobs/?jobRecordsPerPage=10&jobOffset=N
  - Detail:  GET /en_US/careersUSI/JobDetail/<slug>/<job_id>
  - Apply:   GET /en_US/careersUSI/Login?jobId=<job_id>

The listing page is server-rendered and includes direct JobDetail links.
Full job description is available in detail-page JSON-LD (JobPosting.description).
"""

import html as _html
import json
import logging
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests

from config import REQUEST_TIMEOUT
from providers.base import FALLBACK_FIRECRAWL_EXTRACT, ProviderResult
from schema import Portal
from utils import is_india, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_ARTICLE_RE = re.compile(
    r"<article\s+class=\"article--result[^\"]*\"[^>]*>(?P<body>.*?)</article>",
    re.IGNORECASE | re.DOTALL,
)
_DETAIL_LINK_RE = re.compile(
    r'<a\s+href="(?P<url>https://[a-z0-9\.-]*deloitte\.com/en_US/(?:careersUSI|careers)/JobDetail/(?P<slug>[^"]+?)/(?P<id>\d+))"[^>]*>\s*(?P<title>.*?)\s*</a>',
    re.IGNORECASE | re.DOTALL,
)
_SPAN_RE = re.compile(r"<span[^>]*>(?P<t>.*?)</span>", re.IGNORECASE | re.DOTALL)
_TOTAL_RE = re.compile(r"class=['\"]jobListTotalRecords['\"]>\s*(?P<n>\d+)\s*<", re.IGNORECASE)

_JSON_LD_RE = re.compile(
    r'<script\s+type="application/ld\+json">\s*(?P<json>\{.*?\})\s*</script>',
    re.IGNORECASE | re.DOTALL,
)
_APPLY_RE = re.compile(
    r'<a[^>]*class="button\s+button--default"[^>]*href="(?P<url>https://[a-z0-9\.-]*deloitte\.com/en_US/(?:careersUSI|careers)/Login\?jobId=\d+[^"]*)"',
    re.IGNORECASE | re.DOTALL,
)
_DETAIL_LOCS_BLOCK_RE = re.compile(
    r'<div\s+class="article__header--locations[^"]*"[^>]*>(?P<body>.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)
_DETAIL_LOC_P_RE = re.compile(r'<p\s+class="paragraph">(?P<loc>.*?)</p>', re.IGNORECASE | re.DOTALL)


class DeloitteUSIProvider:
    key = "deloitte_usi"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_deloitte_usi(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.fallback(
                policy=FALLBACK_FIRECRAWL_EXTRACT,
                reason="deloitte_usi_unreachable_or_parse_failed",
                portal=portal,
            )
        return ProviderResult.success(jobs)


def _clean_text(raw: str) -> str:
    return re.sub(r"\s+", " ", strip_html(raw or "")).strip()


def _with_page(base_url: str, page_size: int, offset: int) -> str:
    parts = urlsplit(base_url)
    params = dict(parse_qsl(parts.query, keep_blank_values=True))
    params["jobRecordsPerPage"] = str(page_size)
    params["jobOffset"] = str(offset)
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
    for art in _ARTICLE_RE.finditer(listing_html or ""):
        body = art.group("body") or ""
        link_m = _DETAIL_LINK_RE.search(body)
        if not link_m:
            continue

        job_id = (link_m.group("id") or "").strip()
        job_url = _html.unescape((link_m.group("url") or "").strip())
        title = _clean_text(_html.unescape(link_m.group("title") or ""))
        if not job_id or not job_url or not title:
            continue

        spans = [_clean_text(_html.unescape(m.group("t") or "")) for m in _SPAN_RE.finditer(body)]
        spans = [s for s in spans if s]
        location = ""
        for s in reversed(spans):
            if is_india(s):
                location = s
                break
        if not location and spans:
            location = spans[-1]
        business_unit = spans[1] if len(spans) > 1 else (spans[0] if spans else "")

        rows.append(
            {
                "job_id": job_id,
                "job_url": job_url,
                "title": title,
                "listing_location": location,
                "business_unit": business_unit,
            }
        )
    return rows


def _extract_ldjson_detail(job_html: str) -> dict:
    out = {
        "title": "",
        "raw_jd_text": "",
        "date_posted": "",
        "location": "",
    }

    for m in _JSON_LD_RE.finditer(job_html or ""):
        blob = m.group("json") or ""
        try:
            obj = json.loads(blob)
        except Exception:
            continue

        if not isinstance(obj, dict):
            continue
        if obj.get("@type") != "JobPosting":
            continue

        out["title"] = _clean_text(obj.get("title", "") or "")
        out["date_posted"] = (obj.get("datePosted") or "").strip()
        out["raw_jd_text"] = _clean_text(_html.unescape(obj.get("description", "") or ""))

        jl = obj.get("jobLocation")
        if isinstance(jl, list):
            jl = jl[0] if jl else None
        if isinstance(jl, dict):
            addr = jl.get("address", jl)
            if isinstance(addr, dict):
                city = _clean_text(str(addr.get("addressLocality", "") or ""))
                region = _clean_text(str(addr.get("addressRegion", "") or ""))
                country = _clean_text(str(addr.get("addressCountry", "") or ""))
                loc_parts = [p for p in (city, region, country) if p]
                out["location"] = ", ".join(loc_parts)

        if out["title"] or out["raw_jd_text"]:
            break

    if not out["location"]:
        block_m = _DETAIL_LOCS_BLOCK_RE.search(job_html or "")
        if block_m:
            locs = [
                _clean_text(_html.unescape(m.group("loc") or ""))
                for m in _DETAIL_LOC_P_RE.finditer(block_m.group("body") or "")
            ]
            locs = [x for x in locs if x]
            if locs:
                out["location"] = " | ".join(locs)

    return out


def _fetch_detail(session: requests.Session, job_url: str) -> dict:
    out = {
        "title": "",
        "raw_jd_text": "",
        "date_posted": "",
        "location": "",
        "apply_url": job_url,
    }
    try:
        r = session.get(job_url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
    except Exception:
        return out

    html = r.text
    core = _extract_ldjson_detail(html)
    out.update(core)

    apply_m = _APPLY_RE.search(html)
    if apply_m:
        out["apply_url"] = _html.unescape(apply_m.group("url") or out["apply_url"])

    return out


def _scrape_deloitte_usi(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    base_url = (portal.get("endpoint") or "").strip()
    company = portal.get("company", "")
    industry = portal.get("industry", "")
    india_only = portal.get("india_only", True)
    cap = job_limit(max_jobs)

    if not base_url.startswith("http") or "/SearchJobs" not in base_url:
        _log.error(f"    [ERROR] DeloitteUSI: invalid endpoint for {company}: {base_url}")
        return None

    qs = dict(parse_qsl(urlsplit(base_url).query, keep_blank_values=True))
    page_size = int(qs.get("jobRecordsPerPage", "10") or "10")
    if page_size <= 0:
        page_size = 10
    offset = int(qs.get("jobOffset", "0") or "0")

    session = requests.Session()
    session.headers.update(_HEADERS)

    jobs: list[dict] = []
    seen_ids: set[str] = set()
    total_results: int | None = None
    max_pages = 2000
    page_num = 0

    while page_num < max_pages and len(jobs) < cap:
        page_num += 1
        page_url = _with_page(base_url, page_size=page_size, offset=offset)
        try:
            r = session.get(page_url, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
        except Exception as e:
            _log.warning(f"    [WARN] DeloitteUSI page fetch failed (offset={offset}): {e}")
            break

        listing_html = r.text
        if total_results is None:
            total_results = _parse_total_results(listing_html)

        rows = _parse_listing_page(listing_html)
        if not rows:
            break

        new_on_page = 0
        for row in rows:
            job_id = row["job_id"]
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            new_on_page += 1

            detail = _fetch_detail(session, row["job_url"])
            title = detail["title"] or row["title"]
            location = detail["location"] or row["listing_location"] or "India"
            apply_url = detail["apply_url"] or row["job_url"]
            raw_jd = detail["raw_jd_text"] or ""
            date_posted = detail["date_posted"] or ""
            business_unit = row["business_unit"]

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
                    "source_platform": "DeloitteUSI",
                    "industry": industry,
                }
            )
            if len(jobs) >= cap:
                _log.info(f"    {len(jobs)} India jobs via DeloitteUSI ({company}) [max_jobs reached]")
                return jobs

        if new_on_page == 0:
            break
        offset += page_size
        if total_results is not None and offset >= total_results:
            break

    _log.info(
        f"    {len(jobs)} India jobs via DeloitteUSI ({company}); "
        f"total={total_results if total_results is not None else 'unknown'} pages={page_num}"
    )
    return jobs
