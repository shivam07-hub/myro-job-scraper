"""
xhr_inspect.py — Inspect page HTML/JS source to find hidden JSON API endpoints.

Uses Firecrawl to fetch raw HTML (including inline JS), then regex-searches for:
  - fetch() / axios / XMLHttpRequest calls with API URLs
  - ATS platform SDK config objects (Workday, Greenhouse, SmartRecruiters, etc.)
  - JSON endpoint patterns (/api/jobs, /api/search, /api/postings, etc.)
  - Base URL config variables baked into the bundle

Usage:
    python xhr_inspect.py                         # all blocked 'other' companies
    python xhr_inspect.py --company "HSBC"        # single company
    python xhr_inspect.py --company "Deutsche"
"""
import argparse
import json
import re
import sys
from firecrawl import Firecrawl
from config import FIRECRAWL_API_KEY, FIRECRAWL_URL
from portal_reader import parse_portals

# ── Firecrawl client (HTML format) ────────────────────────────────────────────
_kwargs = {"api_key": FIRECRAWL_API_KEY or "local"}
_is_local = FIRECRAWL_URL and "api.firecrawl.dev" not in FIRECRAWL_URL
if _is_local:
    _kwargs["api_url"] = FIRECRAWL_URL
_app = Firecrawl(**_kwargs)


def _fetch_html(url: str) -> str:
    """Fetch full page HTML (includes <script> tags with JS bundles)."""
    try:
        doc = _app.scrape(url, formats=["html"], only_main_content=False)
        return getattr(doc, "html", "") or ""
    except Exception as e:
        print(f"    [HTML FETCH ERROR] {url}: {e}")
        return ""


# ── Patterns to search in JS source ──────────────────────────────────────────

# ATS SDK / widget config patterns
ATS_CONFIG_PATTERNS = [
    # Workday — tenant/career-site embedded in page config or script src
    (r'([\w\-]+)\.wd(\d+)\.myworkdayjobs\.com[/\w\-]*', 'workday',
     'Workday tenant URL in page source'),
    # Greenhouse — board token in config or script
    (r'greenhouse\.io[/\w\-]*boards?[/\s"\']+([\w\-]+)', 'greenhouse',
     'Greenhouse board reference'),
    (r'job-boards\.greenhouse\.io/([\w\-]+)', 'greenhouse',
     'Greenhouse job-boards URL'),
    # SmartRecruiters
    (r'api\.smartrecruiters\.com/v1/companies/([\w\-]+)', 'smartrecruiters',
     'SmartRecruiters company ID in source'),
    (r'"companyIdentifier"\s*:\s*"([\w\-]+)"', 'smartrecruiters',
     'SmartRecruiters companyIdentifier config'),
    # Lever
    (r'jobs\.lever\.co/([\w\-]+)', 'lever',
     'Lever job board URL'),
    # Ashby
    (r'jobs\.ashbyhq\.com/([\w\-]+)', 'ashby',
     'Ashby HQ job board URL'),
    # Workable
    (r'apply\.workable\.com/([\w\-]+)', 'workable',
     'Workable apply URL'),
    # Phenom
    (r'[\w\-]+\.phenompeople\.com', 'phenom',
     'Phenom People domain'),
    (r'careers\.([\w\-]+)\.com/api/jobs', 'phenom_api',
     'Phenom /api/jobs endpoint'),
    # iCIMS
    (r'careers-([\w\-]+)\.icims\.com', 'icims',
     'iCIMS careers domain'),
    # Oracle / Taleo
    (r'(fa-[\w\-]+)\.fa\.\w+\.oraclecloud\.com', 'oracle',
     'Oracle Cloud FA domain'),
    (r'([\w\-]+)\.taleo\.net', 'taleo',
     'Taleo domain'),
    # SAP SuccessFactors
    (r'([\w\-]+)\.successfactors\.(eu|com)', 'sap',
     'SAP SuccessFactors domain'),
    # Rippling ATS
    (r'ats\.rippling\.com/([\w\-]+)', 'rippling',
     'Rippling ATS URL'),
    # Keka HR
    (r'([\w\-]+)\.keka\.com/careers', 'keka',
     'Keka HR careers URL'),
    # Instahyre
    (r'instahyre\.com/jobs-at-([\w\-]+)', 'instahyre',
     'Instahyre jobs URL'),
    # Eightfold
    (r'([\w\-]+)\.eightfold\.ai/careers', 'eightfold',
     'Eightfold AI careers URL'),
    # Jobvite
    (r'jobs\.jobvite\.com/([\w\-]+)', 'jobvite',
     'Jobvite URL'),
    # JazzHR / CATS / BambooHR
    (r'([\w\-]+)\.jazz\.co/careers', 'jazzhr', 'JazzHR URL'),
    (r'([\w\-]+)\.bamboohr\.com/careers', 'bamboohr', 'BambooHR URL'),
]

# Generic API endpoint patterns in JS fetch/axios/xhr calls
API_CALL_PATTERNS = [
    # fetch("...") or axios.get("...") calls
    (r'(?:fetch|axios\.get|axios\.post)\s*\(\s*[`"\'](https?://[^`"\']+/(?:api|jobs|search|careers|postings|openings|requisitions)[^`"\']*)[`"\']',
     'fetch/axios call'),
    # XHR open calls
    (r'\.open\s*\(\s*["\'](?:GET|POST)["\'],\s*["\']([^"\']+/(?:api|jobs|search|postings)[^"\']*)["\']',
     'XHR.open call'),
    # baseURL or apiUrl config vars
    (r'(?:baseURL|apiUrl|apiBase|BASE_URL|API_URL|jobsApiUrl)\s*[=:]\s*["\']([^"\']+)["\']',
     'API base URL config'),
    # Next.js / React env vars baked in
    (r'NEXT_PUBLIC_[A-Z_]*(?:API|URL|BASE)[A-Z_]*["\s]*:["\s]*["\']([^"\']+)["\']',
     'Next.js public env var'),
    # JSON blob with jobs API shape
    (r'"(?:jobsApiEndpoint|searchEndpoint|jobsUrl|careersApiUrl)"\s*:\s*"([^"]+)"',
     'jobs API endpoint config key'),
]

# India-filtered URL patterns anywhere in the source
INDIA_URL_PATTERNS = [
    r'https?://[^\s"\'<>]+(?:india|IN\b|country=IN|location=India|locationsearch=India|qcountry=India)[^\s"\'<>]*',
]


def _search_source(html: str) -> dict:
    """
    Search HTML/JS source for API patterns.
    Returns {
        'ats': [(match_str, ats_type, description), ...],
        'api_calls': [(url, pattern_desc), ...],
        'india_urls': [url, ...],
    }
    """
    results = {'ats': [], 'api_calls': [], 'india_urls': []}

    # ATS config patterns
    seen = set()
    for pattern, ats_type, desc in ATS_CONFIG_PATTERNS:
        for m in re.finditer(pattern, html, re.IGNORECASE):
            hit = m.group(0)
            if hit not in seen:
                seen.add(hit)
                results['ats'].append((hit, ats_type, desc))

    # API call patterns (look in <script> blocks primarily)
    script_blocks = re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
    js_source = '\n'.join(script_blocks) + '\n' + html  # also check full page
    seen_urls = set()
    for pattern, desc in API_CALL_PATTERNS:
        for m in re.finditer(pattern, js_source, re.IGNORECASE):
            url = m.group(1)
            if url not in seen_urls and len(url) > 10:
                seen_urls.add(url)
                results['api_calls'].append((url, desc))

    # India URL patterns
    seen_india = set()
    for pattern in INDIA_URL_PATTERNS:
        for m in re.finditer(pattern, html, re.IGNORECASE):
            url = m.group(0).rstrip('.,;"\' ')
            if url not in seen_india:
                seen_india.add(url)
                results['india_urls'].append(url)

    return results


def inspect(company: str, url: str) -> dict:
    print(f"  [{company}] fetching HTML from {url[:70]} ...", flush=True)
    html = _fetch_html(url)
    if not html:
        return {'company': company, 'url': url, 'html_len': 0,
                'ats': [], 'api_calls': [], 'india_urls': [], 'error': 'empty HTML'}

    findings = _search_source(html)
    findings['company'] = company
    findings['url'] = url
    findings['html_len'] = len(html)
    findings['error'] = None
    return findings


def print_findings(f: dict) -> None:
    c = f['company']
    if f.get('error') and f['html_len'] == 0:
        print(f"  [{c}] ❌ ERROR: {f['error']}\n")
        return

    print(f"  [{c}]  HTML: {f['html_len']:,} chars")

    if f['ats']:
        print(f"    🎯 ATS PLATFORM DETECTED:")
        for hit, ats_type, desc in f['ats'][:5]:
            print(f"      [{ats_type}] {hit[:90]}")
            print(f"               ↳ {desc}")

    if f['india_urls']:
        print(f"    🌏 India-specific URLs found in source:")
        for url in f['india_urls'][:5]:
            print(f"      {url[:100]}")

    if f['api_calls']:
        print(f"    🔌 API calls found in JS:")
        for url, desc in f['api_calls'][:5]:
            print(f"      {url[:90]}")
            print(f"      ↳ {desc}")

    if not f['ats'] and not f['india_urls'] and not f['api_calls']:
        print(f"    ❌ Nothing found — page may load all content via separate bundle JS")

    print()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--company', help='Filter by company name (substring)')
    args = parser.parse_args()

    portals = parse_portals()
    # Focus on js-required 'other' companies that are still using generic URLs
    targets = [p for p in portals if p['ats'] == 'other' and p['js_required']]
    if args.company:
        targets = [p for p in targets if args.company.lower() in p['company'].lower()]

    print(f"XHR inspection of {len(targets)} companies\n{'='*60}\n")

    all_findings = []
    for p in targets:
        f = inspect(p['company'], p['endpoint'])
        print_findings(f)
        all_findings.append(f)

    # Summary
    print('=' * 60)
    print('SUMMARY\n')

    confirmed_ats = [(f['company'], f['ats'][0]) for f in all_findings if f['ats']]
    india_only    = [(f['company'], f['india_urls'][0]) for f in all_findings
                     if not f['ats'] and f['india_urls']]
    api_only      = [(f['company'], f['api_calls'][0][0]) for f in all_findings
                     if not f['ats'] and not f['india_urls'] and f['api_calls']]
    nothing       = [f['company'] for f in all_findings
                     if not f['ats'] and not f['india_urls'] and not f['api_calls']]

    if confirmed_ats:
        print(f"🎯 Confirmed ATS platform ({len(confirmed_ats)}):")
        for company, (hit, ats_type, _) in confirmed_ats:
            print(f"  {company:<35} [{ats_type}]  {hit[:60]}")
        print()

    if india_only:
        print(f"🌏 India URL found ({len(india_only)}):")
        for company, url in india_only:
            print(f"  {company:<35} {url[:70]}")
        print()

    if api_only:
        print(f"🔌 API endpoint found ({len(api_only)}):")
        for company, url in api_only:
            print(f"  {company:<35} {url[:70]}")
        print()

    if nothing:
        print(f"❌ No API found ({len(nothing)}) — need deeper inspection or cloud Firecrawl:")
        for c in nothing:
            print(f"  {c}")


if __name__ == '__main__':
    main()
