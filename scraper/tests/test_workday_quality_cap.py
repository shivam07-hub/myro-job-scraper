"""Guard for Phase-B Workday quality-cap plumbing.

The end-to-end pagination path needs the live Workday API, so here we lock the one
new, network-free seam: `_fetch_workday_jds(..., limit=)` fetches JDs for exactly the
budget it is given (the quality-cap path passes limit == company cap), and defaults to
WORKDAY_JD_FETCH_LIMIT otherwise. The ranking/selection itself is covered by
test_scrape_select.py.
"""
import providers.workday as wd


class _FakeResp:
    def __init__(self, jd):
        self._jd = jd

    def raise_for_status(self):
        pass

    def json(self):
        return {"jobPostingInfo": {"jobDescription": self._jd}}


def _jobs(n):
    # each job missing JD and carrying an _ext → eligible for fetch
    return [{"job_id": f"j{i}", "title": f"Engineer {i}", "_ext": f"/job/{i}",
             "raw_jd_text": ""} for i in range(n)]


def _portal():
    return {"tenant": "acme", "instance": "wd1", "career_site": "External"}


def test_limit_caps_number_of_fetches(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, **kw):
        calls["n"] += 1
        return _FakeResp("A real job description body." * 20)

    monkeypatch.setattr(wd.requests, "get", fake_get)
    jobs = _jobs(50)
    wd._fetch_workday_jds(jobs, _portal(), limit=10)
    assert calls["n"] == 10                          # only 10 fetched
    assert sum(1 for j in jobs if j["raw_jd_text"]) == 10


def test_limit_defaults_to_config(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(wd.requests, "get",
                        lambda url, **kw: (calls.__setitem__("n", calls["n"] + 1) or _FakeResp("x" * 400)))
    jobs = _jobs(wd.WORKDAY_JD_FETCH_LIMIT + 25)
    wd._fetch_workday_jds(jobs, _portal())           # no limit → WORKDAY_JD_FETCH_LIMIT
    assert calls["n"] == wd.WORKDAY_JD_FETCH_LIMIT


def test_already_fetched_are_skipped(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(wd.requests, "get",
                        lambda url, **kw: (calls.__setitem__("n", calls["n"] + 1) or _FakeResp("y" * 400)))
    jobs = _jobs(5)
    jobs[0]["raw_jd_text"] = "already has one"        # pre-filled → not re-fetched
    wd._fetch_workday_jds(jobs, _portal(), limit=100)
    assert calls["n"] == 4
