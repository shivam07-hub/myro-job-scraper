from __future__ import annotations

from schema import Portal

import html as _html
import json
import logging
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.parse import urljoin

import requests

from config import REQUEST_TIMEOUT
from providers.base import FALLBACK_FIRECRAWL_EXTRACT, ProviderResult, ScrapeReason
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Connection": "keep-alive",
}

_LISTING_LINK_RE = re.compile(
    r'<a[^>]+href="(?P<href>/job/[^"]+/(?P<company_id>\d+)/(?P<job_id>\d+))"[^>]*class="[^"]*\bsr-item\b[^"]*"[^>]*>(?P<body>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_LISTING_LINK_RE_ADP = re.compile(
    r'<a[^>]+href="(?P<href>/en/jobs/(?P<job_id>[^/?#"<>\s]+)/[^"#<>\s]+/?)"[^>]*>(?P<body>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_LISTING_LINK_RE_RADANCY = re.compile(
    r'<a[^>]+class="[^"]*(?:\bsr-job-item__link\b|\bsearch-results-link\b)[^"]*"[^>]+href="(?P<href>/job/[^"]+/(?P<company_id>\d+)/(?P<job_id>\d+))"[^>]*>(?P<body>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_LISTING_LINK_RE_SECTION29 = re.compile(
    r'<a[^>]+class="[^"]*\bsection29__search-results-link\b[^"]*"[^>]+href="(?P<href>/(?:[a-z]{2}/)?job/[^"]+/(?P<company_id>\d+)/(?P<job_id>\d+))"[^>]*>(?P<body>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_LISTING_LINK_RE_BARE = re.compile(
    r'<a[^>]+href="(?P<href>/(?:[a-z]{2}/)?job/[^"]+/(?P<company_id>\d+)/(?P<job_id>\d+))"[^>]*data-job-id="(?P<data_job_id>[^"]+)"[^>]*>(?P<body>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_LISTING_CARD_RE_RADANCY = re.compile(
    r'<li[^>]+class="[^"]*\bjob-card\b[^"]*"[^>]*>(?P<body>.*?)</li>',
    re.IGNORECASE | re.DOTALL,
)
_LISTING_CARD_LINK_RE_RADANCY = re.compile(
    r'<a[^>]+class="[^"]*\bjob-card__title\b[^"]*"[^>]+href="(?P<href>/job/[^"]+/(?P<company_id>\d+)/(?P<job_id>\d+))"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_H2_RE = re.compile(r"<h2[^>]*>(?P<title>.*?)</h2>", re.IGNORECASE | re.DOTALL)
_HEADING_RE = re.compile(r"<h[23][^>]*>(?P<title>.*?)</h[23]>", re.IGNORECASE | re.DOTALL)
_LOC_RE = re.compile(
    r'<span[^>]*class="[^"]*\bjob-location\b[^"]*"[^>]*>(?P<loc>.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)
_CARD_LOC_RE = re.compile(
    r'<span[^>]*class="[^"]*\blocation\b[^"]*"[^>]*>(?P<loc>.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)
_SECTION29_LOC_RE = re.compile(
    r'<span[^>]*class="[^"]*\bsection29__result-location\b[^"]*"[^>]*>(?P<loc>.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)
_TOTAL_PAGES_RE = re.compile(r'data-total-pages="(?P<n>\d+)"', re.IGNORECASE)
_TOTAL_RESULTS_RE = re.compile(r'data-total-job-results="(?P<n>\d+)"', re.IGNORECASE)
_JSON_LD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(?P<json>.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
_APPLY_URL_RE = re.compile(
    r'<meta[^>]+name=["\']search-job-apply-url["\'][^>]+content=["\'](?P<url>[^"\']*)["\']',
    re.IGNORECASE,
)
_APPLY_URL_RE_ADP = re.compile(
    r'<a[^>]+href="(?P<url>https://recruiting\.adp\.com[^"]+)"[^>]*>\s*Apply Now',
    re.IGNORECASE,
)
_DETAIL_HEAD_RE = re.compile(r"<h1[^>]*>(?P<title>.*?)</h1>", re.IGNORECASE | re.DOTALL)
_DETAIL_LOC_RE = re.compile(
    r'<h1[^>]*>.*?</h1>\s*<p[^>]*>(?P<loc>.*?)</p>',
    re.IGNORECASE | re.DOTALL,
)
_DESC_SECTION_RE = re.compile(
    r'<h2[^>]*>\s*Description\s*</h2>\s*(?P<desc>.*?)(?:<h2[^>]*>|<section[^>]*class="similar-jobs"|<footer|$)',
    re.IGNORECASE | re.DOTALL,
)


class TalentBrewProvider:
    key = "talentbrew"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        jobs = _scrape_talentbrew(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.fallback(
                policy=FALLBACK_FIRECRAWL_EXTRACT,
                reason="talentbrew_api_blocked",
                portal=portal,
            )
        return ProviderResult.success(jobs)


def _page_url(base_url: str, page: int) -> str:
    # Query-style pagination: ...?page=1&...
    if "?" in base_url and re.search(r"(^|[?&])page=\d+", base_url):
        parts = urlsplit(base_url)
        q = dict(parse_qsl(parts.query, keep_blank_values=True))
        q["page"] = str(page)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q, doseq=True), parts.fragment))

    # Radancy/TalentBrew search pages use ?p=N pagination.
    if "/search-jobs/" in base_url and page > 1:
        parts = urlsplit(base_url)
        q = dict(parse_qsl(parts.query, keep_blank_values=True))
        q["p"] = str(page)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(q, doseq=True), parts.fragment))

    # TalentBrew location pages use path pagination:
    # /location/india-jobs/{org}/{country_id}/{facet_type}/{page}
    if page <= 1:
        return base_url.rstrip("/")
    return f"{base_url.rstrip('/')}/{page}"


def _extract_listing_items(listing_html: str) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    # Pattern A: Intuit-style /job/{slug}/{org}/{job_id}
    for m in _LISTING_LINK_RE.finditer(listing_html):
        job_id = (m.group("job_id") or "").strip()
        href = (m.group("href") or "").strip()
        body = m.group("body") or ""
        if not job_id or not href or job_id in seen:
            continue
        seen.add(job_id)

        title_m = _H2_RE.search(body)
        title = strip_html(_html.unescape(title_m.group("title") if title_m else ""))
        if not title:
            continue

        loc_m = _LOC_RE.search(body)
        listing_loc = strip_html(_html.unescape(loc_m.group("loc") if loc_m else ""))

        items.append(
            {
                "job_id": job_id,
                "href": href,
                "title": title,
                "listing_loc": listing_loc,
            }
        )

    # Pattern B: ADP-style /en/jobs/{job_id}/{slug}/
    for m in _LISTING_LINK_RE_ADP.finditer(listing_html):
        job_id = (m.group("job_id") or "").strip()
        href = (m.group("href") or "").strip()
        body = m.group("body") or ""
        if not job_id or not href or job_id in seen:
            continue
        seen.add(job_id)

        title = strip_html(_html.unescape(body))
        title = re.sub(r"^\s*#+\s*", "", title).strip()
        if not title or len(title) < 2:
            continue

        items.append(
            {
                "job_id": job_id,
                "href": href,
                "title": title,
                "listing_loc": "",
            }
        )

    # Pattern C: Radancy/TalentBrew search pages (Citi, AstraZeneca).
    for m in _LISTING_LINK_RE_RADANCY.finditer(listing_html):
        job_id = (m.group("job_id") or "").strip()
        href = (m.group("href") or "").strip()
        body = m.group("body") or ""
        if not job_id or not href or job_id in seen:
            continue
        seen.add(job_id)

        title_m = _H2_RE.search(body)
        title = strip_html(_html.unescape(title_m.group("title") if title_m else body))
        if not title:
            continue

        loc_m = _LOC_RE.search(body)
        listing_loc = strip_html(_html.unescape(loc_m.group("loc") if loc_m else ""))

        items.append(
            {
                "job_id": job_id,
                "href": href,
                "title": title,
                "listing_loc": listing_loc,
            }
        )

    # Pattern D: newer TalentBrew section29 cards (Palo Alto Networks).
    for m in _LISTING_LINK_RE_SECTION29.finditer(listing_html):
        job_id = (m.group("job_id") or "").strip()
        href = (m.group("href") or "").strip()
        body = m.group("body") or ""
        if not job_id or not href or job_id in seen:
            continue
        seen.add(job_id)

        title_m = _H2_RE.search(body)
        title = strip_html(_html.unescape(title_m.group("title") if title_m else body))
        if not title:
            continue

        loc_m = _SECTION29_LOC_RE.search(body)
        listing_loc = strip_html(_html.unescape(loc_m.group("loc") if loc_m else ""))

        items.append(
            {
                "job_id": job_id,
                "href": href,
                "title": title,
                "listing_loc": listing_loc,
            }
        )

    # Pattern E: newer Radancy cards (Arm) using li.job-card + a.job-card__title.
    for card_m in _LISTING_CARD_RE_RADANCY.finditer(listing_html):
        body = card_m.group("body") or ""
        link_m = _LISTING_CARD_LINK_RE_RADANCY.search(body)
        if not link_m:
            continue
        job_id = (link_m.group("job_id") or "").strip()
        href = (link_m.group("href") or "").strip()
        if not job_id or not href or job_id in seen:
            continue

        title = strip_html(_html.unescape(link_m.group("title") or ""))
        if not title:
            continue

        seen.add(job_id)
        loc_m = _CARD_LOC_RE.search(body)
        listing_loc = strip_html(_html.unescape(loc_m.group("loc") if loc_m else ""))

        items.append(
            {
                "job_id": job_id,
                "href": href,
                "title": title,
                "listing_loc": listing_loc,
            }
        )

    # Pattern F: plain TalentBrew result anchors with h3 + job-location (Cargill).
    for m in _LISTING_LINK_RE_BARE.finditer(listing_html):
        job_id = (m.group("job_id") or m.group("data_job_id") or "").strip()
        href = (m.group("href") or "").strip()
        body = m.group("body") or ""
        if not job_id or not href or job_id in seen:
            continue

        title_m = _HEADING_RE.search(body)
        title = strip_html(_html.unescape(title_m.group("title") if title_m else body))
        if not title:
            continue

        seen.add(job_id)
        loc_m = _LOC_RE.search(body)
        listing_loc = strip_html(_html.unescape(loc_m.group("loc") if loc_m else ""))

        items.append(
            {
                "job_id": job_id,
                "href": href,
                "title": title,
                "listing_loc": listing_loc,
            }
        )
    return items


def _extract_json_ld_job(job_html: str) -> dict | None:
    for m in _JSON_LD_RE.finditer(job_html):
        raw = (m.group("json") or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue

        candidates: list[dict] = []
        if isinstance(payload, dict):
            candidates = [payload]
        elif isinstance(payload, list):
            candidates = [x for x in payload if isinstance(x, dict)]

        for c in candidates:
            if (c.get("@type") or "").lower() == "jobposting":
                return c
    return None


def _parse_location_from_ld(ld: dict, fallback: str) -> str:
    locs = ld.get("jobLocation")
    if isinstance(locs, dict):
        locs = [locs]
    if isinstance(locs, list):
        for loc in locs:
            if not isinstance(loc, dict):
                continue
            addr = loc.get("address")
            if not isinstance(addr, dict):
                continue
            city = (addr.get("addressLocality") or "").strip()
            region = (addr.get("addressRegion") or "").strip()
            country = (addr.get("addressCountry") or "").strip()
            if country.upper() == "IN":
                country = "India"
            parts = [p for p in (city, region, country) if p]
            if parts:
                return ", ".join(parts)
    return fallback or "India"


def _compatible_detail_title(listing_title: str, detail_title: str) -> bool:
    listing = re.sub(r"\s+", " ", listing_title or "").strip().lower()
    detail = re.sub(r"\s+", " ", detail_title or "").strip().lower()
    if not detail:
        return False
    if not listing:
        return True
    return listing in detail or detail in listing


def _extract_adp_description(job_html: str) -> str:
    m = _DESC_SECTION_RE.search(job_html)
    if not m:
        return ""
    return strip_html(_html.unescape(m.group("desc") or ""))


def _scrape_talentbrew(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    base = (portal.get("endpoint") or "").strip()
    if not base.startswith("http"):
        _log.error(f"    [ERROR] TalentBrew: invalid endpoint for {portal.get('company')}")
        return None

    company = portal.get("company", "")
    industry = portal.get("industry", "")

    s = requests.Session()
    s.headers.update(_HEADERS)

    try:
        r0 = s.get(_page_url(base, 1), timeout=REQUEST_TIMEOUT)
        r0.raise_for_status()
    except Exception as e:
        _log.error(f"    [ERROR] TalentBrew listing fetch failed for {company}: {e}")
        return None

    html0 = r0.text
    pages_m = _TOTAL_PAGES_RE.search(html0)
    total_pages = int(pages_m.group("n")) if pages_m else 1
    total_results_m = _TOTAL_RESULTS_RE.search(html0)
    total_results = int(total_results_m.group("n")) if total_results_m else 0

    jobs: list[dict] = []
    seen_ids: set[str] = set()

    for page in range(1, max(total_pages, 1) + 1):
        page_url = _page_url(base, page)
        try:
            rp = r0 if page == 1 else s.get(page_url, timeout=REQUEST_TIMEOUT)
            if page != 1:
                rp.raise_for_status()
            listing_html = rp.text
        except Exception as e:
            _log.warning(f"    [WARN] TalentBrew page {page} failed for {company}: {e}")
            continue

        listing_items = _extract_listing_items(listing_html)
        if not listing_items and page > 1:
            break

        new_on_page = 0
        for item in listing_items:
            jid = item["job_id"]
            if jid in seen_ids:
                continue
            seen_ids.add(jid)
            new_on_page += 1

            job_url = urljoin(base, item["href"])
            title = item["title"]
            listing_title = title
            listing_loc = item.get("listing_loc", "")

            raw_jd = ""
            location = listing_loc or "India"
            apply_url = job_url

            try:
                rj = s.get(job_url, timeout=REQUEST_TIMEOUT)
                if rj.status_code == 200:
                    job_html = rj.text
                    ld = _extract_json_ld_job(job_html)
                    if ld:
                        raw_jd = strip_html(ld.get("description", "") or "")
                        location = _parse_location_from_ld(ld, location)
                        ld_title = (ld.get("title") or "").strip()
                        if _compatible_detail_title(listing_title, ld_title):
                            title = ld_title or title
                    apply_m = _APPLY_URL_RE.search(job_html)
                    if apply_m:
                        apply_url = _html.unescape(apply_m.group("url") or apply_url)

                    # ADP/Happydance fallback path where JSON-LD is absent.
                    if not raw_jd:
                        raw_jd = _extract_adp_description(job_html)
                    if not raw_jd:
                        # last-resort section text from renderer output
                        raw_jd = strip_html(job_html)
                    if not location or location == "India":
                        loc_m = _DETAIL_LOC_RE.search(job_html)
                        if loc_m:
                            location = strip_html(_html.unescape(loc_m.group("loc") or "")).strip() or location
                    if title == listing_title:
                        h1_m = _DETAIL_HEAD_RE.search(job_html)
                        if h1_m:
                            parsed_title = strip_html(_html.unescape(h1_m.group("title") or "")).strip()
                            if _compatible_detail_title(listing_title, parsed_title):
                                title = parsed_title
                    if apply_url == job_url:
                        apply_m_adp = _APPLY_URL_RE_ADP.search(job_html)
                        if apply_m_adp:
                            apply_url = _html.unescape(apply_m_adp.group("url") or apply_url)
            except Exception as e:
                _log.warning(f"    [WARN] TalentBrew JD fetch failed for {company} job {jid}: {e}")

            if portal.get("india_only", True) and not is_india(location):
                continue

            jobs.append(
                {
                    "job_id": jid or job_hash(title, job_url),
                    "title": title,
                    "job_url": apply_url or job_url,
                    "source_api_url": page_url,
                    "business_unit": None,
                    "raw_jd_text": raw_jd,
                    "location_city": location or "India",
                    "date_posted": None,
                    "source_platform": "TalentBrew",
                    "industry": industry,
                }
            )

            if max_jobs and len(jobs) >= max_jobs:
                _log.info(f"    {len(jobs)} India jobs fetched via TalentBrew ({company}) [max_jobs reached]")
                return jobs

        if page > 1 and new_on_page == 0:
            break

    _log.info(
        f"    {len(jobs)} India jobs fetched via TalentBrew ({company}); "
        f"listing total={total_results}, pages={total_pages}"
    )
    return jobs
