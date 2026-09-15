from __future__ import annotations

from schema import Portal

import json
import logging
import re
import threading
import requests
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import firecrawl_client as fc
from config import REQUEST_TIMEOUT, WORKDAY_PAGE_SIZE, WORKDAY_MAX_JOBS, WORKDAY_JD_FETCH_LIMIT
from providers.base import FALLBACK_FIRECRAWL_EXTRACT, ProviderResult, ScrapeReason
from utils import is_india, job_hash, strip_html, workday_req_id
from scrape_select import select_for_cap

_REGISTRY_PATH = Path(__file__).parent.parent / "workday_registry.json"
_registry_lock = threading.Lock()

_log = logging.getLogger("mirror")

_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type":    "application/json",
}

_WORKDAY_BLOCKED = object()  # sentinel: API redirected/errored → try Firecrawl
_LOCALE_SEGMENT = re.compile(r"^[a-z]{2}(?:-[a-z]{2})?$", re.IGNORECASE)


def _workday_public_url(portal: Portal, external_path: str) -> str:
    """Return the addressable public URL for a Workday CXS posting.

    Workday's list API returns ``externalPath`` relative to the configured
    career site (usually ``/job/...``). The public router needs that site slug
    between the optional locale and the job path. Preserve a site already
    present so alternate CXS payload shapes cannot duplicate it.
    """
    external_path = (external_path or "").strip()
    tenant = (portal.get("tenant") or "").strip()
    instance = (portal.get("instance") or "").strip()
    career_site = (portal.get("career_site") or "").strip()
    if not external_path or not tenant or not instance or not career_site:
        return ""

    parsed = urlsplit(external_path)
    segments = [segment for segment in parsed.path.split("/") if segment]
    if not segments:
        return ""

    site_index = 1 if _LOCALE_SEGMENT.fullmatch(segments[0]) else 0
    if len(segments) <= site_index or segments[site_index].casefold() != career_site.casefold():
        segments.insert(site_index, career_site)

    path = "/" + "/".join(segments)
    if parsed.path.endswith("/"):
        path += "/"
    host = f"{tenant}.{instance}.myworkdayjobs.com"
    return urlunsplit(("https", host, path, parsed.query, parsed.fragment))


class WorkdayProvider:
    key = "workday"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
        on_page_complete=None,
    ) -> ProviderResult:
        # Skip API entirely for Cloudflare-blocked tenants — go straight to Firecrawl
        if portal.get('workday_blocked'):
            _log.info(f"    [BLOCKED] {portal.get('company','')} — Cloudflare-blocked Workday, skip to Firecrawl")
            fallback_portal = dict(portal)
            if portal.get("careers_url"):
                fallback_portal["endpoint"] = portal["careers_url"]
            return ProviderResult.fallback(
                policy=FALLBACK_FIRECRAWL_EXTRACT,
                reason="workday_cloudflare_blocked",
                portal=fallback_portal,
            )

        jobs, reason = scrape_workday(portal, max_jobs=max_jobs, validate_mode=validate_mode,
                                      on_page_complete=on_page_complete)

        # Global mode returned 0 or blocked → retry with India UUID before giving up
        if not portal.get('india_only', True):
            should_retry = (
                (jobs is None and reason == ScrapeReason.API_BLOCKED) or
                (isinstance(jobs, list) and len(jobs) == 0 and reason == ScrapeReason.NO_JOBS)
            )
            if should_retry:
                _log.info(f"    [RETRY] Global 0/422 — retrying {portal.get('company','')} with India UUID")
                india_portal = {**portal, 'india_only': True}
                jobs2, reason2 = scrape_workday(india_portal, max_jobs=max_jobs, validate_mode=validate_mode,
                                                on_page_complete=on_page_complete)
                if jobs2 is not None and (len(jobs2) > 0 or jobs is None):
                    return ProviderResult(jobs=jobs2, reason=reason2)
                # India UUID also failed → fall through to Firecrawl
                if jobs is None or reason == ScrapeReason.API_BLOCKED:
                    fallback_portal = dict(portal)
                    if portal.get("careers_url"):
                        fallback_portal["endpoint"] = portal["careers_url"]
                    return ProviderResult.fallback(
                        policy=FALLBACK_FIRECRAWL_EXTRACT,
                        reason="workday_api_blocked",
                        portal=fallback_portal,
                    )

        if jobs is None:
            if reason == ScrapeReason.API_BLOCKED:
                fallback_portal = dict(portal)
                if portal.get("careers_url"):
                    fallback_portal["endpoint"] = portal["careers_url"]
                return ProviderResult.fallback(
                    policy=FALLBACK_FIRECRAWL_EXTRACT,
                    reason="workday_api_blocked",
                    portal=fallback_portal,
                )
            # CONFIG_ERROR: no India UUID found — skip, no Firecrawl fallback
            return ProviderResult.error(reason)
        return ProviderResult(jobs=jobs, reason=reason)


def scrape_workday(
    portal: Portal,
    max_jobs: int | None = None,
    validate_mode: bool = False,
    on_page_complete=None,  # Callable[[list[dict], int], None] | None
) -> tuple[list[dict] | None, ScrapeReason]:
    """
    Returns (jobs, reason):
      ([...], SUCCESS/NO_JOBS)  — normal result
      (None,  API_BLOCKED)      — Cloudflare / HTTP redirect → try Firecrawl
      (None,  CONFIG_ERROR)     — no India UUID found for tenant → skip, no fallback

    Cap behavior (Phase B):
      - validate_mode or streaming (per-page JD via on_page_complete): the cap is an
        early pagination stop (cheap, order-agnostic) — unchanged legacy behavior.
      - standard capped run: page the FULL India listing (metadata only), then
        quality-select the top `max_jobs` on title/career_band, fetch JDs for exactly
        that set, and drop any that still have no JD. This is what stops a big Workday
        integrator (Accenture) from losing its technical tail to pagination order.
    """
    endpoint = portal['endpoint']
    india_only = portal.get('india_only', True)

    company = portal.get('company', '')
    if india_only:
        use_search_text = bool(portal.get('workday_search_text'))
        if use_search_text:
            search_text_val = portal['workday_search_text']
            _log.info(f"    [REGISTRY] Using searchText='{search_text_val}' for {company}")
        elif portal.get('workday_facet_param'):
            facet_param = portal['workday_facet_param']
            india_uuids = portal.get('workday_india_uuids') or []
            _log.info(f"    [REGISTRY] Using hardcoded facet IDs for {company}")
        else:
            uuid_result = _workday_india_uuid(endpoint)
            if uuid_result is _WORKDAY_BLOCKED:
                return None, ScrapeReason.API_BLOCKED
            if uuid_result is None:
                _log.warning(f"    [WARN] no India UUID found for {company}")
                return None, ScrapeReason.CONFIG_ERROR
            facet_param, india_uuid = uuid_result
            india_uuids = [india_uuid]
            # Persist discovered UUID → next run skips discovery entirely
            _persist_uuid(company, facet_param, india_uuid)
    else:
        use_search_text = False
        search_text_val = ""
        facet_param = ""
        india_uuids = []
        _log.info(f"    [SCOPE] Global mode for {company} (no India facet filter)")

    parts = endpoint.split('/')
    referer = '/'.join(parts[:3]) + '/' + parts[-2] if len(parts) >= 8 else endpoint
    headers = {**_HEADERS, "Referer": referer}

    jobs, offset, page_num = [], 0, 0
    seen_ids: set[str] = set()
    while True:
        if not india_only:
            facets = {}
        elif use_search_text:
            facets = {}
        else:
            facets = {facet_param: india_uuids}
            if portal.get('workday_it_uuids'):
                facets[portal['workday_it_facet_param']] = portal['workday_it_uuids']
        payload = {
            "appliedFacets": facets,
            "limit":  WORKDAY_PAGE_SIZE,
            "offset": offset,
            "searchText": search_text_val if use_search_text else "",
        }
        try:
            r = requests.post(endpoint, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            _log.error(f"    [ERROR] Workday {portal['company']} offset={offset}: {e}")
            if offset == 0:
                return None, ScrapeReason.API_BLOCKED
            break

        postings = data.get('jobPostings', [])
        new_on_page = 0
        for p in postings:
            ext = p.get('externalPath', '')
            # CXS list endpoint has no 'jobReqId'; derive the requisition id from
            # bulletFields[0] / the _R… path tail, hash only as last resort.
            jid = p.get('jobReqId') or workday_req_id(p, ext) or ''
            if jid and jid in seen_ids:
                continue
            if jid:
                seen_ids.add(jid)
            new_on_page += 1

            url = _workday_public_url(portal, ext)
            loc = p.get('locationsText') or p.get('primaryLocation', '')
            if india_only and use_search_text and not is_india(loc):
                continue
            bf  = p.get('bulletFields') or []
            bu  = bf[1] if len(bf) > 1 else None
            job = {
                'job_id':          jid or job_hash(p.get('title', ''), url),
                'title':           p.get('title', ''),
                'job_url':         url,
                'source_api_url':  endpoint,
                'business_unit':   bu,
                'raw_jd_text':     strip_html(p.get('jobDescription', '')),
                'location_city':   loc,
                'date_posted':     p.get('postedOn'),
                'source_platform': 'Workday',
                'industry':        portal.get('industry', ''),
                '_ext':            ext,
            }
            jobs.append(job)

        # Listing pagination is metadata-only now; JDs are fetched after selection
        # (Phase B) so a big tenant does not fetch JDs for roles the cap will drop.
        page_num += 1

        if new_on_page == 0 or len(postings) < WORKDAY_PAGE_SIZE:
            break
        # Only validate mode early-stops at the cap. A real run pages the full India
        # listing so the quality selector can rank the whole pool before JD fetch.
        if max_jobs and validate_mode and len(jobs) >= max_jobs:
            _log.info(f"    [WORKDAY] Validate cap reached ({max_jobs} jobs) — stopping pagination")
            break
        if len(jobs) >= WORKDAY_MAX_JOBS:
            _log.info(f"    [WORKDAY] Listing ceiling reached ({WORKDAY_MAX_JOBS}) — stopping pagination")
            break
        offset += WORKDAY_PAGE_SIZE

    # ── Cap + JD fetch (Phase B) ──────────────────────────────────────────────
    # The loop above listed metadata only. Choose the roles to keep, then fetch JDs
    # for exactly that set, flushing in chunks (durability during the slow JD phase).
    # A quality-capped company (over the cap) ranks technical/JD-first and drops any
    # selected role that still has no JD — a role we cannot explain is not indexed.
    quality_cap = bool(max_jobs) and not validate_mode and len(jobs) > max_jobs
    if quality_cap:
        before = len(jobs)
        selected = select_for_cap(jobs, max_jobs)
        _log.info(f"    [WORKDAY] Quality cap: {before} listed → {len(selected)} selected (technical/JD-first)")
    elif max_jobs:
        selected = jobs[:max_jobs]
    else:
        selected = jobs

    budget = max_jobs if max_jobs else len(selected)
    kept: list[dict] = []
    fetched = 0
    for ci, i in enumerate(range(0, len(selected), WORKDAY_PAGE_SIZE)):
        chunk = selected[i:i + WORKDAY_PAGE_SIZE]
        remaining = budget - fetched
        if remaining > 0:
            need = min(sum(1 for j in chunk if not j.get('raw_jd_text') and j.get('_ext')), remaining)
            _fetch_workday_jds(chunk, portal, limit=need)
            fetched += need
        if quality_cap:
            chunk = [j for j in chunk if (j.get('raw_jd_text') or '').strip()]
        kept.extend(chunk)
        if on_page_complete and chunk:
            on_page_complete(chunk, ci)
    jobs = kept
    if quality_cap:
        _log.info(f"    [WORKDAY] Quality cap: {len(jobs)} kept with JD")

    reason = ScrapeReason.SUCCESS if jobs else ScrapeReason.NO_JOBS
    return jobs, reason


def _persist_uuid(company: str, facet_param: str, india_uuid: str) -> None:
    """Write discovered India UUID back to workday_registry.json (thread-safe).
    Only writes if company has no existing registry entry — never overwrites manual entries.
    """
    with _registry_lock:
        try:
            registry = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8")) if _REGISTRY_PATH.exists() else {}
            if company in registry:
                return  # manual entry takes precedence
            registry[company] = {"india_facet_param": facet_param, "india_uuid": india_uuid}
            _REGISTRY_PATH.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")
            _log.info(f"    [REGISTRY] Persisted India UUID for {company} ({facet_param}={india_uuid[:8]}…)")
        except Exception as e:
            _log.warning(f"    [REGISTRY] Failed to persist UUID for {company}: {e}")


def _workday_india_uuid(endpoint: str):
    """POST with empty facets, recursively search response for 'India' UUID.
    Returns: (facet_param, uuid) | None (no India facet) | _WORKDAY_BLOCKED (redirect/error)
    """
    parts = endpoint.split('/')
    referer = '/'.join(parts[:3]) + '/' + parts[-2] if len(parts) >= 8 else endpoint
    headers = {**_HEADERS, "Referer": referer}
    try:
        r = requests.post(
            endpoint,
            json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
            headers=headers,
            timeout=REQUEST_TIMEOUT,
            allow_redirects=False,
        )
        if r.status_code in (301, 302, 303, 307, 308):
            _log.error(f"    [ERROR] Workday UUID discovery: redirect {r.status_code} — API blocked (Cloudflare)")
            return _WORKDAY_BLOCKED
        r.raise_for_status()
        body = r.text.strip()
        if not body:
            _log.error("    [ERROR] Workday UUID discovery: empty response body")
            return _WORKDAY_BLOCKED
        return _find_india_id(r.json())
    except Exception as e:
        _log.error(f"    [ERROR] Workday UUID discovery: {e}")
        return _WORKDAY_BLOCKED


def _find_india_id(obj, _parent_facet_param: str = 'locationCountry') -> tuple[str, str] | None:
    """Recursively walk Workday facet JSON to find (facet_parameter, India UUID)."""
    if isinstance(obj, list):
        for item in obj:
            result = _find_india_id(item, _parent_facet_param)
            if result:
                return result
    elif isinstance(obj, dict):
        facet_param = obj.get('facetParameter', _parent_facet_param)
        descriptor = (obj.get('descriptor') or obj.get('name') or '').lower()
        if descriptor == 'india':
            uid = obj.get('id') or obj.get('value')
            return (facet_param, uid) if uid else None
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                result = _find_india_id(v, facet_param)
                if result:
                    return result
    return None


def _fetch_workday_jds(jobs: list[dict], portal: Portal, limit: int | None = None) -> None:
    """
    Fill raw_jd_text for Workday jobs.
    Strategy 1 — Workday CXS individual-job JSON API (fast, no credits).
    Strategy 2 — Firecrawl Docker batch_scrape on human-facing job_url (fallback when CXS is
                  Cloudflare-blocked; uses Docker so no credit cost).
    Mutates jobs in-place. Fetches at most `limit` missing JDs (default WORKDAY_JD_FETCH_LIMIT);
    the quality-cap path passes limit == the company cap so the whole selected set gets JDs.
    """
    tenant   = portal.get('tenant', '')
    instance = portal.get('instance', '')
    if not tenant or not instance:
        return

    to_fetch = [j for j in jobs if not j.get('raw_jd_text') and j.get('_ext')]
    to_fetch = to_fetch[:(limit or WORKDAY_JD_FETCH_LIMIT)]
    if not to_fetch:
        return

    career_site = portal.get('career_site', '')
    cxs_base = f"https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{career_site}"
    _log.info(f"    Fetching JDs for {len(to_fetch)}/{len(jobs)} jobs via Workday CXS API...")
    ok = fail = 0
    for job in to_fetch:
        detail_url = cxs_base + job['_ext']
        try:
            r = requests.get(detail_url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            info = r.json().get('jobPostingInfo', {})
            detail_location = _workday_detail_location(info)
            if detail_location:
                job['location_city'] = detail_location
            detail_locations = _workday_detail_locations(info, detail_location)
            if detail_locations:
                job['locations'] = detail_locations
            jd   = info.get('jobDescription', '') or info.get('jobSummary', '')
            if jd:
                job['raw_jd_text'] = strip_html(jd)
                ok += 1
            else:
                fail += 1
        except Exception:
            fail += 1

    _log.info(f"    JDs fetched (CXS): {ok} ok  {fail} missing/error")

    still_missing = [j for j in to_fetch if not j.get('raw_jd_text') and j.get('job_url')]
    if still_missing and ok == 0:
        urls = [j['job_url'] for j in still_missing]
        _log.info(f"    [FC FALLBACK] Scraping {len(urls)} Workday JD pages via Docker...")
        BATCH = 20
        fc_ok = 0
        for i in range(0, len(urls), BATCH):
            batch_urls = urls[i:i + BATCH]
            results = fc.batch_scrape(batch_urls)
            for job in still_missing[i:i + BATCH]:
                md = results.get(job['job_url'], '')
                if md and len(md) > 500:
                    job['raw_jd_text'] = md
                    fc_ok += 1
        _log.info(f"    [FC FALLBACK] JDs via Firecrawl: {fc_ok} ok  {len(still_missing) - fc_ok} missing")


def _workday_detail_location(info: dict) -> str:
    """Return the most concrete location string from a Workday detail payload."""
    location = info.get('location')
    if isinstance(location, str) and location.strip():
        return location.strip()
    if isinstance(location, dict):
        descriptor = location.get('descriptor')
        if isinstance(descriptor, str) and descriptor.strip():
            return descriptor.strip()

    req_location = info.get('jobRequisitionLocation')
    if isinstance(req_location, dict):
        descriptor = req_location.get('descriptor')
        if isinstance(descriptor, str) and descriptor.strip():
            return descriptor.strip()

    country = info.get('country')
    if isinstance(country, dict):
        descriptor = country.get('descriptor')
        if isinstance(descriptor, str) and descriptor.strip():
            return descriptor.strip()
    return ''


def _workday_detail_locations(info: dict, primary: str = '') -> list[str]:
    """All cities for a multi-location Workday posting (firecrawl #6).

    Workday CXS detail returns extra cities under additionalLocations (list of
    {descriptor}). Combine with the primary location, deduped and ordered.
    """
    out: list[str] = []
    if primary and primary.strip():
        out.append(primary.strip())
    additional = info.get('additionalLocations')
    if isinstance(additional, list):
        for entry in additional:
            descriptor = ''
            if isinstance(entry, str):
                descriptor = entry
            elif isinstance(entry, dict):
                descriptor = entry.get('descriptor') or ''
            descriptor = descriptor.strip() if isinstance(descriptor, str) else ''
            if descriptor and descriptor not in out:
                out.append(descriptor)
    return out
