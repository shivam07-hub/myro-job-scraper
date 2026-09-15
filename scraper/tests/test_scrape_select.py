"""Guard for Phase-A quality-aware cap selection (`scrape_select.select_for_cap`).

Locks the behavior that a company OVER the cap keeps technical / JD-bearing roles
instead of an arbitrary tail, that a company AT/UNDER the cap is returned unchanged,
and that the stoplist drops non-technical/facilities/clerical roles.
"""
from scrape_select import select_for_cap, is_stoplisted, CAP_MIN_JD_CHARS

_JD = "x " * CAP_MIN_JD_CHARS  # comfortably over the substantial-JD threshold


def _job(title, jd=""):
    return {"title": title, "job_description": jd}


# --- pass-through cases (small companies: no distinction) ----------------------------

def test_under_cap_unchanged():
    jobs = [_job("A"), _job("B"), _job("C")]
    assert select_for_cap(jobs, 5) is jobs  # identity — no work done


def test_at_cap_unchanged():
    jobs = [_job("A"), _job("B"), _job("C")]
    assert select_for_cap(jobs, 3) is jobs


def test_cap_zero_or_none_unlimited():
    jobs = [_job("A")] * 10
    assert select_for_cap(jobs, 0) is jobs
    assert select_for_cap(jobs, None) is jobs


# --- stoplist ------------------------------------------------------------------------

def test_stoplist_flags_nontechnical():
    for t in ["Security Guard", "Housekeeping Staff", "Driver - Fleet",
              "Facilities Manager", "Receptionist", "Data Entry Operator"]:
        assert is_stoplisted(_job(t)), t


def test_stoplist_keeps_real_technical():
    for t in ["Senior Software Engineer", "Data Scientist", "Security Engineer",
              "Platform Reliability Engineer", "Product Manager"]:
        assert not is_stoplisted(_job(t)), t


def test_over_cap_drops_stoplisted_first():
    jobs = [_job("Security Guard"), _job("Housekeeping"),
            _job("Software Engineer", _JD), _job("Data Engineer", _JD)]
    out = select_for_cap(jobs, 2)
    titles = [j["title"] for j in out]
    assert "Security Guard" not in titles and "Housekeeping" not in titles
    assert set(titles) == {"Software Engineer", "Data Engineer"}


# --- quality ranking -----------------------------------------------------------------

def test_technical_jd_bearing_wins_over_nontechnical_nojd():
    # 1 slot, 1 technical+JD vs 1 business no-JD → technical survives
    jobs = [_job("Marketing Coordinator"), _job("Backend Engineer", _JD)]
    out = select_for_cap(jobs, 1)
    assert out[0]["title"] == "Backend Engineer"


def test_jd_bearing_preferred_over_thin_jd_same_band():
    thin = "short"  # under CAP_MIN_JD_CHARS
    jobs = [_job("Data Engineer", thin), _job("Data Engineer II", _JD)]
    out = select_for_cap(jobs, 1)
    assert out[0]["title"] == "Data Engineer II"


def test_workday_style_no_jd_tail_not_all_discarded():
    # cap 3, but only 1 job carries a JD (Workday beyond its JD-fetch limit).
    # Falls back to the stoplist-filtered pool rather than returning just the 1 JD job.
    jobs = [_job("Software Engineer", _JD),
            _job("Cloud Engineer"), _job("QA Engineer"), _job("Network Engineer")]
    out = select_for_cap(jobs, 3)
    assert len(out) == 3
    assert out[0]["title"] == "Software Engineer"  # JD-bearing ranks first


def test_never_pads_junk_back_to_hit_cap():
    # cap 5 but only 2 non-stoplisted jobs exist → return 2, not 5 with guards re-added
    jobs = [_job("Software Engineer", _JD), _job("Data Scientist", _JD),
            _job("Security Guard"), _job("Housekeeping"), _job("Driver"), _job("Peon")]
    out = select_for_cap(jobs, 5)
    assert len(out) == 2
    assert all(not is_stoplisted(j) for j in out)


def test_deterministic_order():
    jobs = [_job(f"Engineer {i}", _JD) for i in range(20)]
    assert select_for_cap(list(jobs), 5) == select_for_cap(list(jobs), 5)
