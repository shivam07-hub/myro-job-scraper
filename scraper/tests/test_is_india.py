"""is_india must match India keywords on letter boundaries, not substrings.

The bug this guards (observed 2026-09-28): is_india did `k in loc`, so "india"
matched inside Indiana/Indianapolis. UBS BrassRing published a job located
"United States - Indiana" into the India feed; _EXCLUDE_PATTERNS only caught
"Indiana, USA"-style strings. Local outputs also showed Target Indianapolis
store addresses and "Indian Land, SC" leaking the same way.
"""

import pytest

from utils import is_india


@pytest.mark.parametrize("location", [
    "India",
    "Bengaluru, India",
    "IN - Navi Mumbai",
    "Hyderabad, Telangana, IN",
    "IN_Bangalore",
    "Bengalurur, IN",  # real source typo; city keeps a leading boundary only
    "Indianapolis, IN; Pune, India",
])
def test_india_locations_match(location: str) -> None:
    assert is_india(location)


@pytest.mark.parametrize("location", [
    "United States - Indiana",
    "Indianapolis, IN",
    "Indiana",
    "Remote-Indiana",
    "5345 Crossridge Blvd, Indian Land,SC 29707-7892",
    "American Indian or Alaska Native",  # US EEO boilerplate in JD-text callers
    "Indiana, USA",
    "",
])
def test_non_india_locations_do_not_match(location: str) -> None:
    assert not is_india(location)
