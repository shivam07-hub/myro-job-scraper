"""Deterministic skill evidence extraction from labelled JD sections.

The LLM should arbitrate ambiguous requirements, not spend tokens rediscovering
skills explicitly listed in "Required skills" or "Preferred qualifications".
This module extracts compact, taxonomy-grounded evidence that can be merged
with model output and used in prompts.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

from normalizer import match_to_taxonomy

_SECTION_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("mandatory", re.compile(r"\b(required|requirements?|must[- ]?have|required skills?|minimum qualifications?)\b", re.I)),
    ("preferred", re.compile(r"\b(preferred|nice to have|good to have|bonus|plus)\b", re.I)),
    ("responsibilities", re.compile(r"\b(responsibilities|what you(?:'|’)ll do|role overview|duties|accountabilities)\b", re.I)),
    ("qualifications", re.compile(r"\b(qualifications|experience|eligibility)\b", re.I)),
    ("tools", re.compile(r"\b(tools|technologies|tech stack|platforms)\b", re.I)),
)

_L4_RE = re.compile(r"\b(expert|mastery|authority|principal|staff[- ]level|5\+?\s*(?:years|yrs)|[6-9]\+?\s*(?:years|yrs))\b", re.I)
_L3_RE = re.compile(r"\b(strong|advanced|deep|lead|architect|design and implement|3\+?\s*(?:years|yrs)|4\+?\s*(?:years|yrs)|3\s*-\s*5\s*(?:years|yrs))\b", re.I)
_L1_RE = re.compile(r"\b(exposure|familiar|awareness|nice to have|good to have|preferred|plus|a plus)\b", re.I)

_WORD_CHARS = r"a-z0-9+#\-"


def _base_term(name: str) -> str:
    return re.sub(r"\s*\(.*\)\s*$", "", name).strip()


def _candidate_terms(candidate: str) -> tuple[str, list[str]]:
    canonical = match_to_taxonomy(candidate) or candidate.strip()
    terms = [canonical, _base_term(canonical)]
    cleaned: list[str] = []
    seen: set[str] = set()
    for term in terms:
        term = term.strip()
        key = term.lower()
        if not term or key in seen:
            continue
        if len(key) < 3 and key not in {"c++", "c#", "go", "r"}:
            continue
        cleaned.append(term)
        seen.add(key)
    return canonical, cleaned


def _contains_term(text: str, term: str) -> bool:
    pattern = rf"(?<![{_WORD_CHARS}]){re.escape(term.lower())}(?![{_WORD_CHARS}])"
    return re.search(pattern, text.lower()) is not None


def _zone_for_heading(line: str) -> str | None:
    heading = line.strip().strip(":").lower()
    if len(heading) > 80:
        return None
    if heading.endswith((".", ";")) and len(heading.split()) > 3:
        return None
    for zone, pattern in _SECTION_PATTERNS:
        if pattern.search(heading):
            return "mandatory" if zone == "qualifications" else zone
    return None


def _section_lines(text: str) -> list[tuple[str, str]]:
    current_zone = "general"
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip(" \t-*•")
        if not line:
            continue

        if ":" in line:
            left, right = line.split(":", 1)
            zone = _zone_for_heading(left)
            if zone:
                current_zone = zone
                if right.strip():
                    out.append((current_zone, right.strip()))
                continue

        zone = _zone_for_heading(line)
        if zone:
            current_zone = zone
            continue
        out.append((current_zone, line))
    return out


def _level_for(zone: str, evidence: str) -> int:
    if _L4_RE.search(evidence):
        return 4
    if _L3_RE.search(evidence):
        return 3
    if zone == "preferred" or _L1_RE.search(evidence):
        return 1
    if zone in {"mandatory", "responsibilities", "tools"}:
        return 2
    return 2


def _zone_rank(zone: str) -> int:
    return {
        "mandatory": 5,
        "tools": 4,
        "responsibilities": 3,
        "preferred": 2,
        "general": 1,
    }.get(zone, 1)


def extract_skill_evidence(text: str, candidates: Iterable[str] | None = None) -> list[dict]:
    """Return compact explicit skill evidence from labelled JD sections.

    `candidates` should be a small Lightcast candidate set, usually from the
    RAG retriever. The function is deterministic and makes no model calls.
    """
    if not text or not candidates:
        return []

    prepared = [_candidate_terms(candidate) for candidate in candidates]
    prepared = [(canonical, terms) for canonical, terms in prepared if terms]
    lines = _section_lines(text)
    best: dict[str, dict] = {}

    for zone, line in lines:
        for canonical, terms in prepared:
            if not any(_contains_term(line, term) for term in terms):
                continue
            item = {
                "name": canonical,
                "required_level": _level_for(zone, line),
                "zone": zone,
                "evidence": line,
            }
            existing = best.get(canonical)
            if not existing:
                best[canonical] = item
                continue
            existing_score = (existing["required_level"], _zone_rank(existing["zone"]))
            item_score = (item["required_level"], _zone_rank(item["zone"]))
            if item_score > existing_score:
                best[canonical] = item

    return list(best.values())
