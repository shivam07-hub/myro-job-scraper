"""`--company` must select exactly the folder the writer made for that company.

The writer names folders with company_slug() ("EY India Experienced" ->
"EY_India_Experienced"). On 2026-10-01 the resolver and importer compared the
raw name with spaces against that folder, so `daily_poll --company` failed for
every multi-word company. A substring match also let "EY India" pull in
"EY_India_Experienced".
"""
from __future__ import annotations

import pytest

import csv_importer
import source_matching_facts as smf

RUN_DATE = "2026_09_30"


@pytest.fixture
def outputs(tmp_path, monkeypatch):
    for folder in ("EY_India", "EY_India_Experienced", "Stripe"):
        run = tmp_path / folder / "Outputs" / RUN_DATE
        run.mkdir(parents=True)
        (run / "jobs.json").write_text("[]", encoding="utf-8")
        (run / "jobs.complete").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(smf, "OUTPUT_BASE", str(tmp_path))
    monkeypatch.setattr(csv_importer, "OUTPUT_BASE", str(tmp_path))
    return tmp_path


def _companies(paths) -> list[str]:
    return [path.parent.parent.parent.name for path in paths]


@pytest.mark.parametrize(
    ("company", "expected"),
    [
        ("EY India Experienced", ["EY_India_Experienced"]),
        ("EY India", ["EY_India"]),
        ("stripe", ["Stripe"]),
    ],
)
def test_resolver_selects_exactly_the_company_folder(outputs, company, expected) -> None:
    assert _companies(smf._find_run_files(RUN_DATE, company)) == expected


@pytest.mark.parametrize(
    ("company", "expected"),
    [
        ("EY India Experienced", ["EY_India_Experienced"]),
        ("EY India", ["EY_India"]),
        ("stripe", ["Stripe"]),
    ],
)
def test_importer_selects_exactly_the_company_folder(outputs, company, expected) -> None:
    files = csv_importer._find_json_files(
        company_filter=company, all_dates=False, batch_date=20260930,
    )
    assert _companies(files) == expected
