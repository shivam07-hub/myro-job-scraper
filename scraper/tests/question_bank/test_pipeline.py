from pathlib import Path

from question_bank.dedupe import dedupe_hash, raw_hash
from question_bank.models import SkillRef, VerificationResult
from question_bank.pipeline import QuestionPipeline
from question_bank.sources import SourceCandidate
from question_bank.state import RunState


VALID_PAYLOAD = {
    "question_text": "Which metric balances precision and recall?",
    "options": ["Accuracy", "F1 score", "R-squared", "Mean absolute error"],
    "correct_index": 1,
    "explanation": "F1 score is the harmonic mean of precision and recall.",
    "level": 2,
    "rejected": False,
    "rejection_reason": "",
}


class FakeNormalizer:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    def normalize(self, candidate, *, skill_description=""):
        self.calls += 1
        return dict(self.payload)


class FakeVerifier:
    def __init__(self, result: VerificationResult) -> None:
        self.result = result
        self.calls = 0

    def verify(self, question, *, skill_key, skill_description="", seed=""):
        self.calls += 1
        return self.result


def candidate(text: str = "How should F1 be used?") -> SourceCandidate:
    return SourceCandidate(
        skill_key="Machine Learning",
        source_url="https://example.org/ml",
        candidate_text=text,
        target_level=2,
    )


def skill_refs() -> dict[str, SkillRef]:
    return {
        "Machine Learning": SkillRef(
            skill_id=2772,
            skill_key="Machine Learning",
            description="Methods for systems that learn patterns from data.",
        )
    }


def verifier_result(
    *,
    chosen_index: int | None = 1,
    ambiguous: bool = False,
    suggested_level: int | None = 2,
) -> VerificationResult:
    return VerificationResult(
        chosen_index=chosen_index,
        ambiguous=ambiguous,
        rationale="F1 score balances precision and recall.",
        suggested_level=suggested_level,
        same_model_verifier=False,
    )


def build_pipeline(
    tmp_path: Path,
    normalizer: FakeNormalizer,
    verifier: FakeVerifier,
    *,
    existing_rows: list[dict] | None = None,
) -> QuestionPipeline:
    return QuestionPipeline(
        normalizer=normalizer,
        verifier=verifier,
        state=RunState(tmp_path, "pilot"),
        skills=skill_refs(),
        existing_rows=existing_rows or [],
    )


def test_agreement_publishes_active_row(tmp_path: Path) -> None:
    pipeline = build_pipeline(
        tmp_path,
        FakeNormalizer(VALID_PAYLOAD),
        FakeVerifier(verifier_result()),
    )

    result = pipeline.process([candidate()])

    assert result.rows[0]["status"] == "active"
    assert result.rows[0]["correct_index"] == 1
    assert result.summary["active"] == 1
    assert result.summary["by_skill_level_status"]["Machine Learning"]["2"]["active"] == 1


def test_answer_disagreement_is_review(tmp_path: Path) -> None:
    pipeline = build_pipeline(
        tmp_path,
        FakeNormalizer(VALID_PAYLOAD),
        FakeVerifier(verifier_result(chosen_index=0)),
    )

    result = pipeline.process([candidate()])
    row = result.rows[0]

    assert row["status"] == "review"
    assert "answer_disagreement" in row["review_reasons"]
    assert result.summary["by_skill_level_status"]["Machine Learning"]["2"]["review"] == 1


def test_ambiguity_is_review(tmp_path: Path) -> None:
    pipeline = build_pipeline(
        tmp_path,
        FakeNormalizer(VALID_PAYLOAD),
        FakeVerifier(verifier_result(ambiguous=True)),
    )

    row = pipeline.process([candidate()]).rows[0]

    assert row["status"] == "review"
    assert "verifier_ambiguous" in row["review_reasons"]


def test_large_level_disagreement_is_review(tmp_path: Path) -> None:
    pipeline = build_pipeline(
        tmp_path,
        FakeNormalizer(VALID_PAYLOAD),
        FakeVerifier(verifier_result(suggested_level=5)),
    )

    row = pipeline.process([candidate()]).rows[0]

    assert row["status"] == "review"
    assert "level_disagreement" in row["review_reasons"]


def test_exact_existing_duplicate_is_rejected_without_verification(tmp_path: Path) -> None:
    existing = [{
        "skill_id": 2772,
        "skill_key": "Machine Learning",
        "level": 2,
        "question_text": VALID_PAYLOAD["question_text"],
        "dedupe_hash": dedupe_hash(VALID_PAYLOAD["question_text"]),
        "status": "active",
    }]
    verifier = FakeVerifier(verifier_result())
    pipeline = build_pipeline(
        tmp_path,
        FakeNormalizer(VALID_PAYLOAD),
        verifier,
        existing_rows=existing,
    )

    result = pipeline.process([candidate()])

    assert result.rows == []
    assert result.summary["rejected_by_reason"]["exact_duplicate"] == 1
    assert verifier.calls == 0


def test_near_duplicate_is_verified_but_kept_for_review(tmp_path: Path) -> None:
    existing_text = "Which metric best evaluates a binary classifier when classes are imbalanced?"
    payload = dict(VALID_PAYLOAD)
    payload["question_text"] = "Which metric evaluates an imbalanced binary classifier most effectively?"
    existing = [{
        "skill_id": 2772,
        "skill_key": "Machine Learning",
        "level": 2,
        "question_text": existing_text,
        "dedupe_hash": dedupe_hash(existing_text),
        "status": "active",
    }]
    verifier = FakeVerifier(verifier_result())
    pipeline = build_pipeline(
        tmp_path,
        FakeNormalizer(payload),
        verifier,
        existing_rows=existing,
    )

    row = pipeline.process([candidate()]).rows[0]

    assert row["status"] == "review"
    assert "near_duplicate" in row["review_reasons"]
    assert verifier.calls == 1


def test_source_wording_that_survives_normalization_is_rejected(tmp_path: Path) -> None:
    source = VALID_PAYLOAD["question_text"]
    pipeline = build_pipeline(
        tmp_path,
        FakeNormalizer(VALID_PAYLOAD),
        FakeVerifier(verifier_result()),
    )

    result = pipeline.process([candidate(source)])

    assert result.rows == []
    assert result.summary["rejected_by_reason"]["source_too_similar"] == 1


def test_resume_verifies_saved_normalization_without_calling_normalizer(tmp_path: Path) -> None:
    source_candidate = candidate()
    source_hash = raw_hash(source_candidate.candidate_text)
    state = RunState(tmp_path, "pilot")
    state.append_normalized({
        "raw_hash": source_hash,
        "skill_id": 2772,
        "skill_key": "Machine Learning",
        "source_url": source_candidate.source_url,
        **{key: value for key, value in VALID_PAYLOAD.items() if key not in {"rejected", "rejection_reason"}},
        "dedupe_hash": dedupe_hash(VALID_PAYLOAD["question_text"]),
    })
    normalizer = FakeNormalizer(VALID_PAYLOAD)
    verifier = FakeVerifier(verifier_result())
    pipeline = QuestionPipeline(
        normalizer=normalizer,
        verifier=verifier,
        state=state,
        skills=skill_refs(),
    )

    result = pipeline.process([source_candidate])

    assert result.rows[0]["status"] == "active"
    assert normalizer.calls == 0
    assert verifier.calls == 1
