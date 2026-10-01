from __future__ import annotations

import daily_cycle


def test_build_commands_runs_poll_then_embeddings_then_worker() -> None:
    poll, embeddings, worker = daily_cycle.build_commands(
        python="python-test",
        scope="india",
        company_cap=250,
        company="Deepgram",
        max_messages=900,
        max_embeddings=800,
    )

    assert poll[:2] == ["python-test", str(daily_cycle.ROOT / "daily_poll.py")]
    assert poll[-2:] == ["--company", "Deepgram"]
    assert embeddings[:2] == [
        "python-test", str(daily_cycle.ROOT / "job_embedding_worker.py")
    ]
    assert embeddings[-1] == "800"
    assert worker[:2] == ["python-test", str(daily_cycle.ROOT / "enrichment_worker.py")]
    assert worker[-1] == "900"


def test_remote_open_weight_skips_lm_studio(monkeypatch) -> None:
    monkeypatch.setattr(daily_cycle, "INFERENCE_PROVIDER", "cloudflare_workers_ai")
    monkeypatch.setattr(daily_cycle, "INFERENCE_MODEL", "@cf/open-model")
    monkeypatch.setattr(
        daily_cycle,
        "_lms_binary",
        lambda: (_ for _ in ()).throw(AssertionError("must not inspect local LM Studio")),
    )

    result = daily_cycle.ensure_inference_ready(
        env={}, model_ttl_seconds=3600, timeout_seconds=1
    )

    assert result == {
        "provider": "cloudflare_workers_ai",
        "model": "@cf/open-model",
        "lm_studio_started": False,
    }


def test_loaded_local_model_needs_no_restart_or_reload(monkeypatch) -> None:
    monkeypatch.setattr(daily_cycle, "INFERENCE_PROVIDER", "local")
    monkeypatch.setattr(daily_cycle, "INFERENCE_MODEL", "google/gemma-3-4b")
    monkeypatch.setattr(daily_cycle, "_lms_binary", lambda: "/tmp/lms")
    monkeypatch.setattr(daily_cycle, "_model_ids", lambda: {"google/gemma-3-4b"})
    monkeypatch.setattr(
        daily_cycle,
        "_loaded_lms_model_ids",
        lambda *args, **kwargs: {"google/gemma-3-4b"},
    )
    monkeypatch.setattr(
        daily_cycle.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no command expected")),
    )

    result = daily_cycle.ensure_inference_ready(
        env={}, model_ttl_seconds=3600, timeout_seconds=1
    )

    assert result["model_loaded"] is False
    assert result["loaded_models"] == ["google/gemma-3-4b"]


def test_downloaded_but_unloaded_local_model_is_loaded(monkeypatch) -> None:
    monkeypatch.setattr(daily_cycle, "INFERENCE_PROVIDER", "local")
    monkeypatch.setattr(daily_cycle, "INFERENCE_MODEL", "google/gemma-3-4b")
    monkeypatch.setattr(daily_cycle, "_lms_binary", lambda: "/tmp/lms")
    monkeypatch.setattr(daily_cycle, "_model_ids", lambda: {"google/gemma-3-4b"})
    monkeypatch.setattr(daily_cycle, "_loaded_lms_model_ids", lambda *args, **kwargs: set())
    commands: list[list[str]] = []
    monkeypatch.setattr(
        daily_cycle,
        "_checked",
        lambda command, **kwargs: commands.append(command),
    )
    monkeypatch.setattr(
        daily_cycle,
        "_wait_for_loaded_lms_model",
        lambda *args, **kwargs: {"google/gemma-3-4b"},
    )

    result = daily_cycle.ensure_inference_ready(
        env={}, model_ttl_seconds=3600, timeout_seconds=1
    )

    assert commands and commands[0][1:3] == ["load", "google/gemma-3-4b"]
    assert result["model_loaded"] is True
    assert result["loaded_models"] == ["google/gemma-3-4b"]


def test_loaded_embedding_model_needs_no_reload(monkeypatch) -> None:
    monkeypatch.setattr(
        daily_cycle,
        "JOB_EMBEDDING_MODEL",
        "text-embedding-nomic-embed-text-v1.5",
    )
    monkeypatch.setattr(daily_cycle, "_lms_binary", lambda: "/tmp/lms")
    monkeypatch.setattr(
        daily_cycle,
        "_embedding_model_ids",
        lambda: {"text-embedding-nomic-embed-text-v1.5"},
    )
    monkeypatch.setattr(
        daily_cycle,
        "_loaded_lms_model_ids",
        lambda *args, **kwargs: {"text-embedding-nomic-embed-text-v1.5"},
    )
    monkeypatch.setattr(
        daily_cycle.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no command expected")),
    )

    result = daily_cycle.ensure_job_embedding_ready(
        env={}, model_ttl_seconds=3600, timeout_seconds=1
    )

    assert result["model_loaded"] is False
    assert result["loaded_models"] == ["text-embedding-nomic-embed-text-v1.5"]


# ── Enrichment supervisor (2026-10-01) ─────────────────────────────────────────
# LM Studio dropped its model two hours into a ~2.5-day drain. The worker
# pauses with exit 4 on inference_unavailable by design, expecting to be
# restarted; the cycle had no supervisor, so the whole drain stopped.


def _stage(monkeypatch, returncodes, *, ensure_error=None):
    calls = {"run": 0, "ensure": 0, "sleeps": []}
    codes = iter(returncodes)

    def run(command, *, env):
        calls["run"] += 1
        return {"command": command, "returncode": next(codes)}

    def ensure(*, env, model_ttl_seconds, timeout_seconds):
        calls["ensure"] += 1
        if ensure_error:
            raise ensure_error
        return {"model_loaded": True}

    step = daily_cycle.run_enrichment_stage(
        ["worker"], env={}, model_ttl_seconds=60, timeout_seconds=1,
        run=run, ensure=ensure, sleep=calls["sleeps"].append, max_restarts=3,
    )
    return step, calls


def test_enrichment_stage_restarts_after_inference_drops(monkeypatch) -> None:
    step, calls = _stage(monkeypatch, [4, 4, 0])

    assert step["returncode"] == 0
    assert step["restarts"] == 2
    assert calls["ensure"] == 2
    assert len(calls["sleeps"]) == 2


def test_enrichment_stage_gives_up_after_bounded_restarts(monkeypatch) -> None:
    step, calls = _stage(monkeypatch, [4, 4, 4, 4, 4])

    assert step["returncode"] == 4
    assert step["restarts"] == 3
    assert calls["run"] == 4


def test_enrichment_stage_does_not_restart_other_failures(monkeypatch) -> None:
    for code in (1, 3):
        step, calls = _stage(monkeypatch, [code])
        assert step["returncode"] == code
        assert calls["run"] == 1
        assert calls["ensure"] == 0


def test_enrichment_stage_stops_when_the_model_cannot_be_reloaded(monkeypatch) -> None:
    step, calls = _stage(monkeypatch, [4, 0], ensure_error=RuntimeError("model not loaded within 1s"))

    assert step["returncode"] == 4
    assert "model not loaded" in step["restart_error"]
    assert calls["run"] == 1
