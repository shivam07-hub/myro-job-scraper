from __future__ import annotations

from csv_importer import _candidate_profile_rows, _upsert_candidate_profiles


class FakeTable:
    def __init__(self) -> None:
        self.upserts: list[tuple[list[dict], str | None]] = []

    def upsert(self, rows, on_conflict=None, ignore_duplicates=False):
        self.upserts.append((rows, on_conflict))
        return self

    def execute(self):
        return type("Response", (), {"data": []})()


class FakeSupabase:
    def __init__(self) -> None:
        self.tables: dict[str, FakeTable] = {}

    def table(self, name: str) -> FakeTable:
        self.tables.setdefault(name, FakeTable())
        return self.tables[name]


def _job(profile: dict | None = None) -> dict:
    return {
        "job_id": "job-1",
        "candidate_profile": profile or {
            "ideal_candidate_summary": "Backend engineer with API ownership.",
            "cv_positioning": ["Lead with API ownership."],
            "proof_points": ["Production API shipped"],
            "gap_risks": ["No production evidence"],
            "project_suggestions": ["Build an API with auth."],
            "resume_keywords": ["Python", "API"],
            "interview_themes": ["API design"],
        },
        "candidate_profile_version": "cv_profile_v1",
        "candidate_profile_hash": "hash-1",
        "candidate_profile_model": "gemma",
    }


def test_candidate_profile_rows_require_profile_and_hash() -> None:
    rows = _candidate_profile_rows([
        _job(),
        {"job_id": "job-2", "candidate_profile": {}, "candidate_profile_hash": "hash-2"},
        {"job_id": "job-3", "candidate_profile": {"ideal_candidate_summary": "x"}},
    ])

    assert rows == [{
        "job_id": "job-1",
        "profile_version": "cv_profile_v1",
        "generated_from_hash": "hash-1",
        "ideal_candidate_summary": "Backend engineer with API ownership.",
        "cv_positioning": ["Lead with API ownership."],
        "proof_points": ["Production API shipped"],
        "gap_risks": ["No production evidence"],
        "project_suggestions": ["Build an API with auth."],
        "resume_keywords": ["Python", "API"],
        "interview_themes": ["API design"],
        "model_name": "gemma",
    }]


def test_upsert_candidate_profiles_respects_dry_run() -> None:
    fake = FakeSupabase()
    count = _upsert_candidate_profiles(fake, [_job()], dry_run=True)

    assert count == 1
    assert "job_candidate_profiles" not in fake.tables


def test_upsert_candidate_profiles_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("SKIP_CANDIDATE_PROFILE_UPLOAD", "1")
    fake = FakeSupabase()
    count = _upsert_candidate_profiles(fake, [_job()], dry_run=False)

    assert count == 0
    assert "job_candidate_profiles" not in fake.tables


def test_upsert_candidate_profiles_writes_rows_on_real_run() -> None:
    fake = FakeSupabase()
    count = _upsert_candidate_profiles(fake, [_job()], dry_run=False)

    assert count == 1
    table = fake.tables["job_candidate_profiles"]
    assert table.upserts[0][1] == "job_id"
    assert table.upserts[0][0][0]["generated_from_hash"] == "hash-1"
