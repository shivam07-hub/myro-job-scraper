from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Iterable

from question_bank.dedupe import dedupe_hash, raw_hash, similarity
from question_bank.models import NormalizedQuestion, SkillRef, validate_normalized_question
from question_bank.sources import SourceCandidate
from question_bank.state import RunState


_SOURCE_SIMILARITY_LIMIT = 0.92
_NEAR_DUPLICATE_LIMIT = 0.80


@dataclass(frozen=True)
class PipelineResult:
    rows: list[dict]
    summary: dict


class QuestionPipeline:
    def __init__(
        self,
        *,
        normalizer,
        verifier,
        state: RunState,
        skills: dict[str, SkillRef],
        existing_rows: list[dict] | None = None,
    ) -> None:
        self.normalizer = normalizer
        self.verifier = verifier
        self.state = state
        self.skills = skills
        self.existing_rows = existing_rows or []

        self._known_hashes: dict[str, set[str]] = defaultdict(set)
        self._known_texts: dict[str, list[str]] = defaultdict(list)
        for row in self.existing_rows:
            skill_key = str(row.get("skill_key") or "")
            question_text = str(row.get("question_text") or "")
            question_hash = str(row.get("dedupe_hash") or "")
            if skill_key and question_hash:
                self._known_hashes[skill_key].add(question_hash)
            if skill_key and question_text:
                self._known_texts[skill_key].append(question_text)

    def process(self, candidates: Iterable[SourceCandidate]) -> PipelineResult:
        completed = self.state.completed_raw_hashes()
        saved_normalized = self.state.normalized_by_hash()
        seen_raw: set[str] = set()
        output_rows: list[dict] = []
        rejected_reasons: Counter[str] = Counter()
        by_skill_level: dict[str, Counter[int]] = defaultdict(Counter)
        by_skill_level_status: dict[str, dict[int, Counter[str]]] = defaultdict(
            lambda: defaultdict(Counter)
        )
        summary = {
            "processed": 0,
            "skipped_completed": 0,
            "active": 0,
            "review": 0,
            "rejected": 0,
        }

        for candidate in candidates:
            source_hash = raw_hash(candidate.candidate_text)
            if source_hash in completed:
                summary["skipped_completed"] += 1
                continue
            if source_hash in seen_raw:
                self._reject(candidate, source_hash, "raw_duplicate")
                summary["rejected"] += 1
                rejected_reasons["raw_duplicate"] += 1
                continue
            seen_raw.add(source_hash)
            summary["processed"] += 1

            skill = self.skills.get(candidate.skill_key)
            if skill is None:
                self._reject(candidate, source_hash, "unknown_skill")
                summary["rejected"] += 1
                rejected_reasons["unknown_skill"] += 1
                continue

            saved = saved_normalized.get(source_hash)
            if saved:
                validation = validate_normalized_question(saved)
            else:
                try:
                    payload = self.normalizer.normalize(
                        candidate,
                        skill_description=skill.description,
                    )
                except Exception as exc:
                    self._reject(candidate, source_hash, "normalizer_error", details=str(exc))
                    summary["rejected"] += 1
                    rejected_reasons["normalizer_error"] += 1
                    continue
                validation = validate_normalized_question(payload)

            if not validation.ok or validation.question is None:
                reason = "model_rejected" if validation.model_rejection_reason else (
                    validation.errors[0] if validation.errors else "invalid_normalization"
                )
                self._reject(
                    candidate,
                    source_hash,
                    reason,
                    details=validation.model_rejection_reason or ",".join(validation.errors),
                )
                summary["rejected"] += 1
                rejected_reasons[reason] += 1
                continue

            question = validation.question
            if similarity(candidate.candidate_text, question.question_text) >= _SOURCE_SIMILARITY_LIMIT:
                self._reject(candidate, source_hash, "source_too_similar")
                summary["rejected"] += 1
                rejected_reasons["source_too_similar"] += 1
                continue

            question_hash = dedupe_hash(question.question_text)
            if question_hash in self._known_hashes[candidate.skill_key]:
                self._reject(candidate, source_hash, "exact_duplicate")
                summary["rejected"] += 1
                rejected_reasons["exact_duplicate"] += 1
                continue

            normalized_row = {
                "raw_hash": source_hash,
                "skill_id": skill.skill_id,
                "skill_key": skill.skill_key,
                "source_url": candidate.source_url,
                **asdict(question),
                "options": list(question.options),
                "dedupe_hash": question_hash,
            }
            if not saved:
                self.state.append_normalized(normalized_row)

            near_duplicate = any(
                similarity(question.question_text, known) >= _NEAR_DUPLICATE_LIMIT
                for known in self._known_texts[candidate.skill_key]
            )

            try:
                verification = self.verifier.verify(
                    question,
                    skill_key=skill.skill_key,
                    skill_description=skill.description,
                    seed=source_hash,
                )
            except Exception as exc:
                verification = None
                verification_error = str(exc)
            else:
                verification_error = ""

            review_reasons: list[str] = []
            if near_duplicate:
                review_reasons.append("near_duplicate")
            if verification is None:
                review_reasons.append("verifier_error")
            else:
                if verification.ambiguous:
                    review_reasons.append("verifier_ambiguous")
                if verification.chosen_index != question.correct_index:
                    review_reasons.append("answer_disagreement")
                if verification.suggested_level is None:
                    review_reasons.append("verifier_level_missing")
                elif abs(verification.suggested_level - question.level) > 1:
                    review_reasons.append("level_disagreement")

            status = "review" if review_reasons else "active"
            row = {
                **normalized_row,
                "status": status,
                "review_reasons": review_reasons,
                "verifier_correct_index": (
                    verification.chosen_index if verification is not None else None
                ),
                "verifier_ambiguous": (
                    verification.ambiguous if verification is not None else None
                ),
                "verifier_rationale": (
                    verification.rationale if verification is not None else verification_error
                ),
                "verifier_suggested_level": (
                    verification.suggested_level if verification is not None else None
                ),
                "same_model_verifier": (
                    verification.same_model_verifier if verification is not None else None
                ),
            }
            self.state.append_verified(row)
            output_rows.append(row)
            summary[status] += 1
            by_skill_level[skill.skill_key][question.level] += 1
            by_skill_level_status[skill.skill_key][question.level][status] += 1
            self._known_hashes[skill.skill_key].add(question_hash)
            self._known_texts[skill.skill_key].append(question.question_text)

        summary["rejected_by_reason"] = dict(sorted(rejected_reasons.items()))
        summary["by_skill_level"] = {
            skill: {str(level): count for level, count in sorted(levels.items())}
            for skill, levels in sorted(by_skill_level.items())
        }
        summary["by_skill_level_status"] = {
            skill: {
                str(level): {
                    "active": statuses.get("active", 0),
                    "review": statuses.get("review", 0),
                }
                for level, statuses in sorted(levels.items())
            }
            for skill, levels in sorted(by_skill_level_status.items())
        }
        self.state.write_summary(summary)
        return PipelineResult(rows=output_rows, summary=summary)

    def _reject(
        self,
        candidate: SourceCandidate,
        source_hash: str,
        reason: str,
        *,
        details: str = "",
    ) -> None:
        self.state.append_rejected({
            "raw_hash": source_hash,
            "skill_key": candidate.skill_key,
            "source_url": candidate.source_url,
            "reason": reason,
            "details": details,
        })
