import json
from pathlib import Path

import pytest

from question_bank.sources import PILOT_SKILLS, iter_jsonl_candidates, load_manifest


def test_pilot_manifest_contains_all_four_approved_skills() -> None:
    manifest_path = Path(__file__).parents[2] / "question_bank" / "pilot_sources.json"

    manifest = load_manifest(manifest_path)

    assert tuple(skill.skill_key for skill in manifest.skills) == PILOT_SKILLS
    assert all(skill.target_per_level == 10 for skill in manifest.skills)


def test_jsonl_ingestion_keeps_provenance_and_transient_text(tmp_path: Path) -> None:
    source = tmp_path / "candidates.jsonl"
    source.write_text(
        json.dumps({
            "skill_key": "Machine Learning",
            "source_url": "https://example.org/ml-interview",
            "candidate_text": "What is overfitting?",
            "target_level": 1,
        }) + "\n",
        encoding="utf-8",
    )

    candidates = list(iter_jsonl_candidates(source, allowed_skills=set(PILOT_SKILLS)))

    assert len(candidates) == 1
    assert candidates[0].candidate_text == "What is overfitting?"
    assert candidates[0].source_url == "https://example.org/ml-interview"
    assert candidates[0].target_level == 1


def test_jsonl_ingestion_rejects_non_http_provenance(tmp_path: Path) -> None:
    source = tmp_path / "candidates.jsonl"
    source.write_text(
        json.dumps({
            "skill_key": "Product Strategy",
            "source_url": "file:///tmp/private-notes",
            "candidate_text": "What is positioning?",
        }) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="source_url"):
        list(iter_jsonl_candidates(source, allowed_skills=set(PILOT_SKILLS)))


def test_jsonl_ingestion_rejects_unknown_skill(tmp_path: Path) -> None:
    source = tmp_path / "candidates.jsonl"
    source.write_text(
        json.dumps({
            "skill_key": "Unknown Skill",
            "source_url": "https://example.org/source",
            "candidate_text": "Question?",
        }) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="skill_key"):
        list(iter_jsonl_candidates(source, allowed_skills=set(PILOT_SKILLS)))

