from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass

from openai import OpenAI

from normalizer import parse_json_response
from question_bank.config import QuestionBankConfig
from question_bank.models import NormalizedQuestion, VerificationResult
from question_bank.prompts import (
    NORMALIZE_SYSTEM_PROMPT,
    NORMALIZE_USER_PROMPT,
    VERIFY_SYSTEM_PROMPT,
    VERIFY_USER_PROMPT,
)
from question_bank.sources import SourceCandidate


@dataclass(frozen=True)
class ShuffledOptions:
    options: tuple[str, str, str, str]
    original_indexes: tuple[int, int, int, int]


def parse_llm_json(text: str) -> dict:
    parsed = parse_json_response(text)
    if not isinstance(parsed, dict):
        raise ValueError("LM Studio response did not contain a JSON object")
    return parsed


def deterministic_shuffle(
    options: tuple[str, str, str, str],
    *,
    seed: str,
) -> ShuffledOptions:
    indexes = list(range(4))
    seed_value = int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16)
    random.Random(seed_value).shuffle(indexes)
    return ShuffledOptions(
        options=tuple(options[index] for index in indexes),
        original_indexes=tuple(indexes),
    )


def remap_shuffled_index(shuffled: ShuffledOptions, chosen_index: int) -> int:
    if not isinstance(chosen_index, int) or isinstance(chosen_index, bool) or not 0 <= chosen_index <= 3:
        raise ValueError("verifier correct_index must be 0-3")
    return shuffled.original_indexes[chosen_index]


class LocalQuestionLLM:
    def __init__(self, config: QuestionBankConfig, client=None) -> None:
        self.config = config
        self.client = client or OpenAI(base_url=config.base_url, api_key=config.api_key)

    def _json_call(self, *, model: str, system: str, user: str, max_tokens: int) -> dict:
        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.0,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content or ""
        return parse_llm_json(content)

    def normalize(
        self,
        candidate: SourceCandidate,
        *,
        skill_description: str = "",
    ) -> dict:
        prompt = NORMALIZE_USER_PROMPT.format(
            skill_key=candidate.skill_key,
            skill_description=skill_description or "Not available",
            target_level=candidate.target_level or "Model assigns level 1-5",
            candidate_text=candidate.candidate_text,
        )
        return self._json_call(
            model=self.config.normalizer_model,
            system=NORMALIZE_SYSTEM_PROMPT,
            user=prompt,
            max_tokens=900,
        )

    def verify(
        self,
        question: NormalizedQuestion,
        *,
        skill_key: str,
        skill_description: str = "",
        seed: str,
    ) -> VerificationResult:
        shuffled = deterministic_shuffle(question.options, seed=seed)
        options_text = "\n".join(
            f"{index}. {option}" for index, option in enumerate(shuffled.options)
        )
        prompt = VERIFY_USER_PROMPT.format(
            skill_key=skill_key,
            skill_description=skill_description or "Not available",
            question_text=question.question_text,
            options_text=options_text,
        )
        payload = self._json_call(
            model=self.config.verifier_model,
            system=VERIFY_SYSTEM_PROMPT,
            user=prompt,
            max_tokens=400,
        )

        chosen_index: int | None = None
        try:
            chosen_index = remap_shuffled_index(shuffled, payload.get("correct_index"))
        except ValueError:
            pass
        suggested_level = payload.get("suggested_level")
        if not isinstance(suggested_level, int) or isinstance(suggested_level, bool) or not 1 <= suggested_level <= 5:
            suggested_level = None

        return VerificationResult(
            chosen_index=chosen_index,
            ambiguous=payload.get("ambiguous") is not False,
            rationale=str(payload.get("rationale") or "").strip(),
            suggested_level=suggested_level,
            same_model_verifier=self.config.same_model_verifier,
        )

