from __future__ import annotations

import json
import tempfile
from pathlib import Path

import firecrawl_client as fc


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS {label}")


class _Doc:
    def __init__(self, url: str, markdown: str, source_url: str = "") -> None:
        self.markdown = markdown
        self.metadata = type("Meta", (), {"url": url, "source_url": source_url})()


class _BatchResponse:
    def __init__(self, docs: list[_Doc]) -> None:
        self.data = docs


class _FakeApp:
    def __init__(self) -> None:
        self.scrape_calls: list[str] = []
        self.batch_calls: list[list[str]] = []
        self.map_calls: list[dict] = []

    def scrape(self, url: str, **kwargs) -> _Doc:
        self.scrape_calls.append(url)
        return _Doc(url, f"fresh markdown for {url}")

    def batch_scrape(self, urls: list[str], **kwargs) -> _BatchResponse:
        self.batch_calls.append(list(urls))
        return _BatchResponse([_Doc(url, f"batch markdown for {url}") for url in urls])

    def map(self, url: str, **kwargs):
        self.map_calls.append({"url": url, **kwargs})
        return {
            "links": [
                {
                    "url": f"{url.rstrip('/')}/careers",
                    "title": "Careers",
                    "description": "Open jobs in India",
                }
            ]
        }


def _reset_cache(path: Path, fake_app: _FakeApp | None = None) -> None:
    fc._CACHE_PATH = path
    fc._cache = None
    fc._app = fake_app
    fc._v1 = fake_app


def test_scrape_returns_fresh_cache_without_sdk_call() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / "firecrawl_cache.json"
        key = fc._cache_key("scrape", "https://example.com/jobs", None)
        cache_path.write_text(
            json.dumps({"entries": {key: {"ts": fc._now(), "markdown": "cached markdown"}}}),
            encoding="utf-8",
        )
        fake = _FakeApp()
        _reset_cache(cache_path, fake)

        result = fc.scrape("https://example.com/jobs")

        check("scrape cache hit result", result == "cached markdown")
        check("scrape cache hit skips sdk", fake.scrape_calls == [])


def test_scrape_writes_successful_markdown_to_cache() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / "firecrawl_cache.json"
        fake = _FakeApp()
        _reset_cache(cache_path, fake)

        result = fc.scrape("https://example.com/jobs")

        key = fc._cache_key("scrape", "https://example.com/jobs", None)
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        check("scrape fresh result", result == "fresh markdown for https://example.com/jobs")
        check("scrape cache persisted", data["entries"][key]["markdown"] == result)


def test_batch_scrape_uses_cache_and_fetches_only_misses() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / "firecrawl_cache.json"
        cached_url = "https://example.com/jobs/1"
        missing_url = "https://example.com/jobs/2"
        key = fc._cache_key("scrape", cached_url, None)
        cache_path.write_text(
            json.dumps({"entries": {key: {"ts": fc._now(), "markdown": "cached detail"}}}),
            encoding="utf-8",
        )
        fake = _FakeApp()
        _reset_cache(cache_path, fake)

        result = fc.batch_scrape([cached_url, missing_url])

        check("batch includes cached url", result[cached_url] == "cached detail")
        check("batch includes fetched url", result[missing_url] == f"batch markdown for {missing_url}")
        check("batch fetches only miss", fake.batch_calls == [[missing_url]])


def test_batch_scrape_uses_source_url_when_destination_redirects() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / "firecrawl_cache.json"
        requested_url = "https://example.com/jobs/123"
        fake = _FakeApp()
        fake.batch_scrape = lambda urls, **kwargs: _BatchResponse([
            _Doc(
                "https://example.com/jobs",
                "redirected detail markdown",
                source_url=requested_url,
            )
        ])
        _reset_cache(cache_path, fake)

        result = fc.batch_scrape([requested_url])

        check("batch redirect maps requested url", result[requested_url] == "redirected detail markdown")


def test_map_site_returns_fresh_cache_without_sdk_call() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / "firecrawl_cache.json"
        payload = {
            "url": "https://example.com",
            "search": "jobs careers india",
            "include_subdomains": True,
            "ignore_query_parameters": False,
            "limit": 50,
            "sitemap": "include",
            "timeout": 60000,
            "location": None,
        }
        key = fc._payload_cache_key("map", payload)
        cache_path.write_text(
            json.dumps(
                {
                    "entries": {
                        key: {
                            "ts": fc._now(),
                            "json": [{"url": "https://example.com/careers", "title": "Careers", "description": ""}],
                        }
                    }
                }
            ),
            encoding="utf-8",
        )
        fake = _FakeApp()
        _reset_cache(cache_path, fake)

        result = fc.map_site("https://example.com", search="jobs careers india")

        check("map cache hit result", result[0]["url"] == "https://example.com/careers")
        check("map cache hit skips sdk", fake.map_calls == [])


def test_map_site_writes_normalized_links_to_cache() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        cache_path = Path(tmp) / "firecrawl_cache.json"
        fake = _FakeApp()
        _reset_cache(cache_path, fake)

        result = fc.map_site("https://example.com", search="jobs careers india")

        payload = {
            "url": "https://example.com",
            "search": "jobs careers india",
            "include_subdomains": True,
            "ignore_query_parameters": False,
            "limit": 50,
            "sitemap": "include",
            "timeout": 60000,
            "location": None,
        }
        key = fc._payload_cache_key("map", payload)
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        check("map fresh result", result[0]["url"] == "https://example.com/careers")
        check("map cache persisted", data["entries"][key]["json"][0]["title"] == "Careers")


def main() -> None:
    test_scrape_returns_fresh_cache_without_sdk_call()
    test_scrape_writes_successful_markdown_to_cache()
    test_batch_scrape_uses_cache_and_fetches_only_misses()
    test_batch_scrape_uses_source_url_when_destination_redirects()
    test_map_site_returns_fresh_cache_without_sdk_call()
    test_map_site_writes_normalized_links_to_cache()
    print("All Firecrawl cache tests passed.")


if __name__ == "__main__":
    main()
