"""Motherson Group careers site (careers.motherson.com).

The site is a Next.js front end. ``/en/jobs`` embeds every open posting
worldwide in its ``__NEXT_DATA__`` script; each posting's full description is
in that page's Next.js data route (``/_next/data/{buildId}/{locale}/job/{slug}.json``).
Candidates apply on the ATS the posting's ``applyUrl`` names - SAP
SuccessFactors for most, ``apply.motherson.com`` for the rest.

A posting whose apply host does not exist in DNS is left out: its Apply button
leads to an error page. The check runs every scrape, so those postings come
back on their own once the host resolves again.
"""

from __future__ import annotations

import json
import logging
import re
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import requests

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import strip_html

_log = logging.getLogger("mirror")
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S
)
_REQ_ID_RE = re.compile(r"-(\d+)$")
_COUNTRY = "India"
_WORKERS = 4
# Cloudflare's WAF answers about 1 request in 50-100 with "Sorry, you have
# been blocked" (403), at random and at any concurrency; the same URL loads
# on the next try.
_RETRY_STATUS = {403, 429, 500, 502, 503, 504}
_ATTEMPTS = 3
_RETRY_PAUSE_S = 1.0
# The page's own headings, in reading order for the JD.
_SECTIONS = (
    ("introduction", ""),
    ("tasks", "What you'll do"),
    ("profile", "What we are looking for"),
    ("whatWeOffer", "What we offer"),
)
# getaddrinfo codes that mean "this name does not exist", not "DNS is down".
_NO_SUCH_HOST = {socket.EAI_NONAME} | (
    {socket.EAI_NODATA} if hasattr(socket, "EAI_NODATA") else set()
)


class _LayoutChanged(Exception):
    pass


def parse_listing(page_html: str) -> tuple[str, str, list[dict]]:
    """Return (buildId, locale, every posting) from the /jobs page."""
    match = _NEXT_DATA_RE.search(page_html)
    if not match:
        raise _LayoutChanged("no __NEXT_DATA__ script")
    try:
        data = json.loads(match.group(1))
    except ValueError as exc:
        raise _LayoutChanged(f"__NEXT_DATA__ is not JSON: {exc}") from exc
    jobs = ((data.get("props") or {}).get("pageProps") or {}).get("allJobs")
    if not isinstance(jobs, list) or not data.get("buildId"):
        raise _LayoutChanged("no allJobs or buildId in __NEXT_DATA__")
    return data["buildId"], data.get("locale") or "en", jobs


def _get(url: str) -> requests.Response:
    response = None
    for attempt in range(_ATTEMPTS):
        if attempt:
            time.sleep(_RETRY_PAUSE_S * attempt)
        response = requests.get(url, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
        if response.status_code not in _RETRY_STATUS:
            break
    response.raise_for_status()
    return response


def _country(job: dict) -> str:
    return (((job.get("location") or {}).get("country") or {}).get("name") or "").strip()


def _origin(endpoint: str) -> str:
    parts = urlparse(endpoint)
    return f"{parts.scheme}://{parts.netloc}"


def detail_url(origin: str, build_id: str, locale: str, slug: str) -> str:
    return f"{origin}/_next/data/{build_id}/{locale}/job/{slug}.json"


def jd_text(job: dict) -> str:
    facts = [
        ("Career level", (job.get("careerLevel") or {}).get("name")),
        ("Division", (job.get("businessDivision") or {}).get("name")),
        ("Hours per week", job.get("hoursPerWeek")),
    ]
    parts = ["\n".join(f"{label}: {value}" for label, value in facts if value)]
    for field, heading in _SECTIONS:
        text = strip_html(job.get(field) or "").strip()
        if not text.strip("- \n"):
            continue
        parts.append(f"{heading}\n{text}" if heading else text)
    return "\n\n".join(p for p in parts if p)


def _resolves(host: str) -> bool:
    """False only when DNS answers that the host does not exist."""
    try:
        socket.getaddrinfo(host, 443)
    except socket.gaierror as exc:
        return exc.errno not in _NO_SUCH_HOST
    return True


def job_record(job: dict, endpoint: str, locale: str, industry: str) -> dict:
    slug = job["slug"]
    req = _REQ_ID_RE.search(slug)
    company = (job.get("company") or {}).get("name") or ""
    division = (job.get("businessDivision") or {}).get("name") or ""
    city = ((job.get("location") or {}).get("name") or "").strip()
    return {
        "job_id": req.group(1) if req else job["id"],
        "title": (job.get("title") or "").strip(),
        "job_url": f"{_origin(endpoint)}/{locale}/job/{slug}",
        "source_api_url": endpoint,
        "business_unit": company or division,
        "raw_jd_text": jd_text(job),
        "location_city": f"{city}, {_COUNTRY}" if city else _COUNTRY,
        "date_posted": "",
        "source_platform": "Motherson Careers",
        "industry": industry,
    }


class MothersonCareersProvider:
    key = "motherson_careers"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        endpoint = (portal.get("endpoint") or "").strip()
        if not endpoint.startswith("http"):
            return ProviderResult.error(ScrapeReason.CONFIG_ERROR, "bad_motherson_endpoint")
        try:
            listing = _get(endpoint)
            build_id, locale, postings = parse_listing(listing.text)
        except _LayoutChanged as exc:
            return ProviderResult.error(ScrapeReason.PARSE_ERROR, str(exc))
        except requests.RequestException as exc:
            return ProviderResult.error(ScrapeReason.API_BLOCKED, str(exc))

        if postings and not any(_country(p) for p in postings):
            return ProviderResult.error(ScrapeReason.PARSE_ERROR, "postings_without_country")
        india = [p for p in postings if _country(p) == _COUNTRY and p.get("slug")]
        india = india[: max_jobs or len(india)]
        origin = _origin(endpoint)

        def fetch(posting: dict) -> tuple[dict, dict | None, str]:
            url = detail_url(origin, build_id, locale, posting["slug"])
            try:
                response = _get(url)
                job = (response.json().get("pageProps") or {}).get("job")
            except (requests.RequestException, ValueError) as exc:
                return posting, None, str(exc)
            return posting, job, "" if job else "no_job_in_data_route"

        with ThreadPoolExecutor(max_workers=_WORKERS) as pool:
            fetched = list(pool.map(fetch, india))

        host_alive: dict[str, bool] = {}
        jobs: list[dict] = []
        failures: list[str] = []
        dead_apply: list[str] = []
        for posting, job, error in fetched:
            if job is None:
                failures.append(f"{posting['slug']}: {error}")
                continue
            host = urlparse(job.get("applyUrl") or "").hostname or ""
            if host and host not in host_alive:
                host_alive[host] = _resolves(host)
            if not host or not host_alive[host]:
                dead_apply.append(f"{posting['slug']} ({host or 'no apply url'})")
                continue
            jobs.append(job_record(job, endpoint, locale, portal.get("industry", "")))

        if dead_apply:
            _log.warning(
                "    left out %s Motherson postings whose apply host does not exist; first=%s",
                len(dead_apply),
                dead_apply[0],
            )
        if failures:
            return ProviderResult.partial(
                jobs, f"motherson_detail_failures={len(failures)}; first={failures[0]}"
            )
        _log.info("    %s India jobs via careers.motherson.com", len(jobs))
        return ProviderResult.success(jobs)
