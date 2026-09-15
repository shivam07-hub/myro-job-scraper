from question_bank.dedupe import canonicalize_question_text, dedupe_hash, similarity


def test_canonicalization_normalizes_unicode_whitespace_and_terminal_punctuation() -> None:
    left = '  What is “product strategy” ? '
    right = 'what is "product strategy"'

    assert canonicalize_question_text(left) == canonicalize_question_text(right)
    assert dedupe_hash(left) == dedupe_hash(right)


def test_similarity_flags_close_paraphrases() -> None:
    left = "Which metric is most suitable for evaluating an imbalanced binary classifier?"
    right = "Which metric best evaluates a binary classifier when its classes are imbalanced?"

    assert similarity(left, right) >= 0.80


def test_similarity_keeps_unrelated_questions_apart() -> None:
    left = "Which metric is most suitable for evaluating an imbalanced binary classifier?"
    right = "What is the primary purpose of a product roadmap?"

    assert similarity(left, right) < 0.50

