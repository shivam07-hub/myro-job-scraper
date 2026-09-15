from __future__ import annotations
from job_cap import job_limit

"""SAP SuccessFactors Jobs2Web HTML provider.

Pattern validated on EY experienced-professionals board:
  - Listing: GET /{tenant_path}/search/?q=india&optionsFacetsDD_country=IN&startrow=N
  - Rows: table#searchresults tr.data-row with /job/.../{posting_id}/ links
  - Detail: /{tenant_path}/job/{slug}/{posting_id}/ with full JD in
    [data-careersite-propertyid="description"] / itemprop="description"
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
from utils import is_india, strip_html, job_hash

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_POSTING_ID_RE = re.compile(r"/(\d{6,})/?$")
# Jobs2Web commonly uses ", IN" as the India country code. Keep this stricter
# than a plain word-boundary match so Indiana/US locations do not leak in.
_IN_COUNTRY_TOKEN_RE = re.compile(r"(?:,\s*IN(?:\s*,|\s*$)|\bIndia\b)", re.IGNORECASE)


def _is_india_listing_location(text: str) -> bool:
    """Accept Jobs2Web India tokens while avoiding Indiana/US false positives."""
    s = (text or "").strip()
    if not s:
        return False
    if s.upper() == "IN":
        return True
    tokens = [tok.strip(" ,") for tok in s.split()]
    if tokens and all(tok.upper() == "IN" for tok in tokens):
        return True
    return bool(is_india(s) or _IN_COUNTRY_TOKEN_RE.search(s))


class SAPJobs2WebHTMLProvider:
    key = "sap_jobs2web_html"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_sap_jobs2web_html(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.fallback(
                policy=FALLBACK_FIRECRAWL_EXTRACT,
                reason="sap_jobs2web_html_unreachable_or_parse_failed",
                portal=portal,
            )
        return ProviderResult.success(jobs)


def _build_listing_url(base_url: str, startrow: int) -> str:
    parts = urlsplit(base_url)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    # Preserve existing India filters from URL, but force pagination offset.
    if startrow > 0:
        q["startrow"] = str(startrow)
    else:
        q.pop("startrow", None)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q, doseq=True), parts.fragment))


def _extract_rows(list_html: str) -> list[dict]:
    soup = BeautifulSoup(list_html, "html.parser")
    rows = soup.select("table#searchresults tbody tr.data-row")

    out: list[dict] = []
    seen_href: set[str] = set()

    for row in rows:
        a = row.select_one("a.jobTitle-link")
        if not a:
            continue
        href = (a.get("href") or "").strip()
        if not href or href in seen_href:
            continue
        seen_href.add(href)

        title = strip_html(_unescape(a.get_text(" ", strip=True)))
        loc_node = row.select_one("span.jobLocation")
        listing_loc = strip_html(_unescape(loc_node.get_text(" ", strip=True))) if loc_node else ""
        cells = [strip_html(_unescape(c.get_text(" ", strip=True))) for c in row.select("td")]
        if len(cells) > 4 and cells[4]:
            business_unit = cells[4]
        else:
            business_unit = cells[2] if len(cells) > 2 and cells[2] != listing_loc else ""

        out.append({
            "href": href,
            "title": title,
            "listing_location": listing_loc,
            "business_unit": business_unit,
        })

    return out


def _extract_detail(session: requests.Session, detail_url: str, fallback_title: str, fallback_loc: str) -> dict:
    out = {
        "title": fallback_title,
        "job_id": "",
        "location": fallback_loc or "India",
        "apply_url": detail_url,
        "raw_jd_text": "",
        "date_posted": "",
    }
    try:
        r = session.get(detail_url, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return out
    except Exception:
        return out

    html = r.text
    soup = BeautifulSoup(html, "html.parser")

    # Title
    t = soup.select_one('[data-careersite-propertyid="title"]') or soup.select_one('span[itemprop="title"]')
    if t:
        out["title"] = strip_html(_unescape(t.get_text(" ", strip=True))) or out["title"]

    # Job ID from URL or explicit requisition field
    m = _POSTING_ID_RE.search(r.url or detail_url)
    if m:
        out["job_id"] = m.group(1)
    req = soup.select_one('[data-careersite-propertyid="customfield5"]')
    if req:
        req_text = strip_html(_unescape(req.get_text(" ", strip=True)))
        if req_text and req_text.isdigit():
            out["job_id"] = req_text

    # Location
    city = soup.select_one('[data-careersite-propertyid="city"]')
    if city:
        city_text = strip_html(_unescape(city.get_text(" ", strip=True)))
        if city_text:
            out["location"] = city_text

    # Date posted
    d = soup.select_one('[data-careersite-propertyid="date"]')
    if d:
        out["date_posted"] = strip_html(_unescape(d.get_text(" ", strip=True)))

    # Apply URL
    apply = soup.select_one("a.dialogApplyBtn.apply[href]")
    if apply:
        out["apply_url"] = urljoin(detail_url, apply.get("href") or "")

    # Full JD
    jd = soup.select_one('[data-careersite-propertyid="description"]') or soup.select_one('[itemprop="description"]')
    if jd:
        out["raw_jd_text"] = strip_html(_unescape(str(jd)))

    return out


def _scrape_sap_jobs2web_html(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    endpoint = (portal.get("endpoint") or "").strip()
    company = portal.get("company", "")
    industry = portal.get("industry", "")
    india_only = portal.get("india_only", True)
    cap = job_limit(max_jobs)

    if not endpoint.startswith("http"):
        _log.error(f"    [ERROR] SAP Jobs2Web HTML: invalid endpoint for {company}: {endpoint}")
        return None

    session = requests.Session()
    session.headers.update(_HEADERS)

    jobs: list[dict] = []
    seen_ids: set[str] = set()
    seen_detail_urls: set[str] = set()

    startrow = 0
    page_size_hint = 25
    max_pages = 1000
    page = 0

    while page < max_pages and len(jobs) < cap:
        page += 1
        listing_url = _build_listing_url(endpoint, startrow)
        try:
            r = session.get(listing_url, timeout=REQUEST_TIMEOUT)
            if r.status_code != 200:
                _log.warning(f"    [WARN] SAP Jobs2Web listing status={r.status_code} row={startrow} ({company})")
                break
            list_html = r.text
        except Exception as e:
            _log.warning(f"    [WARN] SAP Jobs2Web listing fetch failed row={startrow} ({company}): {e}")
            break

        rows = _extract_rows(list_html)
        if not rows:
            break

        new_on_page = 0
        for row in rows:
            # Fast path: for India-only runs, skip obvious non-India rows before
            # expensive per-job detail fetch.
            listing_loc = (row.get("listing_location") or "").strip()
            if india_only and listing_loc:
                if not _is_india_listing_location(listing_loc):
                    continue

            detail_url = urljoin(endpoint, row["href"])
            if detail_url in seen_detail_urls:
                continue
            seen_detail_urls.add(detail_url)

            detail = _extract_detail(session, detail_url, row["title"], row["listing_location"])
            title = (detail.get("title") or row["title"]).strip()
            loc = (row.get("listing_location") or detail.get("location") or "India").strip()
            raw_jd = (detail.get("raw_jd_text") or "").strip()
            apply_url = (detail.get("apply_url") or detail_url).strip()

            if india_only:
                loc_check = f"{loc} {detail.get('location','')}"
                # Jobs2Web list rows usually include country code token "IN".
                if not _is_india_listing_location(loc_check):
                    continue

            jid = str(detail.get("job_id") or "").strip()
            if not jid:
                m = _POSTING_ID_RE.search(detail_url)
                jid = m.group(1) if m else job_hash(title, detail_url)
            if jid in seen_ids:
                continue
            seen_ids.add(jid)

            jobs.append(
                {
                    "job_id": jid,
                    "title": title,
                    "job_url": apply_url,
                    "source_api_url": listing_url,
                    "business_unit": row.get("business_unit", ""),
                    "raw_jd_text": raw_jd,
                    "location_city": loc,
                    "date_posted": detail.get("date_posted", ""),
                    "source_platform": "SAPJobs2WebHTML",
                    "industry": industry,
                }
            )
            new_on_page += 1
            if len(jobs) >= cap:
                break

        # End conditions
        if new_on_page == 0 or len(rows) < page_size_hint:
            break
        startrow += page_size_hint

    _log.info(f"    {len(jobs)} jobs via SAP Jobs2Web HTML ({company})")
    return jobs
