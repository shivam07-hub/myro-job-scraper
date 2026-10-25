#!/usr/bin/env python3
"""Run the forward-only daily source polling lane.

This is the scheduler entrypoint for Phase 1 -> Phase 3.  It deliberately does
not wait for Phase 2 inference: completed source snapshots are published first,
and the durable enrichment worker runs on its own cadence.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

from config import OUTPUT_BASE
from run_retention import prune_logs, prune_run_outputs


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
LOG_DIR = REPO_ROOT / "logs"
DEFAULT_TIMEZONE = "Asia/Kolkata"


def build_commands(
    *,
    python: str,
    run_date: str,
    scope: str,
    company_cap: int,
    company: str | None = None,
) -> list[tuple[str, list[str]]]:
    scrape = [
        python,
        str(ROOT / "main.py"),
        "--skip-enrich",
        "--scope",
        scope,
        "--company-cap",
        str(company_cap),
        "--run-date",
        run_date,
    ]
    # Career band is an optional source-level matching fact. This step stamps
    # every provable band and clears stale claims before publication; a job with
    # no provable band still publishes for browse with career_band=NULL.
    # --skip-model by decision on 2026-08-08, measured on a 33,246-job run:
    # deterministic rules banded 86.5% in 13 seconds, while the model pass ran at
    # ~2.7 calls/min and accepted ~7% of what it saw — hours added to a 9-hour
    # cycle to band a few hundred jobs. Run source_matching_facts.py by hand,
    # without this flag, to chase the tail.
    resolve = [
        python,
        str(ROOT / "source_matching_facts.py"),
        "--run-date",
        run_date,
        "--skip-model",
        "--allow-unresolved",
    ]
    publish = [
        python,
        str(ROOT / "csv_importer.py"),
        "--source-only",
        "--publish-unclassified",
        "--run-date",
        run_date,
    ]
    if company:
        scrape.extend(["--company", company])
        resolve.extend(["--company", company])
        publish.extend(["--company", company])
    return [("scrape", scrape), ("resolve", resolve), ("publish", publish)]


def _run_step(name: str, command: list[str], *, env: dict[str, str]) -> dict:
    started = datetime.now().astimezone()
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    ended = datetime.now().astimezone()
    return {
        "name": name,
        "command": command,
        "returncode": completed.returncode,
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "duration_seconds": round((ended - started).total_seconds(), 3),
    }


def _write_report(report: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = LOG_DIR / f"daily_poll_{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Daily forward-only career source poll and immediate Supabase publication"
    )
    parser.add_argument("--scope", choices=["india", "global"], default="india")
    parser.add_argument("--company-cap", type=int, default=0,
                        help="Max jobs per company (default: 0 = unlimited).")
    parser.add_argument("--company", help="Run one company only (operational canary)")
    parser.add_argument("--timezone", default=os.getenv("POLL_TIMEZONE", DEFAULT_TIMEZONE))
    parser.add_argument("--dry-run", action="store_true", help="Print the execution plan without running it")
    parser.add_argument("--keep-runs", type=int, default=0,
                        help="Keep output folders for only the newest N run dates (default: 0 = keep all).")
    parser.add_argument("--keep-log-days", type=int, default=0,
                        help="Delete log files older than N days (default: 0 = keep all).")
    args = parser.parse_args()
    if args.company_cap < 0:
        parser.error("--company-cap cannot be negative")

    timezone = ZoneInfo(args.timezone)
    run_started = datetime.now(timezone)
    run_date = run_started.strftime("%Y_%m_%d")
    commands = build_commands(
        python=sys.executable,
        run_date=run_date,
        scope=args.scope,
        company_cap=args.company_cap,
        company=args.company,
    )
    if args.dry_run:
        print(json.dumps({"run_date": run_date, "steps": commands}, indent=2))
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    # Prune before taking the lock: on a full volume even the lock write fails.
    # Safe without the lock, since a concurrent poll writes only today's folder
    # (always kept) and fresh logs (younger than any cutoff).
    retention = {
        "outputs": prune_run_outputs(Path(OUTPUT_BASE), keep_runs=args.keep_runs, protect=run_date),
        "logs": prune_logs(LOG_DIR, keep_days=args.keep_log_days),
    }
    lock_path = LOG_DIR / "daily_poll.lock"
    with lock_path.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Daily poll is already running; refusing an overlapping run.", file=sys.stderr)
            raise SystemExit(3)
        lock.write(str(os.getpid()))
        lock.flush()

        env = dict(os.environ)
        env["TZ"] = args.timezone
        env["SCRAPE_DIAGNOSTICS_DISABLED"] = "1"
        if hasattr(time, "tzset"):
            time.tzset()

        report = {
            "run_date": run_date,
            "timezone": args.timezone,
            "scope": args.scope,
            "company": args.company,
            "status": "running",
            "retention": retention,
            "steps": [],
        }
        scrape_name, scrape_command = commands[0]
        scrape_step = _run_step(scrape_name, scrape_command, env=env)
        report["steps"].append(scrape_step)
        if scrape_step["returncode"] != 0:
            report["status"] = "failed"
            report["failed_step"] = scrape_name
            path = _write_report(report)
            print(f"Daily poll failed in {scrape_name}; report: {path}", file=sys.stderr)
            raise SystemExit(scrape_step["returncode"])

        # One logical scrape owns one immutable output date. The writer keeps
        # every page flush and its final completion marker in this folder even
        # when wall-clock midnight passes during the scrape.
        report["publish_dates"] = [run_date]

        # No inference gate here: the resolver runs --skip-model, and this lane
        # runs on Railway, which has no LM Studio. Embeddings and enrichment are
        # drained separately by `daily_cycle.py --inference-only` on the laptop.
        for step_label, command in commands[1:]:
            step_name = f"{step_label}:{run_date}"
            step = _run_step(step_name, command, env=env)
            report["steps"].append(step)
            if step["returncode"] != 0:
                report["status"] = "failed"
                report["failed_step"] = step_name
                path = _write_report(report)
                print(f"Daily poll failed in {step_name}; report: {path}", file=sys.stderr)
                raise SystemExit(step["returncode"])

        report["status"] = "complete"
        path = _write_report(report)
        print(f"Daily source poll complete; report: {path}")


if __name__ == "__main__":
    main()
