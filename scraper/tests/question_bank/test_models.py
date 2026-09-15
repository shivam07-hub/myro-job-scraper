from question_bank.models import validate_normalized_question


def valid_payload() -> dict:
    return {
        "question_text": "Which metric best evaluates a binary classifier when classes are imbalanced?",
        "options": ["Accuracy", "F1 score", "Mean squared error", "R-squared"],
        "correct_index": 1,
        "explanation": "F1 score balances precision and recall, making it useful when class frequencies differ.",
        "level": 2,
    }


def test_accepts_well_formed_question() -> None:
    result = validate_normalized_question(valid_payload())

    assert result.ok is True
    assert result.question is not None
    assert result.question.level == 2


def test_requires_exactly_four_distinct_options() -> None:
    payload = valid_payload()
    payload["options"] = ["A", "B", "B", "D"]

    result = validate_normalized_question(payload)

    assert result.ok is False
    assert "options_not_distinct" in result.errors


def test_rejects_out_of_range_answer_and_level() -> None:
    payload = valid_payload()
    payload["correct_index"] = 4
    payload["level"] = 6

    result = validate_normalized_question(payload)

    assert result.ok is False
    assert "correct_index_out_of_range" in result.errors
    assert "level_out_of_range" in result.errors


def test_rejects_aggregate_options() -> None:
    payload = valid_payload()
    payload["options"][3] = "All of the above"

    result = validate_normalized_question(payload)

    assert result.ok is False
    assert "forbidden_aggregate_option" in result.errors


def test_requires_one_sentence_explanation() -> None:
    payload = valid_payload()
    payload["explanation"] = "F1 balances precision and recall. It is useful for imbalanced data."

    result = validate_normalized_question(payload)

    assert result.ok is False
    assert "explanation_not_one_sentence" in result.errors


def test_respects_explicit_model_rejection() -> None:
    payload = {
        "rejected": True,
        "rejection_reason": "The source asks for an opinion.",
    }

    result = validate_normalized_question(payload)

    assert result.ok is False
    assert result.model_rejection_reason == "The source asks for an opinion."

