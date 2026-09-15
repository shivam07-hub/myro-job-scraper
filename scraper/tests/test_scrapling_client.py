from scrapling_client import fetch_listing_markdown, html_to_listing_markdown


def test_html_anchors_become_markdown_links() -> None:
    html = """
    <html><body>
      <a href="/jobs/42">Staff Engineer</a>
      <a href="javascript:void(0)">Ignore</a>
      <a href="#top">Top</a>
    </body></html>
    """
    md = html_to_listing_markdown(html, base_url="https://careers.example.com/")
    assert "[Staff Engineer](https://careers.example.com/jobs/42)" in md
    assert "javascript" not in md
    assert "#top" not in md


def test_fetch_listing_markdown_returns_none_without_scrapling(monkeypatch) -> None:
    import scrapling_client as client

    def _boom(url: str):
        raise AssertionError("must not fetch when html is missing")

    monkeypatch.setattr(client, "fetch_html", lambda url: None)
    assert fetch_listing_markdown("https://example.com/careers") is None
