"""Optional Scrapling browser probe for unresolved career portals.

This module is deliberately outside provider dispatch.  It records bounded,
redacted route evidence (XHR/fetch requests and job-detail links) but never
returns jobs and never writes to Supabase.  Once a durable endpoint is found it
must be promoted to a normal direct provider.
"""

from __future__ import annotations

import asyncio
import html
import json
import re
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

_CAPTURE_PATTERN = r"(?i)(job|career|vacanc|opening|position|recruit|search|api)"
_ROUTE_RE = re.compile(_CAPTURE_PATTERN)
_JOB_LINK_RE = re.compile(
    r"(?i)(/jobs?/(?:careers?/)?[^/?#]+|/careers?/job/[^/?#]+|jobdetails?\.(?:aspx|html?)|/positions?/[^/?#]+)"
)
_STATIC_RE = re.compile(r"(?i)\.(?:js|css|png|jpe?g|gif|svg|woff2?|ttf|ico|map)(?:\?|$)")
_SENSITIVE_RE = re.compile(r"(?i)(token|auth|session|cookie|secret|signature|api[_-]?key|password)")
_TRACKER_HOSTS = ("google-analytics.com", "googletagmanager.com", "doubleclick.net", "facebook.net")


@dataclass
class ScraplingProbeResult:
    company: str
    careers_url: str
    verdict: str  # ROUTE_FOUND | PAGE_ONLY | NO_SIGNAL | DEPENDENCY_MISSING | ERROR
    reachable: bool = False
    status: int = 0
    final_url: str = ""
    elapsed_seconds: float = 0.0
    job_link_count: int = 0
    candidate_urls: list[str] = field(default_factory=list)
    xhr_requests: list[dict] = field(default_factory=list)
    error: str = ""


def _sanitize_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        query = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            query.append((key, "[REDACTED]" if _SENSITIVE_RE.search(key) else value))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))[:2000]
    except Exception:
        return url[:2000]


def _redact_payload(value):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _SENSITIVE_RE.search(str(key)) else _redact_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_payload(item) for item in value[:50]]
    return value


def _sanitize_post_data(value: str | None) -> str:
    if not value:
        return ""
    try:
        return json.dumps(_redact_payload(json.loads(value)), ensure_ascii=False)[:2000]
    except (ValueError, TypeError):
        return "[NON_JSON_BODY_OMITTED]"


def _useful_route(url: str) -> bool:
    if not url or _STATIC_RE.search(url) or not _ROUTE_RE.search(url):
        return False
    host = urlsplit(url).netloc.lower()
    return not any(host == tracker or host.endswith(f".{tracker}") for tracker in _TRACKER_HOSTS)


def _job_links(body: bytes | str, base_url: str) -> list[str]:
    text = body.decode("utf-8", errors="ignore") if isinstance(body, bytes) else body
    links: list[str] = []
    for raw in re.findall(r"(?i)href\s*=\s*['\"]([^'\"]+)['\"]", text):
        url = _sanitize_url(urljoin(base_url, html.unescape(raw)))
        if _JOB_LINK_RE.search(url) and url not in links:
            links.append(url)
    return links[:50]


def result_from_response(
    company: str,
    careers_url: str,
    response,
    request_evidence: list[dict],
    elapsed_seconds: float,
) -> ScraplingProbeResult:
    """Classify a fetched page. A successful render alone is never route evidence."""
    status = int(getattr(response, "status", 0) or 0)
    final_url = _sanitize_url(str(getattr(response, "url", "") or careers_url))
    links = _job_links(getattr(response, "body", b""), final_url)

    xhr_urls: list[str] = []
    for captured in getattr(response, "captured_xhr", []) or []:
        url = _sanitize_url(str(getattr(captured, "url", "") or ""))
        captured_status = int(getattr(captured, "status", 0) or 0)
        if _useful_route(url) and 200 <= captured_status < 400 and url not in xhr_urls:
            xhr_urls.append(url)
    for evidence in request_evidence:
        url = evidence.get("url", "")
        if _useful_route(url) and url not in xhr_urls:
            xhr_urls.append(url)

    candidates = (xhr_urls + [link for link in links if link not in xhr_urls])[:20]
    reachable = 200 <= status < 400
    verdict = "ROUTE_FOUND" if candidates else ("PAGE_ONLY" if reachable else "NO_SIGNAL")
    return ScraplingProbeResult(
        company=company,
        careers_url=careers_url,
        verdict=verdict,
        reachable=reachable,
        status=status,
        final_url=final_url,
        elapsed_seconds=round(elapsed_seconds, 2),
        job_link_count=len(links),
        candidate_urls=candidates,
        xhr_requests=request_evidence[:30],
    )


async def probe_companies_scrapling(
    portals: list[dict],
    *,
    max_companies: int = 5,
    concurrency: int = 2,
    timeout_ms: int = 45_000,
    wait_ms: int = 1_500,
) -> list[ScraplingProbeResult]:
    """Probe a bounded portal batch in one shared stealth browser session."""
    selected = [portal for portal in portals if portal.get("endpoint") or portal.get("careers_url")][
        : max(1, min(max_companies, 20))
    ]
    if not selected:
        return []
    try:
        from scrapling.fetchers import AsyncStealthySession
    except ImportError:
        return [
            ScraplingProbeResult(
                company=portal.get("company", "?"),
                careers_url=portal.get("careers_url") or portal.get("endpoint") or "",
                verdict="DEPENDENCY_MISSING",
                error="install scraper/requirements-scrapling.txt and run `scrapling install`",
            )
            for portal in selected
        ]

    limit = max(1, min(concurrency, 3))
    semaphore = asyncio.Semaphore(limit)
    try:
        async with AsyncStealthySession(
            headless=True,
            max_pages=limit,
            disable_resources=True,
            block_ads=True,
            solve_cloudflare=True,
            network_idle=False,
            google_search=False,
            timeout=max(5_000, min(timeout_ms, 90_000)),
            wait=max(0, min(wait_ms, 10_000)),
            retries=1,
            capture_xhr=_CAPTURE_PATTERN,
        ) as session:

            async def probe_one(portal: dict) -> ScraplingProbeResult:
                company = portal.get("company", "?")
                url = portal.get("careers_url") or portal.get("endpoint") or ""
                evidence: list[dict] = []

                async def page_setup(page) -> None:
                    def record(request) -> None:
                        try:
                            if request.resource_type not in {"xhr", "fetch"}:
                                return
                            request_url = _sanitize_url(request.url)
                            if not _useful_route(request_url) or len(evidence) >= 30:
                                return
                            evidence.append(
                                {
                                    "method": request.method,
                                    "url": request_url,
                                    "post_data": _sanitize_post_data(request.post_data),
                                }
                            )
                        except Exception:
                            return

                    page.on("request", record)

                started = time.monotonic()
                async with semaphore:
                    try:
                        response = await session.fetch(url, page_setup=page_setup)
                    except Exception as exc:
                        return ScraplingProbeResult(
                            company=company,
                            careers_url=url,
                            verdict="ERROR",
                            elapsed_seconds=round(time.monotonic() - started, 2),
                            error=str(exc),
                        )
                return result_from_response(
                    company,
                    url,
                    response,
                    evidence,
                    time.monotonic() - started,
                )

            return await asyncio.gather(*(probe_one(portal) for portal in selected))
    except Exception as exc:
        return [
            ScraplingProbeResult(
                company=portal.get("company", "?"),
                careers_url=portal.get("careers_url") or portal.get("endpoint") or "",
                verdict="ERROR",
                error=f"scrapling_session_start_failed: {exc}",
            )
            for portal in selected
        ]
