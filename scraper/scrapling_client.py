"""Optional Scrapling fetch seam used before Firecrawl on opaque HTML boards.

https://github.com/D4Vinci/Scrapling is a fetch/parse framework, not a job
pipeline. Direct ATS APIs stay the default. When a portal has no durable JSON
route, Scrapling's HTTP Fetcher reads the listing (and detail pages) locally
with no Firecrawl credits. Firecrawl remains the last resort.

StealthyFetcher / DynamicFetcher need a browser and are not wired here.
"""
from __future__ import annotations

from html.parser import HTMLParser
import logging
from urllib.parse import urljoin

_log = logging.getLogger("mirror")


class _AnchorParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href") or ""
        if href:
            self._href = href
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return
        self.links.append(("".join(self._text).strip(), self._href))
        self._href = None
        self._text = []


def html_to_listing_markdown(html: str, *, base_url: str = "") -> str:
    """Turn raw HTML anchors into the markdown-link shape firecrawl_js already parses."""
    parser = _AnchorParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return ""
    lines: list[str] = []
    for text, href in parser.links:
        if href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        absolute = urljoin(base_url, href)
        if not absolute.startswith("http"):
            continue
        label = " ".join(text.split()) or absolute
        lines.append(f"[{label}]({absolute})")
    return "\n".join(lines)


def fetch_listing_markdown(url: str) -> str | None:
    """HTTP-fetch ``url`` via Scrapling. None if Scrapling is missing or the page fails."""
    html = fetch_html(url)
    if not html:
        return None
    markdown = html_to_listing_markdown(html, base_url=url)
    return markdown or None


def fetch_html(url: str) -> str | None:
    try:
        from scrapling.fetchers import Fetcher
    except ImportError:
        _log.info("    Scrapling not installed — skipping to Firecrawl for %s", url)
        return None
    try:
        page = Fetcher.get(url)
    except Exception as exc:
        _log.info("    Scrapling fetch failed for %s: %s", url, exc)
        return None
    status = getattr(page, "status", None)
    if isinstance(status, int) and status >= 400:
        _log.info("    Scrapling HTTP %s for %s", status, url)
        return None
    return _page_html(page)


def fetch_text(url: str) -> str | None:
    html = fetch_html(url)
    if not html:
        return None
    from utils import strip_html

    text = strip_html(html).strip()
    return text or None


def _page_html(page: object) -> str | None:
    body = getattr(page, "body", None)
    if isinstance(body, bytes):
        encoding = getattr(page, "encoding", None) or "utf-8"
        try:
            return body.decode(encoding, errors="replace")
        except LookupError:
            return body.decode("utf-8", errors="replace")
    if isinstance(body, str) and body.strip():
        return body
    html = getattr(page, "html", None)
    if isinstance(html, str) and html.strip():
        return html
    text = str(page or "").strip()
    return text or None
