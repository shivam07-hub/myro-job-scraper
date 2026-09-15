"""
discover_endpoints.py — Use Firecrawl as a discovery microscope, not the final scraper.

Workflow per portal:
  1. Firecrawl /map to quickly enumerate likely careers URLs on the site.
  2. If map does not already reveal the ATS endpoint, Firecrawl /scrape only a tiny shortlist.
  3. Promote the direct ATS/XHR route into KNOWN_PORTALS.md + portal routing once confirmed.

Usage:
    python discover_endpoints.py                    # all js-required portals
    python discover_endpoints.py --company "HSBC"   # single company, any current ATS
    python discover_endpoints.py --confirm          # print KNOWN_PORTALS.md update suggestions
"""
import argparse
import re
from urllib.parse import urlparse

import firecrawl_client as fc
from portal_reader import parse_portals

# ── ATS platform patterns to detect in links ─────────────────────────────────
ATS_PATTERNS = [
    (r'[\w\-]+\.wd\d+\.myworkdayjobs\.com',           'workday'),
    (r'boards\.greenhouse\.io|jobs\.lever\.co',        'greenhouse/lever'),
    (r'api\.smartrecruiters\.com|careers\.smartrecruiters\.com', 'smartrecruiters'),
    (r'[\w\-]+\.eightfold\.ai',                        'eightfold'),
    (r'jobs\.ashbyhq\.com',                            'ashby'),
    (r'apply\.workable\.com',                          'workable'),
    (r'icims\.com|phenom\.com',                        'icims/phenom'),
    (r'taleo\.net|oraclecloud\.com',                   'oracle/taleo'),
    (r'successfactors\.com|jobs2web\.com',             'sap'),
    (r'myrecruitment\+\.com|jobvite\.com',             'jobvite'),
]

# ── URL patterns that indicate a job listing page ────────────────────────────
JOB_URL_PATTERNS = [
    r'/jobs[/\?]',
    r'/careers?([/\?]|$)',
    r'/careers/jobs',
    r'/careers/search',
    r'/open-positions',
    r'/openings',
    r'/positions',
    r'/search-jobs',
    r'/job-search',
    r'SearchJobs',
    r'search-results',
    r'join-us',
    r'work-with-us',
    r'locationsearch=India',
    r'location=India',
    r'country=India',
    r'qcountry=India',
    r'country=IN\b',
    r'/india[/\?]',
    r'\?.*india',
]

# Skip these generic/noisy patterns
SKIP_PATTERNS = [
    r'\.(png|jpg|jpeg|gif|svg|webp|ico|pdf|css|js)(\?|$)',
    r'#',
    r'mailto:',
    r'linkedin\.com',
    r'twitter\.com|x\.com',
    r'facebook\.com',
    r'instagram\.com',
    r'youtube\.com',
]

MAP_SEARCH_QUERY = "jobs careers openings hiring india"
SCRAPE_CANDIDATE_LIMIT = 3


def _extract_links(markdown: str) -> list[str]:
    """Extract all URLs from markdown link syntax [text](url)."""
    links = re.findall(r'\]\((https?://[^\s\)]+)\)', markdown)
    # Also grab bare URLs
    links += re.findall(r'(?<!\()(https?://[^\s\)\]"\'<>]+)', markdown)
    # Deduplicate, skip noise
    seen = set()
    out = []
    for url in links:
        url = url.rstrip('.,;)')
        if url in seen:
            continue
        seen.add(url)
        if any(re.search(p, url, re.I) for p in SKIP_PATTERNS):
            continue
        out.append(url)
    return out


def _classify_link(url: str, title: str = "", description: str = "") -> tuple[str | None, str | None]:
    """
    Returns (ats_type, reason) if the URL is useful, else (None, None).
    ats_type: 'workday' | 'greenhouse' | ... | 'job_page' | None
    reason: short description of why this URL is interesting
    """
    # ATS platform detection
    for pattern, ats in ATS_PATTERNS:
        if re.search(pattern, url, re.I):
            return ats, f"ATS platform: {ats}"

    # Job listing page patterns
    haystack = " ".join(part for part in [url, title, description] if part)
    for pattern in JOB_URL_PATTERNS:
        if re.search(pattern, haystack, re.I):
            return 'job_page', f"job listing URL pattern: {pattern}"

    return None, None


def _candidate_score(url: str, title: str = "", description: str = "") -> int:
    haystack = " ".join(part for part in [url, title, description] if part)
    score = 0
    if re.search(r'india', haystack, re.I):
        score += 8
    if re.search(r'jobs?|openings?|positions?|hiring|search-results|search-jobs', haystack, re.I):
        score += 6
    if re.search(r'/careers?([/\?]|$)', url, re.I):
        score += 4
    return score


def _scrape_candidates(current_url: str, mapped_links: list[dict[str, str]]) -> list[str]:
    candidates = []
    seen = set()

    def add(url: str) -> None:
        if not url or url in seen:
            return
        seen.add(url)
        candidates.append(url)

    scored = sorted(
        mapped_links,
        key=lambda item: (
            _candidate_score(item.get("url", ""), item.get("title", ""), item.get("description", "")),
            item.get("url", ""),
        ),
        reverse=True,
    )
    current_host = urlparse(current_url).netloc.lower()
    for item in scored:
        url = item.get("url", "")
        if not url:
            continue
        host = urlparse(url).netloc.lower()
        if host and current_host and host != current_host and not host.endswith("." + current_host):
            continue
        if _candidate_score(url, item.get("title", ""), item.get("description", "")) <= 0:
            continue
        add(url)
        if len(candidates) >= SCRAPE_CANDIDATE_LIMIT:
            break

    add(current_url)
    return candidates[:SCRAPE_CANDIDATE_LIMIT]


def discover(company_name: str, current_url: str) -> dict:
    """
    Scrape `current_url` and return a findings dict:
      {
        'company': str,
        'current_url': str,
        'ats_links': [(url, ats_type, reason), ...],
        'job_links': [(url, reason), ...],
        'markdown_len': int,
        'error': str | None,
      }
    """
    print(f"  Mapping {current_url} ...", flush=True)
    mapped_links = fc.map_site(
        current_url,
        search=MAP_SEARCH_QUERY,
        include_subdomains=True,
        ignore_query_parameters=False,
        limit=50,
        sitemap="include",
        timeout=60000,
    )
    ats_links = []
    job_links = []
    seen_ats = set()
    seen_jobs = set()

    def add_ats(url: str, ats_type: str, reason: str) -> None:
        key = (url, ats_type)
        if key in seen_ats:
            return
        seen_ats.add(key)
        ats_links.append((url, ats_type, reason))

    def add_job(url: str, reason: str) -> None:
        if url in seen_jobs:
            return
        seen_jobs.add(url)
        job_links.append((url, reason))

    for item in mapped_links:
        url = item.get("url", "")
        ats_type, reason = _classify_link(url, item.get("title", ""), item.get("description", ""))
        if ats_type == 'job_page':
            add_job(url, reason)
        elif ats_type:
            add_ats(url, ats_type, reason)

    inspected_pages = []
    if not ats_links:
        for candidate in _scrape_candidates(current_url, mapped_links):
            md = fc.scrape(candidate)
            inspected_pages.append((candidate, len(md)))
            if not md:
                continue
            for url in _extract_links(md):
                ats_type, reason = _classify_link(url)
                if ats_type == 'job_page':
                    add_job(url, f"{reason} via scrape({candidate})")
                elif ats_type:
                    add_ats(url, ats_type, f"{reason} via scrape({candidate})")

    return {
        'company': company_name,
        'current_url': current_url,
        'ats_links': ats_links,
        'job_links': job_links,
        'map_count': len(mapped_links),
        'inspected_pages': inspected_pages,
        'error': None if mapped_links or ats_links or job_links else 'Firecrawl map/scrape found no useful links',
    }


def _best_url(findings: dict) -> tuple[str | None, str | None]:
    """
    Pick the single best candidate URL from findings.
    Priority: ATS platform link > India job_link > generic job_link
    Returns (url, reason).
    """
    # Prefer ATS platform links
    if findings['ats_links']:
        url, ats_type, reason = findings['ats_links'][0]
        return url, f"{ats_type} ATS detected"

    # Prefer India-specific job links
    india_links = [
        (u, r) for u, r in findings['job_links']
        if re.search(r'india', u, re.I)
    ]
    if india_links:
        return india_links[0][0], "India-specific job listing page"

    # Generic job links
    if findings['job_links']:
        return findings['job_links'][0][0], findings['job_links'][0][1]

    return None, None


def print_findings(findings: dict) -> None:
    c = findings['company']
    if findings['error']:
        print(f"  [{c}] ERROR: {findings['error']}")
        return

    best_url, best_reason = _best_url(findings)

    print(f"  [{c}]  mapped URLs: {findings['map_count']}")

    if findings['inspected_pages']:
        print(f"    Scraped follow-up pages:")
        for url, md_len in findings['inspected_pages']:
            print(f"      {md_len:>5} chars  {url[:80]}")

    if findings['ats_links']:
        print(f"    ATS links found:")
        for url, ats, _ in findings['ats_links'][:3]:
            print(f"      {ats:<20} {url[:80]}")

    if findings['job_links']:
        print(f"    Job listing links found:")
        for url, _ in findings['job_links'][:3]:
            print(f"      {url[:80]}")

    if best_url:
        print(f"    ✅ BEST CANDIDATE: {best_url}")
        print(f"       Reason: {best_reason}")
    else:
        print(f"    ❌ No useful links found — page may be fully JS-rendered or block Firecrawl")

    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--company', help='Filter by company name (substring)')
    parser.add_argument('--confirm', action='store_true',
                        help='Print KNOWN_PORTALS.md update suggestions')
    args = parser.parse_args()

    portals = parse_portals()
    if args.company:
        targets = [p for p in portals if args.company.lower() in p['company'].lower()]
    else:
        targets = [p for p in portals if p.get('js_required')]

    print(f"Discovering endpoints for {len(targets)} target companies\n")

    all_findings = []
    for p in targets:
        findings = discover(p['company'], p['endpoint'])
        print_findings(findings)
        all_findings.append(findings)

    # Summary
    found = [(f['company'], *(_best_url(f))) for f in all_findings if _best_url(f)[0]]
    not_found = [f['company'] for f in all_findings if not _best_url(f)[0]]

    print("=" * 70)
    print(f"SUMMARY: {len(found)} companies with better URLs, {len(not_found)} still blocked\n")

    if found:
        print("✅ Found better endpoints:")
        for company, url, reason in found:
            print(f"  {company:<35} {reason}")
            print(f"    → {url}")
        print()

    if not_found:
        print("❌ No useful links found (fully JS-rendered or blocked):")
        for c in not_found:
            print(f"  {c}")


if __name__ == '__main__':
    main()
