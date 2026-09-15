from __future__ import annotations

import argparse
import itertools
import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


from question_bank.config import QuestionBankConfig
from question_bank.llm import LocalQuestionLLM
from question_bank.pipeline import QuestionPipeline
from question_bank.sources import (
    PILOT_SKILLS,
    SourceManifest,
    iter_jsonl_candidates,
    load_manifest,
)
from question_bank.state import RunState
from question_bank.supabase_writer import QuestionBankSupabase

from environment import load_environment

_HERE = Path(__file__).resolve().parent
_SCRAPER_DIR = _HERE.parent
_ROOT = _SCRAPER_DIR.parent
_DEFAULT_MANIFEST = _HERE / "pilot_sources.json"
_DEFAULT_LOG_DIR = _ROOT / "logs" / "question_bank"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalize, verify, and publish local-LM skill questions."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=_DEFAULT_MANIFEST,
        help="Pilot source manifest JSON.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        action="append",
        default=[],
        help="Copyright-sensitive source candidate JSONL; may be repeated.",
    )
    parser.add_argument(
        "--skill",
        action="append",
        choices=PILOT_SKILLS,
        help="Limit the run to one or more approved pilot skills.",
    )
    parser.add_argument("--limit", type=int, default=0, help="Global candidate cap; 0 is unlimited.")
    parser.add_argument("--run-id", help="Create or continue this run ID.")
    parser.add_argument("--resume-run", help="Resume this existing run ID.")
    parser.add_argument(
        "--logs-dir",
        type=Path,
        default=_DEFAULT_LOG_DIR,
        help="Copyright-safe run diagnostics directory.",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Validate Supabase schema and taxonomy keys, then exit before LM Studio.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Run fully but make no Supabase writes.")
    mode.add_argument("--publish", action="store_true", help="Allow guarded Supabase upserts.")
    return parser


def selected_skill_keys(args: argparse.Namespace, manifest: SourceManifest) -> tuple[str, ...]:
    available = tuple(skill.skill_key for skill in manifest.skills)
    if not args.skill:
        return available
    selected = tuple(dict.fromkeys(args.skill))
    missing = [key for key in selected if key not in available]
    if missing:
        raise ValueError("selected skill is absent from manifest: " + ", ".join(missing))
    return selected


def _input_paths(args: argparse.Namespace, manifest: SourceManifest) -> list[Path]:
    if args.input:
        return [path.resolve() for path in args.input]
    return [
        (args.manifest.parent / relative).resolve()
        for relative in manifest.input_files
    ]


def _candidate_stream(
    paths: list[Path],
    *,
    manifest_skills: set[str],
    selected_skills: set[str],
    limit: int,
):
    stream = (
        candidate
        for path in paths
        for candidate in iter_jsonl_candidates(path, allowed_skills=manifest_skills)
        if candidate.skill_key in selected_skills
    )
    return itertools.islice(stream, limit) if limit > 0 else stream


def _coverage_summary(
    manifest: SourceManifest,
    selected: tuple[str, ...],
    existing_rows: list[dict],
    new_rows: list[dict],
) -> dict:
    targets = {skill.skill_key: skill.target_per_level for skill in manifest.skills}
    counts: dict[str, Counter[int]] = defaultdict(Counter)
    for row in existing_rows + new_rows:
        if row.get("status") != "active" or row.get("skill_key") not in selected:
            continue
        level = row.get("level")
        if isinstance(level, int) and 1 <= level <= 5:
            counts[row["skill_key"]][level] += 1

    coverage: dict[str, dict] = {}
    for skill_key in selected:
        target = targets[skill_key]
        coverage[skill_key] = {
            str(level): {
                "active": counts[skill_key][level],
                "target": target,
                "remaining": max(target - counts[skill_key][level], 0),
            }
            for level in range(1, 6)
        }
    return coverage


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.run_id and args.resume_run:
        parser.error("--run-id and --resume-run cannot be combined")
    if args.limit < 0:
        parser.error("--limit cannot be negative")

    load_environment()
    manifest = load_manifest(args.manifest)
    selected = selected_skill_keys(args, manifest)

    supabase_url = (os.getenv("SUPABASE_URL") or "").strip()
    service_key = (os.getenv("SUPABASE_SERVICE_KEY") or "").strip()
    store = QuestionBankSupabase(supabase_url, service_key)
    store.preflight()
    skills = store.resolve_skills(selected)
    existing_rows = store.load_existing(skill.skill_id for skill in skills.values())
    print(
        json.dumps({
            "preflight": "ok",
            "skills": {
                key: {"skill_id": ref.skill_id, "has_description": bool(ref.description)}
                for key, ref in skills.items()
            },
            "existing_questions": len(existing_rows),
        }, indent=2, sort_keys=True)
    )
    if args.preflight_only:
        return 0

    paths = _input_paths(args, manifest)
    if not paths:
        parser.error("no candidate inputs; pass --input or add input_files to the manifest")
    missing_paths = [str(path) for path in paths if not path.exists()]
    if missing_paths:
        parser.error("candidate input not found: " + ", ".join(missing_paths))

    config = QuestionBankConfig.from_env()
    llm = LocalQuestionLLM(config)
    run_id = (
        args.resume_run
        or args.run_id
        or f"qb_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    state = RunState(args.logs_dir, run_id)
    pipeline = QuestionPipeline(
        normalizer=llm,
        verifier=llm,
        state=state,
        skills=skills,
        existing_rows=existing_rows,
    )
    candidates = _candidate_stream(
        paths,
        manifest_skills={skill.skill_key for skill in manifest.skills},
        selected_skills=set(selected),
        limit=args.limit,
    )
    pipeline_result = pipeline.process(candidates)
    publish_result = store.publish(
        pipeline_result.rows,
        existing_rows=existing_rows,
        dry_run=not args.publish,
    )

    final_summary = {
        **pipeline_result.summary,
        "run_id": run_id,
        "mode": "publish" if args.publish else "dry-run",
        "normalizer_model": config.normalizer_model,
        "verifier_model": config.verifier_model,
        "same_model_verifier": config.same_model_verifier,
        "supabase": {
            "planned": publish_result.planned,
            "written": publish_result.written,
            "skipped": publish_result.skipped,
        },
        "coverage": _coverage_summary(
            manifest,
            selected,
            existing_rows,
            pipeline_result.rows,
        ),
    }
    summary_path = state.write_summary(final_summary)
    print(json.dumps(final_summary, indent=2, sort_keys=True))
    print(f"summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

