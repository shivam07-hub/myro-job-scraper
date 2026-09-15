"""Extractive card summary stamped at scrape time.

The LLM summary remains an upgrade written by enrichment_worker. Import
must never wait on inference, but every published card needs a body, so
the source pass writes the first factual sentences of the JD (or the
missing-JD note). Re-scrapes must not overwrite a non-empty summary that
is already on the row — that is how the model upgrade survives.
"""
from __future__ import annotations

import re

from schema import MISSING_JD_NOTE, is_missing_jd_description

_SUMMARY_MAX_WORDS = 60
_SKIP_SENTENCE_RE = re.compile(
    r"\b(cookie|privacy policy|terms of use|click here|apply now|"
    r"subscribe|sign in|log in|accept all)\b",
    re.IGNORECASE,
)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def extractive_job_summary(
    job_title: str,
    job_description: str,
    *,
    metadata_only: bool = False,
) -> str:
    if metadata_only or is_missing_jd_description(job_description):
        return MISSING_JD_NOTE
    text = " ".join(str(job_description or "").split())
    if not text:
        title = str(job_title or "").strip()
        return title or MISSING_JD_NOTE

    chosen: list[str] = []
    for part in _SENTENCE_RE.split(text):
        sentence = part.strip()
        if len(sentence) < 20 or _SKIP_SENTENCE_RE.search(sentence):
            continue
        chosen.append(sentence)
        if len(" ".join(chosen).split()) >= 40:
            break
    blob = " ".join(chosen) if chosen else text
    words = blob.split()
    if len(words) > _SUMMARY_MAX_WORDS:
        blob = " ".join(words[:_SUMMARY_MAX_WORDS]).rstrip(",;:") + "."
    return blob
