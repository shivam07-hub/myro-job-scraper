import json

import pytest

from question_bank.config import QuestionBankConfig
from question_bank.llm import (
    LocalQuestionLLM,
    deterministic_shuffle,
    parse_llm_json,
    remap_shuffled_index,
)
from question_bank.models import NormalizedQuestion
from question_bank.sources import SourceCandidate


def test_config_rejects_cloud_llm_endpoint() -> None:
    with pytest.raises(ValueError, match="loopback"):
        QuestionBankConfig.from_env({
            "LM_STUDIO_BASE_URL": "https://api.openai.com/v1",
            "LM_STUDIO_MODEL": "cloud-model",
        })


def test_config_prefers_distinct_verifier_model() -> None:
    config = QuestionBankConfig.from_env({
        "LM_STUDIO_BASE_URL": "http://localhost:1234/v1",
        "LM_STUDIO_MODEL": "fallback",
        "QUESTION_NORMALIZER_MODEL": "local-normalizer",
        "QUESTION_VERIFIER_MODEL": "local-verifier",
    })

    assert config.normalizer_model == "local-normalizer"
    assert config.verifier_model == "local-verifier"
    assert config.same_model_verifier is False


def test_config_records_same_model_fallback() -> None:
    config = QuestionBankConfig.from_env({
        "LM_STUDIO_BASE_URL": "http://127.0.0.1:1234/v1",
        "LM_STUDIO_MODEL": "one-local-model",
    })

    assert config.verifier_model == "one-local-model"
    assert config.same_model_verifier is True


def test_deterministic_shuffle_can_map_answer_back() -> None:
    options = ("zero", "one", "two", "three")

    first = deterministic_shuffle(options, seed="raw-hash")
    second = deterministic_shuffle(options, seed="raw-hash")

    assert first == second
    assert set(first.options) == set(options)
    for shuffled_index, original_index in enumerate(first.original_indexes):
        assert remap_shuffled_index(first, shuffled_index) == original_index


def test_parse_llm_json_accepts_fenced_payload() -> None:
    payload = parse_llm_json('```json\n{"level": 3}\n```')

    assert payload == {"level": 3}


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.choices = [_FakeChoice(json.dumps(payload))]


class _FakeCompletions:
    def __init__(self, payloads: list[dict], calls: list[dict]) -> None:
        self.payloads = payloads
        self.calls = calls

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeResponse(self.payloads.pop(0))


class _FakeChat:
    def __init__(self, payloads: list[dict], calls: list[dict]) -> None:
        self.completions = _FakeCompletions(payloads, calls)


class _FakeClient:
    def __init__(self, payloads: list[dict]) -> None:
        self.calls: list[dict] = []
        self.chat = _FakeChat(payloads, self.calls)


def test_local_llm_uses_separate_models_for_normalize_and_verify() -> None:
    config = QuestionBankConfig.from_env({
        "LM_STUDIO_BASE_URL": "http://localhost:1234/v1",
        "QUESTION_NORMALIZER_MODEL": "normalizer",
        "QUESTION_VERIFIER_MODEL": "verifier",
    })
    client = _FakeClient([
        {
            "question_text": "Which metric balances precision and recall?",
            "options": ["Accuracy", "F1 score", "R-squared", "MAE"],
            "correct_index": 1,
            "explanation": "F1 score is the harmonic mean of precision and recall.",
            "level": 1,
            "rejected": False,
            "rejection_reason": "",
        },
        {
            "correct_index": 0,
            "ambiguous": False,
            "rationale": "F1 score balances precision and recall.",
            "suggested_level": 1,
        },
    ])
    llm = LocalQuestionLLM(config, client=client)
    candidate = SourceCandidate(
        skill_key="Machine Learning",
        source_url="https://example.org/source",
        candidate_text="What is the F1 metric?",
        target_level=1,
    )
    normalized = llm.normalize(candidate, skill_description="Machine learning model evaluation.")
    question = NormalizedQuestion(
        question_text=normalized["question_text"],
        options=tuple(normalized["options"]),
        correct_index=normalized["correct_index"],
        explanation=normalized["explanation"],
        level=normalized["level"],
    )

    verification = llm.verify(
        question,
        skill_key="Machine Learning",
        skill_description="Machine learning model evaluation.",
        seed="stable-seed",
    )

    assert client.calls[0]["model"] == "normalizer"
    assert client.calls[1]["model"] == "verifier"
    assert verification.ambiguous is False
    assert verification.same_model_verifier is False

