"""CDSL careers provider.

https://www.cdslindia.com/Main/careers.html is static HTML. Retired adverts
stay in the file inside HTML comments, so those comments are removed before
parsing. Live roles are the inner panels of ``accordion10``.
"""

from __future__ import annotations

import logging
import re

import requests
from bs4 import BeautifulSoup

from config import REQUEST_TIMEOUT
from providers.base import ProviderResult, ScrapeReason
from schema import Portal
from utils import company_slug, job_hash, strip_html

_log = logging.getLogger("mirror")

_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_ACCORDION_ID = "accordion10"
_SKIP_HEADERS = {"position", "designation", "location"}
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class CdslCareersProvider:
    key = "cdsl_careers"

    def scrape(
        self,
        portal: Portal,
        *,
        max_jobs: int | None = None,
        validate_mode: bool = False,
    ) -> ProviderResult:
        endpoint = (portal.get("endpoint") or portal.get("careers_url") or "").strip()
        if not endpoint.startswith("http"):
            return ProviderResult.error(ScrapeReason.CONFIG_ERROR, "bad_cdsl_endpoint")
        try:
            response = requests.get(endpoint, headers=_HEADERS, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
        except requests.Timeout as exc:
            return ProviderResult.error(ScrapeReason.TIMEOUT, str(exc))
        except requests.RequestException as exc:
            return ProviderResult.error(ScrapeReason.API_BLOCKED, str(exc))

        jobs = parse_cdsl_html(_response_html(response), portal)
        if jobs is None:
            return ProviderResult.error(ScrapeReason.PARSE_ERROR, "cdsl_accordion_missing")
        if max_jobs:
            jobs = jobs[:max_jobs]
        _log.info("    [CDSL] %s jobs", len(jobs))
        return ProviderResult.success(jobs)


def _response_html(response) -> str:
    """The careers page is UTF-8 with a BOM and no charset on the HTTP header.

    Requests would otherwise read it as Latin-1 and turn en-dashes into mojibake.
    """
    headers = getattr(response, "headers", None) or {}
    content_type = ""
    if hasattr(headers, "get"):
        content_type = headers.get("Content-Type") or headers.get("content-type") or ""
    if "charset=" in content_type.lower():
        return response.text
    content = getattr(response, "content", None)
    if isinstance(content, (bytes, bytearray)):
        return bytes(content).decode("utf-8-sig", "replace")
    return response.text


def decode_cfemail(value: str) -> str:
    """Cloudflare hides the address as hex: first byte is the XOR key."""
    hex_value = re.sub(r"[^0-9a-fA-F]", "", value or "")
    if len(hex_value) < 4 or len(hex_value) % 2:
        return ""
    raw = bytes.fromhex(hex_value)
    key = raw[0]
    return bytes(byte ^ key for byte in raw[1:]).decode("utf-8", "replace")


def parse_cdsl_html(page_html: str, portal: Portal) -> list[dict] | None:
    """Jobs in accordion10. None when that accordion is absent."""
    soup = BeautifulSoup(_COMMENT_RE.sub("", page_html or ""), "html.parser")
    accordion = soup.find(id=_ACCORDION_ID)
    if accordion is None:
        return None

    company = portal.get("company") or "CDSL"
    page_url = (portal.get("careers_url") or portal.get("endpoint") or "").strip()
    industry = portal.get("industry", "")
    slug = company_slug(company).lower()
    jobs: list[dict] = []
    seen: set[str] = set()

    for department_panel in accordion.find_all("div", recursive=False):
        headings = department_panel.find_all("h4", class_="panel-title")
        if len(headings) < 2:
            continue
        department = _heading_text(headings[0])
        for heading in headings[1:]:
            title = _heading_text(heading)
            panel = heading.find_parent("div", class_="panel")
            table = panel.find("table") if panel is not None else None
            if not title or table is None:
                continue
            location, description = _parse_table(table)
            job_id = f"{slug}_{job_hash(title, location)}"
            if job_id in seen:
                continue
            seen.add(job_id)
            jobs.append(
                {
                    "job_id": job_id,
                    "title": title,
                    "job_url": page_url,
                    "source_api_url": page_url,
                    "business_unit": department,
                    "raw_jd_text": description,
                    "location_city": location,
                    "date_posted": "",
                    "source_platform": "CDSL",
                    "industry": industry,
                }
            )
    return jobs


def _heading_text(heading) -> str:
    link = heading.find("a")
    return " ".join((link or heading).get_text(" ", strip=True).split())


def _cell_text(cell) -> str:
    _reveal_emails(cell)
    text = strip_html(str(cell))
    # The page writes ``&amp;nbsp`` in a few descriptions, which unescapes to
    # the literal ``&nbsp`` and glues the next word on.
    text = text.replace("&nbsp;", " ").replace("&nbsp", " ")
    return " ".join(text.split())


def _reveal_emails(node) -> None:
    for element in list(node.find_all(attrs={"data-cfemail": True})):
        email = decode_cfemail(element.get("data-cfemail") or "")
        if email:
            element.replace_with(email)


def _parse_table(table) -> tuple[str, str]:
    header: list[str] = []
    data: list[str] = []
    descriptions: list[str] = []
    for row in table.find_all("tr"):
        cells = []
        spanned = False
        for cell in row.find_all(["td", "th"], recursive=False):
            if cell.get("colspan"):
                spanned = True
            cells.append(_cell_text(cell))
        if not any(cells):
            continue
        if spanned or len(cells) == 1:
            text = " ".join(cell for cell in cells if cell).strip()
            if text:
                descriptions.append(text)
            continue
        if not header:
            header = cells
            continue
        if not data:
            data = cells

    location = ""
    labeled: list[str] = []
    for label, value in zip(header, data):
        key = label.strip().lower()
        if key == "location":
            location = value
        elif key not in _SKIP_HEADERS and value:
            labeled.append(f"{label.strip()}: {value}")
    if not location and len(data) >= 2:
        location = data[1]
    parts = labeled + descriptions
    return location, "\n\n".join(parts).strip()
