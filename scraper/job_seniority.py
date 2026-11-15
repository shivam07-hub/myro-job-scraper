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
from typing import Any, Callable


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

_YEAR_UNIT = r"(?:year\(s\)|years?|yrs?)"
# A year count may be a decimal ("1.5"). The lookbehinds stop a match starting
# inside a number, which is how "1.5" used to be read as 5.
_YEAR_COUNT = r"(?<!\d)(?<!\d\.)\d{1,2}(?:\.\d{1,2})?"
# Accepts "5+ years", "3-5 yrs", "5 to 10yrs", "6 years to 10 years" and
# "1.5-2.5 years".
_YEARS_RANGE = (
    rf"(?P<minimum>{_YEAR_COUNT})\s*"
    r"(?:(?:" + _YEAR_UNIT + rf"\s*)?(?:[-–—]\s*|to\s+)(?P<maximum>{_YEAR_COUNT})|\+)?\s*"
    + _YEAR_UNIT
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
    # Labelled form: "Experience: 8-10 Years", "Exp - 10 - 15 years",
    # "Work Experience (Range of years): 10-12 Years". The label may carry a
    # few words but no digits or sentence punctuation, and a separator must
    # follow it, so the years stay inside the experience clause.
    re.compile(
        r"\b(?:experience|exp)\b[a-z \t()]{0,25}?[:\-–—][ \t:\-–—]*"
        r"(?:(?:more\s+than|over|minimum|min\.?|at\s+least)\s+)?"
        + _YEARS_RANGE,
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
    provider_value = str(job.get("seniority_level") or "").strip().casefold()
    # A canonical level is already normalized: source_matching_facts re-runs
    # this on rows the writer stamped, and "mid"/"executive" match no signal.
    provider_level = (
        provider_value if provider_value in _LEVEL_RANK
        else _level_from_text(provider_value)
    )
    title_level = _level_from_text(title)

    source_min = _coerce_year(job.get("min_years_experience"))
    source_max = _coerce_year(job.get("max_years_experience"))
    description_min, description_max = _experience_bounds(description)
    minimum = _highest_year(source_min, description_min)
    maximum = _highest_year(source_max, description_max)
    if minimum is not None and maximum is not None and maximum < minimum:
        # Bounds from different sentences disagree; keep the minimum only.
        maximum = None
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
            minimum = _description_year(match.group("minimum"), math.floor)
            maximum = _description_year(match.group("maximum"), math.ceil)
            if minimum is not None:
                minimums.append(minimum)
            if maximum is not None:
                maximums.append(maximum)
    return (
        max(minimums) if minimums else None,
        max(maximums) if maximums else None,
    )


def _description_year(value: str | None, to_whole: Callable[[float], int]) -> int | None:
    """Turn a JD year count into whole years for the integer columns.

    The minimum is floored and the maximum ceiled, so the stored window always
    holds the one the JD asks for: "1.5-2.5 years" is stored as 1-3.
    """
    if value is None:
        return None
    return _coerce_year(to_whole(float(value)))


def _highest_year(*years: int | None) -> int | None:
    known = [year for year in years if year is not None]
    return max(known) if known else None
