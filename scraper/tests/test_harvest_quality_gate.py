"""Guard for the 2b board-harvest quality gate (`looks_like_pollution`).

Myro indexes single EMPLOYERS, not job listings. Recruitment agencies / aggregators /
microtask boards hire for undisclosed clients, so they must never auto-promote into the
company-truthful feed — they are routed to status='review' instead.

These cases are the real hits from the 2026-06-13 harvest (discovery/harvested_boards.csv),
so the gate is locked against the exact pollution it was built to stop, and against the
real product companies it must NOT bench.
"""
from discovery.harvest_boards import looks_like_pollution, HIGH_TOTAL, LOW_INDIA_RATIO


def _hit(slug, total, india, board_name=""):
    return {"ats": "x", "slug": slug, "total": total, "india": india, "board_name": board_name}


# --- MUST be flagged to review (agency / aggregator / microtask) --------------------

def test_flags_consulting_name():
    # Squircle — huge multi-client dump, name carries "consulting"
    assert looks_like_pollution(
        _hit("squircleitconsultingservicespvtltd", 1784, 100, "SQUIRCLE IT CONSULTING SERVICES PVT. LTD")
    )


def test_flags_advisory_name():
    # Capital Aim — "advisory" in name (also total>400 low-ratio)
    assert looks_like_pollution(
        _hit("capitalaimfinancialadvisorypvtltd", 474, 100, "Capital Aim Financial Advisory Pvt. Ltd")
    )


def test_flags_high_total_low_india_ratio():
    # Welocalize — no agency word, but 543 total / 55 India (10%) is a classic multi-client board
    assert looks_like_pollution(_hit("weloglobal", 543, 55, ""))


def test_flags_consulting_in_slug():
    # Beghou — flagged on slug alone, low total
    assert looks_like_pollution(_hit("beghouconsulting", 88, 54, ""))


def test_flags_small_staffing_by_name():
    # name-based flag works independently of size
    assert looks_like_pollution(_hit("acmestaffing", 5, 5, "Acme Staffing LLP"))


# --- MUST NOT be flagged (real single-employer product companies) -------------------

def test_keeps_brillio():
    assert not looks_like_pollution(_hit("brillio-2", 126, 80, ""))


def test_keeps_truecaller():
    assert not looks_like_pollution(_hit("truecaller", 2, 2, "Truecaller"))


def test_keeps_6sense():
    assert not looks_like_pollution(_hit("6sense", 38, 17, "6sense"))


def test_keeps_netgear():
    assert not looks_like_pollution(_hit("netgear", 45, 22, "netgear"))


def test_keeps_atomicwork():
    assert not looks_like_pollution(_hit("atomicwork", 27, 21, "Atomicwork Inc"))


def test_ratio_protects_genuine_large_india_employer():
    # >400 jobs but India-heavy (450/500 = 90%) → a real India employer, must NOT be benched.
    # This is the whole point of the ratio refinement over a bare total>400 rule.
    assert not looks_like_pollution(_hit("bigproductco", 500, 450, "Big Product Co"))


# --- Deliberate, documented misses (accepted trade-off, not a bug) ------------------

def test_known_miss_generic_agency_slips_through():
    # Weekday (lever aggregator): generic slug, no agency word, total<400 → not caught here.
    # By design: we do NOT hard-code names or add bare "network" (would false-flag real
    # "...Networks" product companies). These surface in the promote list where the human
    # reviewer still confirms single-employer. Locking the known behavior explicitly.
    assert not looks_like_pollution(_hit("weekdayworks", 58, 56, ""))


def test_threshold_constants_unchanged():
    # If someone retunes these, they should update the ratio/total reasoning above too.
    assert HIGH_TOTAL == 400
    assert LOW_INDIA_RATIO == 0.20
