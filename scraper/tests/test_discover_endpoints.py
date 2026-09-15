from __future__ import annotations

import discover_endpoints as de


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS {label}")


class _FakeFirecrawl:
    def __init__(self, *, mapped_links: list[dict[str, str]], markdown_by_url: dict[str, str] | None = None) -> None:
        self.mapped_links = mapped_links
        self.markdown_by_url = markdown_by_url or {}
        self.map_calls: list[dict] = []
        self.scrape_calls: list[str] = []

    def map_site(self, url: str, **kwargs) -> list[dict[str, str]]:
        self.map_calls.append({"url": url, **kwargs})
        return list(self.mapped_links)

    def scrape(self, url: str) -> str:
        self.scrape_calls.append(url)
        return self.markdown_by_url.get(url, "")


def test_discover_prefers_map_results_and_skips_scrape_when_ats_is_already_known() -> None:
    fake = _FakeFirecrawl(
        mapped_links=[
            {
                "url": "https://jobs.ashbyhq.com/mondee",
                "title": "Mondee jobs",
                "description": "Open roles",
            }
        ]
    )
    original_map_site = de.fc.map_site
    original_scrape = de.fc.scrape
    de.fc.map_site = fake.map_site
    de.fc.scrape = fake.scrape
    try:
        findings = de.discover("Mondee Holdings", "https://jobs.ashbyhq.com/mondee")
        best_url, best_reason = de._best_url(findings)
        check("map-only best url", best_url == "https://jobs.ashbyhq.com/mondee")
        check("map-only best reason", best_reason == "ashby ATS detected")
        check("map-only skips scrape", fake.scrape_calls == [])
    finally:
        de.fc.map_site = original_map_site
        de.fc.scrape = original_scrape


def test_discover_scrapes_shortlist_when_map_only_finds_careers_page() -> None:
    careers_url = "https://example.com/careers"
    fake = _FakeFirecrawl(
        mapped_links=[
            {
                "url": careers_url,
                "title": "Careers at Example",
                "description": "Open jobs in India",
            }
        ],
        markdown_by_url={
            careers_url: "[Apply](https://tenant.wd3.myworkdayjobs.com/en-US/External)",
        },
    )
    original_map_site = de.fc.map_site
    original_scrape = de.fc.scrape
    de.fc.map_site = fake.map_site
    de.fc.scrape = fake.scrape
    try:
        findings = de.discover("Example Co", "https://example.com")
        best_url, best_reason = de._best_url(findings)
        check("scrape-followup best url", best_url == "https://tenant.wd3.myworkdayjobs.com/en-US/External")
        check("scrape-followup reason", best_reason == "workday ATS detected")
        check("scrape-followup scraped careers page first", fake.scrape_calls[0] == careers_url)
        check("scrape-followup captures ats link", findings["ats_links"][0][1] == "workday")
    finally:
        de.fc.map_site = original_map_site
        de.fc.scrape = original_scrape


def main() -> None:
    test_discover_prefers_map_results_and_skips_scrape_when_ats_is_already_known()
    test_discover_scrapes_shortlist_when_map_only_finds_careers_page()
    print("All discover_endpoints tests passed.")


if __name__ == "__main__":
    main()
