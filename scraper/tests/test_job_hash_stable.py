"""job_hash must be stable across scrapes.

The bug this guards (diagnosed 2026-07-24): job_hash used to hash the raw URL,
so tracking/session query params (?utm=, ?source=, expiring tokens) that vary
run-to-run minted a NEW job_id for the SAME live posting on every scrape. The
old row was never re-observed (last_seen stuck at first_seen) and the delisting
loop reaped live jobs. job_hash now hashes only the stable scheme+host+path.
"""

from utils import _stable_url_key, job_hash


def test_query_params_do_not_change_the_id() -> None:
    # Same posting, different per-scrape tracking params → SAME id.
    a = job_hash("Data Engineer", "https://careers.acme.com/job/123?utm_source=run1&t=abc")
    b = job_hash("Data Engineer", "https://careers.acme.com/job/123?utm_source=run2&t=xyz")
    c = job_hash("Data Engineer", "https://careers.acme.com/job/123#apply")
    assert a == b == c


def test_clean_url_id_is_unchanged_by_normalisation() -> None:
    # A URL with no query/fragment is already stable → normalisation is a no-op,
    # so ids for clean-path providers (e.g. metacareers.com/jobs/<id>/) don't move.
    assert _stable_url_key("https://www.metacareers.com/jobs/1041895918495893/") == (
        "https://www.metacareers.com/jobs/1041895918495893"
    )


def test_distinct_postings_still_get_distinct_ids() -> None:
    # Different path (different req) → different id. No merging of real jobs.
    assert job_hash("SDE", "https://x.com/job/1") != job_hash("SDE", "https://x.com/job/2")
    # Different title, same url → different id.
    assert job_hash("SDE I", "https://x.com/job/1") != job_hash("SDE II", "https://x.com/job/1")


def test_host_case_and_trailing_slash_normalised() -> None:
    assert job_hash("QA", "https://Careers.ACME.com/job/9/") == job_hash(
        "QA", "https://careers.acme.com/job/9"
    )


def test_bare_slug_and_empty_pass_through() -> None:
    # Non-URL fallbacks (job_hash(title, "") or a bare slug) must not crash and
    # must stay deterministic.
    assert job_hash("Analyst", "") == job_hash("Analyst", "")
    assert _stable_url_key("") == ""
    assert _stable_url_key("just-a-slug") == "just-a-slug"
