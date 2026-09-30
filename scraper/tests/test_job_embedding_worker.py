from __future__ import annotations

import pytest

from job_embedding_worker import (
    EmbeddingJob,
    InvalidEmbedding,
    LMStudioEmbeddingClient,
    process_batch,
    run_worker,
)


def _job(job_id: str = "job-1") -> EmbeddingJob:
    return EmbeddingJob(
        job_id=job_id,
        claim_token=f"token-{job_id}",
        attempts=1,
        job_title="Data Engineer",
        job_description="Build Python and SQL analytics platforms.",
        company_name="Example",
        industry="Software",
        location="Bengaluru, India",
        location_country="India",
        location_mode="hybrid",
    )


class FakeClient:
    def __init__(self, dimensions: int = 3, *, error: BaseException | None = None) -> None:
        self.dimensions = dimensions
        self.error = error
        self.texts: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.texts.extend(texts)
        if self.error:
            raise self.error
        return [[float(index + 1)] * self.dimensions for index, _ in enumerate(texts)]


class FakeStore:
    def __init__(self, batches: list[list[EmbeddingJob]] | None = None) -> None:
        self.batches = list(batches or [])
        self.applied_items: list[dict] = []
        self.retried: list[tuple[list[EmbeddingJob], str, int]] = []

    def claim(self, quantity: int, max_attempts: int) -> list[EmbeddingJob]:
        return self.batches.pop(0) if self.batches else []

    def apply(self, items: list[dict]) -> tuple[int, int]:
        self.applied_items.extend(items)
        return len(items), 0

    def retry(self, jobs: list[EmbeddingJob], error: str, max_attempts: int) -> int:
        self.retried.append((jobs, error, max_attempts))
        return len(jobs)


def test_process_batch_applies_claim_tokens_hashes_and_vectors() -> None:
    store = FakeStore()
    client = FakeClient()

    applied, rejected = process_batch(
        [_job("a"), _job("b")],
        client=client,  # type: ignore[arg-type]
        store=store,
        max_attempts=5,
    )

    assert (applied, rejected) == (2, 0)
    assert store.applied_items[0]["claim_token"] == "token-a"
    assert len(store.applied_items[0]["input_hash"]) == 64
    assert store.applied_items[1]["embedding"] == [2.0, 2.0, 2.0]
    assert all(text.startswith("search_document: ") for text in client.texts)


def test_failed_batch_is_returned_for_retry() -> None:
    store = FakeStore()
    client = FakeClient(error=RuntimeError("model stopped"))

    with pytest.raises(RuntimeError, match="model stopped"):
        process_batch(
            [_job()],
            client=client,  # type: ignore[arg-type]
            store=store,
            max_attempts=5,
        )

    assert len(store.retried) == 1
    assert store.retried[0][2] == 5


def test_interrupted_batch_is_returned_for_retry() -> None:
    store = FakeStore()
    client = FakeClient(error=KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        process_batch(
            [_job()],
            client=client,  # type: ignore[arg-type]
            store=store,
            max_attempts=5,
        )

    assert len(store.retried) == 1
    assert store.retried[0][1] == "KeyboardInterrupt"


def test_run_worker_drains_claimed_batches() -> None:
    store = FakeStore([[_job("a")], [_job("b")]])
    counts = run_worker(
        store,
        FakeClient(),  # type: ignore[arg-type]
        batch_size=1,
        max_jobs=10,
        max_attempts=5,
    )

    assert counts == {"claimed": 2, "applied": 2, "rejected": 0, "retryable": 0, "aborted": 0}


class FlakyStore(FakeStore):
    """apply() raises the queued errors first, then succeeds."""

    def __init__(self, batches: list[list[EmbeddingJob]], errors: list[Exception]) -> None:
        super().__init__(batches)
        self.errors = list(errors)

    def apply(self, items: list[dict]) -> tuple[int, int]:
        if self.errors:
            raise self.errors.pop(0)
        return super().apply(items)


def test_run_worker_rides_out_a_transient_failure() -> None:
    # 2026-09-30: one statement timeout while the post-publish analytics
    # refresh ran aborted the whole stage, and enrichment never started.
    timeout = RuntimeError("canceling statement due to statement timeout")
    store = FlakyStore([[_job("a")], [_job("a")], [_job("b")]], [timeout])
    sleeps: list[float] = []

    counts = run_worker(
        store,
        FakeClient(),  # type: ignore[arg-type]
        batch_size=1,
        max_jobs=10,
        max_attempts=5,
        sleep=sleeps.append,
    )

    assert counts["applied"] == 2
    assert counts["retryable"] == 1
    assert counts["aborted"] == 0
    assert len(store.retried) == 1
    assert len(sleeps) == 1


def test_run_worker_stops_after_repeated_failures() -> None:
    down = RuntimeError("database unavailable")
    store = FlakyStore([[_job(str(i))] for i in range(10)], [down] * 10)
    sleeps: list[float] = []

    counts = run_worker(
        store,
        FakeClient(),  # type: ignore[arg-type]
        batch_size=1,
        max_jobs=10,
        max_attempts=5,
        sleep=sleeps.append,
    )

    assert counts["aborted"] == 1
    assert counts["applied"] == 0
    assert counts["claimed"] == 3
    assert len(store.retried) == 3
    assert sleeps == sorted(sleeps) and len(sleeps) == 2


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload


class FakeSession:
    def post(self, *args, **kwargs) -> FakeResponse:
        return FakeResponse({
            "data": [
                {"index": 1, "embedding": [4, 5, 6]},
                {"index": 0, "embedding": [1, 2, 3]},
            ]
        })


def test_client_restores_response_index_order() -> None:
    client = LMStudioEmbeddingClient(
        dimensions=3,
        session=FakeSession(),  # type: ignore[arg-type]
    )

    assert client.embed(["one", "two"]) == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]


class WrongDimensionSession(FakeSession):
    def post(self, *args, **kwargs) -> FakeResponse:
        return FakeResponse({"data": [{"index": 0, "embedding": [1, 2]}]})


def test_client_rejects_wrong_vector_dimension() -> None:
    client = LMStudioEmbeddingClient(
        dimensions=3,
        session=WrongDimensionSession(),  # type: ignore[arg-type]
    )

    with pytest.raises(InvalidEmbedding, match="2 dimensions"):
        client.embed(["one"])
