"""
normalizer.py — Shared Lightcast taxonomy normalisation utilities.

Single source of truth for:
  - Taxonomy index build (exact + stripped-parenthetical)
  - Skill name → canonical L3 name matching (3-tier: exact → stripped → fuzzy)
  - LLM JSON response parsing

Used by enricher.py and csv_importer.py.
Replaces independent re-implementations of the same matching logic.
"""
from __future__ import annotations

import re
import json
import difflib
from pathlib import Path

_TAXONOMY_PATH = Path(__file__).parent / "lightcast_skills_taxonomy.json"

# Module-level singletons — built once on first match_to_taxonomy() call
_L3_INDEX: dict[str, str] | None = None
_L3_STRIPPED: dict[str, str] | None = None
_L3_KEYS: list[str] | None = None


def _build_l3_index() -> tuple[dict[str, str], dict[str, str]]:
    """
    Load taxonomy JSON → two lookup dicts:
      exact_index    — lower(name) → canonical L3 name
      stripped_index — lower(base without parenthetical) → canonical (unambiguous only)

    Ambiguous stripped keys (e.g. "UIKit" maps to both Apple and Web) are excluded.
    """
    if not _TAXONOMY_PATH.exists():
        return {}, {}
    with open(_TAXONOMY_PATH, encoding="utf-8") as f:
        root = json.load(f)

    exact: dict[str, str] = {}
    stripped_multi: dict[str, list[str]] = {}

    for l1 in root.get("children", []):
        for l2 in l1.get("children", []):
            for l3 in l2.get("children", []):
                name = l3.get("name", "").strip()
                if not name:
                    continue
                exact[name.lower()] = name
                base = re.sub(r"\s*\(.*\)\s*$", "", name).strip()
                if base and base.lower() != name.lower():
                    stripped_multi.setdefault(base.lower(), []).append(name)

    stripped: dict[str, str] = {
        k: v[0] for k, v in stripped_multi.items() if len(v) == 1
    }
    return exact, stripped


def _ensure_index() -> tuple[dict[str, str], dict[str, str], list[str]]:
    global _L3_INDEX, _L3_STRIPPED, _L3_KEYS
    if _L3_INDEX is None:
        _L3_INDEX, _L3_STRIPPED = _build_l3_index()
        _L3_KEYS = list(_L3_INDEX.keys())
    return _L3_INDEX, _L3_STRIPPED, _L3_KEYS


def match_to_taxonomy(skill: str) -> str | None:
    """
    Return the canonical Lightcast L3 name for a skill string, or None.

    Match strategy (in order):
      1. Exact (case-insensitive): "Machine Learning" → "Machine Learning"
      2. Stripped-parenthetical:   "Docker" → "Docker (Software)"
         Uses unambiguous pre-built index — "Java" → "Java (Programming Language)"
         without matching "Java Foundation Classes".
      3. Fuzzy via difflib (cutoff=0.88, min 8 chars) — catches minor spelling
         differences ("Stakeholder Mgmt" → "Stakeholder Management").
         High cutoff + length guard prevent short-term false positives.

    If taxonomy file is missing, passes skill through unchanged (graceful degradation).
    """
    l3_index, l3_stripped, l3_keys = _ensure_index()

    if not l3_index:
        return skill if (isinstance(skill, str) and skill.strip()) else None

    normalized = skill.strip().lower()
    if not normalized:
        return None

    if normalized in l3_index:
        return l3_index[normalized]

    if normalized in l3_stripped:
        return l3_stripped[normalized]

    if len(normalized) >= 8:
        matches = difflib.get_close_matches(normalized, l3_keys, n=1, cutoff=0.88)
        if matches:
            return l3_index[matches[0]]

    return None


def get_all_canonical_names() -> set[str]:
    """Return the full set of canonical L3 skill names (for batch validation)."""
    l3_index, _, _ = _ensure_index()
    return set(l3_index.values())


# ── JD pre-clean (for LLM input only) ───────────────────────────────────────────
# Some providers (e.g. cognizant_xml) carry page-scrape junk inside the JD text:
# markdown nav links, rule lines, requisition IDs, "Date published …", "Location […]".
# We strip these from the COPY fed to the LLM so the summary stays clean and the
# context window isn't wasted. The stored job_description is left untouched (Tailor CV).

_MD_LINK_RE   = re.compile(r'\[([^\]]+)\]\((?:[^)]*)\)')          # [text](url) → text
_RULE_RE      = re.compile(r'^[\s=*_-]{4,}$', re.MULTILINE)        # ==== / **** rules
_NAV_RE       = re.compile(r'(?im)^\s*(skip to (main )?content|apply now|share this job|save job)\s*$')
_META_LINE_RE = re.compile(r'(?im)^\s*[*\-]?\s*(date published|posted on|requisition id|req id|job id)\b.*$')
_MULTISPACE   = re.compile(r'[ \t]{2,}')
_MULTINL      = re.compile(r'\n{3,}')


def clean_jd_for_llm(text: str) -> str:
    """Return a de-junked copy of a job description for LLM summarisation.

    Removes markdown links (keeps link text), horizontal rules, nav boilerplate,
    and metadata lines (date/requisition) that belong in their own columns.
    Does NOT mutate or replace the stored raw job_description.
    """
    if not text:
        return ''
    t = _MD_LINK_RE.sub(r'\1', text)
    t = _NAV_RE.sub('', t)
    t = _META_LINE_RE.sub('', t)
    t = _RULE_RE.sub('', t)
    t = _MULTISPACE.sub(' ', t)
    t = _MULTINL.sub('\n\n', t)
    return t.strip()


def parse_json_response(text: str):
    """
    Extract JSON from LLM output that may contain markdown fences or prose.
    Finds the first {...} or [...] block and parses it.
    Returns parsed dict/list, or None on failure.
    """
    text = re.sub(r'```(?:json)?\s*', '', text).strip().rstrip('`').strip()
    for open_c, close_c in [('{', '}'), ('[', ']')]:
        start = text.find(open_c)
        end = text.rfind(close_c)
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    return None
