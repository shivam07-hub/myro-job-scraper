import json
from pathlib import Path

import pytest

from question_bank.state import RunState


def test_state_never_persists_source_candidate_text(tmp_path: Path) -> None:
    state = RunState(tmp_path, "run-1")

    with pytest.raises(ValueError, match="copyright-sensitive"):
        state.append_normalized({
            "raw_hash": "abc",
            "candidate_text": "verbatim source text",
        })

    assert not (state.run_dir / "normalized.jsonl").exists()


def test_resume_distinguishes_normalized_from_completed(tmp_path: Path) -> None:
    state = RunState(tmp_path, "run-2")
    state.append_normalized({"raw_hash": "abc", "question_text": "Normalized question?"})

    reloaded = RunState(tmp_path, "run-2")

    assert reloaded.normalized_by_hash()["abc"]["question_text"] == "Normalized question?"
    assert "abc" not in reloaded.completed_raw_hashes()

    reloaded.append_verified({"raw_hash": "abc", "status": "active"})

    assert "abc" in RunState(tmp_path, "run-2").completed_raw_hashes()


def test_rejection_checkpoint_contains_only_safe_metadata(tmp_path: Path) -> None:
    state = RunState(tmp_path, "run-3")
    state.append_rejected({
        "raw_hash": "def",
        "source_url": "https://example.org/source",
        "reason": "ambiguous",
    })

    row = json.loads((state.run_dir / "rejected.jsonl").read_text(encoding="utf-8"))

    assert row["reason"] == "ambiguous"
    assert "candidate_text" not in row
    assert not list(state.run_dir.glob("*.tmp"))

