#!/usr/bin/env python3
"""Lazy, forward-only Phase 2 enrichment worker.

The source pipeline publishes jobs first.  A database trigger queues only jobs
inserted after cutover (plus later source changes to those tracked rows).  This
worker drains that durable queue whenever LM Studio or an approved remote
open-weight endpoint is available.

No historical scan or backfill is performed here.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import os
from typing import Callable, Protocol

import requests  # type: ignore[import-untyped]
from supabase import Client, create_client

from config import (
    INFERENCE_API_KEY,
    INFERENCE_BASE_URL,
    INFERENCE_MODEL,
    INFERENCE_PROVIDER,
)
from enrichment_state import (
    CORE_ENRICHMENT_VERSION,
    has_enrichable_description,
)
from enricher import (
    InferenceQuotaExceeded,
    InferenceUnavailable,
    enrich_job,
    has_terminal_core_enrichment,
)
from writer import job_content_hash
from lm_worker_lock import BUSY_EXIT_CODE, WorkerBusy, local_inference_lock

# A loaded model answers a 1-token probe in well under this. An unloaded one
# either stalls or errors, which is the signal we want before claiming work.
INFERENCE_HEALTH_TIMEOUT_SECONDS = 30


from environment import load_environment

load_environment()

log = logging.getLogger("enrichment_worker")


@dataclass(frozen=True)
class EnrichmentMessage:
    msg_id: int | None
    read_count: int
    job_id: str
    source_hash: str
    version: str
    claimed: bool = False
    priority: bool = False

    @classmethod
    def from_queue_row(cls, row: dict) -> "EnrichmentMessage":
        payload = row.get("message") or {}
        if not isinstance(payload, dict):
            raise ValueError("queue message payload must be an object")
        job_id = str(payload.get("job_id") or "").strip()
        source_hash = str(payload.get("source_content_hash") or "").strip()
        version = str(payload.get("enrichment_version") or "").strip()
        if not job_id or not source_hash or not version:
            raise ValueError("queue message is missing job_id, source hash, or version")
        return cls(
            msg_id=int(row["msg_id"]),
            read_count=int(row.get("read_ct") or 0),
            job_id=job_id,
            source_hash=source_hash,
            version=version,
        )


@dataclass(frozen=True)
class ProcessOutcome:
    action: str
    pause: bool = False


class QueueBackend(Protocol):
    def archive(self, msg_id: int) -> bool: ...
    def retry(self, msg_id: int, delay_seconds: int) -> bool: ...


class EnrichmentStore(Protocol):
    def fetch_job(self, job_id: str) -> dict | None: ...
    def claim_priority(self, quantity: int) -> list[EnrichmentMessage]: ...
    def mark_processing(self, job_id: str, source_hash: str) -> bool: ...
    def mark_retryable(self, job_id: str, source_hash: str, error: str) -> None: ...
    def mark_failed(self, job_id: str, source_hash: str, error: str) -> None: ...
    def mark_not_applicable(self, job_id: str, source_hash: str, reason: str) -> None: ...
    def apply(self, job: dict, source_hash: str) -> bool: ...


class PgmqQueueBackend:
    def __init__(self, sb: Client) -> None:
        self.sb = sb

    def read(self, *, visibility_seconds: int, quantity: int) -> list[dict]:
        response = self.sb.rpc(
            "read_job_enrichment_queue",
            {
                "p_visibility_seconds": visibility_seconds,
                "p_qty": quantity,
            },
        ).execute()
        data = response.data
        if not isinstance(data, list):
            return []
        return [dict(item) for item in data if isinstance(item, dict)]

    def archive(self, msg_id: int) -> bool:
        response = self.sb.rpc(
            "archive_job_enrichment_message", {"p_msg_id": msg_id}
        ).execute()
        return _rpc_bool(response.data)

    def retry(self, msg_id: int, delay_seconds: int) -> bool:
        response = self.sb.rpc(
            "retry_job_enrichment_message",
            {"p_msg_id": msg_id, "p_delay_seconds": delay_seconds},
        ).execute()
        return _rpc_bool(response.data)


class SupabaseEnrichmentStore:
    _SELECT = (
        "job_id,job_title,job_description,job_summary,role_domain,main_skills,side_skills,"
        "quality_status,source_content_hash,enriched_source_hash,enrichment_status,is_active"
    )

    def __init__(self, sb: Client) -> None:
        self.sb = sb

    def fetch_job(self, job_id: str) -> dict | None:
        data = (
            self.sb.table("jobs")
            .select(self._SELECT)
            .eq("job_id", job_id)
            .limit(1)
            .execute()
        ).data
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return None
        return dict(data[0])

    def claim_priority(self, quantity: int) -> list[EnrichmentMessage]:
        data = self.sb.rpc(
            "read_priority_job_enrichment", {"p_qty": max(1, min(quantity, 100))}
        ).execute().data
        if not isinstance(data, list):
            return []
        messages: list[EnrichmentMessage] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            job_id = str(row.get("job_id") or "").strip()
            source_hash = str(row.get("source_content_hash") or "").strip()
            version = str(row.get("enrichment_version") or "").strip()
            if job_id and source_hash and version:
                messages.append(EnrichmentMessage(
                    msg_id=None,
                    read_count=1,
                    job_id=job_id,
                    source_hash=source_hash,
                    version=version,
                    claimed=True,
                    priority=True,
                ))
        return messages

    def mark_processing(self, job_id: str, source_hash: str) -> bool:
        response = self.sb.rpc(
            "claim_job_enrichment",
            {"p_job_id": job_id, "p_source_content_hash": source_hash},
        ).execute()
        return _rpc_bool(response.data)

    def mark_retryable(self, job_id: str, source_hash: str, error: str) -> None:
        self._mark(job_id, source_hash, "retryable", error)

    def mark_failed(self, job_id: str, source_hash: str, error: str) -> None:
        self._mark(job_id, source_hash, "failed", error)

    def mark_not_applicable(self, job_id: str, source_hash: str, reason: str) -> None:
        self._mark(job_id, source_hash, "not_applicable", reason)

    def _mark(self, job_id: str, source_hash: str, status: str, error: str) -> None:
        payload = {
            "enrichment_status": status,
            "enrichment_last_error": _bounded_error(error),
        }
        if status in {"retryable", "failed", "not_applicable"}:
            payload["enrichment_priority_requested_at"] = None
        (
            self.sb.table("jobs")
            .update(payload)
            .eq("job_id", job_id)
            .eq("source_content_hash", source_hash)
            .execute()
        )

    def apply(self, job: dict, source_hash: str) -> bool:
        response = self.sb.rpc(
            "apply_job_enrichment",
            {
                "p_job_id": str(job.get("job_id") or ""),
                "p_source_content_hash": source_hash,
                "p_job_summary": str(job.get("job_summary") or ""),
                "p_role_domain": str(job.get("role_domain") or ""),
                "p_skills": job.get("skills") or [],
                "p_model": INFERENCE_MODEL,
                "p_version": CORE_ENRICHMENT_VERSION,
                "p_job_content_hash": job_content_hash(job),
            },
        ).execute()
        return _rpc_bool(response.data)


def process_message(
    message: EnrichmentMessage,
    *,
    store: EnrichmentStore,
    queue: QueueBackend,
    enrich: Callable[[dict], dict] = enrich_job,
    max_attempts: int = 5,
) -> ProcessOutcome:
    job = store.fetch_job(message.job_id)
    if job is None:
        _archive(queue, message)
        return ProcessOutcome("missing_job")

    if message.version != CORE_ENRICHMENT_VERSION:
        store.mark_failed(message.job_id, message.source_hash, "unsupported enrichment version")
        _archive(queue, message)
        return ProcessOutcome("unsupported_version")

    if job.get("source_content_hash") != message.source_hash:
        _archive(queue, message)
        return ProcessOutcome("stale_message")

    if (
        job.get("enrichment_status") == "complete"
        and job.get("enriched_source_hash") == message.source_hash
    ):
        _archive(queue, message)
        return ProcessOutcome("duplicate_complete")

    # NULL is the deliberate legacy/untracked sentinel.  Never turn this into a
    # backward-fill job just because a queue message was malformed or replayed.
    if job.get("enrichment_status") is None:
        _archive(queue, message)
        return ProcessOutcome("legacy_untracked")

    if job.get("is_active") is not True:
        store.mark_not_applicable(message.job_id, message.source_hash, "job inactive before enrichment")
        _archive(queue, message)
        return ProcessOutcome("inactive")

    if not has_enrichable_description(job):
        store.mark_not_applicable(message.job_id, message.source_hash, "no usable job description")
        _archive(queue, message)
        return ProcessOutcome("not_enrichable")

    if not message.claimed and not store.mark_processing(message.job_id, message.source_hash):
        _archive(queue, message)
        return ProcessOutcome("claim_lost")

    work = dict(job)
    work["skills"] = []
    work["main_skills"] = []
    work["side_skills"] = []
    work["job_summary"] = ""
    work["role_domain"] = ""

    try:
        enriched = enrich(work)
    except InferenceQuotaExceeded as exc:
        store.mark_retryable(message.job_id, message.source_hash, str(exc))
        _retry(queue, message, 3600)
        return ProcessOutcome("quota_retry", pause=True)
    except InferenceUnavailable as exc:
        store.mark_retryable(message.job_id, message.source_hash, str(exc))
        _retry(queue, message, 900)
        return ProcessOutcome("inference_unavailable", pause=True)
    except Exception as exc:
        return _handle_job_failure(
            message,
            store=store,
            queue=queue,
            error=str(exc),
            max_attempts=max_attempts,
        )

    if not has_terminal_core_enrichment(enriched):
        return _handle_job_failure(
            message,
            store=store,
            queue=queue,
            error="enrichment returned no terminal core output",
            max_attempts=max_attempts,
        )

    if not store.apply(enriched, message.source_hash):
        # A source change or lifecycle transition won the race and the database
        # rejected a stale result, or the model returned no summary/role_domain.
        # Both are terminal for THIS message, so archiving is still correct.
        #
        # The "produced no taxonomy skill" case is no longer one of them.
        # `apply_job_enrichment` stopped writing `job_skills` on 20260807b --
        # skills belong to True_Yodha's Stage A (JD position) and Stage B
        # (depth), and a write from this side deleted their read and replaced it
        # with a constant `is_primary`.  Asserting a skill row here would now
        # stamp `not_applicable` on jobs for the sole reason that STAGE A had
        # not run yet, which is the same shape of fault in the other direction.
        _archive(queue, message)
        return ProcessOutcome("apply_incomplete")

    _archive(queue, message)
    return ProcessOutcome("complete")


def _handle_job_failure(
    message: EnrichmentMessage,
    *,
    store: EnrichmentStore,
    queue: QueueBackend,
    error: str,
    max_attempts: int,
    pause: bool = False,
) -> ProcessOutcome:
    if message.read_count >= max_attempts:
        store.mark_failed(message.job_id, message.source_hash, error)
        _archive(queue, message)
        return ProcessOutcome("failed")

    delay = min(3600, 60 * (2 ** max(0, min(message.read_count - 1, 6))))
    store.mark_retryable(message.job_id, message.source_hash, error)
    _retry(queue, message, delay)
    return ProcessOutcome("retryable", pause=pause)


def local_inference_ready() -> bool:
    """Avoid claiming queue messages while local LM Studio cannot actually infer.

    `/v1/models` lists models LM Studio has **downloaded**, not the ones it has
    **loaded**. Checking only that list is why a whole drain could pass preflight
    with nothing loaded and then grind through the queue retrying
    `/chat/completions` — the model's TTL had expired mid-run (observed
    2026-08-08). So the listing check is kept as the cheap first gate, and then
    the model is actually exercised.

    The probe does more than detect: LM Studio JIT-loads a model to answer a
    request, so this both forces the load and waits for it to finish (verified
    2026-08-12 — an `lms ps` of `[]` became `['google/gemma-3-4b']` after one
    probe). That is why it is worth a generous timeout: paying the load cost once
    here is what stops every message in the drain paying it as a retry. It
    returns False only when the model genuinely cannot serve.
    """
    if INFERENCE_PROVIDER != "local":
        return True
    headers = {"Authorization": f"Bearer {INFERENCE_API_KEY}"}
    try:
        response = requests.get(
            f"{INFERENCE_BASE_URL.rstrip('/')}/models",
            headers=headers,
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return False
    model_ids = {
        str(item.get("id"))
        for item in (payload.get("data") or [])
        if isinstance(item, dict) and item.get("id")
    }
    if INFERENCE_MODEL not in model_ids:
        return False

    try:
        probe = requests.post(
            f"{INFERENCE_BASE_URL.rstrip('/')}/chat/completions",
            headers={**headers, "Content-Type": "application/json"},
            json={
                "model": INFERENCE_MODEL,
                "messages": [{"role": "user", "content": "ok"}],
                "max_tokens": 1,
                "temperature": 0,
            },
            timeout=INFERENCE_HEALTH_TIMEOUT_SECONDS,
        )
        probe.raise_for_status()
    except (requests.RequestException, ValueError):
        log.error(
            "%s is listed but did not answer a 1-token probe within %ss — it is "
            "most likely unloaded (TTL expired). Load it before draining: "
            "lms load %s --ttl 86400 --yes",
            INFERENCE_MODEL,
            INFERENCE_HEALTH_TIMEOUT_SECONDS,
            INFERENCE_MODEL,
        )
        return False
    return True


def run_worker(
    sb: Client,
    *,
    batch_size: int,
    visibility_seconds: int,
    max_messages: int,
    max_attempts: int,
) -> dict[str, int]:
    queue = PgmqQueueBackend(sb)
    store = SupabaseEnrichmentStore(sb)
    counts: dict[str, int] = {}
    processed = 0

    while processed < max_messages:
        quantity = min(batch_size, max_messages - processed)
        # Personalized search requests only raise database priority.  Claim
        # those rows atomically before reading the normal durable queue; the
        # original pgmq message remains as the crash-safe fallback and becomes
        # a cheap duplicate-complete archive after priority work succeeds.
        priority = store.claim_priority(quantity)
        for message in priority:
            outcome = process_message(
                message,
                store=store,
                queue=queue,
                max_attempts=max_attempts,
            )
            counts[outcome.action] = counts.get(outcome.action, 0) + 1
            processed += 1
            log.info("%s: %s (priority)", message.job_id, outcome.action)
            if outcome.pause or processed >= max_messages:
                return counts
        if priority:
            continue

        rows = queue.read(visibility_seconds=visibility_seconds, quantity=quantity)
        if not rows:
            break
        for row in rows:
            try:
                message = EnrichmentMessage.from_queue_row(row)
            except (KeyError, TypeError, ValueError) as exc:
                msg_id = row.get("msg_id")
                if msg_id is not None:
                    queue.archive(int(msg_id))
                counts["invalid_message"] = counts.get("invalid_message", 0) + 1
                log.warning("Archived invalid queue message %s: %s", msg_id, exc)
                processed += 1
                continue

            outcome = process_message(
                message,
                store=store,
                queue=queue,
                max_attempts=max_attempts,
            )
            counts[outcome.action] = counts.get(outcome.action, 0) + 1
            processed += 1
            log.info("%s: %s", message.job_id, outcome.action)
            if outcome.pause or processed >= max_messages:
                return counts
    return counts


def _archive(queue: QueueBackend, message: EnrichmentMessage) -> bool:
    return message.msg_id is None or queue.archive(message.msg_id)


def _retry(queue: QueueBackend, message: EnrichmentMessage, delay_seconds: int) -> bool:
    # A priority claim is backed by its original pgmq message.  Resetting the
    # job to retryable is sufficient; the durable message remains the retry.
    return message.msg_id is None or queue.retry(message.msg_id, delay_seconds)


def _rpc_bool(data) -> bool:
    if isinstance(data, bool):
        return data
    if isinstance(data, list):
        return bool(data and _rpc_bool(data[0]))
    if isinstance(data, dict):
        return any(bool(value) for value in data.values())
    return bool(data)


def _bounded_error(value: str, limit: int = 1000) -> str:
    return str(value or "unknown enrichment error").strip()[:limit]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _supabase() -> Client:
    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (os.getenv("SUPABASE_SERVICE_KEY") or "").strip()
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY are required")
    return create_client(url, key)


def main() -> None:
    parser = argparse.ArgumentParser(description="Drain forward-only job enrichment work")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--visibility-seconds", type=int, default=900)
    parser.add_argument("--max-messages", type=int, default=100)
    parser.add_argument("--max-attempts", type=int, default=5)
    parser.add_argument(
        "--skip-local-preflight",
        action="store_true",
        help="Attempt queue work even if local /models preflight fails",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-7s  %(message)s",
    )

    if args.batch_size < 1 or args.max_messages < 1 or args.max_attempts < 1:
        parser.error("batch size, max messages, and max attempts must be positive")

    if not args.skip_local_preflight and not local_inference_ready():
        log.info(
            "Inference unavailable or model %s not loaded; queue left untouched",
            INFERENCE_MODEL,
        )
        return

    try:
        with local_inference_lock("enrichment_worker"):
            counts = run_worker(
                _supabase(),
                batch_size=min(args.batch_size, 100),
                visibility_seconds=max(30, min(args.visibility_seconds, 7200)),
                max_messages=args.max_messages,
                max_attempts=args.max_attempts,
            )
    except WorkerBusy as exc:
        log.error("%s", exc)
        raise SystemExit(BUSY_EXIT_CODE) from exc
    log.info("Enrichment worker complete: %s", counts or {"queue_empty": 1})
    if counts.get("inference_unavailable") or counts.get("quota_retry"):
        raise SystemExit(4)


if __name__ == "__main__":
    main()
