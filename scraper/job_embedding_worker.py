#!/usr/bin/env python3
"""Embed source-published jobs with local LM Studio and store them privately.

This worker is independent from core LLM enrichment.  It claims durable rows
from ``private.job_embeddings``, embeds batches through LM Studio's
OpenAI-compatible ``/v1/embeddings`` endpoint, and applies results through
hash/audit metadata guarded by per-claim tokens.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import logging
import math
import os
from typing import Protocol

import requests  # type: ignore[import-untyped]
from supabase import Client, create_client

from config import (
    JOB_EMBEDDING_API_KEY,
    JOB_EMBEDDING_BASE_URL,
    JOB_EMBEDDING_DIMENSIONS,
    JOB_EMBEDDING_MODEL,
)
from job_embedding_state import (
    JOB_EMBEDDING_VERSION,
    build_job_embedding_text,
    build_job_query_text,
    job_embedding_input_hash,
)
from lm_worker_lock import BUSY_EXIT_CODE, WorkerBusy, local_inference_lock


from environment import load_environment

load_environment()
log = logging.getLogger("job_embedding_worker")


class EmbeddingUnavailable(RuntimeError):
    pass


class InvalidEmbedding(RuntimeError):
    pass


@dataclass(frozen=True)
class EmbeddingJob:
    job_id: str
    claim_token: str
    attempts: int
    job_title: str
    job_description: str
    company_name: str
    industry: str
    location: str
    location_country: str
    location_mode: str

    @classmethod
    def from_row(cls, row: dict) -> "EmbeddingJob":
        job_id = str(row.get("job_id") or "").strip()
        claim_token = str(row.get("claim_token") or "").strip()
        if not job_id or not claim_token:
            raise ValueError("claimed embedding row is missing job_id or claim_token")
        return cls(
            job_id=job_id,
            claim_token=claim_token,
            attempts=int(row.get("attempts") or 0),
            job_title=str(row.get("job_title") or ""),
            job_description=str(row.get("job_description") or ""),
            company_name=str(row.get("company_name") or ""),
            industry=str(row.get("industry") or ""),
            location=str(row.get("location") or ""),
            location_country=str(row.get("location_country") or ""),
            location_mode=str(row.get("location_mode") or ""),
        )

    def as_document(self) -> dict:
        return {
            "job_title": self.job_title,
            "job_description": self.job_description,
            "company_name": self.company_name,
            "industry": self.industry,
            "location": self.location,
            "location_country": self.location_country,
            "location_mode": self.location_mode,
        }


class EmbeddingStore(Protocol):
    def claim(self, quantity: int, max_attempts: int) -> list[EmbeddingJob]: ...
    def apply(self, items: list[dict]) -> tuple[int, int]: ...
    def retry(self, jobs: list[EmbeddingJob], error: str, max_attempts: int) -> int: ...


class LMStudioEmbeddingClient:
    def __init__(
        self,
        *,
        base_url: str = JOB_EMBEDDING_BASE_URL,
        api_key: str = JOB_EMBEDDING_API_KEY,
        model: str = JOB_EMBEDDING_MODEL,
        dimensions: int = JOB_EMBEDDING_DIMENSIONS,
        timeout_seconds: int = 180,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.dimensions = dimensions
        self.timeout_seconds = timeout_seconds
        self.session = session or requests.Session()
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def loaded_models(self) -> set[str]:
        try:
            response = self.session.get(
                f"{self.base_url}/models",
                headers=self.headers,
                timeout=5,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise EmbeddingUnavailable("LM Studio embeddings endpoint is unavailable") from exc
        return {
            str(item.get("id"))
            for item in (payload.get("data") or [])
            if isinstance(item, dict) and item.get("id")
        }

    def preflight(self) -> None:
        if self.model not in self.loaded_models():
            raise EmbeddingUnavailable(f"embedding model {self.model!r} is not loaded")
        self.embed([build_job_query_text("embedding health check")])

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = self.session.post(
                f"{self.base_url}/embeddings",
                headers=self.headers,
                json={"model": self.model, "input": texts},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise EmbeddingUnavailable("LM Studio embedding request failed") from exc

        data = payload.get("data") or []
        if not isinstance(data, list) or len(data) != len(texts):
            raise InvalidEmbedding(
                f"expected {len(texts)} embeddings, received {len(data) if isinstance(data, list) else 0}"
            )

        ordered: list[list[float] | None] = [None] * len(texts)
        for fallback_index, item in enumerate(data):
            if not isinstance(item, dict):
                raise InvalidEmbedding("embedding response item must be an object")
            index = int(item.get("index", fallback_index))
            vector = item.get("embedding")
            if index < 0 or index >= len(texts) or not isinstance(vector, list):
                raise InvalidEmbedding("embedding response has an invalid index or vector")
            if len(vector) != self.dimensions:
                raise InvalidEmbedding(
                    f"model returned {len(vector)} dimensions; expected {self.dimensions}"
                )
            try:
                values = [float(value) for value in vector]
            except (TypeError, ValueError) as exc:
                raise InvalidEmbedding("embedding contains a non-numeric value") from exc
            if not all(math.isfinite(value) for value in values):
                raise InvalidEmbedding("embedding contains a non-finite value")
            ordered[index] = values

        if any(vector is None for vector in ordered):
            raise InvalidEmbedding("embedding response omitted one or more indexes")
        return [vector for vector in ordered if vector is not None]


class SupabaseEmbeddingStore:
    def __init__(self, sb: Client) -> None:
        self.sb = sb

    def claim(self, quantity: int, max_attempts: int) -> list[EmbeddingJob]:
        data = self.sb.rpc(
            "claim_job_embeddings",
            {
                "p_qty": max(1, min(quantity, 100)),
                "p_max_attempts": max(1, max_attempts),
            },
        ).execute().data
        if not isinstance(data, list):
            return []
        return [EmbeddingJob.from_row(row) for row in data if isinstance(row, dict)]

    def apply(self, items: list[dict]) -> tuple[int, int]:
        data = self.sb.rpc(
            "apply_job_embeddings",
            {
                "p_items": items,
                "p_model": JOB_EMBEDDING_MODEL,
                "p_version": JOB_EMBEDDING_VERSION,
            },
        ).execute().data
        row = data[0] if isinstance(data, list) and data else data
        if not isinstance(row, dict):
            return 0, len(items)
        return int(row.get("applied") or 0), int(row.get("rejected") or 0)

    def retry(self, jobs: list[EmbeddingJob], error: str, max_attempts: int) -> int:
        items = [
            {"job_id": job.job_id, "claim_token": job.claim_token}
            for job in jobs
        ]
        data = self.sb.rpc(
            "retry_job_embeddings",
            {
                "p_items": items,
                "p_error": str(error or "embedding failure")[:1000],
                "p_max_attempts": max(1, max_attempts),
            },
        ).execute().data
        if isinstance(data, int):
            return data
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, int):
                return first
            if isinstance(first, dict):
                return int(next(iter(first.values()), 0) or 0)
        return 0

    def semantic_search(
        self,
        query_embedding: list[float],
        *,
        match_count: int,
        countries: list[str] | None,
        include_remote: bool,
        excluded_job_ids: list[str] | None = None,
    ) -> list[dict]:
        data = self.sb.rpc(
            "match_jobs_semantic",
            {
                "p_query_embedding": json.dumps(query_embedding, separators=(",", ":")),
                "p_match_count": max(1, min(match_count, 500)),
                "p_target_countries": countries or None,
                "p_include_remote": include_remote,
                "p_excluded_job_ids": excluded_job_ids or [],
            },
        ).execute().data
        return [dict(row) for row in (data or []) if isinstance(row, dict)]


def process_batch(
    jobs: list[EmbeddingJob],
    *,
    client: LMStudioEmbeddingClient,
    store: EmbeddingStore,
    max_attempts: int,
) -> tuple[int, int]:
    texts = [build_job_embedding_text(job.as_document()) for job in jobs]
    try:
        vectors = client.embed(texts)
        items = [
            {
                "job_id": job.job_id,
                "claim_token": job.claim_token,
                "input_hash": job_embedding_input_hash(text),
                "embedding": vector,
            }
            for job, text, vector in zip(jobs, texts, vectors, strict=True)
        ]
        return store.apply(items)
    except (KeyboardInterrupt, SystemExit) as exc:
        store.retry(jobs, str(exc) or exc.__class__.__name__, max_attempts)
        raise
    except Exception as exc:
        store.retry(jobs, str(exc), max_attempts)
        raise


def run_worker(
    store: EmbeddingStore,
    client: LMStudioEmbeddingClient,
    *,
    batch_size: int,
    max_jobs: int,
    max_attempts: int,
) -> dict[str, int]:
    counts = {"claimed": 0, "applied": 0, "rejected": 0, "retryable": 0}
    while counts["claimed"] < max_jobs:
        jobs = store.claim(min(batch_size, max_jobs - counts["claimed"]), max_attempts)
        if not jobs:
            break
        counts["claimed"] += len(jobs)
        try:
            applied, rejected = process_batch(
                jobs,
                client=client,
                store=store,
                max_attempts=max_attempts,
            )
        except Exception as exc:
            counts["retryable"] += len(jobs)
            log.error("Embedding batch failed; claimed rows returned for retry: %s", exc)
            break
        counts["applied"] += applied
        counts["rejected"] += rejected
        log.info(
            "Embedding progress: claimed=%s applied=%s rejected=%s",
            counts["claimed"], counts["applied"], counts["rejected"],
        )
    return counts


def _supabase() -> Client:
    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (os.getenv("SUPABASE_SERVICE_KEY") or "").strip()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY are required")
    return create_client(url, key)


def main() -> None:
    parser = argparse.ArgumentParser(description="Embed recent jobs with local LM Studio")
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--max-jobs", type=int, default=1000)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument(
        "--runtime-model",
        default=JOB_EMBEDDING_MODEL,
        help=(
            "Loaded LM Studio identifier. It may be an additional runtime alias "
            "of the canonical model for a bounded backfill."
        ),
    )
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--semantic-query", help="Embed a query and inspect live semantic matches")
    parser.add_argument("--match-count", type=int, default=10)
    parser.add_argument("--country", action="append", dest="countries")
    parser.add_argument("--exclude-remote", action="store_true")
    args = parser.parse_args()
    if min(args.batch_size, args.max_jobs, args.max_attempts, args.timeout_seconds) < 1:
        parser.error("batch size, max jobs, max attempts, and timeout must be positive")
    if not args.runtime_model.strip():
        parser.error("runtime model identifier must not be empty")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-7s  %(message)s")
    client = LMStudioEmbeddingClient(
        model=args.runtime_model.strip(),
        timeout_seconds=args.timeout_seconds,
    )
    try:
        client.preflight()
    except (EmbeddingUnavailable, InvalidEmbedding) as exc:
        log.info("Embedding preflight failed; database work left untouched: %s", exc)
        raise SystemExit(4) from exc

    if args.preflight_only:
        print(json.dumps({
            "status": "ready",
            "base_url": JOB_EMBEDDING_BASE_URL,
            "model": JOB_EMBEDDING_MODEL,
            "runtime_model": args.runtime_model.strip(),
            "dimensions": JOB_EMBEDDING_DIMENSIONS,
            "version": JOB_EMBEDDING_VERSION,
        }, indent=2))
        return

    store = SupabaseEmbeddingStore(_supabase())
    if args.semantic_query:
        vector = client.embed([build_job_query_text(args.semantic_query)])[0]
        matches = store.semantic_search(
            vector,
            match_count=args.match_count,
            countries=args.countries,
            include_remote=not args.exclude_remote,
        )
        print(json.dumps(matches, ensure_ascii=False, indent=2))
        return

    try:
        with local_inference_lock("job_embedding_worker"):
            counts = run_worker(
                store,
                client,
                batch_size=min(args.batch_size, 100),
                max_jobs=args.max_jobs,
                max_attempts=args.max_attempts,
            )
    except WorkerBusy as exc:
        log.error("%s", exc)
        raise SystemExit(BUSY_EXIT_CODE) from exc
    log.info("Job embedding worker complete: %s", counts)
    if counts["retryable"]:
        raise SystemExit(4)


if __name__ == "__main__":
    main()
