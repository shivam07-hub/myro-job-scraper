import pytest

from question_bank.cli import build_parser, selected_skill_keys
from question_bank.sources import PILOT_SKILLS, SourceManifest, PilotSkill


def manifest() -> SourceManifest:
    return SourceManifest(
        skills=tuple(PilotSkill(skill_key=value) for value in PILOT_SKILLS),
    )


def test_cli_defaults_to_safe_dry_run() -> None:
    args = build_parser().parse_args(["--input", "candidates.jsonl"])

    assert args.publish is False
    assert args.dry_run is False
    assert args.resume_run is None


def test_cli_rejects_dry_run_and_publish_together() -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args(["--input", "candidates.jsonl", "--dry-run", "--publish"])


def test_cli_can_select_multiple_pilot_skills() -> None:
    args = build_parser().parse_args([
        "--input",
        "candidates.jsonl",
        "--skill",
        "Machine Learning",
        "--skill",
        "Financial Accounting",
    ])

    assert selected_skill_keys(args, manifest()) == (
        "Machine Learning",
        "Financial Accounting",
    )


def test_cli_uses_all_manifest_skills_when_no_filter_is_given() -> None:
    args = build_parser().parse_args(["--input", "candidates.jsonl"])

    assert selected_skill_keys(args, manifest()) == PILOT_SKILLS


def test_cli_accepts_resume_run_and_preflight_only() -> None:
    args = build_parser().parse_args([
        "--resume-run",
        "qb_20260611_120000",
        "--preflight-only",
    ])

    assert args.resume_run == "qb_20260611_120000"
    assert args.preflight_only is True

