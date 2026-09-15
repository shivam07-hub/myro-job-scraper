from __future__ import annotations

from schema import Portal

import json
import logging
import re
import requests
from pathlib import Path
from urllib.parse import urlencode

from config import REQUEST_TIMEOUT
from providers.base import FALLBACK_FIRECRAWL_EXTRACT, ProviderResult, ScrapeReason
from utils import is_india, job_hash, strip_html

_log = logging.getLogger("mirror")
_GENERIC_REGISTRY_PATH = Path(__file__).parent.parent / "generic_registry.json"
_generic_registry: dict | None = None


def _load_generic_registry() -> dict:
    global _generic_registry
    if _generic_registry is None:
        if _GENERIC_REGISTRY_PATH.exists():
            try:
                _generic_registry = json.loads(_GENERIC_REGISTRY_PATH.read_text(encoding="utf-8"))
            except Exception:
                _generic_registry = {}
        else:
            _generic_registry = {}
    return _generic_registry


def _persist_field_map(company: str, field_map: dict) -> None:
    """Persist which JSON keys worked for this company — next run uses registry directly."""
    reg = _load_generic_registry()
    if company in reg:
        return  # already known
    reg[company] = field_map
    try:
        _GENERIC_REGISTRY_PATH.write_text(json.dumps(reg, indent=2, ensure_ascii=False), encoding="utf-8")
        _log.info(f"    [REGISTRY] Persisted field map for {company}: {field_map}")
    except Exception as e:
        _log.warning(f"    [REGISTRY] Failed to persist field map for {company}: {e}")

_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type":    "application/json",
}


class GenericJSONProvider:
    key = "generic_json"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        raw = scrape_get(portal, max_jobs=max_jobs)

        # Oracle HCM REST is auth-gated — 400 or empty both mean fall to careers_url
        if (raw is None or not raw) and portal.get("ats") == "oracle" and portal.get("careers_url"):
            fc_portal = {**portal, "endpoint": portal["careers_url"]}
            return ProviderResult.fallback(
                policy=FALLBACK_FIRECRAWL_EXTRACT,
                reason="oracle_api_empty_fallback_careers_url",
                portal=fc_portal,
            )

        if raw is None:
            return ProviderResult.error(ScrapeReason.API_BLOCKED)

        if raw and raw[0].get("_needs_firecrawl"):
            return ProviderResult.fallback(
                policy=FALLBACK_FIRECRAWL_EXTRACT,
                reason="generic_get_requires_firecrawl",
                portal=portal,
            )

        return ProviderResult.success(raw)


_EXTRA_HEADERS: dict[str, dict] = {
    # Infosys gateway requires origin + referer + a correlation ID
    'infosysapps.com': {
        'origin':           'https://career.infosys.com',
        'referer':          'https://career.infosys.com/',
        'x-correlation-id': 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
    },
}


def _fetch_response(url: str, headers: dict) -> requests.Response | None:
    try:
        r = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r
    except Exception as e:
        _log.error(f"    [ERROR] GET {url}: {e}")
        return None


def _is_json_response(r: requests.Response) -> bool:
    ct = r.headers.get('Content-Type', '')
    return 'json' in ct or r.text.lstrip().startswith(('{', '['))


def _oracle_page_url(url: str, *, limit: int, offset: int) -> str:
    out = re.sub(r'([?&,])limit=\d+', rf'\1limit={limit}', url, count=1)
    if out == url:
        sep = '&' if '?' in out else '?'
        out = f"{out}{sep}limit={limit}"
    out = re.sub(r'([?&,])offset=\d+', rf'\1offset={offset}', out, count=1)
    if 'offset=' not in out:
        out = out.replace('sortBy=', f'offset={offset},sortBy=', 1) if 'sortBy=' in out else f"{out},offset={offset}"
    return out


def _oracle_total_count(data: dict) -> int:
    wrapper = data.get('items')
    if not isinstance(wrapper, list) or not wrapper or not isinstance(wrapper[0], dict):
        return 0
    try:
        return int(wrapper[0].get('TotalJobsCount') or 0)
    except Exception:
        return 0


def _scrape_oracle_nested(portal: Portal, headers: dict, max_jobs: int | None = None) -> list[dict] | None:
    base_url = portal['endpoint']
    page_limit = min(max_jobs or 100, 100)
    offset = 0
    total = None
    jobs: list[dict] = []
    seen_ids = set()

    while True:
        page_url = _oracle_page_url(base_url, limit=page_limit, offset=offset)
        r = _fetch_response(page_url, headers)
        if r is None:
            return jobs if jobs else None
        if not _is_json_response(r):
            return [{'_needs_firecrawl': True, '_url': page_url, '_company': portal['company'],
                     '_platform': portal.get('ats', 'Custom')}]

        try:
            data = r.json()
        except Exception:
            _log.error(f"    [ERROR] Oracle JSON decode failed: {page_url}")
            return jobs if jobs else None

        total = total or _oracle_total_count(data)
        page_jobs = _parse_json_response(data, portal, page_url, max_jobs=None, headers=headers)
        for job in page_jobs:
            jid = job.get('job_id') or job_hash(job.get('title', ''), job.get('job_url', ''))
            if jid in seen_ids:
                continue
            seen_ids.add(jid)
            jobs.append(job)
            if max_jobs and len(jobs) >= max_jobs:
                return jobs[:max_jobs]

        if not page_jobs:
            break
        offset += page_limit
        if total and offset >= total:
            break

    return jobs


def scrape_get(portal: Portal, max_jobs: int | None = None) -> list[dict] | None:
    """Best-effort GET-based scraper for Amazon, Microsoft, Apple, SAP, etc.
    Returns None on hard request error (caller maps to ScrapeReason.API_BLOCKED).
    Returns [] with _needs_firecrawl sentinel when HTML detected.
    """
    url = portal['endpoint']
    if not url.startswith('http'):
        _log.warning(f"    [SKIP] {portal['company']}: endpoint not a URL")
        return None

    headers = dict(_HEADERS)
    for domain, extra in _EXTRA_HEADERS.items():
        if domain in url:
            headers.update(extra)
            break

    if portal.get('oracle_nested'):
        return _scrape_oracle_nested(portal, headers, max_jobs=max_jobs)

    r = _fetch_response(url, headers)
    if r is None:
        return None

    if _is_json_response(r):
        try:
            return _parse_json_response(r.json(), portal, url, max_jobs=max_jobs)
        except Exception:
            pass

    return [{'_needs_firecrawl': True, '_url': url, '_company': portal['company'],
             '_platform': portal.get('ats', 'Custom')}]


_ITEMS_KEYS = ['jobPostings', 'jobs', 'results', 'data', 'items']


_ORACLE_HTML_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html",
}

_DETAIL_JD_MIN_CHARS = 1200


def _fetch_oracle_html_jd(host: str, site_num: str, jid: str) -> str:
    """Fetch Oracle CandidateExperience job page; extract og:description when API JD is empty."""
    url = f"https://{host}/hcmUI/CandidateExperience/en/sites/{site_num}/job/{jid}"
    try:
        r = requests.get(url, headers=_ORACLE_HTML_HEADERS, timeout=REQUEST_TIMEOUT)
        if r.status_code != 200:
            return ""
        m = re.search(r'<meta property="og:description" content="(.*?)"', r.text)
        return m.group(1) if m else ""
    except Exception:
        return ""


def _fetch_oracle_detail_jd(host: str, site_num: str, jid: str, headers: dict) -> str:
    """Read the full public Oracle HCM requisition payload, not its list teaser."""
    finder = f'ById;siteNumber={site_num},Id="{jid}"'
    query = urlencode({"expand": "all", "onlyData": "true", "finder": finder})
    url = (
        f"https://{host}/hcmRestApi/resources/latest/"
        f"recruitingCEJobRequisitionDetails?{query}"
    )
    r = _fetch_response(url, headers)
    if r is None or not _is_json_response(r):
        return ""
    try:
        data = r.json()
    except Exception:
        return ""

    # Oracle tenants return the requisition at the root today; retain the
    # collection form for older CandidateExperience deployments.
    detail = data
    if isinstance(data, dict) and isinstance(data.get("items"), list) and data["items"]:
        detail = data["items"][0]
    if not isinstance(detail, dict):
        return ""

    parts: list[str] = []
    for field in (
        "ExternalDescriptionStr",
        "ExternalResponsibilitiesStr",
        "ExternalQualificationsStr",
    ):
        value = strip_html(detail.get(field) or "")
        if value and value not in parts:
            parts.append(value)
    return "\n\n".join(parts)


def _extract_oracle_nested(data: dict) -> list[dict]:
    """Oracle HCM finder=findReqs response: jobs at items[0].requisitionList[]."""
    wrapper = data.get('items')
    if not isinstance(wrapper, list) or not wrapper:
        return []
    req_list = wrapper[0].get('requisitionList') if isinstance(wrapper[0], dict) else None
    return req_list if isinstance(req_list, list) else []


def _parse_oracle_job(p: dict, host: str, site_num: str = "careers") -> dict:
    """Map Oracle HCM field names (Title, Id, PrimaryLocation) to canonical shape."""
    title = p.get('Title') or p.get('title') or ''
    loc_raw = p.get('PrimaryLocation') or p.get('primaryLocation') or ''
    loc = loc_raw if isinstance(loc_raw, str) else ''
    jid = str(p.get('Id') or p.get('requisitionId') or p.get('id') or job_hash(title, ''))
    site = site_num or "careers"
    job_url = f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{jid}" if jid else ''
    return {
        '_title': title,
        '_loc':   loc,
        '_jid':   jid,
        '_url':   job_url,
        '_jd':    strip_html(p.get('ExternalDescriptionStr') or p.get('ShortDescriptionStr') or p.get('jobDescription') or ''),
        '_date':  p.get('PostedDate') or p.get('ExternalPostedStartDate') or '',
    }


def _parse_json_response(
    data,
    portal: Portal,
    source_url: str,
    max_jobs: int | None = None,
    headers: dict | None = None,
) -> list[dict]:
    """Walk common JSON structures to extract job listings.
    Checks generic_registry.json first — skips discovery for known companies.
    Persists successful key-path after first discovery so next run is instant.
    """
    platform = portal.get('ats', 'Custom').title()
    company  = portal.get('company', '')

    # Oracle HCM nested response (finder=findReqs): items[0].requisitionList[]
    if portal.get('oracle_nested'):
        raw_items = _extract_oracle_nested(data)
        host = source_url.split('/hcmRestApi')[0].removeprefix('https://').removeprefix('http://')
        site_m = re.search(r'siteNumber=([^,&]+)', source_url)
        site_num = site_m.group(1) if site_m else ''
        jobs = []
        for p in raw_items:
            if not isinstance(p, dict):
                continue
            mapped = _parse_oracle_job(p, host, site_num)
            if not mapped['_title']:
                continue
            india_only = portal.get('india_only', True)
            if india_only and not is_india(mapped['_loc']):
                continue
            jd = mapped['_jd']
            if len(jd) < _DETAIL_JD_MIN_CHARS and site_num and mapped['_jid']:
                detail_jd = _fetch_oracle_detail_jd(
                    host,
                    site_num,
                    mapped['_jid'],
                    headers or _HEADERS,
                )
                if len(detail_jd) > len(jd):
                    jd = detail_jd
            if not jd and site_num and mapped['_jid']:
                jd = _fetch_oracle_html_jd(host, site_num, mapped['_jid'])
            jobs.append({
                'job_id':          mapped['_jid'],
                'title':           mapped['_title'],
                'job_url':         mapped['_url'],
                'source_api_url':  source_url,
                'business_unit':   None,
                'raw_jd_text':     jd,
                'location_city':   mapped['_loc'],
                'date_posted':     mapped['_date'],
                'source_platform': 'Oracle',
                'industry':        portal.get('industry', ''),
            })
            if max_jobs and len(jobs) >= max_jobs:
                break
        return jobs

    # Registry fast-path: use known key if available
    reg = _load_generic_registry().get(company, {})
    items_key = reg.get('items_key')
    if items_key:
        items = data.get(items_key) if items_key != '__list__' else (data if isinstance(data, list) else [])
    else:
        # Discovery: flat list short-circuit (e.g. Infosys returns bare [])
        if isinstance(data, list):
            items = data
            discovered_key = '__list__'
        else:
            # Discovery: try each key in order
            items = None
            discovered_key = None
            for k in _ITEMS_KEYS:
                v = data.get(k)
                if isinstance(v, list) and v:
                    items = v
                    discovered_key = k
                    break
        if items is None:
            if isinstance(data, list) and data:
                items = data
                discovered_key = '__list__'
            else:
                items = []
        if discovered_key and company:
            _persist_field_map(company, {'items_key': discovered_key})

    if not isinstance(items, list):
        return []

    jobs = []
    for p in items:
        if not isinstance(p, dict):
            continue

        # Unwrap single-key {data: {...}} envelope (ZS Associates pattern)
        if list(p.keys()) == ['data'] and isinstance(p.get('data'), dict):
            p = p['data']

        title = (
            p.get('title') or p.get('name') or p.get('jobTitle') or
            p.get('postingTitle') or ''
        )
        if not title:
            continue

        raw_loc = (
            p.get('normalized_location') or p.get('location') or
            p.get('full_location') or p.get('city') or p.get('country') or
            p.get('locations') or ''
        )
        if isinstance(raw_loc, str):
            loc = raw_loc
        elif isinstance(raw_loc, dict):
            loc = raw_loc.get('city') or raw_loc.get('name') or raw_loc.get('label') or ''
        elif isinstance(raw_loc, list):
            loc_parts = []
            for x in raw_loc:
                if isinstance(x, str):
                    loc_parts.append(x)
                elif isinstance(x, dict):
                    loc_parts.append(x.get('city') or x.get('name') or x.get('label') or '')
            loc = ' | '.join([s for s in loc_parts if s])
        else:
            loc = ''

        india_only = portal.get('india_only', True)
        if india_only and not is_india(loc):
            continue

        if company == "Infosys":
            # The Infosys listing response is already the detail source, but
            # its substantive responsibilities are not stored in the generic
            # description keys.  Prefer those fields over a card summary.
            infosys_parts = []
            for field in (
                "postingDescription",
                "rolesResponsibilities",
                "technicalRequirement",
                "additionalResponsibility",
                "educationalRequirement",
            ):
                value = strip_html(p.get(field) or "")
                if value and value not in infosys_parts:
                    infosys_parts.append(value)
            raw_jd = "\n\n".join(infosys_parts)
        else:
            raw_jd = strip_html(
                p.get('description') or p.get('jobDescription') or
                p.get('content') or p.get('summary') or
                p.get('postingDescription') or ''
            )
        if not raw_jd:
            # Atlassian / similar portals split JD across multiple sections.
            jd_parts = []
            if p.get('overview'):
                jd_parts.append(f"Overview: {p.get('overview')}")
            if p.get('responsibilities'):
                jd_parts.append(f"Responsibilities: {p.get('responsibilities')}")
            if p.get('qualifications'):
                jd_parts.append(f"Qualifications: {p.get('qualifications')}")
            raw_jd = strip_html('\n\n'.join(jd_parts))
        job_path = p.get('job_path', '')
        ref_code = p.get('referenceCode') or ''
        job_url = (
            p.get('url') or p.get('job_url') or p.get('absolute_url') or
            p.get('apply_job_url') or p.get('applyUrl') or p.get('ref') or
            (f"https://jobs.zs.com/all/jobs/{p.get('slug')}" if p.get('slug') else '') or
            (f"https://career.infosys.com/jobdesc?referenceCode={ref_code}" if ref_code else '') or
            (f"https://www.amazon.jobs{job_path}" if job_path else '') or ''
        )
        jid = str(
            p.get('referenceCode') or p.get('id_icims') or p.get('id') or
            p.get('jobId') or p.get('postingId') or p.get('slug') or p.get('req_id') or
            job_hash(title, job_url)
        )
        bu = (
            p.get('business_category') or p.get('department') or
            p.get('team') or p.get('category') or p.get('unit') or
            p.get('functionalArea')
        )
        if isinstance(bu, dict):
            bu = bu.get('label') or bu.get('name')

        jobs.append({
            'job_id':          jid,
            'title':           title,
            'job_url':         job_url,
            'source_api_url':  source_url,
            'business_unit':   bu,
            'raw_jd_text':     raw_jd,
            'location_city':   loc,
            'date_posted':     (
                p.get('posted_date') or p.get('date_posted') or
                p.get('updated_at') or p.get('releasedDate') or
                p.get('createdOn')
            ),
            'source_platform': platform,
            'industry':        portal.get('industry', ''),
        })
        if max_jobs and len(jobs) >= max_jobs:
            break
    return jobs
