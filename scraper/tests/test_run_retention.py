from __future__ import annotations

import json
import os
import sys
import time

from run_retention import prune_logs, prune_run_outputs


def _run_folder(base, company: str, date: str):
    folder = base / company / "Outputs" / date
    folder.mkdir(parents=True)
    (folder / "jobs.json").write_text("[]", encoding="utf-8")
    return folder


def test_keeps_newest_run_dates_across_companies(tmp_path) -> None:
    for date in ["2026_10_18", "2026_10_19", "2026_10_20", "2026_10_21"]:
        _run_folder(tmp_path, "Stripe", date)
    # A company that failed recently keeps nothing older than the cutoff either.
    _run_folder(tmp_path, "Accenture", "2026_10_01")
    _run_folder(tmp_path, "Accenture", "2026_10_21")

    result = prune_run_outputs(tmp_path, keep_runs=2, protect="2026_10_25")

    assert result["kept_dates"] == ["2026_10_20", "2026_10_21"]
    assert result["removed_folders"] == 3
    assert result["freed_bytes"] == 6
    assert sorted(p.name for p in (tmp_path / "Stripe" / "Outputs").iterdir()) == [
        "2026_10_20", "2026_10_21",
    ]
    assert [p.name for p in (tmp_path / "Accenture" / "Outputs").iterdir()] == ["2026_10_21"]


def test_current_run_date_is_never_pruned(tmp_path) -> None:
    _run_folder(tmp_path, "Stripe", "2026_10_24")
    today = _run_folder(tmp_path, "Stripe", "2026_10_25")
    _run_folder(tmp_path, "Postman", "2026_10_26")

    prune_run_outputs(tmp_path, keep_runs=1, protect="2026_10_25")

    assert today.exists()
    assert not (tmp_path / "Stripe" / "Outputs" / "2026_10_24").exists()


def test_only_run_date_folders_are_touched(tmp_path) -> None:
    _run_folder(tmp_path, "Stripe", "2026_10_01")
    _run_folder(tmp_path, "Stripe", "2026_10_25")
    stray = tmp_path / "Stripe" / "Outputs" / "manual_backup"
    stray.mkdir()
    loose = tmp_path / "Stripe" / "notes.txt"
    loose.write_text("keep", encoding="utf-8")

    prune_run_outputs(tmp_path, keep_runs=1, protect="2026_10_25")

    assert stray.exists()
    assert loose.exists()


def test_zero_keep_runs_keeps_everything(tmp_path) -> None:
    """The laptop passes no flag and keeps its full output history."""
    old = _run_folder(tmp_path, "Stripe", "2026_06_01")

    assert prune_run_outputs(tmp_path, keep_runs=0, protect="2026_10_25") == {"skipped": True}
    assert old.exists()


def test_old_logs_go_but_fresh_logs_and_locks_stay(tmp_path) -> None:
    now = time.time()
    old = tmp_path / "run_2026_10_01.log"
    old.write_text("x" * 10, encoding="utf-8")
    fresh = tmp_path / "run_2026_10_25.log"
    fresh.write_text("y", encoding="utf-8")
    lock = tmp_path / "daily_poll.lock"
    lock.write_text("123", encoding="utf-8")
    subdir = tmp_path / "__pycache__"
    subdir.mkdir()
    for path in (old, lock, subdir):
        os.utime(path, (now - 30 * 86400, now - 30 * 86400))

    result = prune_logs(tmp_path, keep_days=14, now=now)

    assert result == {"removed_files": 1, "freed_bytes": 10}
    assert not old.exists()
    assert fresh.exists() and lock.exists() and subdir.exists()


def test_daily_poll_prunes_before_scraping_only_when_asked(monkeypatch, tmp_path) -> None:
    import daily_poll

    outputs = tmp_path / "outputs"
    logs = tmp_path / "logs"
    logs.mkdir()
    old = _run_folder(outputs, "Stripe", "2026_01_01")
    _run_folder(outputs, "Stripe", "2026_10_24")
    monkeypatch.setattr(daily_poll, "OUTPUT_BASE", str(outputs))
    monkeypatch.setattr(daily_poll, "LOG_DIR", logs)
    seen_at_scrape: list[bool] = []

    def run_step(name, command, *, env):
        if name == "scrape":
            seen_at_scrape.append(old.exists())
        return {"name": name, "returncode": 0}

    monkeypatch.setattr(daily_poll, "_run_step", run_step)

    monkeypatch.setattr(sys, "argv", ["daily_poll.py"])
    daily_poll.main()
    assert old.exists()

    monkeypatch.setattr(sys, "argv", ["daily_poll.py", "--keep-runs", "1", "--keep-log-days", "14"])
    daily_poll.main()

    assert seen_at_scrape == [True, False]
    reports = sorted(logs.glob("daily_poll_*.json"))
    report = json.loads(reports[-1].read_text(encoding="utf-8"))
    assert report["retention"]["outputs"]["removed_folders"] == 1
