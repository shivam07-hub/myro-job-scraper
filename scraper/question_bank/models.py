from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


_SENTENCE_END_RE = re.compile(r"[.!?](?:\s|$)")
_FORBIDDEN_OPTIONS = {
    "all of the above",
    "none of the above",
    "both a and b",
    "all options are correct",
}


@dataclass(frozen=True)
class NormalizedQuestion:
    question_text: str
    options: tuple[str, str, str, str]
    correct_index: int
    explanation: str
    level: int


@dataclass(frozen=True)
class SkillRef:
    skill_id: int
    skill_key: str
    description: str = ""


@dataclass(frozen=True)
class ValidationResult:
    question: NormalizedQuestion | None
    errors: tuple[str, ...] = ()
    model_rejection_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.question is not None and not self.errors


@dataclass(frozen=True)
class VerificationResult:
    chosen_index: int | None
    ambiguous: bool
    rationale: str
    suggested_level: int | None
    same_model_verifier: bool


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def validate_normalized_question(payload: Any) -> ValidationResult:
    if not isinstance(payload, dict):
        return ValidationResult(None, ("payload_not_object",))

    if payload.get("rejected") is True:
        reason = _clean(payload.get("rejection_reason")) or "model_rejected"
        return ValidationResult(None, ("model_rejected",), reason)

    errors: list[str] = []
    question_text = _clean(payload.get("question_text"))
    explanation = _clean(payload.get("explanation"))
    options_raw = payload.get("options")
    correct_index = payload.get("correct_index")
    level = payload.get("level")

    if not question_text:
        errors.append("question_text_missing")
    elif len(question_text) > 500:
        errors.append("question_text_too_long")

    options: list[str] = []
    if not isinstance(options_raw, list) or len(options_raw) != 4:
        errors.append("options_count_not_four")
    else:
        options = [_clean(option) for option in options_raw]
        if any(not option for option in options):
            errors.append("option_empty")
        if any(len(option) > 300 for option in options):
            errors.append("option_too_long")
        option_keys = [option.casefold() for option in options]
        if len(set(option_keys)) != 4:
            errors.append("options_not_distinct")
        if any(option.casefold().rstrip(".") in _FORBIDDEN_OPTIONS for option in options):
            errors.append("forbidden_aggregate_option")

    if not isinstance(correct_index, int) or isinstance(correct_index, bool) or not 0 <= correct_index <= 3:
        errors.append("correct_index_out_of_range")

    if not isinstance(level, int) or isinstance(level, bool) or not 1 <= level <= 5:
        errors.append("level_out_of_range")

    if not explanation:
        errors.append("explanation_missing")
    elif len(explanation) > 500:
        errors.append("explanation_too_long")
    elif len(_SENTENCE_END_RE.findall(explanation)) != 1 or explanation[-1] not in ".!?":
        errors.append("explanation_not_one_sentence")

    if errors:
        return ValidationResult(None, tuple(errors))

    return ValidationResult(
        NormalizedQuestion(
            question_text=question_text,
            options=(options[0], options[1], options[2], options[3]),
            correct_index=correct_index,
            explanation=explanation,
            level=level,
        )
    )
