from __future__ import annotations

import json

from writer import save_jobs


def _job(job_id):
    return {"job_id": job_id, "job_title": f"Role {job_id}", "job_description": "A" * 120}


def test_save_jobs_dedupes_existing_and_current_batch_ids(tmp_path):
    path, new_count = save_jobs(
        "Example",
        [_job("one"), _job("one"), _job("two")],
        output_base=str(tmp_path),
        run_date="2026_08_13",
    )
    assert new_count == 2
    assert [job["job_id"] for job in json.loads(open(path, encoding="utf-8").read())] == ["one", "two"]

    path, new_count = save_jobs(
        "Example",
        [_job("two"), _job("three"), _job("three")],
        output_base=str(tmp_path),
        run_date="2026_08_13",
    )
    assert new_count == 1
    assert [job["job_id"] for job in json.loads(open(path, encoding="utf-8").read())] == ["one", "two", "three"]
