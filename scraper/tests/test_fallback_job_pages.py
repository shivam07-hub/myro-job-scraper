"""The Scrapling fallback route must title and place jobs from the job page itself.

Found 2026-09-30 on Atomicwork's careers page: every listing link reads
"Apply Now", which became the job title, and the location ("Bengaluru,
Karnataka") sits ~7,000 characters into the page, after menus and inline CSS,
so the first-1,500-character India check rejected the only India job.
"""
from __future__ import annotations

import scrapling_client
from providers import firecrawl_js

CHROME = "<style>.nav{color:red}" + ".x{margin:0}" * 300 + "</style>" + (
    "<nav>" + "".join(f"<a href='/p{i}'>Product {i}</a>" for i in range(80)) + "</nav>"
)


def _page(title: str, location: str, body: str = "Own the platform roadmap. " * 40) -> str:
    return (
        f"<html><head><title>{title} | Atomicwork Jobs</title><script>var t=1;</script></head>"
        f"<body>{CHROME}<main><p>Product Management</p><h1>{title}</h1><p>{location}</p>"
        f"<div>{body}</div></main><footer>Offices in Bengaluru and Palo Alto</footer></body></html>"
    )


def test_job_page_title_comes_from_the_heading_and_text_starts_there() -> None:
    page = scrapling_client.parse_job_page(_page("Product Manager - Platform", "Bengaluru, Karnataka"))

    assert page.title == "Product Manager - Platform"
    assert page.text.startswith("Product Manager - Platform")
    assert "Bengaluru, Karnataka" in page.text[:200]
    assert "margin" not in page.text and "var t" not in page.text


def test_job_page_falls_back_to_the_document_title() -> None:
    page = scrapling_client.parse_job_page(
        "<html><head><title>Data Engineer | Example Careers</title></head><body><p>Pune</p></body></html>"
    )

    assert page.title == "Data Engineer"


def test_fallback_route_titles_and_filters_from_the_job_page(monkeypatch) -> None:
    pages = {
        "https://www.atomicwork.com/careers/4080659008": _page("Product Manager - Platform", "Bengaluru, Karnataka"),
        "https://www.atomicwork.com/careers/4405097008": _page("Product Marketer", "Palo Alto, California"),
    }
    listing = "\n".join(f"[Apply Now]({url})" for url in pages)
    monkeypatch.setattr(scrapling_client, "fetch_listing_markdown", lambda url: listing + "\n" + "x" * 300)
    monkeypatch.setattr(scrapling_client, "fetch_html", lambda url: pages.get(url))

    jobs = firecrawl_js.scrape_extract({
        "company": "Atomicwork",
        "endpoint": "https://www.atomicwork.com/company/careers",
        "india_only": True,
    })

    assert [job["title"] for job in jobs] == ["Product Manager - Platform"]
    assert jobs[0]["raw_jd_text"].startswith("Product Manager - Platform")
    assert jobs[0]["source_platform"] == "Scrapling"


def test_atomicwork_registry_row_is_india_only_on_the_fallback_route() -> None:
    from portal_reader import parse_portals

    portals = [p for p in parse_portals() if p["company"] == "Atomicwork"]

    assert len(portals) == 1
    assert portals[0]["ats"] == "other" and portals[0]["js_required"] is True
    assert portals[0]["india_only"] is True
