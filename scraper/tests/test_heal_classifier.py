"""Bucket taxonomy is the test surface: fixture run_summary -> asserted buckets."""

from __future__ import annotations

from heal.baseline import update_ledger
from heal.classifier import (
    BLOCKED_EXPECTED,
    COOKIE_NEEDED,
    INCOMPLETE_SNAPSHOT,
    LOW_COUNT,
    NEEDS_CRACK,
    OK,
    PARAM_SUSPECT,
    REGRESSION,
    classify_run,
)


def _summary(stats):
    return {"run_id": "test", "scope": "india", "company_stats": stats, "unresolved": [], "low_count": []}


def _by_company(verdicts):
    return {v.company: v for v in verdicts}


def test_regression_when_baseline_collapses():
    s = _summary([{"company": "NVIDIA", "ats": "pcsx", "raw_jobs": 0, "saved_new": 0, "status": "no_jobs"}])
    baseline = {"NVIDIA": {"last_good_count": 201}}
    v = _by_company(classify_run(s, baseline, set()))["NVIDIA"]
    assert v.bucket == REGRESSION
    assert v.last_good_count == 201


def test_big_drop_is_regression_not_low_count():
    s = _summary([{"company": "Micron", "ats": "pcsx", "raw_jobs": 3, "saved_new": 3, "status": "ok"}])
    baseline = {"Micron": {"last_good_count": 294}}
    v = _by_company(classify_run(s, baseline, set()))["Micron"]
    assert v.bucket == REGRESSION  # 3 < 294*0.5


def test_partial_snapshot_is_quarantined_before_regression_logic():
    s = _summary([{"company": "Micron", "ats": "pcsx", "raw_jobs": 170, "saved_new": 0, "status": "partial"}])
    s["unresolved"] = [{"company": "Micron", "ats": "pcsx", "reason": "partial_snapshot"}]
    baseline = {"Micron": {"last_good_count": 294}}
    v = _by_company(classify_run(s, baseline, set()))["Micron"]
    assert v.bucket == INCOMPLETE_SNAPSHOT
    assert "quarantine" in v.suggested_action


def test_blocked_workday_is_expected_not_regression():
    s = _summary([{"company": "Engie", "ats": "workday", "raw_jobs": 0, "saved_new": 0, "status": "no_jobs"}])
    v = _by_company(classify_run(s, {}, {"Engie"}))["Engie"]
    assert v.bucket == BLOCKED_EXPECTED


def test_blocked_tenant_with_baseline_is_still_regression():
    # If a "blocked" tenant ever produced jobs and now 0, that's a real regression.
    s = _summary([{"company": "Intuit", "ats": "workday", "raw_jobs": 0, "saved_new": 0, "status": "no_jobs"}])
    v = _by_company(classify_run(s, {"Intuit": {"last_good_count": 40}}, {"Intuit"}))["Intuit"]
    assert v.bucket == REGRESSION


def test_darwinbox_is_cookie_needed():
    s = _summary([{"company": "Flipkart", "ats": "darwinbox", "raw_jobs": 0, "saved_new": 0, "status": "no_jobs"}])
    v = _by_company(classify_run(s, {}, set()))["Flipkart"]
    assert v.bucket == COOKIE_NEEDED


def test_other_ats_zero_is_needs_crack():
    s = _summary([{"company": "Uber", "ats": "other", "raw_jobs": 0, "saved_new": 0, "status": "no_jobs"}])
    v = _by_company(classify_run(s, {}, set()))["Uber"]
    assert v.bucket == NEEDS_CRACK


def test_direct_route_zero_no_baseline_is_param_suspect():
    s = _summary([{"company": "Societe Generale", "ats": "smartrecruiters", "raw_jobs": 0, "saved_new": 0, "status": "no_jobs"}])
    v = _by_company(classify_run(s, {}, set()))["Societe Generale"]
    assert v.bucket == PARAM_SUSPECT


def test_low_count():
    s = _summary([{"company": "Coca-Cola", "ats": "workday", "raw_jobs": 2, "saved_new": 0, "status": "ok"}])
    v = _by_company(classify_run(s, {}, set()))["Coca-Cola"]
    assert v.bucket == LOW_COUNT


def test_healthy_is_ok():
    s = _summary([{"company": "Stripe", "ats": "greenhouse", "raw_jobs": 40, "saved_new": 40, "status": "ok"}])
    v = _by_company(classify_run(s, {}, set()))["Stripe"]
    assert v.bucket == OK


def test_ledger_forward_only_ignores_zero():
    ledger = {}
    assert update_ledger(ledger, "NVIDIA", "pcsx", 201, "r1") is True
    assert update_ledger(ledger, "NVIDIA", "pcsx", 0, "r2") is False  # bad run never lowers baseline
    assert ledger["NVIDIA"]["last_good_count"] == 201


def test_ledger_refresh_does_not_erase_known_ats():
    ledger = {"NVIDIA": {"company": "NVIDIA", "ats": "pcsx", "last_good_count": 201}}
    assert update_ledger(ledger, "NVIDIA", "", 218, "r2") is True
    assert ledger["NVIDIA"]["ats"] == "pcsx"
