"""
RAG skill retrieval — keyword inverted index over Lightcast L3 taxonomy.

At import time, builds an in-memory inverted index from the taxonomy JSON.
retrieve(text, k) returns the top-k most keyword-relevant L3 skill names
for a given JD text. No model calls — pure token overlap scoring.

These names are injected into the LLM prompt as a constrained vocabulary
so the model picks from canonical taxonomy names directly.
"""
import json
import math
import re
from collections import defaultdict
from pathlib import Path

_TAXONOMY_PATH = Path(__file__).parent / "lightcast_skills_taxonomy.json"


def _load_skills() -> list[str]:
    with open(_TAXONOMY_PATH, encoding="utf-8") as f:
        root = json.load(f)
    return [
        l3["name"]
        for l1 in root.get("children", [])
        for l2 in l1.get("children", [])
        for l3 in l2.get("children", [])
        if l3.get("name")
    ]


def _tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9#+.]+", text.lower()) if len(t) >= 2]


# ── Build inverted index + IDF weights at module load (< 0.5s) ───────────────

_SKILLS: list[str] = _load_skills()

# token → list of skill indices
_INVERTED: dict[str, list[int]] = defaultdict(list)
for _idx, _name in enumerate(_SKILLS):
    for _tok in _tokenize(_name):
        _INVERTED[_tok].append(_idx)

# IDF: rare tokens (e.g. "python") score higher than common ones (e.g. "learning")
_N = len(_SKILLS)
_IDF: dict[str, float] = {
    tok: math.log(_N / len(idxs)) for tok, idxs in _INVERTED.items()
}

# ── Public API ────────────────────────────────────────────────────────────────

def retrieve(text: str, k: int = 40) -> list[str]:
    """
    Score every L3 skill by token overlap with `text`, return top-k names.

    Token overlap works well for skill extraction: JDs write "Python", "SQL",
    "Machine Learning" — the same words appear in taxonomy skill names.
    False positives (irrelevant skills in the 40) are tolerated; the LLM
    ignores them. False negatives (relevant skills missing from 40) are rare
    because skill names are short and literal.
    """
    tokens = set(_tokenize(text))
    scores: dict[int, float] = defaultdict(float)
    for tok in tokens:
        idf = _IDF.get(tok, 0.0)
        for idx in _INVERTED.get(tok, []):
            scores[idx] += idf

    # Normalise by skill name length so "Python" ranks above "Python Tools for Visual Studio"
    _skill_lens = {i: max(math.sqrt(len(_tokenize(_SKILLS[i]))), 1) for i in scores}
    ranked = sorted(scores.items(), key=lambda x: -(x[1] / _skill_lens[x[0]]))
    result = [_SKILLS[i] for i, _ in ranked[:k]]

    # Pad with common anchor skills if fewer than k matches
    if len(result) < k:
        seen = {i for i, _ in ranked}
        for i, name in enumerate(_SKILLS):
            if i not in seen:
                result.append(name)
            if len(result) >= k:
                break

    return result
