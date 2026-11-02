"""Workday's listing stops at about 2,000 postings and does not say so.

Past the ceiling it repeats a full page, and `total` still reads 2,000. Accenture
holds 34,608 jobs in India, so a run saw 2,000, called the source complete, and
closed everything else: 2,244 jobs on 2026-11-02, 12 of 12 sampled still open.
A listing that stops before its end is real evidence of what is open and no
evidence of what is gone, so the run publishes what it saw and closes nothing.
"""
import providers.workday as wd
import trusted_job_lifecycle as lifecycle
from writer import to_canonical


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _page(start: int, size: int = wd.WORKDAY_PAGE_SIZE) -> list[dict]:
    return [
        {"title": f"Analyst {n}", "externalPath": f"/job/Pune/Analyst_R{n}",
         "locationsText": "Pune", "bulletFields": [f"R{n}"]}
        for n in range(start, start + size)
    ]


PORTAL = {
    "company": "Accenture",
    "endpoint": "https://accenture.wd103.myworkdayjobs.com/wday/cxs/accenture/AccentureCareers/jobs",
    "tenant": "accenture", "instance": "wd103", "career_site": "AccentureCareers",
    "workday_india_site": True,
}


def _scrape(monkeypatch, listing) -> list[dict]:
    monkeypatch.setattr(
        wd.requests, "post",
        lambda url, json=None, **kwargs: _Resp({"total": 2000, "jobPostings": listing(json["offset"])}),
    )
    monkeypatch.setattr(wd, "_fetch_workday_jds", lambda jobs, portal, limit=None: None)
    jobs, _reason = wd.scrape_workday(PORTAL)
    return jobs


def test_a_listing_that_repeats_a_full_page_stopped_before_its_end(monkeypatch):
    size = wd.WORKDAY_PAGE_SIZE
    jobs = _scrape(monkeypatch, lambda offset: _page(min(offset, size)))

    assert len(jobs) == size * 2
    assert all(job["listing_truncated"] is True for job in jobs)


def test_a_listing_that_ends_on_a_short_page_is_whole(monkeypatch):
    size = wd.WORKDAY_PAGE_SIZE
    jobs = _scrape(monkeypatch, lambda offset: _page(0) if offset == 0 else _page(size, 3))

    assert len(jobs) == size + 3
    assert not any(job.get("listing_truncated") for job in jobs)


def test_a_listing_that_ends_on_an_empty_page_is_whole(monkeypatch):
    jobs = _scrape(monkeypatch, lambda offset: _page(0) if offset == 0 else [])

    assert not any(job.get("listing_truncated") for job in jobs)


def test_the_ceiling_setting_also_stops_a_listing_short(monkeypatch):
    monkeypatch.setattr(wd, "WORKDAY_MAX_JOBS", wd.WORKDAY_PAGE_SIZE)
    jobs = _scrape(monkeypatch, lambda offset: _page(offset))

    assert all(job["listing_truncated"] is True for job in jobs)


RAW = {"job_id": "R1", "title": "Analyst", "job_url": "https://x.example/1", "source_platform": "Workday"}


def test_the_mark_reaches_the_published_file_only_when_it_is_true():
    assert to_canonical({**RAW, "listing_truncated": True}, "Accenture")["listing_truncated"] is True
    assert "listing_truncated" not in to_canonical(RAW, "Accenture")


def _run(monkeypatch, jobs):
    calls = {"seen": 0, "missing": 0, "written": []}

    def seen(*_a, **_k):
        calls["seen"] += 1

    def missing(*_a, **_k):
        calls["missing"] += 1

    def write_run(sb, **kwargs):
        calls["written"].append(kwargs["assessment"])
        return "run-1"

    monkeypatch.setattr(lifecycle, "_apply_seen", seen)
    monkeypatch.setattr(lifecycle, "_apply_missing", missing)
    monkeypatch.setattr(lifecycle, "_resolve_company", lambda sb, company: "c1")
    monkeypatch.setattr(lifecycle, "_fetch_company_jobs", lambda sb, company_id: [])
    monkeypatch.setattr(lifecycle, "_prior_good_count", lambda sb, company_id: 2000)
    monkeypatch.setattr(lifecycle, "_write_source_run", write_run)
    result = lifecycle.sync_company_run(
        object(), feed_run_id="f1", company="Accenture", jobs=jobs,
        skill_id_map={}, quality_status="ok", dry_run=False, write_skill_facts=False,
    )
    return result, calls


def test_a_truncated_listing_stamps_what_it_saw_and_closes_nothing(monkeypatch):
    jobs = [{"job_id": str(n), "listing_truncated": True} for n in range(2000)]
    result, calls = _run(monkeypatch, jobs)

    assert result.status == "partial"
    assert result.coverage_ratio == 1.0
    assert "before its end" in result.failure_reason
    assert calls["seen"] == 1
    assert calls["missing"] == 0
    assert calls["written"] == [result]


def test_a_whole_listing_still_closes_what_it_did_not_see(monkeypatch):
    result, calls = _run(monkeypatch, [{"job_id": str(n)} for n in range(2000)])

    assert result.status == "complete"
    assert calls["missing"] == 1
