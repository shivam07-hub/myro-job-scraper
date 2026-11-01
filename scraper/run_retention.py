"""Bounded disk use for a poll host with a small volume.

Railway's 5 GB volume filled after ten daily polls (2026-10-21): each full poll
writes ~380 MB of jobs.json + jobs.csv, and nothing removed old run folders, so
every run after that died on ENOSPC before publishing.

Pruning old date folders is safe for the daily lane. The writer only reads its
own date folder, and the resolver and importer select the run's exact
``--run-date``. Older folders are debugging evidence, not inputs. The laptop
keeps its full history: these functions only run when a caller passes a
positive keep value.
"""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

RUN_DATE_DIR = re.compile(r"^\d{4}_\d{2}_\d{2}$")


def _size(folder: Path) -> int:
    return sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())


def prune_run_outputs(output_base: Path, *, keep_runs: int, protect: str) -> dict:
    """Delete company date folders outside the newest ``keep_runs`` run dates.

    Run dates are counted across every company, so a company that failed in
    recent runs loses its old folder too; no daily step reads it. ``protect``
    is the current run date, which may not exist yet.
    """
    if keep_runs <= 0 or not output_base.is_dir():
        return {"skipped": True}
    date_dirs = [
        d for d in output_base.glob("*/Outputs/*")
        if d.is_dir() and RUN_DATE_DIR.match(d.name)
    ]
    newest = sorted({d.name for d in date_dirs}, reverse=True)[:keep_runs]
    keep = set(newest) | {protect}
    freed = 0
    removed = 0
    for folder in date_dirs:
        if folder.name in keep:
            continue
        freed += _size(folder)
        shutil.rmtree(folder)
        removed += 1
    return {"kept_dates": sorted(newest), "removed_folders": removed, "freed_bytes": freed}


def prune_logs(log_dir: Path, *, keep_days: int, now: float | None = None) -> dict:
    """Delete top-level log files older than ``keep_days``.

    Lock files are never touched: a running poll or inference worker holds
    them open, and they are rewritten in place rather than recreated.
    """
    if keep_days <= 0 or not log_dir.is_dir():
        return {"skipped": True}
    cutoff = (now if now is not None else time.time()) - keep_days * 86400
    freed = 0
    removed = 0
    for path in log_dir.iterdir():
        if not path.is_file() or path.suffix == ".lock":
            continue
        stat = path.stat()
        if stat.st_mtime >= cutoff:
            continue
        path.unlink(missing_ok=True)
        freed += stat.st_size
        removed += 1
    return {"removed_files": removed, "freed_bytes": freed}
