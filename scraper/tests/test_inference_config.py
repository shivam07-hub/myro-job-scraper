from __future__ import annotations

import pytest

from config import resolve_inference_config, resolve_job_embedding_config


def test_legacy_lm_studio_variables_remain_supported() -> None:
    config = resolve_inference_config({
        "LM_STUDIO_BASE_URL": "http://localhost:1234/v1",
        "LM_STUDIO_API_KEY": "lm-studio",
        "LM_STUDIO_MODEL": "google/gemma-3-4b",
    })

    assert config.provider == "local"
    assert config.model == "google/gemma-3-4b"


def test_generic_inference_variables_take_precedence() -> None:
    config = resolve_inference_config({
        "INFERENCE_BASE_URL": "http://127.0.0.1:1234/v1",
        "INFERENCE_API_KEY": "local",
        "INFERENCE_MODEL": "llama-3.2-3b-instruct",
        "LM_STUDIO_MODEL": "google/gemma-3-4b",
    })

    assert config.provider == "local"
    assert config.model == "llama-3.2-3b-instruct"


def test_remote_open_weight_requires_allowlist() -> None:
    with pytest.raises(ValueError, match="allowlist"):
        resolve_inference_config({
            "INFERENCE_BASE_URL": "https://open-weight.example/v1",
            "INFERENCE_MODEL": "google/gemma-3-4b",
        })


def test_remote_open_weight_accepts_allowlisted_model() -> None:
    config = resolve_inference_config({
        "INFERENCE_BASE_URL": "https://open-weight.example/v1",
        "INFERENCE_API_KEY": "placeholder",
        "INFERENCE_MODEL": "google/gemma-3-4b",
        "OPEN_WEIGHT_MODEL_ALLOWLIST": "google/gemma-3-4b",
    })

    assert config.provider == "remote_open_weight"
    assert config.model_allowlist == ("google/gemma-3-4b",)


def test_cloudflare_workers_ai_derives_openai_compatible_endpoint() -> None:
    model = "@cf/meta/llama-3.1-8b-instruct-fp8-fast"
    config = resolve_inference_config({
        "CLOUDFLARE_ACCOUNT_ID": "account-id",
        "CLOUDFLARE_API_TOKEN": "token",
        "CLOUDFLARE_WORKERS_AI_MODEL": model,
        "CLOUDFLARE_WORKERS_AI_MODEL_ALLOWLIST": model,
    })

    assert config.provider == "cloudflare_workers_ai"
    assert config.base_url == "https://api.cloudflare.com/client/v4/accounts/account-id/ai/v1"
    assert config.api_key == "token"


def test_job_embeddings_default_to_local_nomic_768() -> None:
    config = resolve_job_embedding_config({})

    assert config.base_url == "http://localhost:1234/v1"
    assert config.model == "text-embedding-nomic-embed-text-v1.5"
    assert config.dimensions == 768


def test_job_embeddings_reject_remote_endpoint() -> None:
    with pytest.raises(ValueError, match="loopback"):
        resolve_job_embedding_config({
            "JOB_EMBEDDING_BASE_URL": "https://embedding.example/v1",
        })
