from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

import daily_cycle
import lm_worker_lock
from lm_worker_lock import WorkerBusy, local_inference_lock


def test_second_worker_is_refused_while_the_first_holds_the_lock(tmp_path, monkeypatch) -> None:
    """Two local-inference workers must never run together.

    Running the embedding and enrichment workers at once makes LM Studio evict
    one model to load the other, and both then fail as network errors that name
    nothing about the real cause (observed 2026-08-08).
    """
    monkeypatch.setattr(lm_worker_lock, "LOCK_DIR", tmp_path)

    with local_inference_lock("job_embedding_worker"):
        with pytest.raises(WorkerBusy) as excinfo:
            with local_inference_lock("enrichment_worker"):
                pass

    assert "enrichment_worker" in str(excinfo.value)


def test_lock_is_released_so_the_next_worker_can_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(lm_worker_lock, "LOCK_DIR", tmp_path)

    with local_inference_lock("job_embedding_worker"):
        pass
    with local_inference_lock("enrichment_worker"):
        pass


def test_lock_is_released_even_when_the_worker_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(lm_worker_lock, "LOCK_DIR", tmp_path)

    with pytest.raises(ValueError):
        with local_inference_lock("job_embedding_worker"):
            raise ValueError("drain blew up")

    # A crashed worker must not wedge the lock for every later run.
    with local_inference_lock("enrichment_worker"):
        pass


def test_lock_excludes_a_separate_process(tmp_path, monkeypatch) -> None:
    """flock is per-file-description, so prove it holds across processes too."""
    monkeypatch.setattr(lm_worker_lock, "LOCK_DIR", tmp_path)

    probe = textwrap.dedent(
        f"""
        import sys
        sys.path.insert(0, {str(lm_worker_lock.__file__).rsplit("/", 1)[0]!r})
        import lm_worker_lock
        from pathlib import Path
        lm_worker_lock.LOCK_DIR = Path({str(tmp_path)!r})
        try:
            with lm_worker_lock.local_inference_lock("other_process"):
                print("ACQUIRED")
        except lm_worker_lock.WorkerBusy:
            print("BUSY")
        """
    )

    with local_inference_lock("job_embedding_worker"):
        result = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            check=False,
        )

    assert result.stdout.strip() == "BUSY", result.stderr


def test_daily_cycle_unloads_embedding_model_before_loading_generative(monkeypatch) -> None:
    """The cycle must hand the model slot over, not stack both models."""
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(daily_cycle, "_lms_binary", lambda: "/fake/lms")
    monkeypatch.setattr(daily_cycle.subprocess, "run", fake_run)

    result = daily_cycle.unload_embedding_model(env={})

    assert result["unloaded"] is True
    assert calls == [["/fake/lms", "unload", daily_cycle.JOB_EMBEDDING_MODEL]]


def test_unload_failure_does_not_abort_the_cycle(monkeypatch) -> None:
    """A tight memory fit is a worse reason to discard a finished scrape."""
    monkeypatch.setattr(
        daily_cycle,
        "_lms_binary",
        lambda: (_ for _ in ()).throw(RuntimeError("lms not installed")),
    )

    result = daily_cycle.unload_embedding_model(env={})

    assert result["unloaded"] is False
    assert "lms not installed" in result["reason"]
