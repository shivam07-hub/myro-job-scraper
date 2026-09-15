"""Product job caps vs runaway pagination guards.

A falsy ``max_jobs`` (None or 0) means "read every card the ATS returns".
Providers used to substitute 2000 in that case, which silently truncated
large India boards and made presence-based delisting dishonest.

``job_limit`` is the only number a listing loop should compare against: the
caller's cap when one was set, otherwise a runaway ceiling so a broken
paginator cannot loop forever.
"""
from __future__ import annotations

# Not a product cap. Larger than any real company India board we have seen.
RUNAWAY_LISTING_CAP = 100_000


def job_limit(max_jobs: int | None) -> int:
    if max_jobs and max_jobs > 0:
        return int(max_jobs)
    return RUNAWAY_LISTING_CAP
