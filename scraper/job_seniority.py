"""Deterministic, source-owned seniority normalization for scraped jobs.

This module intentionally uses no model inference.  It turns the structured
facts a provider supplies (when present), explicit title signals, and minimum
experience requirements in the JD into the level Myro consumes downstream.
The result is written only as part of a future source publication; it never
scans or rewrites historic Supabase rows.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any


_LEVEL_RANK = {
    "intern": 0,
    "entry": 1,
    "mid": 2,
    "senior": 3,
    "lead": 4,
    "executive": 5,
}

_TITLE_LEVELS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("executive", ("vice president", " vp ", "director", "chief")),
    ("lead", ("head of", "principal", "staff", "lead")),
    ("senior", ("senior", " sr ", "sr.")),
    ("mid", ("manager", "engineer ii", "engineer 2", "sde ii", "sde 2", "consultant")),
    ("entry", ("junior", " jr ", "jr.", "graduate", "entry", "associate", "analyst", "assistant")),
    ("intern", ("intern", "internship", "apprentice", "trainee")),
)

_YEARS_RANGE = (
    r"(?P<minimum>\d{1,2})\s*"
    r"(?:(?:[-–—]\s*|\s+to\s+)(?P<maximum>\d{1,2})|\+)?\s*"
    r"(?:years?|yrs?)"
)
_EXPERIENCE_PATTERNS = (
    re.compile(
        rf"\b{_YEARS_RANGE}\s*[’']?\s*"
        r"(?:of\s+)?(?:[a-z][a-z-]*\s+){0,3}experience\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:expert\s+)?experience\s+(?:of\s+)?{_YEARS_RANGE}\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?:requirements?\s*:?\s*|minimum(?:\s+period\s+of)?\s+|"
        rf"at\s+least\s+){_YEARS_RANGE}\s*[’']?\s*"
        r"(?:of|in|handling|working|developing|leading)\b",
        re.IGNORECASE,
    ),
)


@dataclass(frozen=True)
class NormalizedSeniority:
    seniority_level: str
    min_years_experience: int | None
    max_years_experience: int | None


def normalize_job_seniority(job: dict[str, Any]) -> NormalizedSeniority:
    """Return canonical job level and experience bounds without mutating ``job``.

    Explicitly senior title/experience evidence wins over lower signals. That
    protects entry-level feeds when a generic title (such as ``Analyst``) masks
    a role that requires several years of experience.
    """
    title = str(job.get("job_title") or job.get("title") or "")
    description = str(job.get("job_description") or job.get("raw_jd_text") or "")
    provider_level = _level_from_text(str(job.get("seniority_level") or ""))
    title_level = _level_from_text(title)

    source_min = _coerce_year(job.get("min_years_experience"))
    source_max = _coerce_year(job.get("max_years_experience"))
    description_min, description_max = _experience_bounds(description)
    minimum = _highest_year(source_min, description_min)
    maximum = _highest_year(source_max, description_max)
    experience_level = _level_from_years(minimum)

    return NormalizedSeniority(
        seniority_level=_highest_level(provider_level, title_level, experience_level),
        min_years_experience=minimum,
        max_years_experience=maximum,
    )


def _level_from_text(value: str) -> str:
    lowered = f" {value.casefold()} "
    matches = [
        level
        for level, signals in _TITLE_LEVELS
        if any(signal in lowered for signal in signals)
    ]
    return _highest_level(*matches)


def _level_from_years(minimum: int | None) -> str:
    if minimum is None:
        return ""
    if minimum <= 1:
        return "entry"
    if minimum <= 4:
        return "mid"
    if minimum <= 7:
        return "senior"
    if minimum <= 10:
        return "lead"
    return "executive"


def _highest_level(*levels: str) -> str:
    known = [level for level in levels if level in _LEVEL_RANK]
    return max(known, key=_LEVEL_RANK.__getitem__) if known else ""


def _coerce_year(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= 60 else None
    if isinstance(value, float):
        return int(value) if math.isfinite(value) and value.is_integer() and 0 <= value <= 60 else None
    if isinstance(value, str):
        try:
            parsed = float(value.strip())
        except ValueError:
            return None
        return int(parsed) if math.isfinite(parsed) and parsed.is_integer() and 0 <= parsed <= 60 else None
    return None


def _experience_bounds(description: str) -> tuple[int | None, int | None]:
    minimums: list[int] = []
    maximums: list[int] = []
    for pattern in _EXPERIENCE_PATTERNS:
        for match in pattern.finditer(description):
            minimum = _coerce_year(match.group("minimum"))
            maximum = _coerce_year(match.group("maximum"))
            if minimum is not None:
                minimums.append(minimum)
            if maximum is not None:
                maximums.append(maximum)
    return (
        max(minimums) if minimums else None,
        max(maximums) if maximums else None,
    )


def _highest_year(*years: int | None) -> int | None:
    known = [year for year in years if year is not None]
    return max(known) if known else None
