"""Stable text contract for semantic job retrieval.

Job documents and candidate queries must be embedded by the same model, but
they use different Nomic task prefixes.  Keep this module deliberately small so
the scraper worker and downstream Myro integration can share an auditable
contract without coupling embeddings to slower Phase-2 enrichment.
"""
from __future__ import annotations

import hashlib
import re


JOB_EMBEDDING_VERSION = "job_search_v1"
JOB_DOCUMENT_PREFIX = "search_document: "
JOB_QUERY_PREFIX = "search_query: "
DEFAULT_JOB_DESCRIPTION_CHARS = 6000

_BLANK_LINES_RE = re.compile(r"\n{3,}")
_INLINE_SPACE_RE = re.compile(r"[ \t]+")


def _clean_block(value: object) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [_INLINE_SPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    return _BLANK_LINES_RE.sub("\n\n", "\n".join(lines)).strip()


def build_job_embedding_text(
    job: dict,
    *,
    description_chars: int = DEFAULT_JOB_DESCRIPTION_CHARS,
) -> str:
    """Build the source-first document embedded for one job.

    Only source-owned or deterministic importer fields participate.  Model
    enrichment (summary, role domain, skills) is intentionally excluded so a
    newly published job can become searchable before Phase 2 completes.
    """
    if description_chars < 1:
        raise ValueError("description_chars must be positive")

    description = _clean_block(job.get("job_description"))[:description_chars]
    fields = [
        ("Job title", _clean_block(job.get("job_title"))),
        ("Company", _clean_block(job.get("company_name"))),
        ("Industry", _clean_block(job.get("industry"))),
        ("Location", _clean_block(job.get("location"))),
        ("Country", _clean_block(job.get("location_country"))),
        ("Work mode", _clean_block(job.get("location_mode"))),
    ]
    metadata = "\n".join(f"{label}: {value}" for label, value in fields if value)
    body = f"{metadata}\nJob description:\n{description}".strip()
    return f"{JOB_DOCUMENT_PREFIX}{body}"


def job_embedding_input_hash(text: str) -> str:
    payload = f"{JOB_EMBEDDING_VERSION}\n{text}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_job_query_text(query: str) -> str:
    """Prefix a Myro candidate/search description for compatible retrieval."""
    cleaned = _clean_block(query)
    if not cleaned:
        raise ValueError("semantic query must not be empty")
    return f"{JOB_QUERY_PREFIX}{cleaned}"
