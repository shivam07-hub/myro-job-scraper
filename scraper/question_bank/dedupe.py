from __future__ import annotations

import difflib
import hashlib
import re
import unicodedata


_PUNCT_TRANSLATION = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2013": "-",
    "\u2014": "-",
})
_TOKEN_RE = re.compile(r"[a-z0-9+#.]+")
_STOP_WORDS = {
    "a", "an", "and", "are", "for", "is", "its", "most", "of", "the",
    "to", "what", "when", "which", "with",
}


def canonicalize_question_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "").translate(_PUNCT_TRANSLATION)
    normalized = re.sub(r"\s+", " ", normalized).strip().casefold()
    normalized = re.sub(r"\s*[.!?]+\s*$", "", normalized).strip()
    return normalized


def dedupe_hash(text: str) -> str:
    canonical = canonicalize_question_text(text)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def raw_hash(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(canonicalize_question_text(text))


def _stem(token: str) -> str:
    for suffix in ("ing", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[:-len(suffix)]
    return token


def _content_tokens(text: str) -> set[str]:
    return {
        _stem(token)
        for token in _tokens(text)
        if token not in _STOP_WORDS
    }


def similarity(left: str, right: str) -> float:
    left_canonical = canonicalize_question_text(left)
    right_canonical = canonicalize_question_text(right)
    if not left_canonical or not right_canonical:
        return 0.0
    if left_canonical == right_canonical:
        return 1.0

    character_ratio = difflib.SequenceMatcher(None, left_canonical, right_canonical).ratio()
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    sorted_ratio = difflib.SequenceMatcher(
        None,
        " ".join(sorted(left_tokens)),
        " ".join(sorted(right_tokens)),
    ).ratio()
    left_content = _content_tokens(left)
    right_content = _content_tokens(right)
    overlap = 0.0
    if left_content and right_content:
        overlap = len(left_content & right_content) / min(len(left_content), len(right_content))
    return max(character_ratio, sorted_ratio, overlap)
