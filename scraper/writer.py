"""
Normalize raw scraper dicts to the 10-field canonical schema and
persist to All_CSV_Outputs/{Company}/Outputs/YYYY_MM_DD/jobs.json (+ CSV).

Schema (v2, Dump 4+):
  job_id, job_title, job_description,
  industry, role_domain,          ← static from portal / LLM-derived
  company_name, apply_url,
  main_skills, side_skills,       ← LLM-derived
  batch_date                      ← auto-stamped integer YYYYMMDD

Completion contract:
  jobs.complete is written ONLY after both jobs.json and jobs.csv succeed.
  already_scraped() in main.py uses this marker as the canonical signal.
  Legacy runs (no marker) are detected via date-folder comparison.
"""
import json
import csv
import hashlib
from datetime import datetime
from pathlib import Path
from utils import company_slug
from config import OUTPUT_BASE
from job_career_band import normalize_job_career_band
from job_seniority import normalize_job_seniority
from job_summary import extractive_job_summary
from schema import CANONICAL_FIELDS, MIN_JOB_DESCRIPTION_LEN, MISSING_JD_NOTE

# SCHEMA kept as alias for backward-compat imports (e.g. main.py: from writer import SCHEMA)
SCHEMA = CANONICAL_FIELDS


def _skills_to_csv(skills) -> str:
    """Serialize the structured skills list to a human-readable CSV cell: 'name:level | …'.
    JSON remains the importer's source of truth; this is only for the human-facing CSV."""
    out = []
    for s in skills or []:
        if isinstance(s, dict) and s.get('name'):
            out.append(f"{s['name']}:{s.get('required_level', 2)}")
    return ' | '.join(out)

COMPLETE_MARKER_NAME = "jobs.complete"


def write_complete_marker(folder: Path, job_count: int, new_count: int, run_id: str = "") -> None:
    """Write jobs.complete after both JSON and CSV are confirmed written."""
    payload: dict = {
        "completed_at": datetime.now().isoformat(),
        "job_count":    job_count,
        "new_jobs":     new_count,
    }
    if run_id:
        payload["run_id"] = run_id
    (folder / COMPLETE_MARKER_NAME).write_text(json.dumps(payload), encoding='utf-8')

def _today() -> int:
    return int(datetime.now().strftime("%Y%m%d"))


def normalize_run_date(run_date: str | None) -> tuple[str, int]:
    """Return output-folder and batch-date forms for one logical scrape run."""
    if run_date is None:
        now = datetime.now()
        return now.strftime("%Y_%m_%d"), int(now.strftime("%Y%m%d"))

    normalized = run_date.replace("-", "_")
    if len(normalized) == 8 and normalized.isdigit():
        normalized = f"{normalized[:4]}_{normalized[4:6]}_{normalized[6:]}"
    try:
        parsed = datetime.strptime(normalized, "%Y_%m_%d")
    except ValueError as exc:
        raise ValueError(
            "run_date must be YYYYMMDD, YYYY-MM-DD, or YYYY_MM_DD"
        ) from exc
    return parsed.strftime("%Y_%m_%d"), int(parsed.strftime("%Y%m%d"))


def job_content_hash(job: dict) -> str:
    """Stable signal for re-embedding when JD/title/skills materially change."""
    skills = job.get("main_skills") or []
    if not isinstance(skills, list):
        skills = [str(skills)] if skills else []
    payload = {
        "job_title": str(job.get("job_title") or "").strip(),
        "job_description": str(job.get("job_description") or "").strip(),
        "main_skills": [str(skill).strip() for skill in skills if str(skill or "").strip()],
    }
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def stamp_job_content_hash(job: dict) -> dict:
    job["job_content_hash"] = job_content_hash(job)
    return job


def to_canonical(raw: dict, company_name: str) -> dict:
    """Map raw scraper dict to canonical schema using RAW_FIELD_MAP for renames."""
    def _get(raw_key: str, canonical_key: str, default=''):
        # Try canonical key first (already-mapped field), then raw key alias
        return raw.get(canonical_key) or raw.get(raw_key) or default

    location = _get('location_city', 'location') or raw.get('Location') or raw.get('location_raw') or 'India'
    source_job_description = _get('raw_jd_text', 'job_description')
    job_description = source_job_description
    metadata_only = len(str(source_job_description or '').strip()) < MIN_JOB_DESCRIPTION_LEN
    if metadata_only:
        job_description = MISSING_JD_NOTE
    normalized_seniority = normalize_job_seniority({
        **raw,
        "job_title": _get('title', 'job_title'),
        # The card may hide a short JD, but its source text can still contain
        # a deterministic experience requirement such as "12+ years".
        "job_description": source_job_description,
    })
    source_role_domain = raw.get('role_domain') or raw.get('business_unit') or ''
    normalized_career_band = normalize_job_career_band({
        **raw,
        "job_title": _get('title', 'job_title'),
        "role_domain": source_role_domain,
    })
    job_title = _get('title', 'job_title')
    existing_summary = str(raw.get('job_summary') or '').strip()
    if (
        existing_summary
        and not metadata_only
        and existing_summary != MISSING_JD_NOTE
    ):
        job_summary = existing_summary
    else:
        job_summary = extractive_job_summary(
            job_title,
            source_job_description,
            metadata_only=metadata_only,
        )

    row = {
        "job_id":           raw.get('job_id') or '',
        "job_title":        job_title,
        "job_description":  job_description,
        "job_summary":      job_summary,
        "industry":         raw.get('industry') or '',
        "industry_group":   raw.get('industry_group') or '',
        "company_name":     company_name,
        "location":         location,
        "location_raw":     raw.get('location_raw') or location,
        "location_city":    raw.get('location_city') or location,
        "location_country": raw.get('location_country') or ('India' if location else ''),
        "location_mode":    raw.get('location_mode') or '',
        "location_quality": raw.get('location_quality') or '',
        # per-city raw strings for multi-location postings (firecrawl #6).
        # csv_importer._normalize_location canonicalizes; empty list → derived from scalar.
        "locations":        [location for location in (raw.get('locations') or []) if isinstance(location, str) and location.strip()],
        "apply_url":        _get('job_url', 'apply_url'),
        "source_url":       raw.get('source_url') or raw.get('source_api_url') or '',
        "source_platform":  raw.get('source_platform') or raw.get('ats') or '',
        "ingestion_source": raw.get('ingestion_source') or 'scraper',
        "quality_status":   raw.get('quality_status') or 'auto_extracted',
        "role_domain":      source_role_domain,
        "career_band":      normalized_career_band,
        # One flat skill list. `skills` carries model required_level → job_skills;
        # `main_skills` mirrors the names (True_Yodha chips); `side_skills` always [].
        "skills":           raw.get('skills') or [],
        "main_skills":      raw.get('main_skills') or [],
        "side_skills":      [],
        "candidate_profile":        raw.get('candidate_profile') or {},
        "candidate_profile_version": raw.get('candidate_profile_version') or '',
        "candidate_profile_hash":    raw.get('candidate_profile_hash') or '',
        "candidate_profile_model":   raw.get('candidate_profile_model') or '',
        "job_content_hash":          raw.get('job_content_hash') or '',
        # Structured source facts. Seniority is normalized deterministically from
        # provider metadata, title, and JD during the forward scrape; no LLM pass.
        "date_posted":            raw.get('date_posted') or raw.get('date_posted_raw') or '',
        "seniority_level":        normalized_seniority.seniority_level,
        "work_mode":              raw.get('work_mode') or '',
        "min_years_experience":   normalized_seniority.min_years_experience if normalized_seniority.min_years_experience is not None else '',
        "max_years_experience":   normalized_seniority.max_years_experience if normalized_seniority.max_years_experience is not None else '',
        "batch_date":       raw.get('batch_date') or _today(),
    }
    row["job_content_hash"] = row.get("job_content_hash") or job_content_hash(row)
    return {field: row.get(field, '') for field in CANONICAL_FIELDS}


def save_jobs(
    company_name: str,
    jobs: list[dict],
    write_csv: bool = True,
    output_base: str = OUTPUT_BASE,
    write_marker: bool = True,
    run_id: str = "",
    run_date: str | None = None,
) -> tuple[str, int]:
    """
    Write jobs to All_CSV_Outputs/{Company}/Outputs/YYYY_MM_DD/jobs.json (+ CSV).
    Deduplicates by job_id within the same date folder.
    write_marker=True (default): writes jobs.complete after both JSON and CSV succeed.
    write_marker=False: intermediate/page-level save — no marker (run still in progress).
    Returns (json_path, new_jobs_count).
    """
    folder_date, default_batch_date = normalize_run_date(run_date)
    folder = (
        Path(output_base)
        / company_slug(company_name)
        / "Outputs"
        / folder_date
    )
    folder.mkdir(parents=True, exist_ok=True)
    json_path      = folder / "jobs.json"
    tmp_path       = folder / "jobs.tmp.json"
    complete_marker = folder / COMPLETE_MARKER_NAME

    # Remove stale marker — this save is in progress
    if complete_marker.exists():
        complete_marker.unlink()

    existing: list[dict] = []
    if json_path.exists():
        try:
            existing = json.loads(json_path.read_text(encoding='utf-8'))
        except Exception:
            existing = []

    # Provider pages can overlap while the upstream board is changing. Keep a
    # single row per requisition even if the same id is repeated within either
    # the existing file or the newly completed snapshot.
    deduped_existing: list[dict] = []
    existing_ids: set[str] = set()
    for job in existing:
        job_id = str(job.get('job_id') or '')
        if not job_id or job_id in existing_ids:
            continue
        existing_ids.add(job_id)
        deduped_existing.append(job)

    new_jobs: list[dict] = []
    new_ids: set[str] = set()
    for job in jobs:
        job_id = str(job.get('job_id') or '')
        if not job_id or job_id in existing_ids or job_id in new_ids:
            continue
        new_ids.add(job_id)
        new_jobs.append(job)

    all_jobs = []
    for job in deduped_existing + new_jobs:
        batch_date = (
            default_batch_date
            if run_date is not None
            else job.get("batch_date") or default_batch_date
        )
        all_jobs.append(stamp_job_content_hash({**job, "batch_date": batch_date}))

    # Atomic JSON write: tmp → rename (POSIX atomic)
    tmp_path.write_text(json.dumps(all_jobs, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp_path.rename(json_path)

    if write_csv and all_jobs:
        csv_path = folder / "jobs.csv"
        with csv_path.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=SCHEMA, extrasaction='ignore')
            w.writeheader()
            for job in all_jobs:
                row = dict(job)
                row['skills'] = _skills_to_csv(job.get('skills'))
                row['main_skills'] = ', '.join(job.get('main_skills') or [])
                row['side_skills'] = ''
                row['locations'] = ' | '.join(job.get('locations') or [])
                w.writerow(row)

    # Marker written only after BOTH JSON and CSV succeed (skipped for page-level saves)
    if write_marker:
        write_complete_marker(folder, len(all_jobs), len(new_jobs), run_id=run_id)

    return str(json_path), len(new_jobs)
