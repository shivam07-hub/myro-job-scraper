"""
Mirror Job Scraper — Weekly Orchestrator
========================================
Reads KNOWN_PORTALS.md, routes active portals through providers, enriches via
LM Studio (structured skills + back-compat arrays), and writes canonical JSON/CSV output.

Firecrawl credit rules:
  - crawl() is NEVER called — too expensive (N credits per company)
  - scrape_extract() (fc.extract) is used ONLY for js_required portals (1 call)
  - scrape() is only called inside individual scrapers for JD fetch, not here

Usage:
    python main.py                      # all active portals
    python main.py --company "Stripe"   # single company (substring match)
    python main.py --ats workday        # one ATS type only
    python main.py --dry-run            # parse portals only, no scraping
    python main.py --skip-enrich        # scrape only, skip LLM enrichment
    python main.py --resume             # skip companies already scraped
    python main.py --enrich-only        # enrich saved jobs (LM Studio on)
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

from concurrent.futures import ThreadPoolExecutor, as_completed
from portal_reader import parse_portals
from providers import dispatch_scrape_result
from providers.base import ProviderResult, ScrapeReason
from enricher import InferenceQuotaExceeded, enrich_job, has_terminal_core_enrichment
from writer import (
    COMPLETE_MARKER_NAME,
    SCHEMA,
    _skills_to_csv,
    normalize_run_date,
    save_jobs,
    stamp_job_content_hash,
    to_canonical,
    write_complete_marker,
)
from run_checkpoint import RunCheckpoint
from typing import Callable
from utils import company_slug
from config import OUTPUT_BASE
from validation import LOW_COUNT_THRESHOLD
from pipeline_validator import run_gate
from schema import is_missing_jd_description
from scrape_select import select_for_cap
from source_matching_facts import _normalize_source_facts

_VALIDATE_OUTPUT_BASE = str(Path(OUTPUT_BASE).parent / "validation_outputs")
_VALIDATE_MAX_JOBS    = 5
# 0 = unlimited. A volume gate makes presence-based delisting dishonest: the
# truncated tail looks missing on the next complete census. Quality filters
# (identity, thin JD) still drop junk; they are not a count cap.
_DEFAULT_COMPANY_CAP = 0

_INTER_COMPANY_DELAY = 2   # seconds between companies


def already_scraped(company: str) -> bool:
    """Return True if this company has a *complete* scrape.

    Priority:
      1. jobs.complete marker present in any date folder (new system).
      2. Legacy: jobs.json exists in a past date folder and no marker
         (pre-marker era runs — assume complete if not today).
    A partial jobs.json in today's folder without a marker = incomplete.
    """
    outputs_dir = Path(OUTPUT_BASE) / company_slug(company) / "Outputs"
    if not outputs_dir.exists():
        return False

    today = datetime.now().strftime("%Y_%m_%d")

    for date_dir in outputs_dir.iterdir():
        if not date_dir.is_dir():
            continue
        if (date_dir / COMPLETE_MARKER_NAME).exists():
            return True
        # Legacy fallback: past date folder with jobs.json but no marker
        if date_dir.name < today and (date_dir / "jobs.json").exists():
            return True

    return False


# ── Logging setup ─────────────────────────────────────────────────────────────

def setup_logging(log_dir: str = "../logs") -> logging.Logger:
    log_path = Path(log_dir) / f"run_{datetime.now().strftime('%Y_%m_%d_%H%M%S_%f')}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    fmt = "%(asctime)s  %(levelname)-7s  %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
    )
    log = logging.getLogger("mirror")
    log.info(f"Log file: {log_path.resolve()}")
    return log


# ── Dispatch ──────────────────────────────────────────────────────────────────

def scrape_portal(portal: dict, log: logging.Logger, max_jobs: int | None = None,
                  validate_mode: bool = False, on_page_complete=None) -> ProviderResult:
    return dispatch_scrape_result(
        portal,
        log,
        max_jobs=max_jobs,
        validate_mode=validate_mode,
        on_page_complete=on_page_complete,
    )


# ── Page-flush callback ───────────────────────────────────────────────────────

def _make_page_callback(
    company: str,
    output_base: str,
    checkpoint: RunCheckpoint | None,
    log: logging.Logger,
    run_date: str | None,
) -> Callable[[list[dict], int], None]:
    """Return a callback that normalises + saves a raw page chunk to disk.

    Called by Workday/Taleo after each page's JDs are fetched.
    Writes jobs.complete=False (write_marker=False) so already_scraped() correctly
    sees the run as incomplete until the final save_jobs() stamps the marker.
    """
    pages_flushed = [0]

    def on_page_complete(raw_page_jobs: list[dict], page: int) -> None:
        if not raw_page_jobs:
            return
        canonical_chunk = [to_canonical(j, company) for j in raw_page_jobs]
        canonical_chunk = [j for j in canonical_chunk if j.get("job_id")]
        if not canonical_chunk:
            return
        try:
            _, new_count = save_jobs(
                company,
                canonical_chunk,
                output_base=output_base,
                write_marker=False,
                run_date=run_date,
            )
            pages_flushed[0] += 1
            total_so_far = pages_flushed[0] * len(canonical_chunk)
            if checkpoint:
                checkpoint.update_progress(company, page=page, jobs_so_far=total_so_far)
            if new_count:
                log.debug(f"  [PAGE {page}] flushed {new_count} new jobs ({company})")
        except Exception as e:
            log.warning(f"  [PAGE FLUSH] error at page {page} for {company}: {e}")

    return on_page_complete


# ── Pipeline ──────────────────────────────────────────────────────────────────

def run(portals: list[dict], skip_enrich: bool, log: logging.Logger,
        max_jobs: int | None = None, output_base: str = OUTPUT_BASE,
        validate_mode: bool = False, scope: str = "india",
        checkpoint: RunCheckpoint | None = None,
        run_date: str | None = None) -> dict:
    summary = {
        "scope": scope,
        "run_id": checkpoint.run_id if checkpoint else datetime.now().strftime("%Y%m%d_%H%M%S_%f"),
        "processed": 0, "skipped": 0, "total_new": 0,
        "total_validation_drops": 0,
        "unresolved": [],
        "low_count": [],
        "company_stats": [],
        "errors": [], "start": datetime.now().isoformat(),
    }
    total = len(portals)

    for idx, portal in enumerate(portals, 1):
        company = portal["company"]
        ats     = portal["ats"]
        js_flag = "  [JS/Firecrawl extract]" if portal.get("js_required") else ""
        log.info(f"[{idx}/{total}] {company}  ({ats}){js_flag}")

        if checkpoint:
            checkpoint.start(company, ats)

        # ── Scrape ────────────────────────────────────────────────────────────
        page_cb = _make_page_callback(
            company, output_base, checkpoint, log, run_date
        )
        try:
            scrape_result = scrape_portal(
                portal,
                log,
                max_jobs=max_jobs,
                validate_mode=validate_mode,
                on_page_complete=page_cb,
            )
        except Exception as e:
            log.error(f"  FATAL scrape error — {company}: {e}")
            if checkpoint:
                checkpoint.mark_failed(company, reason=f"scrape_exception: {e}")
            summary["errors"].append({"company": company, "stage": "scrape", "error": str(e)})
            summary["unresolved"].append({
                "company": company,
                "ats": ats,
                "scope": scope,
                "reason": "scrape_exception",
                "details": str(e),
            })
            summary["skipped"] += 1
            continue

        raw_jobs = scrape_result.jobs
        if scrape_result.reason == ScrapeReason.PARTIAL:
            details = scrape_result.fallback_reason or "provider returned an incomplete snapshot"
            log.error(
                "  PARTIAL SNAPSHOT — %s returned %d rows before failure; "
                "quarantining the batch",
                company,
                len(raw_jobs),
            )
            if checkpoint:
                checkpoint.mark_failed(company, reason=f"partial_snapshot: {details}")
            summary["unresolved"].append({
                "company": company,
                "ats": ats,
                "scope": scope,
                "reason": "partial_snapshot",
                "details": details,
            })
            summary["company_stats"].append({
                "company": company,
                "ats": ats,
                "raw_jobs": len(raw_jobs),
                "saved_new": 0,
                "status": "partial",
            })
            summary["skipped"] += 1
            continue

        if not raw_jobs:
            reason = scrape_result.reason.value
            log.info(f"  0 {scope} jobs ({reason}) — skipping")
            if checkpoint:
                checkpoint.mark_failed(company, reason=reason)
            summary["unresolved"].append({
                "company": company,
                "ats": ats,
                "scope": scope,
                "reason": reason,
                "details": scrape_result.fallback_reason or "scraper returned empty result set",
            })
            summary["company_stats"].append({
                "company": company,
                "ats": ats,
                "raw_jobs": 0,
                "saved_new": 0,
                "status": reason,
            })
            summary["skipped"] += 1
            continue

        # Cap enforcement. Validate mode keeps the blunt truncation (schema-coverage
        # safety, order-agnostic). Real runs use the quality-aware selector: companies
        # over the cap keep technical / JD-bearing roles instead of an arbitrary tail
        # (Phase A — see docs/DESIGN_quality_aware_company_cap.md).
        if max_jobs:
            if validate_mode:
                raw_jobs = raw_jobs[:max_jobs]
            else:
                raw_jobs = select_for_cap(raw_jobs, max_jobs)

        log.info(f"  {len(raw_jobs)} raw jobs scraped")

        for raw_job in raw_jobs:
            raw_job.setdefault("source_platform", ats)
            raw_job.setdefault("source_url", raw_job.get("source_api_url") or portal.get("endpoint") or portal.get("careers_url") or "")
            raw_job.setdefault("ingestion_source", "scraper")
            raw_job.setdefault("quality_status", "auto_extracted")

        # ── Normalise to 7-field schema ───────────────────────────────────────
        canonical = [to_canonical(j, company) for j in raw_jobs]

        # ── Gate 1: post_scrape — identity + placeholder ──────────────────────
        g1 = run_gate(canonical, "post_scrape")
        if g1.drop_count:
            log.warning(f"  {g1.drop_count} jobs dropped [post_scrape] — {g1.reasons}")
        summary["total_validation_drops"] += g1.drop_count

        # ── Gate 2: pre_enrich — description present + min length ─────────────
        g2 = run_gate(g1.passed, "pre_enrich")
        if g2.drop_count:
            log.warning(f"  {g2.drop_count} jobs dropped [pre_enrich] — {g2.reasons}")
        summary["total_validation_drops"] += g2.drop_count

        canonical = g2.passed

        # ── Enrich (structured skills + back-compat arrays from JD) ──────────
        if skip_enrich:
            enriched = canonical
            log.info("  LLM enrichment skipped (--skip-enrich)")
        else:
            enriched = []
            ok = fail = 0
            for job in canonical:
                try:
                    enriched.append(enrich_job(job))
                    ok += 1
                except Exception as e:
                    log.warning(f"  enrich failed for '{job.get('job_title')}': {e}")
                    enriched.append(job)
                    fail += 1
            log.info(f"  LLM enrichment: {ok} ok  {fail} failed")

        # ── Save ──────────────────────────────────────────────────────────────
        _run_id = checkpoint.run_id if checkpoint else ""
        try:
            path, new_count = save_jobs(
                company,
                enriched,
                output_base=output_base,
                run_id=_run_id,
                run_date=run_date,
            )
            log.info(f"  Saved {new_count} new jobs → {path}")
            if checkpoint:
                checkpoint.mark_complete(company, job_count=len(enriched))
            if len(raw_jobs) < LOW_COUNT_THRESHOLD:
                log.warning(f"  LOW COUNT: {len(raw_jobs)} scraped job(s) for {company}")
                summary["low_count"].append({
                    "company": company,
                    "ats": ats,
                    "raw_jobs": len(raw_jobs),
                    "saved_new": new_count,
                    "reason": "below_5_scraped_jobs",
                })
            summary["company_stats"].append({
                "company": company,
                "ats": ats,
                "raw_jobs": len(raw_jobs),
                "validation_drops": g1.drop_count + g2.drop_count,
                "saved_new": new_count,
                "status": "ok",
            })
            summary["processed"] += 1
            summary["total_new"] += new_count
        except Exception as e:
            log.error(f"  FATAL save error — {company}: {e}")
            if checkpoint:
                checkpoint.mark_failed(company, reason=f"save_exception: {e}")
            summary["unresolved"].append({
                "company": company,
                "ats": ats,
                "scope": scope,
                "reason": "save_exception",
                "details": str(e),
            })
            summary["company_stats"].append({
                "company": company,
                "ats": ats,
                "raw_jobs": len(raw_jobs),
                "saved_new": 0,
                "status": "save_error",
                "error": str(e),
            })
            summary["errors"].append({"company": company, "stage": "save", "error": str(e)})

        time.sleep(_INTER_COMPANY_DELAY)

    summary["end"] = datetime.now().isoformat()
    return summary


def _persist_diagnostics_to_supabase(summary: dict, log: logging.Logger) -> None:
    """
    Best-effort write of run diagnostics to Supabase.
    If table/env is missing, this no-ops with a warning (does not fail the run).
    """
    if os.getenv("SCRAPE_DIAGNOSTICS_DISABLED", "").lower() in {"1", "true", "yes"}:
        log.info("  Diagnostics table skipped: SCRAPE_DIAGNOSTICS_DISABLED=1")
        return

    table = os.getenv("SCRAPE_DIAGNOSTICS_TABLE", "scrape_diagnostics")
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not supabase_url or not supabase_key:
        log.info("  Diagnostics table skipped: SUPABASE_URL/SUPABASE_SERVICE_KEY not set")
        return

    try:
        from supabase import create_client
    except Exception as e:
        log.warning(f"  Diagnostics table skipped: could not import supabase client ({e})")
        return

    unresolved_map = {u.get("company"): u for u in summary.get("unresolved", [])}
    rows = []
    for stat in summary.get("company_stats", []):
        company = stat.get("company")
        unresolved = unresolved_map.get(company, {})
        rows.append({
            "run_id": summary.get("run_id"),
            "scope": summary.get("scope"),
            "started_at": summary.get("start"),
            "ended_at": summary.get("end"),
            "company_name": company,
            "ats": stat.get("ats"),
            "raw_jobs": stat.get("raw_jobs", 0),
            "saved_new": stat.get("saved_new", 0),
            "status": stat.get("status", "unknown"),
            "reason": unresolved.get("reason"),
            "details": unresolved.get("details"),
        })

    if not rows:
        return

    try:
        sb = create_client(supabase_url, supabase_key)
        batch_size = 200
        for i in range(0, len(rows), batch_size):
            sb.table(table).insert(rows[i:i + batch_size]).execute()
        log.info(f"  Diagnostics table rows : {len(rows)} inserted into `{table}`")
    except Exception as e:
        log.warning(f"  Diagnostics table write failed (`{table}`): {e}")


# ── Enrich-only pass ──────────────────────────────────────────────────────────

def _needs_enrichment(job: dict) -> bool:
    """True if the job has JD text and is missing core Phase 2 skills."""
    has_jd     = bool((job.get('job_description') or '').strip())
    if is_missing_jd_description(job.get('job_description')):
        return False
    return has_jd and not has_terminal_core_enrichment(job)


def _company_name_from_json_path(json_path: Path) -> str:
    return json_path.parent.parent.parent.name


def _filter_enrich_json_files(json_files: list[Path], company_filter: str | None) -> list[Path]:
    if not company_filter:
        return json_files
    needle = company_filter.lower()
    return [path for path in json_files if needle in _company_name_from_json_path(path).lower()]


def _latest_enrich_json_files(json_files: list[Path]) -> list[Path]:
    latest: dict[str, Path] = {}
    for path in json_files:
        company = _company_name_from_json_path(path)
        current = latest.get(company)
        if current is None or path.parent.name > current.parent.name:
            latest[company] = path
    return sorted(latest.values())


def enrich_only_run(
    log: logging.Logger,
    *,
    company_filter: str | None = None,
    max_jobs_per_company: int | None = None,
    latest_only: bool = False,
) -> None:
    """
    Walk All_CSV_Outputs/*/Outputs/*/jobs.json — enrich unenriched jobs in-place.
    LM Studio must be running. No Firecrawl calls are made.
    """
    base = Path(OUTPUT_BASE)
    json_files = _filter_enrich_json_files(sorted(base.rglob("jobs.json")), company_filter)
    if latest_only:
        json_files = _latest_enrich_json_files(json_files)
    log.info(f"Enrich-only mode: found {len(json_files)} jobs.json file(s)")
    if company_filter:
        log.info(f"Enrich-only company filter: {company_filter}")
    if latest_only:
        log.info("Enrich-only latest-output mode enabled")
    if max_jobs_per_company:
        log.info(f"Enrich-only cap: {max_jobs_per_company} jobs/company")

    total_enriched = total_failed = 0
    attempted_by_company: dict[str, int] = {}

    for json_path in json_files:
        folder_company = _company_name_from_json_path(json_path)
        remaining_cap = None
        if max_jobs_per_company:
            used = attempted_by_company.get(folder_company, 0)
            remaining_cap = max_jobs_per_company - used
            if remaining_cap <= 0:
                log.info(f"  {folder_company}: enrich-only cap reached — skipping remaining files")
                continue

        try:
            jobs = json.loads(json_path.read_text(encoding='utf-8'))
        except Exception as e:
            log.warning(f"  Could not read {json_path}: {e}")
            continue

        pending = [j for j in jobs if _needs_enrichment(j)]
        to_enrich = pending[:remaining_cap] if remaining_cap else pending
        if not to_enrich:
            log.info(f"  {json_path.parent.parent.parent.name}: all jobs already enriched — skipping")
            continue

        company = jobs[0].get('company_name', json_path.parent.parent.parent.name) if jobs else '?'
        log.info(f"  {company}: enriching {len(to_enrich)}/{len(pending)} pending jobs ({len(jobs)} total)")

        ok = fail = 0
        quota_exhausted = False
        _workers = int(os.getenv("ENRICH_WORKERS", "4"))
        with ThreadPoolExecutor(max_workers=_workers) as pool:
            futures = {
                pool.submit(enrich_job, job): job
                for job in to_enrich
            }
            for fut in as_completed(futures):
                try:
                    fut.result()
                    ok += 1
                except InferenceQuotaExceeded as e:
                    log.warning(f"    inference quota exhausted for '{futures[fut].get('job_title')}': {e}")
                    fail += 1
                    quota_exhausted = True
                    for pending_fut in futures:
                        pending_fut.cancel()
                    break
                except Exception as e:
                    log.warning(f"    enrich failed for '{futures[fut].get('job_title')}': {e}")
                    fail += 1

        log.info(f"    {ok} ok  {fail} failed")
        total_enriched += ok
        total_failed   += fail
        attempted_by_company[folder_company] = attempted_by_company.get(folder_company, 0) + len(to_enrich)

        # Write back JSON (atomic: tmp → rename)
        for job in jobs:
            _normalize_source_facts(job)
            stamp_job_content_hash(job)

        tmp_path = json_path.with_name("jobs.tmp.json")
        tmp_path.write_text(json.dumps(jobs, indent=2, ensure_ascii=False), encoding='utf-8')
        tmp_path.rename(json_path)

        # Rewrite CSV
        csv_path = json_path.with_name("jobs.csv")
        with csv_path.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=SCHEMA, extrasaction='ignore')
            w.writeheader()
            for job in jobs:
                row = dict(job)
                row['skills'] = _skills_to_csv(job.get('skills'))
                row['main_skills'] = ', '.join(job.get('main_skills') or [])
                row['side_skills'] = ''
                w.writerow(row)

        # Marker after both JSON and CSV succeed
        write_complete_marker(json_path.parent, len(jobs), ok)
        if quota_exhausted:
            log.warning("Enrich-only stopped early because inference quota was exhausted")
            break

    log.info(f"Enrich-only complete — {total_enriched} enriched, {total_failed} failed")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Mirror Job Scraper (v2)")
    parser.add_argument("--company",               help="Filter by company name (substring, case-insensitive)")
    parser.add_argument("--ats",                   help="Filter by ATS type (workday, smartrecruiters, …)")
    parser.add_argument("--dry-run",               action="store_true", help="List portals only, no scraping")
    parser.add_argument("--skip-enrich",           action="store_true", help="Skip LLM enrichment, save raw scraped data")
    parser.add_argument("--resume",                action="store_true", help="Skip companies that already have output in All_CSV_Outputs")
    parser.add_argument("--enrich-only",           action="store_true", help="Enrich already-scraped jobs (no scraping, LM Studio only)")
    parser.add_argument("--latest-only",           action="store_true", help="With --enrich-only, process only each company's latest output folder")
    parser.add_argument("--scope", choices=["india", "global"], default="india",
                        help="Job geography scope (default: india).")
    parser.add_argument("--company-cap", type=int, default=_DEFAULT_COMPANY_CAP,
                        help="Max jobs per company (default: 0 = unlimited). Set a positive integer only for probes.")
    parser.add_argument("--global-cap", type=int, default=None,
                        help="Alias for --company-cap (kept for backward compat).")
    parser.add_argument("--resume-run", metavar="RUN_ID",
                        help="Resume a specific interrupted run by its run_id "
                             "(e.g. 20260430_141922). Skips companies marked complete in that run.")
    parser.add_argument(
        "--run-date",
        help="Pin all output from this logical run to YYYY_MM_DD, even across midnight",
    )
    parser.add_argument("--validate",              action="store_true",
                        help=f"Validation run: scrape {_VALIDATE_MAX_JOBS} jobs/company, no enrichment, "
                             f"write to validation_outputs/ — use to verify column coverage across all portals")
    args = parser.parse_args()

    if args.run_date:
        try:
            args.run_date = normalize_run_date(args.run_date)[0]
        except ValueError as exc:
            parser.error(str(exc))

    log = setup_logging()

    if args.enrich_only:
        raw_cap = args.global_cap if args.global_cap is not None else args.company_cap
        max_jobs = raw_cap if raw_cap else None
        enrich_only_run(
            log,
            company_filter=args.company,
            max_jobs_per_company=max_jobs,
            latest_only=args.latest_only,
        )
        return

    # --validate: cap to 5 jobs/company, no enrichment, separate output folder
    # --company-cap: 0 = unlimited (default); a positive integer is a probe/debug limit
    validate_mode = args.validate
    if validate_mode:
        max_jobs = _VALIDATE_MAX_JOBS
    else:
        # --global-cap is a backward-compat alias; explicit --company-cap wins
        raw_cap = args.global_cap if args.global_cap is not None else args.company_cap
        max_jobs = raw_cap if raw_cap else None
    output_base = _VALIDATE_OUTPUT_BASE if validate_mode else OUTPUT_BASE
    if validate_mode:
        log.info(f"VALIDATE MODE: max {_VALIDATE_MAX_JOBS} jobs/company → {output_base}")
    elif max_jobs:
        log.info(f"Cap: {max_jobs} jobs/company")

    portals = parse_portals()
    if args.company:
        portals = [p for p in portals if args.company.lower() in p["company"].lower()]
    if args.ats:
        portals = [p for p in portals if p["ats"] == args.ats.lower()]
    # ── Determine resume checkpoint (--resume-run or auto-detect via --resume) ──
    log_dir = Path(__file__).resolve().parent.parent / "logs"
    resume_checkpoint: RunCheckpoint | None = None

    if args.resume_run:
        resume_checkpoint = RunCheckpoint.load(args.resume_run, log_dir)
        if not resume_checkpoint:
            log.warning(f"--resume-run: checkpoint {args.resume_run} not found — running fresh")
    elif args.resume:
        resume_checkpoint = RunCheckpoint.load_latest_partial(log_dir)
        if resume_checkpoint:
            log.info(f"--resume: auto-detected partial run {resume_checkpoint.run_id}")

    # ── Filter already-done companies ─────────────────────────────────────────
    if resume_checkpoint:
        before = len(portals)
        portals = [p for p in portals if not resume_checkpoint.is_complete(p["company"])]
        label = f"--resume-run {resume_checkpoint.run_id}" if args.resume_run else "--resume (checkpoint)"
        log.info(f"{label}: skipping {before - len(portals)} complete, {len(portals)} remaining")
    elif args.resume:
        # No checkpoint found — fall back to file-date comparison
        before = len(portals)
        portals = [p for p in portals if not already_scraped(p["company"])]
        log.info(f"--resume (file-date): skipping {before - len(portals)} already-scraped, {len(portals)} remaining")

    # Scope override:
    # india  -> force India filtering across adapters
    # global -> disable India filtering where adapter supports it
    for p in portals:
        p["india_only"] = (args.scope == "india")

    log.info(f"Scope: {args.scope}")
    log.info(f"Portals to process: {len(portals)}")
    for p in portals:
        flag = "🌐" if p["js_required"] else "⚡"
        log.info(f"  {flag}  {p['company']:<30} [{p['ats']}]")

    if args.dry_run:
        return

    # Create checkpoint for this run (always — not only on --resume)
    run_id  = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    checkpoint = resume_checkpoint or RunCheckpoint.new(run_id, log_dir)
    if resume_checkpoint:
        log.info(f"Resuming run_id={checkpoint.run_id}")
    else:
        log.info(f"Checkpoint: logs/checkpoint_{run_id}.json")

    log.info("─" * 60)
    summary = run(portals, skip_enrich=args.skip_enrich or validate_mode, log=log,
                  max_jobs=max_jobs, output_base=output_base,
                  validate_mode=validate_mode, scope=args.scope,
                  checkpoint=checkpoint, run_date=args.run_date)

    log.info("─" * 60)
    log.info("RUN COMPLETE")
    log.info(f"  Run ID              : {checkpoint.run_id}")
    log.info(f"  Companies processed : {summary['processed']}")
    log.info(f"  Companies skipped   : {summary['skipped']}")
    log.info(f"  Total new jobs      : {summary['total_new']}")
    log.info(f"  Started             : {summary['start']}")
    log.info(f"  Ended               : {summary['end']}")
    cp_summary = checkpoint.summary()
    log.info(f"  Checkpoint states   : complete={cp_summary['complete']} "
             f"failed={cp_summary['failed']} partial={cp_summary['in_progress']}")

    if summary["errors"]:
        log.warning(f"  Errors ({len(summary['errors'])}):")
        for e in summary["errors"]:
            log.warning(f"    [{e['stage']}] {e['company']}: {e['error']}")

    if summary["low_count"]:
        log.warning(f"  Low-count companies (<5 scraped jobs): {len(summary['low_count'])}")
        for row in summary["low_count"]:
            log.warning(f"    {row['company']} [{row['ats']}]: scraped={row['raw_jobs']} saved_new={row['saved_new']}")

    reports_dir = Path(__file__).resolve().parent.parent / "logs"
    reports_dir.mkdir(parents=True, exist_ok=True)
    summary_path = reports_dir / f"run_summary_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info(f"  Run summary JSON    : {summary_path}")
    _persist_diagnostics_to_supabase(summary, log)
    _run_self_diagnosis(summary, log)


def _run_self_diagnosis(summary: dict, log: logging.Logger) -> None:
    """Best-effort: classify this run's 0/low companies and write the handoff.

    Cheap and network-free — no probing here. Heavy re-testing stays in the
    standalone `python diagnose.py --probe`. Never let this break a scrape.
    """
    try:
        from diagnose import LOGS_DIR, load_blocked_tenants, render_report
        from heal.baseline import load_ledger
        from heal.classifier import classify_run, bucket_counts, BUCKET_ORDER, OK

        verdicts = classify_run(summary, load_ledger(), load_blocked_tenants())
        counts = bucket_counts([v for v in verdicts if v.is_failure])
        log.info(f"  Self-diagnosis      : {sum(counts.values())} companies need attention")
        for b in BUCKET_ORDER:
            if b != OK and counts.get(b):
                log.info(f"    {b:<18} {counts[b]}")
        out = Path(LOGS_DIR) / f"diagnosis_{summary.get('run_id', 'latest')}.md"
        out.write_text(render_report(summary, verdicts) + "\n", encoding="utf-8")
        log.info(f"  Diagnosis report    : {out}  (run `python diagnose.py --probe` to re-test regressions)")
    except Exception as e:  # noqa: BLE001 — diagnostics must never fail a run
        log.warning(f"  Self-diagnosis skipped: {e}")


if __name__ == "__main__":
    main()
