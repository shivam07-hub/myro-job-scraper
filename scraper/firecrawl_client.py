from __future__ import annotations

"""
Firecrawl cloud API client — uses the official firecrawl-py SDK.

ONE singleton _app instance. Discovery-first calls:

  map_site(url)                      → [{"url","title","description"}] (1 credit per site)
  scrape(url)                        → markdown str  (1 credit per URL)
  extract(urls, schema, prompt)      → structured dict (js-required portals only)
  batch_scrape(urls)                 → {url: markdown} (Workday JD fetch)

crawl() is intentionally NOT exposed — banned, too expensive (N credits per company).

Usage in providers / main.py:
    import firecrawl_client as fc
    links    = fc.map_site(career_url, search="jobs careers india")
    markdown = fc.scrape(career_url)
    data     = fc.extract([career_url], schema, prompt)
"""
from firecrawl import Firecrawl
from config import FIRECRAWL_API_KEY, FIRECRAWL_CLOUD_API_KEY, FIRECRAWL_URL
import hashlib
import json
import os
from pathlib import Path
import time

# ── One instance, shared across all calls ─────────────────────────────────────
# FIRECRAWL_URL=http://localhost:3002  → Docker (self-hosted, any key works)
# FIRECRAWL_URL unset or cloud URL    → Firecrawl cloud (paid API key required)
_CLOUD_DOMAINS = ("api.firecrawl.dev",)

def _is_local(url: str) -> bool:
    return bool(url) and not any(d in url for d in _CLOUD_DOMAINS)

# Singletons — None until first use
_app: Firecrawl | None = None
_v1 = None
_cloud_app: Firecrawl | None = None

_CACHE_PATH = Path(os.getenv("FIRECRAWL_CACHE_PATH", Path(__file__).parent / "firecrawl_cache.json"))
_CACHE_TTL_SECONDS = int(os.getenv("FIRECRAWL_CACHE_TTL_SECONDS", str(7 * 24 * 60 * 60)))
_cache: dict | None = None


def _now() -> int:
    return int(time.time())


def _cache_key(kind: str, url: str, actions: list[dict] | None) -> str:
    payload = {
        "kind": kind,
        "url": url,
        "actions": actions or [],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _payload_cache_key(kind: str, payload: dict) -> str:
    raw = json.dumps({"kind": kind, "payload": payload}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _load_cache() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    try:
        _cache = json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        _cache = {"version": 1, "entries": {}}
    _cache.setdefault("entries", {})
    return _cache


def _save_cache() -> None:
    if _CACHE_TTL_SECONDS <= 0:
        return
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = _CACHE_PATH.with_suffix(_CACHE_PATH.suffix + ".tmp")
        tmp.write_text(json.dumps(_load_cache(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(_CACHE_PATH)
    except Exception as e:
        print(f"    [FC CACHE WARN] could not persist cache: {e}")


def _is_fresh(entry: dict) -> bool:
    ts = int(entry.get("ts") or 0)
    return bool(ts and _now() - ts <= _CACHE_TTL_SECONDS)


def _cache_get_markdown(kind: str, url: str, actions: list[dict] | None = None) -> str:
    if _CACHE_TTL_SECONDS <= 0:
        return ""
    entry = _load_cache().get("entries", {}).get(_cache_key(kind, url, actions), {})
    markdown = entry.get("markdown", "")
    if markdown and _is_fresh(entry):
        return markdown
    return ""


def _cache_set_markdown(kind: str, url: str, markdown: str, actions: list[dict] | None = None) -> None:
    if _CACHE_TTL_SECONDS <= 0 or not markdown:
        return
    cache = _load_cache()
    cache["entries"][_cache_key(kind, url, actions)] = {
        "ts": _now(),
        "markdown": markdown,
    }
    _save_cache()


def _cache_get_json(kind: str, payload: dict):
    if _CACHE_TTL_SECONDS <= 0:
        return None
    entry = _load_cache().get("entries", {}).get(_payload_cache_key(kind, payload), {})
    if _is_fresh(entry):
        return entry.get("json")
    return None


def _cache_set_json(kind: str, payload: dict, value) -> None:
    if _CACHE_TTL_SECONDS <= 0 or value is None:
        return
    cache = _load_cache()
    cache["entries"][_payload_cache_key(kind, payload)] = {
        "ts": _now(),
        "json": value,
    }
    _save_cache()


def _normalize_map_links(result) -> list[dict[str, str]]:
    if hasattr(result, "model_dump"):
        result = result.model_dump(exclude_none=True)
    if isinstance(result, dict):
        links = result.get("links") or result.get("data") or []
    else:
        links = result or []
    out: list[dict[str, str]] = []
    for item in links:
        if hasattr(item, "model_dump"):
            item = item.model_dump(exclude_none=True)
        elif hasattr(item, "__dict__") and not isinstance(item, dict):
            item = {
                "url": getattr(item, "url", ""),
                "title": getattr(item, "title", ""),
                "description": getattr(item, "description", ""),
            }
        if isinstance(item, str):
            out.append({"url": item, "title": "", "description": ""})
            continue
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        out.append({
            "url": url,
            "title": str(item.get("title") or "").strip(),
            "description": str(item.get("description") or "").strip(),
        })
    return out


def _document_source_url(document) -> str:
    metadata = getattr(document, "metadata", None)
    if hasattr(metadata, "model_dump"):
        metadata = metadata.model_dump(exclude_none=True)
    if isinstance(metadata, dict):
        return str(
            metadata.get("source_url")
            or metadata.get("sourceURL")
            or metadata.get("url")
            or ""
        )
    return str(
        getattr(metadata, "source_url", "")
        or getattr(metadata, "sourceURL", "")
        or getattr(metadata, "url", "")
        or ""
    )


def _get_app() -> Firecrawl:
    global _app, _v1
    if _app is None:
        kwargs: dict = {"api_key": FIRECRAWL_API_KEY or "local"}
        if _is_local(FIRECRAWL_URL):
            kwargs["api_url"] = FIRECRAWL_URL
            print(f"[FC] Using Docker at {FIRECRAWL_URL}")
        else:
            print(f"[FC] Using cloud API")
        _app = Firecrawl(**kwargs)
        # SDK v4.22+ routes extract() to /v2/extract; Docker only has /v1/extract.
        _v1 = _app._v1_client if hasattr(_app, '_v1_client') else _app
    return _app


def _get_cloud_app() -> Firecrawl:
    global _cloud_app
    if _cloud_app is None:
        if not FIRECRAWL_CLOUD_API_KEY:
            raise RuntimeError("FIRECRAWL_CLOUD_API_KEY is not configured")
        _cloud_app = Firecrawl(api_key=FIRECRAWL_CLOUD_API_KEY)
        print("[FC] Using cloud API")
    return _cloud_app


# ── Public API ────────────────────────────────────────────────────────────────

def scrape(url: str, actions: list[dict] | None = None) -> str:
    """Scrape a URL via Playwright and return markdown. Works on Docker + cloud.
    actions: optional Firecrawl action list (click, wait, scroll) run before extraction.
    Actions require Fire Engine (cloud only) — silently ignored when using Docker.
    """
    cached = _cache_get_markdown("scrape", url, actions)
    if cached:
        return cached
    try:
        kwargs: dict = {"formats": ["markdown"], "only_main_content": True}
        # actions require Fire Engine (cloud). Skip silently when using Docker.
        if actions and not _is_local(FIRECRAWL_URL):
            kwargs["actions"] = actions
        doc = _get_app().scrape(url, **kwargs)
        markdown = doc.markdown or ""
        _cache_set_markdown("scrape", url, markdown, actions)
        return markdown
    except Exception as e:
        print(f"    [FC SCRAPE ERROR] {url}: {e}")
        return ""


def map_site(
    url: str,
    *,
    search: str | None = None,
    include_subdomains: bool = True,
    ignore_query_parameters: bool = False,
    limit: int = 50,
    sitemap: str = "include",
    timeout: int = 60000,
    location=None,
) -> list[dict[str, str]]:
    """
    Fast URL discovery pass via Firecrawl /map.
    Returns normalized link dicts: {"url", "title", "description"}.
    """
    payload = {
        "url": url,
        "search": search or "",
        "include_subdomains": bool(include_subdomains),
        "ignore_query_parameters": bool(ignore_query_parameters),
        "limit": int(limit),
        "sitemap": sitemap,
        "timeout": int(timeout),
        "location": location,
    }
    cached = _cache_get_json("map", payload)
    if isinstance(cached, list):
        return cached
    try:
        result = _get_app().map(
            url,
            search=search,
            include_subdomains=include_subdomains,
            ignore_query_parameters=ignore_query_parameters,
            limit=limit,
            sitemap=sitemap,
            timeout=timeout,
            location=location,
        )
        links = _normalize_map_links(result)
        _cache_set_json("map", payload, links)
        return links
    except Exception as e:
        print(f"    [FC MAP ERROR] {url}: {e}")
        return []


def cloud_map_site(
    url: str,
    *,
    search: str | None = None,
    include_subdomains: bool = True,
    ignore_query_parameters: bool = False,
    limit: int = 50,
    sitemap: str = "include",
    timeout: int = 60000,
    location=None,
) -> list[dict[str, str]]:
    """Explicit paid-cloud map for portals that cannot be reached through direct HTTP."""
    payload = {
        "url": url,
        "search": search or "",
        "include_subdomains": bool(include_subdomains),
        "ignore_query_parameters": bool(ignore_query_parameters),
        "limit": int(limit),
        "sitemap": sitemap,
        "timeout": int(timeout),
        "location": location,
        "provider": "cloud",
    }
    cached = _cache_get_json("map", payload)
    if isinstance(cached, list):
        return cached
    legacy_payload = {key: value for key, value in payload.items() if key != "provider"}
    cached = _cache_get_json("map", legacy_payload)
    if isinstance(cached, list):
        _cache_set_json("map", payload, cached)
        return cached
    try:
        result = _get_cloud_app().map(
            url,
            search=search,
            include_subdomains=include_subdomains,
            ignore_query_parameters=ignore_query_parameters,
            limit=limit,
            sitemap=sitemap,
            timeout=timeout,
            location=location,
        )
        links = _normalize_map_links(result)
        _cache_set_json("map", payload, links)
        return links
    except Exception as e:
        print(f"    [FC CLOUD MAP ERROR] {url}: {e}")
        return []


def extract(urls: list[str], schema: dict, prompt: str) -> dict:
    """
    LLM-powered structured extraction via /v1/extract (Docker-compatible).
    Use only for js-required portals where no direct ATS API is available.
    Returns {} on failure.
    """
    try:
        _get_app()  # ensure _v1 is initialised
        result = _v1.extract(urls, prompt=prompt, schema=schema)
        # extract() returns the extracted data directly (typed or dict)
        if hasattr(result, "model_dump"):
            return result.model_dump(exclude_none=True)
        if isinstance(result, dict):
            return result.get("data") or result
        return {}
    except Exception as e:
        print(f"    [FC EXTRACT ERROR] {urls}: {e}")
        return {}


def cloud_extract(urls: list[str], schema: dict, prompt: str) -> dict:
    """Explicit paid-cloud LLM extraction (v2). Use for JS/logo-wall pages where
    markdown scraping misses content (e.g. recruiter logo grids on placement pages).
    Returns {} on failure. Results are cached by url+prompt+schema."""
    payload = {"urls": sorted(urls), "schema": schema, "prompt": prompt}
    cached = _cache_get_json("extract", payload)
    if isinstance(cached, dict):
        return cached
    try:
        result = _get_cloud_app().extract(urls, prompt=prompt, schema=schema)
        if hasattr(result, "model_dump"):
            result = result.model_dump(exclude_none=True)
        data = result.get("data") if isinstance(result, dict) else None
        out = data if isinstance(data, dict) else (result if isinstance(result, dict) else {})
        _cache_set_json("extract", payload, out)
        return out
    except Exception as e:
        print(f"    [FC CLOUD EXTRACT ERROR] {urls}: {e}")
        return {}


def batch_scrape(urls: list[str]) -> dict[str, str]:
    """
    Scrape multiple URLs in one SDK call (e.g. Workday individual JD pages).
    Returns {url: markdown}. Each URL costs 1 credit — use sparingly.
    """
    if not urls:
        return {}
    out = {}
    misses = []
    for url in urls:
        cached = _cache_get_markdown("scrape", url)
        if cached:
            out[url] = cached
        else:
            misses.append(url)
    if not misses:
        return out
    try:
        results = _get_app().batch_scrape(misses, formats=["markdown"], only_main_content=True)
        # batch_scrape returns a BatchScrapeResponse; iterate its data list
        pages = getattr(results, "data", None) or []
        for doc in pages:
            url = _document_source_url(doc)
            md  = getattr(doc, "markdown", None) or ""
            if url and md:
                out[url] = md
                _cache_set_markdown("scrape", url, md)
        return out
    except Exception as e:
        print(f"    [FC BATCH ERROR] {len(misses)} URLs: {e}")
        return out


def cloud_batch_scrape(urls: list[str]) -> dict[str, str]:
    """Explicit paid-cloud batch scrape. Each uncached URL consumes one credit."""
    if not urls:
        return {}
    out: dict[str, str] = {}
    misses: list[str] = []
    for url in urls:
        cached = _cache_get_markdown("scrape", url)
        if cached:
            out[url] = cached
        else:
            misses.append(url)
    if not misses:
        return out
    try:
        results = _get_cloud_app().batch_scrape(
            misses,
            formats=["markdown"],
            only_main_content=True,
        )
        pages = getattr(results, "data", None) or []
        for doc in pages:
            url = _document_source_url(doc)
            markdown = getattr(doc, "markdown", None) or ""
            if url and markdown:
                out[url] = markdown
                _cache_set_markdown("scrape", url, markdown)
    except Exception as e:
        print(f"    [FC CLOUD BATCH ERROR] {len(misses)} URLs: {e}")
    return out
