from job_cap import RUNAWAY_LISTING_CAP, job_limit


def test_falsy_cap_is_runaway_not_two_thousand() -> None:
    assert job_limit(None) == RUNAWAY_LISTING_CAP
    assert job_limit(0) == RUNAWAY_LISTING_CAP
    assert job_limit(None) > 2000


def test_positive_cap_is_honored() -> None:
    assert job_limit(25) == 25
    assert job_limit(2500) == 2500
