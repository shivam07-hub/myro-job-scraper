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
