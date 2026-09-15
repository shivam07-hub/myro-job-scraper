from __future__ import annotations

import pytest

from enrichment_state import source_content_hash
from source_matching_facts import (
    _normalize_source_facts,
    _parse_accepted_classifications,
)


def test_cli_help_renders_percentages_without_argparse_failure(monkeypatch, capsys) -> None:
    import source_matching_facts

    monkeypatch.setattr("sys.argv", ["source_matching_facts.py", "--help"])
    with pytest.raises(SystemExit) as exc:
        source_matching_facts.main()

    assert exc.value.code == 0
    assert "~7%" in capsys.readouterr().out


def _job() -> dict:
    return {
        "job_title": "Associate",
        "job_description": "Prepare monthly financial reports and reconcile accounts.",
    }


def test_accepts_high_confidence_grounded_band() -> None:
    accepted = _parse_accepted_classifications({
        "classifications": [{
            "id": 0,
            "career_band": "business_product_operations",
            "evidence": "financial reports",
            "confidence": "high",
        }],
    }, {0: _job()})

    assert accepted[0]["career_band"] == "business_product_operations"


def test_rejects_evidence_that_supports_a_different_band() -> None:
    accepted = _parse_accepted_classifications({
        "classifications": [{
            "id": 0,
            "career_band": "engineering_data",
            "evidence": "financial reports",
            "confidence": "high",
        }],
    }, {0: _job()})

    assert accepted == {}


def test_rejects_employer_boilerplate_as_function_evidence() -> None:
    job = {
        "job_title": "Associate",
        "job_description": "Collaborate with innovative 3Mers around the world.",
    }
    accepted = _parse_accepted_classifications({
        "classifications": [{
            "id": 0,
            "career_band": "engineering_data",
            "evidence": "innovative 3Mers around the world",
            "confidence": "high",
        }],
    }, {0: job})

    assert accepted == {}


def test_rejects_ungrounded_evidence() -> None:
    accepted = _parse_accepted_classifications({
        "classifications": [{
            "id": 0,
            "career_band": "engineering_data",
            "evidence": "software development",
            "confidence": "high",
        }],
    }, {0: _job()})

    assert accepted == {}


def test_rejects_generic_title_as_evidence() -> None:
    accepted = _parse_accepted_classifications({
        "classifications": [{
            "id": 0,
            "career_band": "business_product_operations",
            "evidence": "Associate",
            "confidence": "high",
        }],
    }, {0: _job()})

    assert accepted == {}


def test_rejects_non_high_confidence_output() -> None:
    accepted = _parse_accepted_classifications({
        "classifications": [{
            "id": 0,
            "career_band": "business_product_operations",
            "evidence": "financial reports",
            "confidence": "medium",
        }],
    }, {0: _job()})

    assert accepted == {}


def test_normalization_preserves_fresh_grounded_model_band() -> None:
    job = {
        **_job(),
        "career_band": "business_product_operations",
        "career_band_source": "model_grounded",
        "career_band_evidence": "financial reports",
        "career_band_model": "@cf/openai/gpt-oss-120b",
    }
    job["career_band_source_hash"] = source_content_hash(job)

    _normalize_source_facts(job)

    assert job["career_band"] == "business_product_operations"
    assert job["career_band_source"] == "model_grounded"


def test_normalization_discards_stale_grounded_model_band() -> None:
    job = {
        **_job(),
        "career_band": "business_product_operations",
        "career_band_source": "model_grounded",
        "career_band_evidence": "financial reports",
        "career_band_source_hash": "stale",
    }

    _normalize_source_facts(job)

    assert job["career_band"] == ""
    assert "career_band_source" not in job


def test_fully_deterministic_run_still_persists_provenance(tmp_path, monkeypatch) -> None:
    """A company whose titles all resolve without the model must still be written.

    The provenance stamp lives only in memory until the file is rewritten, and
    `csv_importer` withholds any row that lacks it — so skipping the write when
    no job needed the model silently withheld the entire company.
    """
    import json

    import source_matching_facts as smf

    folder = tmp_path / "Stripe" / "Outputs" / "2026_08_07"
    folder.mkdir(parents=True)
    (folder / "jobs.complete").write_text("{}", encoding="utf-8")
    (folder / "jobs.json").write_text(
        json.dumps([{
            "job_id": "1",
            "job_title": "Senior Software Engineer",
            "job_description": "Build backend services.",
            "company_name": "Stripe",
        }]),
        encoding="utf-8",
    )
    monkeypatch.setattr(smf, "OUTPUT_BASE", str(tmp_path))

    report = smf.resolve_run(
        run_date="2026_08_07",
        company=None,
        batch_size=8,
        workers=1,
        dry_run=False,
    )

    assert report["unresolved"] == 0
    assert report["model_resolved"] == 0
    written = json.loads((folder / "jobs.json").read_text(encoding="utf-8"))
    assert written[0]["career_band"] == "engineering_data"
    assert written[0]["career_band_source"] == "deterministic_title_or_role_domain"
    assert written[0]["career_band_source_hash"]
