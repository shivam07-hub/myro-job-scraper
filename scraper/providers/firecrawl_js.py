from __future__ import annotations

from schema import Portal

import logging
import re

import firecrawl_client as fc
import scrapling_client as scrapling
from providers.base import ProviderResult, ScrapeReason
from utils import is_india, job_hash

_log = logging.getLogger("mirror")

_NOISE_EXT   = ('.svg', '.png', '.jpg', '.css', '.js', '.ico', '.woff', '.gif', '.webp')
_NOISE_WORDS = ('menu', 'search', 'home', 'cookie', 'nav', 'sign in', 'log in', 'privacy', 'about us')

# Cookie consent click actions — run before scraping to dismiss modal
# Selector tries common consent button patterns; Firecrawl ignores unknown selectors safely.
_COOKIE_DISMISS_ACTIONS = [
    {"type": "wait", "milliseconds": 1500},
    {"type": "click", "selector": "button#onetrust-accept-btn-handler"},
    {"type": "click", "selector": "button.cookie-accept"},
    {"type": "click", "selector": "button[data-cookiebanner='accept_button']"},
    {"type": "click", "selector": "button[aria-label='Accept cookies']"},
    {"type": "click", "selector": "#accept-all-cookies"},
    {"type": "click", "selector": ".cookiebot button[data-cookiebot='accept']"},
    {"type": "click", "selector": "button.js-accept-cookie"},
    {"type": "wait", "milliseconds": 800},
]

_LINK_PATTERNS = [
    # Workday human-facing detail pages
    re.compile(r'\[([^\]]+)\]\((https?://[^\)]+/details/\d+[^\)]*)\)'),
    # /jobs/ or /job/ in path (most ATS)
    re.compile(r'\[([^\]]+)\]\((https?://[^\)]+/job[s]?/[^\)]{5,})\)'),
    # /careers/ with enough path to not match the listing page itself
    re.compile(r'\[([^\]]+)\]\((https?://[^\)]+/careers?/[^\)]{10,})\)'),
    # /openings/
    re.compile(r'\[([^\]]+)\]\((https?://[^\)]+/opening[s]?/[^\)]{5,})\)'),
    # /positions/ or /position/ (Oracle, SAP CandidateExperience)
    re.compile(r'\[([^\]]+)\]\((https?://[^\)]+/position[s]?/[^\)]{5,})\)'),
    # /requisitions/ (Oracle HCM)
    re.compile(r'\[([^\]]+)\]\((https?://[^\)]+/requisition[s]?/[^\)]{5,})\)'),
    # /apply/ with job ID
    re.compile(r'\[([^\]]+)\]\((https?://[^\)]+/apply/[^\)]{5,})\)'),
    # Plain URL forms (no markdown link)
    re.compile(r'(https?://[^\s\)\]\"]+/details/\d+[^\s\)\]\"]+)'),
    re.compile(r'(https?://[^\s\)\]\"]{20,}/job[s]?/[^\s\)\]\"]{8,})'),
    re.compile(r'(https?://[^\s\)\]\"]{20,}/position[s]?/[^\s\)\]\"]{5,})'),
]


class FirecrawlJSProvider:
    key = "firecrawl_js"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        if validate_mode:
            jobs = scrape_validate(portal, max_jobs=max_jobs or 5)
        else:
            jobs = scrape_extract(portal, max_jobs=max_jobs)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED, "firecrawl_returned_no_markdown")
        return ProviderResult.success(jobs)


def scrape_validate(portal: Portal, max_jobs: int = 5) -> list[dict] | None:
    """Validate-mode: fc.scrape() only — parse markdown for job title links.
    Returns None if Firecrawl returned no markdown (hard failure).
    """
    url = portal['endpoint']
    _log.info(f"    Listing scrape (validate): {url}")
    md = scrapling.fetch_listing_markdown(url)
    if not md:
        md = fc.scrape(url)
    if not md:
        return None

    jobs = []
    links = re.findall(r'\[([^\]]{10,120})\]\((https?://[^\)]+)\)', md)
    for title, job_url in links[:max_jobs * 3]:
        if any(w in title.lower() for w in ('cookie', 'privacy', 'sign in', 'log in', 'menu', 'search', 'home', 'about', 'contact', 'careers')):
            continue
        jobs.append({
            'job_id':          job_hash(title, job_url),
            'title':           title.strip(),
            'job_url':         job_url,
            'source_api_url':  url,
            'business_unit':   None,
            'raw_jd_text':     '',
            'location_city':   '',
            'date_posted':     None,
            'source_platform': 'Firecrawl',
            'industry':        portal.get('industry', ''),
        })
        if len(jobs) >= max_jobs:
            break

    if not jobs:
        _log.warning("    0 entries from scrape (no parseable job links)")
        return []

    _log.info(f"    {len(jobs)} entries from scrape")
    return jobs


def scrape_extract(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    """Two-pass Firecrawl Docker: scrape listing → batch_scrape individual job pages.
    Returns None if Firecrawl returned no markdown (hard failure).
    """
    url     = portal.get('endpoint') or portal.get('careers_url', '')
    company = portal.get('company', '')

    # Use cookie-dismiss actions if portal has a known selector, or use universal fallback
    cookie_selector = portal.get('cookie_accept_selector')
    if cookie_selector:
        actions = [
            {"type": "wait", "milliseconds": 1500},
            {"type": "click", "selector": cookie_selector},
            {"type": "wait", "milliseconds": 800},
        ]
    else:
        actions = _COOKIE_DISMISS_ACTIONS

    _log.info(f"    Listing scrape: {url}")
    markdown = scrapling.fetch_listing_markdown(url)
    listing_via = "scrapling"
    if not markdown or len(markdown) < 200:
        listing_via = "firecrawl"
        markdown = fc.scrape(url, actions=actions)
    if not markdown or len(markdown) < 200:
        return None

    seen, job_links = set(), []
    for pat in _LINK_PATTERNS:
        for m in pat.finditer(markdown):
            if pat.groups >= 2:
                title, link = m.group(1), m.group(2)
            else:
                title, link = '', m.group(1)
            clean = link.split('?')[0].rstrip('/')
            if any(clean.endswith(e) for e in _NOISE_EXT):
                continue
            if clean in seen:
                continue
            seen.add(clean)
            job_links.append((title.strip(), link))

    _log.info(f"    Found {len(job_links)} candidate job URLs in listing markdown")

    if not job_links:
        _log.warning("    No job links found — returning 0 jobs (no placeholder row)")
        return []

    if listing_via == "scrapling":
        cap = max_jobs  # None = every link Scrapling found
    else:
        # Firecrawl batch_scrape spends one credit per detail URL.
        cap = max_jobs or 200
    job_links = job_links[:cap] if cap else job_links

    BATCH = 20
    india_only = portal.get('india_only', True)
    jobs = []
    pending_firecrawl: list[tuple[str, str]] = []
    for link_title, job_url in job_links:
        jd_md = ""
        if listing_via == "scrapling":
            jd_md = scrapling.fetch_text(job_url) or ""
        if not jd_md or len(jd_md) < 100:
            pending_firecrawl.append((link_title, job_url))
            continue
        if india_only and not is_india(link_title + ' ' + jd_md[:1500]):
            continue
        title = link_title if (
            len(link_title) > 5 and
            not any(w in link_title.lower() for w in _NOISE_WORDS)
        ) else company
        jobs.append({
            'job_id':          job_hash(title, job_url),
            'title':           title,
            'job_url':         job_url,
            'source_api_url':  url,
            'business_unit':   None,
            'raw_jd_text':     jd_md,
            'location_city':   'India',
            'date_posted':     None,
            'source_platform': 'Scrapling' if listing_via == "scrapling" else 'Firecrawl',
            'industry':        portal.get('industry', ''),
        })

    if listing_via == "scrapling":
        pending_firecrawl = pending_firecrawl[: min(len(pending_firecrawl), 200)]

    for i in range(0, len(pending_firecrawl), BATCH):
        chunk = pending_firecrawl[i:i + BATCH]
        results = fc.batch_scrape([link for _, link in chunk])
        for link_title, job_url in chunk:
            jd_md = results.get(job_url, '')
            if not jd_md or len(jd_md) < 100:
                continue
            if india_only and not is_india(link_title + ' ' + jd_md[:1500]):
                continue
            title = link_title if (
                len(link_title) > 5 and
                not any(w in link_title.lower() for w in _NOISE_WORDS)
            ) else company
            jobs.append({
                'job_id':          job_hash(title, job_url),
                'title':           title,
                'job_url':         job_url,
                'source_api_url':  url,
                'business_unit':   None,
                'raw_jd_text':     jd_md,
                'location_city':   'India',
                'date_posted':     None,
                'source_platform': 'Firecrawl',
                'industry':        portal.get('industry', ''),
            })

    scope_label = "India" if india_only else "global"
    _log.info(f"    {len(jobs)} {scope_label} jobs extracted from individual pages")
    return jobs
