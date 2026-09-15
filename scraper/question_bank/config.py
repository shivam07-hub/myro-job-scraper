from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping
from urllib.parse import urlparse


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass(frozen=True)
class QuestionBankConfig:
    base_url: str
    api_key: str
    normalizer_model: str
    verifier_model: str

    @property
    def same_model_verifier(self) -> bool:
        return self.normalizer_model == self.verifier_model

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "QuestionBankConfig":
        values = os.environ if env is None else env
        base_url = values.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1").strip()
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in _LOOPBACK_HOSTS:
            raise ValueError("question-bank LLM endpoint must be an HTTP loopback URL")

        fallback_model = (
            values.get("LM_STUDIO_MODEL")
            or values.get("LM_STUDIO_MODEL_FAST")
            or "google/gemma-3-4b"
        ).strip()
        normalizer_model = values.get("QUESTION_NORMALIZER_MODEL", fallback_model).strip()
        verifier_model = values.get("QUESTION_VERIFIER_MODEL", normalizer_model).strip()
        if not normalizer_model or not verifier_model:
            raise ValueError("normalizer and verifier model names are required")

        return cls(
            base_url=base_url.rstrip("/"),
            api_key=values.get("LM_STUDIO_API_KEY", "lm-studio"),
            normalizer_model=normalizer_model,
            verifier_model=verifier_model,
        )

