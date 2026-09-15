from __future__ import annotations

from enrichment_state import CORE_ENRICHMENT_VERSION
from enrichment_worker import EnrichmentMessage, process_message
from enricher import InferenceUnavailable


class FakeQueue:
    def __init__(self) -> None:
        self.archived: list[int] = []
        self.retried: list[tuple[int, int]] = []

    def archive(self, msg_id: int) -> bool:
        self.archived.append(msg_id)
        return True

    def retry(self, msg_id: int, delay_seconds: int) -> bool:
        self.retried.append((msg_id, delay_seconds))
        return True


class FakeStore:
    def __init__(self, job: dict | None, *, apply_result: bool = True) -> None:
        self.job = job
        self.apply_result = apply_result
        self.processing: list[tuple[str, str]] = []
        self.retryable: list[tuple[str, str, str]] = []
        self.failed: list[tuple[str, str, str]] = []
        self.not_applicable: list[tuple[str, str, str]] = []
        self.applied: list[tuple[dict, str]] = []

    def fetch_job(self, job_id: str) -> dict | None:
        return dict(self.job) if self.job is not None else None

    def claim_priority(self, quantity: int) -> list[EnrichmentMessage]:
        return []

    def mark_processing(self, job_id: str, source_hash: str) -> bool:
        self.processing.append((job_id, source_hash))
        return True

    def mark_retryable(self, job_id: str, source_hash: str, error: str) -> None:
        self.retryable.append((job_id, source_hash, error))

    def mark_failed(self, job_id: str, source_hash: str, error: str) -> None:
        self.failed.append((job_id, source_hash, error))

    def mark_not_applicable(self, job_id: str, source_hash: str, reason: str) -> None:
        self.not_applicable.append((job_id, source_hash, reason))

    def apply(self, job: dict, source_hash: str) -> bool:
        self.applied.append((job, source_hash))
        return self.apply_result


def _message(**overrides) -> EnrichmentMessage:
    values = {
        "msg_id": 9,
        "read_count": 1,
        "job_id": "job-1",
        "source_hash": "source-hash",
        "version": CORE_ENRICHMENT_VERSION,
    }
    values.update(overrides)
    return EnrichmentMessage(**values)


def _job(**overrides) -> dict:
    values = {
        "job_id": "job-1",
        "job_title": "Data Engineer",
        "job_description": "Build reliable data platforms using Python and SQL for analytics workloads.",
        "job_summary": None,
        "role_domain": None,
        "main_skills": [],
        "side_skills": [],
        "source_content_hash": "source-hash",
        "enriched_source_hash": None,
        "enrichment_status": "pending",
        "is_active": True,
    }
    values.update(overrides)
    return values


def _successful_enrich(job: dict) -> dict:
    job["job_summary"] = "Builds reliable analytics data platforms."
    job["role_domain"] = "Data & Analytics"
    job["skills"] = [{"name": "Python (Programming Language)", "required_level": 3}]
    job["main_skills"] = ["Python (Programming Language)"]
    return job


def test_legacy_rows_are_never_backward_filled() -> None:
    queue = FakeQueue()
    store = FakeStore(_job(enrichment_status=None))

    outcome = process_message(
        _message(),
        store=store,
        queue=queue,
        enrich=lambda job: (_ for _ in ()).throw(AssertionError("must not enrich")),
    )

    assert outcome.action == "legacy_untracked"
    assert queue.archived == [9]
    assert store.processing == []


def test_inactive_job_is_archived_without_compute() -> None:
    queue = FakeQueue()
    store = FakeStore(_job(is_active=False))

    outcome = process_message(_message(), store=store, queue=queue, enrich=_successful_enrich)

    assert outcome.action == "inactive"
    assert queue.archived == [9]
    assert store.not_applicable
    assert store.processing == []


def test_stale_message_cannot_overwrite_a_changed_jd() -> None:
    queue = FakeQueue()
    store = FakeStore(_job(source_content_hash="newer-hash"))

    outcome = process_message(_message(), store=store, queue=queue, enrich=_successful_enrich)

    assert outcome.action == "stale_message"
    assert queue.archived == [9]
    assert store.applied == []


def test_successful_message_applies_and_archives() -> None:
    queue = FakeQueue()
    store = FakeStore(_job())

    outcome = process_message(_message(), store=store, queue=queue, enrich=_successful_enrich)

    assert outcome.action == "complete"
    assert store.processing == [("job-1", "source-hash")]
    assert store.applied[0][0]["role_domain"] == "Data & Analytics"
    assert queue.archived == [9]
    assert queue.retried == []


def test_inference_unavailable_leaves_message_for_retry() -> None:
    queue = FakeQueue()
    store = FakeStore(_job())

    def unavailable(job: dict) -> dict:
        raise InferenceUnavailable("LM Studio disconnected")

    outcome = process_message(_message(), store=store, queue=queue, enrich=unavailable)

    assert outcome.action == "inference_unavailable"
    assert outcome.pause is True
    assert store.retryable
    assert queue.retried == [(9, 900)]
    assert queue.archived == []


def test_apply_that_did_not_complete_archives_instead_of_retrying() -> None:
    # apply_job_enrichment returns FALSE for two terminal cases: a stale result
    # that lost the race, and an enrichment that produced no taxonomy skill (the
    # RPC stamps `not_applicable` with a reason rather than calling it complete).
    # Neither is worth replaying this message for.
    queue = FakeQueue()
    store = FakeStore(_job(), apply_result=False)

    outcome = process_message(_message(), store=store, queue=queue, enrich=_successful_enrich)

    assert outcome.action == "apply_incomplete"
    assert queue.archived == [9]


def test_skill_only_output_is_retried_instead_of_marked_complete() -> None:
    queue = FakeQueue()
    store = FakeStore(_job())

    def skill_only(job: dict) -> dict:
        job["skills"] = [{"name": "Python (Programming Language)", "required_level": 3}]
        job["main_skills"] = ["Python (Programming Language)"]
        return job

    outcome = process_message(_message(), store=store, queue=queue, enrich=skill_only)

    assert outcome.action == "retryable"
    assert outcome.pause is False
    assert store.applied == []
    assert queue.archived == []
    assert queue.retried


def test_already_claimed_priority_work_is_singleflight_and_has_no_queue_ack() -> None:
    queue = FakeQueue()
    store = FakeStore(_job(enrichment_status="processing"))

    outcome = process_message(
        _message(msg_id=None, claimed=True, priority=True),
        store=store,
        queue=queue,
        enrich=_successful_enrich,
    )

    assert outcome.action == "complete"
    assert store.processing == []
    assert queue.archived == []
    assert store.applied
