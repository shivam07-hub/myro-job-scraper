"""Avature careers provider (server-rendered SearchJobs HTML).

Built on Macquarie's board (recruitment.macquarie.com, 2026-11-15):

- Listing: ``GET {endpoint}&jobOffset=N``. The endpoint carries the board's own
  country facet (Macquarie India: ``10671=[871433]``). The board serves 9 cards
  a page whatever ``jobRecordsPerPage`` asks for, and a page past the end is a
  200 with no cards. Each card (``article--result``) links
  ``JobDetail?jobId=N`` and ``ApplicationMethods?jobId=N`` and shows the
  office, posted date and job category. ``aria-label="70 results"`` is the
  total.
- Detail: ``GET JobDetail?jobId=N``. The first ``article--details`` block holds
  named fields (``field--location``, ``field--date``, ``field--employmentterm``
  and one labelled "Job category"); the later blocks are the description, most
  under an ``<h3>`` section heading.
- Apply: the card's ``ApplicationMethods`` link opens the CV-upload form
  without a login, so it is the job's apply URL.

Each page takes about 3.5 s, so a fetch that fails for a transport reason is
retried before it counts.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
import time
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests

from config import REQUEST_TIMEOUT
from job_cap import job_limit
from providers.base import FALLBACK_FIRECRAWL_EXTRACT, ProviderResult, ScrapeReason, is_transport_status
from schema import Portal
from utils import is_india, strip_html

_log = logging.getLogger("mirror")
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_MAX_PAGES = 300
_ATTEMPTS = 3
_RETRY_PAUSE_S = 1.0
_DATE_FORMATS = ("%d %b %Y", "%d-%b-%Y")

_CARD_RE = re.compile(r'<article class="article article--result[^"]*">(?P<body>.*?)</article>', re.S)
_DETAIL_LINK_RE = re.compile(
    r'<a class="link" href="(?P<url>[^"]*/JobDetail\?jobId=(?P<id>\d+)[^"]*)"[^>]*>(?P<title>.*?)</a>', re.S
)
_APPLY_LINK_RE = re.compile(r'href="(?P<url>[^"]*/ApplicationMethods\?jobId=\d+[^"]*)"')
_CARD_DATA_RE = re.compile(r'<div class="article__details__data">(?P<body>.*?)</div>', re.S)
_CARD_KEY_RE = re.compile(r'alt="(?P<alt>[^"]*?):?"|<p class="icon">(?P<icon>.*?)</p>', re.S)
_P_RE = re.compile(r"<p>(?P<text>.*?)</p>", re.S)
_TOTAL_RE = re.compile(r'aria-label="(?P<n>[\d,]+) results"')

_DETAILS_RE = re.compile(r'<article class="article article--details[^"]*">(?P<body>.*?)</article>', re.S)
_META_FIELD_RE = re.compile(
    r'<div class="article__content__view__field field--(?P<kind>[a-z]+)[^"]*">\s*'
    r'(?:<div class="article__content__view__field__label">(?P<label>.*?)</div>\s*)?'
    r'<div class="article__content__view__field__value">(?P<value>.*?)</div>',
    re.S,
)
_HEADING_RE = re.compile(r'<h3 class="article__header__text__title[^"]*">(?P<text>.*?)</h3>', re.S)
_HIDDEN_RE = re.compile(r'<p class="visibility--hidden--visually"[^>]*>.*?</p>', re.S)


class _LayoutChanged(Exception):
    pass


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", strip_html(fragment or "")).strip()


def _get(session: requests.Session, url: str) -> requests.Response:
    """GET with retries on timeouts, dropped connections, 429 and 5xx."""
    failure: requests.RequestException | None = None
    for attempt in range(_ATTEMPTS):
        if attempt:
            time.sleep(_RETRY_PAUSE_S * attempt)
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT)
        except (requests.ConnectionError, requests.Timeout) as exc:
            failure = exc
            continue
        if not is_transport_status(response.status_code):
            return response
        failure = requests.HTTPError(f"HTTP {response.status_code}", response=response)
    assert failure is not None
    raise failure


def _with_offset(endpoint: str, offset: int) -> str:
    parts = urlsplit(endpoint)
    params = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != "jobOffset"]
    params.append(("jobOffset", str(offset)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), parts.fragment))


def _iso_date(value: str) -> str:
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def _office(value: str) -> str:
    # Cards say "Gurugram Office"; the job page says "Gurugram".
    return re.sub(r"\s+Office$", "", value.strip())


def total_results(page_html: str) -> int | None:
    match = _TOTAL_RE.search(page_html)
    return int(match.group("n").replace(",", "")) if match else None


def parse_cards(page_html: str, page_url: str) -> list[dict]:
    cards = []
    for card in _CARD_RE.finditer(page_html):
        body = card.group("body")
        link = _DETAIL_LINK_RE.search(body)
        if not link:
            continue
        fields: dict[str, str] = {}
        for data in _CARD_DATA_RE.finditer(body):
            block = data.group("body")
            key = _CARD_KEY_RE.search(block)
            values = _P_RE.findall(block)
            if key and values:
                name = _text(key.group("alt") or key.group("icon") or "")
                fields[name.casefold()] = _text(values[-1])
        apply = _APPLY_LINK_RE.search(body)
        cards.append(
            {
                "job_id": link.group("id"),
                "title": _text(link.group("title")),
                "detail_url": urljoin(page_url, html_lib.unescape(link.group("url"))),
                "apply_url": urljoin(page_url, html_lib.unescape(apply.group("url"))) if apply else "",
                "office": _office(fields.get("office location", "")),
                "posted": fields.get("posted date", ""),
                "category": fields.get("job category", ""),
            }
        )
    return cards


def parse_detail(page_html: str) -> dict:
    """Named fields from the first block, the description from the rest."""
    blocks = [m.group("body") for m in _DETAILS_RE.finditer(page_html)]
    if not blocks:
        raise _LayoutChanged("job page has no article--details blocks")
    offices: list[str] = []
    detail = {"offices": offices, "date": "", "employment": "", "category": "", "raw_jd_text": ""}
    sections: list[str] = []
    for body in blocks:
        fields = list(_META_FIELD_RE.finditer(body))
        if fields:
            for field in fields:
                kind = field.group("kind")
                label = _text(field.group("label") or "").casefold()
                value = _text(field.group("value"))
                if kind == "location" and value:
                    offices.append(value)
                elif kind == "date":
                    detail["date"] = value
                elif kind == "employmentterm":
                    detail["employment"] = value
                elif label == "job category":
                    detail["category"] = value
            continue
        heading = _HEADING_RE.search(body)
        text = _text(_HEADING_RE.sub("", _HIDDEN_RE.sub("", body)))
        if not text:
            continue
        sections.append(f"{_text(heading.group('text'))}\n{text}" if heading else text)
    detail["raw_jd_text"] = "\n\n".join(sections)
    return detail


def _level(employment: str) -> str:
    # "Permanent - Full time, Junior" / "Fixed term, Entry level": the level
    # follows the last comma.
    return employment.rsplit(",", 1)[1].strip() if "," in employment else ""


def job_record(card: dict, detail: dict, page_url: str, industry: str) -> dict:
    offices = list(dict.fromkeys(detail["offices"])) or ([card["office"]] if card["office"] else [])
    return {
        "job_id": card["job_id"],
        "title": card["title"],
        "job_url": card["apply_url"] or card["detail_url"],
        "source_api_url": page_url,
        "business_unit": detail["category"] or card["category"],
        "raw_jd_text": detail["raw_jd_text"],
        "location_city": " | ".join(offices) or "India",
        "locations": offices,
        "date_posted": _iso_date(card["posted"]) or _iso_date(detail["date"]),
        "seniority_level": _level(detail["employment"]),
        "source_platform": "Avature",
        "industry": industry,
    }


class AvatureProvider:
    key = "avature"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        endpoint = (portal.get("endpoint") or portal.get("careers_url") or "").strip()
        if not endpoint.startswith("http") or "/SearchJobs" not in endpoint:
            return ProviderResult.error(ScrapeReason.CONFIG_ERROR, "bad_avature_searchjobs_url")
        company = portal["company"]
        industry = portal.get("industry", "")
        cap = job_limit(max_jobs)
        session = requests.Session()
        session.headers.update(_HEADERS)

        jobs: list[dict] = []
        seen: set[str] = set()
        outside_india = 0
        total: int | None = None
        offset = 0
        for page in range(_MAX_PAGES):
            page_url = _with_offset(endpoint, offset)
            try:
                response = _get(session, page_url)
                response.raise_for_status()
            except requests.RequestException as exc:
                if page == 0:
                    _log.warning(f"    [Avature] {company}: listing unreachable ({exc})")
                    return ProviderResult.fallback(policy=FALLBACK_FIRECRAWL_EXTRACT, reason="avature_unreachable")
                return ProviderResult.partial(jobs, f"avature_offset_{offset}: {exc}")

            if page == 0:
                total = total_results(response.text)
                if total is None:
                    return ProviderResult.error(ScrapeReason.PARSE_ERROR, "avature_no_results_total")
            cards = parse_cards(response.text, page_url)
            new = [c for c in cards if c["job_id"] not in seen]
            if not new:
                if page == 0 and total:
                    return ProviderResult.error(ScrapeReason.PARSE_ERROR, f"avature_no_cards_of_{total}")
                break

            for card in new:
                seen.add(card["job_id"])
                if not is_india(card["office"]):
                    outside_india += 1
                    continue
                try:
                    detail_response = _get(session, card["detail_url"])
                except requests.RequestException as exc:
                    return ProviderResult.partial(jobs, f"avature_job_{card['job_id']}: {exc}")
                if detail_response.status_code != 200:
                    # Taken down between the listing and its page.
                    _log.warning(
                        f"    [Avature] {company}: job {card['job_id']} answered HTTP "
                        f"{detail_response.status_code}; skipped"
                    )
                    continue
                try:
                    detail = parse_detail(detail_response.text)
                except _LayoutChanged as exc:
                    return ProviderResult.error(ScrapeReason.PARSE_ERROR, f"avature_job_{card['job_id']}: {exc}")
                jobs.append(job_record(card, detail, page_url, industry))
                if len(jobs) >= cap:
                    return ProviderResult.success(jobs)

            offset += len(cards)
            if total is not None and offset >= total:
                break
        else:
            return ProviderResult.partial(jobs, f"avature_page_limit={_MAX_PAGES}")

        if outside_india:
            _log.warning(f"    [Avature] {company}: {outside_india} cards outside India skipped — check the country facet")
        if total is not None and len(seen) < total:
            _log.warning(f"    [Avature] {company}: listed {len(seen)} of {total} results")
        _log.info(f"    {len(jobs)} jobs fetched via Avature ({company})")
        return ProviderResult.success(jobs)
