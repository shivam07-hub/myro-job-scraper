"""
RunCheckpoint — per-run state machine for scrape progress.

Tracks each company through: pending → in_progress → complete | partial | failed.
Persists atomically to logs/checkpoint_{run_id}.json after every state change.
Prepares the ground for Candidate 2 (page-flush callback) via update_progress().

States
------
  pending      not yet started in this run
  in_progress  scrape started, pages being fetched
  partial      interrupted mid-scrape (some jobs on disk, not complete)
  complete     scrape + save both succeeded
  failed       api_blocked, exception, or 0 jobs returned

Integration
-----------
  - main.py creates RunCheckpoint.new() at run start
  - run() calls start/mark_complete/mark_failed per company
  - update_progress() is a no-op stub until Candidate 2 wires page-flush callbacks
  - --resume-run <run_id> loads an existing checkpoint to skip complete companies
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Literal

_log = logging.getLogger("mirror")

State = Literal["pending", "in_progress", "partial", "complete", "failed"]
_CHECKPOINT_PREFIX = "checkpoint_"


class RunCheckpoint:

    def __init__(self, run_id: str, checkpoint_path: Path) -> None:
        self.run_id = run_id
        self._path  = checkpoint_path
        self._data: dict = {
            "run_id":     run_id,
            "started_at": datetime.now().isoformat(),
            "companies":  {},
        }

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def new(cls, run_id: str, log_dir: Path) -> "RunCheckpoint":
        """Create a fresh checkpoint for this run. Overwrites any same-id file."""
        log_dir.mkdir(parents=True, exist_ok=True)
        path = log_dir / f"{_CHECKPOINT_PREFIX}{run_id}.json"
        cp = cls(run_id, path)
        cp._flush()
        return cp

    @classmethod
    def load(cls, run_id: str, log_dir: Path) -> "RunCheckpoint | None":
        """Load a specific run's checkpoint by run_id."""
        path = log_dir / f"{_CHECKPOINT_PREFIX}{run_id}.json"
        if not path.exists():
            _log.warning(f"[RunCheckpoint] No checkpoint found for run_id={run_id}")
            return None
        return cls._read(path)

    @classmethod
    def load_latest_partial(cls, log_dir: Path) -> "RunCheckpoint | None":
        """Load most recent checkpoint that still has in_progress or partial companies.
        Returns None if all past runs completed cleanly."""
        checkpoints = sorted(log_dir.glob(f"{_CHECKPOINT_PREFIX}*.json"), reverse=True)
        for p in checkpoints:
            cp = cls._read(p)
            if cp is None:
                continue
            if any(
                c.get("state") in ("in_progress", "partial")
                for c in cp._data.get("companies", {}).values()
            ):
                return cp
        return None

    @classmethod
    def _read(cls, path: Path) -> "RunCheckpoint | None":
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            run_id = data.get("run_id", path.stem.replace(_CHECKPOINT_PREFIX, ""))
            cp = cls(run_id, path)
            cp._data = data
            return cp
        except Exception as e:
            _log.warning(f"[RunCheckpoint] Could not read {path}: {e}")
            return None

    # ── State transitions ─────────────────────────────────────────────────────

    def start(self, company: str, ats: str) -> None:
        self._set(company, {
            "state":      "in_progress",
            "ats":        ats,
            "last_page":  0,
            "jobs_so_far": 0,
            "started_at": _now(),
            "updated_at": _now(),
        })

    def update_progress(self, company: str, page: int, jobs_so_far: int) -> None:
        """Record page-level progress. Called per page once Candidate 2 is wired.
        Safe to call now — updates state and flushes without error."""
        entry = self._get(company)
        entry.update({
            "state":      "in_progress",
            "last_page":  page,
            "jobs_so_far": jobs_so_far,
            "updated_at": _now(),
        })
        self._set(company, entry)

    def mark_complete(self, company: str, job_count: int) -> None:
        entry = self._get(company)
        entry.update({
            "state":        "complete",
            "job_count":    job_count,
            "completed_at": _now(),
            "updated_at":   _now(),
        })
        self._set(company, entry)

    def mark_partial(self, company: str, page: int, jobs_so_far: int) -> None:
        """Explicit partial marker — used when provider yields mid-pagination (Candidate 2)."""
        entry = self._get(company)
        entry.update({
            "state":      "partial",
            "last_page":  page,
            "jobs_so_far": jobs_so_far,
            "updated_at": _now(),
        })
        self._set(company, entry)

    def mark_failed(self, company: str, reason: str = "") -> None:
        entry = self._get(company)
        entry.update({
            "state":      "failed",
            "reason":     reason,
            "updated_at": _now(),
        })
        self._set(company, entry)

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_state(self, company: str) -> State:
        return self._get(company).get("state", "pending")

    def is_complete(self, company: str) -> bool:
        return self.get_state(company) == "complete"

    def get_resume_page(self, company: str) -> int:
        """Returns last successfully flushed page. Used by Candidate 2 providers."""
        return self._get(company).get("last_page", 0)

    def get_progress(self, company: str) -> dict:
        e = self._get(company)
        return {"last_page": e.get("last_page", 0), "jobs_so_far": e.get("jobs_so_far", 0)}

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {s: 0 for s in ("complete", "partial", "in_progress", "failed", "pending")}
        for c in self._data.get("companies", {}).values():
            state = c.get("state", "pending")
            counts[state] = counts.get(state, 0) + 1
        return counts

    # ── Internal ──────────────────────────────────────────────────────────────

    def _key(self, company: str) -> str:
        return company.lower().replace(" ", "_")

    def _get(self, company: str) -> dict:
        return dict(self._data["companies"].get(self._key(company), {}))

    def _set(self, company: str, entry: dict) -> None:
        self._data["companies"][self._key(company)] = entry
        self._flush()

    def _flush(self) -> None:
        """Atomic write: tmp → rename (POSIX atomic)."""
        tmp = self._path.with_suffix(".tmp.json")
        tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        tmp.rename(self._path)


def _now() -> str:
    return datetime.now().isoformat()
