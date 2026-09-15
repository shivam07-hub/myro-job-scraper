from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


PILOT_SKILLS = (
    "Machine Learning",
    "Product Strategy",
    "Management Consulting",
    "Financial Accounting",
)


@dataclass(frozen=True)
class PilotSkill:
    skill_key: str
    target_per_level: int = 10


@dataclass(frozen=True)
class SourceManifest:
    skills: tuple[PilotSkill, ...]
    input_files: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceCandidate:
    skill_key: str
    source_url: str
    candidate_text: str
    target_level: int | None = None


def load_manifest(path: Path) -> SourceManifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != 1:
        raise ValueError("manifest version must be 1")
    skills = tuple(
        PilotSkill(
            skill_key=str(item.get("skill_key") or "").strip(),
            target_per_level=int(item.get("target_per_level", 10)),
        )
        for item in data.get("skills", [])
    )
    if tuple(skill.skill_key for skill in skills) != PILOT_SKILLS:
        raise ValueError("manifest skills must match the four approved pilot skills")
    if any(skill.target_per_level < 1 for skill in skills):
        raise ValueError("target_per_level must be positive")
    input_files = tuple(str(value) for value in data.get("input_files", []))
    return SourceManifest(skills=skills, input_files=input_files)


def _valid_source_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def iter_jsonl_candidates(
    path: Path,
    *,
    allowed_skills: set[str],
    limit: int | None = None,
):
    count = 0
    with path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, 1):
            if not raw_line.strip():
                continue
            try:
                item = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSON") from exc

            skill_key = str(item.get("skill_key") or "").strip()
            source_url = str(item.get("source_url") or "").strip()
            candidate_text = str(item.get("candidate_text") or "").strip()
            target_level = item.get("target_level")

            if skill_key not in allowed_skills:
                raise ValueError(f"{path}:{line_number}: invalid skill_key {skill_key!r}")
            if not _valid_source_url(source_url):
                raise ValueError(f"{path}:{line_number}: source_url must be HTTP(S)")
            if not candidate_text:
                raise ValueError(f"{path}:{line_number}: candidate_text is required")
            if target_level is not None:
                if not isinstance(target_level, int) or isinstance(target_level, bool) or not 1 <= target_level <= 5:
                    raise ValueError(f"{path}:{line_number}: target_level must be 1-5")

            yield SourceCandidate(
                skill_key=skill_key,
                source_url=source_url,
                candidate_text=candidate_text,
                target_level=target_level,
            )
            count += 1
            if limit is not None and count >= limit:
                return

