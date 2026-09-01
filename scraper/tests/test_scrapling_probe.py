from __future__ import annotations

from heal.scrapling_probe import _sanitize_post_data, _sanitize_url, result_from_response


class _Captured:
    def __init__(self, url, status=200):
        self.url = url
        self.status = status


class _Response:
    status = 200
    url = "https://example.com/careers"
    body = b'<html><a href="/about">About</a></html>'
    captured_xhr = []


def test_rendered_page_alone_is_not_job_evidence():
    result = result_from_response("Example", _Response.url, _Response(), [], 0.5)
    assert result.verdict == "PAGE_ONLY"
    assert result.candidate_urls == []


def test_xhr_or_job_link_is_route_evidence_and_sensitive_query_is_redacted():
    response = _Response()
    response.body = b'<a href="/jobs/123/data-engineer?session=abc">Data Engineer</a>'
    response.captured_xhr = [_Captured("https://example.com/api/jobs?token=secret&country=India")]
    result = result_from_response("Example", response.url, response, [], 0.5)

    assert result.verdict == "ROUTE_FOUND"
    assert result.job_link_count == 1
    assert "secret" not in result.candidate_urls[0]
    assert "%5BREDACTED%5D" in result.candidate_urls[0]


def test_probe_artifact_redaction_omits_non_json_bodies():
    assert "secret" not in _sanitize_url("https://x.test/api/jobs?api_key=secret")
    assert "secret" not in _sanitize_post_data('{"token":"secret","filters":{"country":"India"}}')
    assert _sanitize_post_data("opaque=form&token=secret") == "[NON_JSON_BODY_OMITTED]"
