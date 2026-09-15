"""Resolve source-level matching facts before initial job publication.

Career band is mandatory for frontend routing, but it must never be inferred
from employer industry or filled with a default. Deterministic title/domain
evidence runs first. Remaining jobs are classified by the configured local
LM Studio model and accepted only when the response includes a grounded,
high-confidence source phrase.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any

from openai import OpenAI

from config import (
    INFERENCE_API_KEY,
    INFERENCE_BASE_URL,
    INFERENCE_MODEL,
    INFERENCE_PROVIDER,
    OUTPUT_BASE,
)
from enrichment_state import source_content_hash
from job_career_band import VALID_CAREER_BANDS, normalize_job_career_band
from job_seniority import normalize_job_seniority
from normalizer import clean_jd_for_llm, parse_json_response
from schema import CANONICAL_FIELDS
from writer import _skills_to_csv


log = logging.getLogger("source_matching_facts")

_GENERIC_EVIDENCE = re.compile(
    r"^(?:senior|junior|lead|principal|staff|associate|analyst|specialist|"
    r"manager|executive|officer|consultant|assistant|coordinator|apprentice|"
    r"trainee|intern|l[1-4])(?:\s+(?:l[1-4]|contract))?$",
    re.IGNORECASE,
)
_BAND_EVIDENCE = {
    "engineering_data": re.compile(
        r"\b(?:software|developer|engineering|engineer|technical|technology|data|"
        r"analytics|machine learning|ai|cloud|network|database|infrastructure|"
        r"application|cyber|security|automation|manufacturing|machine|quality|"
        r"inspection|root cause|process validation|sap|erp)\b",
        re.IGNORECASE,
    ),
    "business_product_operations": re.compile(
        r"\b(?:finance|financial|accounting|accounts?|banking|sales|marketing|"
        r"customer|product management|operations|supply chain|procurement|"
        r"planning|commercial|revenue|growth|consulting|strategy|audit|tax|"
        r"treasury|credit|insurance|underwriting|project|program|category)\b",
        re.IGNORECASE,
    ),
    "research_people_public_impact": re.compile(
        r"\b(?:research|science|scientific|clinical|medical|healthcare|human resources|"
        r"people|talent|recruiting|legal|counsel|compliance|policy|education|"
        r"training|learning|community|public affairs|government|patent)\b",
        re.IGNORECASE,
    ),
    "design_creative": re.compile(
        r"\b(?:ux|ui|design|designer|graphic|visual|creative|copywriting|"
        r"illustration|animation|art direction)\b",
        re.IGNORECASE,
    ),
}
_BOILERPLATE_EVIDENCE = re.compile(
    r"\b(?:innovative \w+ers|around the world|long-standing reputation|"
    r"equal opportunity employer|committed to innovation)\b",
    re.IGNORECASE,
)
_CLIENT_LOCAL = threading.local()

_BAND_GUIDE = """\
engineering_data: software, data, AI, IT infrastructure, cybersecurity,
technical engineering, manufacturing engineering, technical quality/QA/testing,
or technical architecture.
business_product_operations: finance, banking, product management, consulting,
sales, marketing, business operations, customer operations, supply chain, or
general management. Service/process quality belongs here only when the source
clearly describes nontechnical customer or business operations.
research_people_public_impact: scientific or clinical research, healthcare,
HR/people, recruiting, legal/compliance, policy, education, or social impact.
design_creative: UX/UI, product/graphic/visual design, writing, or other
creative production."""


def _client() -> OpenAI:
    client = getattr(_CLIENT_LOCAL, "client", None)
    if client is None:
        client = OpenAI(
            base_url=INFERENCE_BASE_URL,
            api_key=INFERENCE_API_KEY,
            timeout=180,
        )
        _CLIENT_LOCAL.client = client
    return client


def _source_excerpt(job: dict[str, Any], limit: int = 1800) -> str:
    description = clean_jd_for_llm(str(job.get("job_description") or ""))
    return description[:limit]


def _classification_prompt(items: list[dict[str, Any]]) -> str:
    return f"""\
Classify each job into exactly one source-level career band using only its
title and JD excerpt.

{_BAND_GUIDE}

Rules:
- Employer industry is not role evidence.
- evidence must be a short exact phrase copied from the supplied title or JD
  excerpt that demonstrates the role function, not merely seniority.
- Use confidence "high" only when that phrase clearly supports the band.
- If evidence is ambiguous, return career_band null and confidence "low".

Return only this JSON shape:
{{"classifications":[{{"id":0,"career_band":"engineering_data","evidence":"exact source phrase","confidence":"high"}}]}}

Jobs:
{json.dumps(items, ensure_ascii=False)}
"""


def _parse_accepted_classifications(
    raw: Any,
    jobs_by_id: dict[int, dict[str, Any]],
) -> dict[int, dict[str, str]]:
    if isinstance(raw, str):
        raw = parse_json_response(raw)
    if not isinstance(raw, dict):
        return {}
    items = raw.get("classifications")
    if not isinstance(items, list):
        return {}

    accepted: dict[int, dict[str, str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if not isinstance(item_id, int) or item_id not in jobs_by_id:
            continue
        band = str(item.get("career_band") or "").strip()
        evidence = " ".join(str(item.get("evidence") or "").split())
        confidence = str(item.get("confidence") or "").strip().casefold()
        if (
            band not in VALID_CAREER_BANDS
            or confidence != "high"
            or len(evidence) < 4
            or _GENERIC_EVIDENCE.fullmatch(evidence)
            or _BOILERPLATE_EVIDENCE.search(evidence)
        ):
            continue
        supported_bands = {
            candidate
            for candidate, pattern in _BAND_EVIDENCE.items()
            if pattern.search(evidence)
        }
        if supported_bands != {band}:
            continue

        job = jobs_by_id[item_id]
        source = f"{job.get('job_title') or ''}\n{_source_excerpt(job)}".casefold()
        if evidence.casefold() not in source:
            continue
        accepted[item_id] = {
            "career_band": band,
            "evidence": evidence,
            "confidence": confidence,
        }
    return accepted


def _classify_batch(
    indexed_jobs: list[tuple[int, dict[str, Any]]],
) -> dict[int, dict[str, str]]:
    local_jobs = {
        local_id: job
        for local_id, (_, job) in enumerate(indexed_jobs)
    }
    local_to_source_id = {
        local_id: source_id
        for local_id, (source_id, _) in enumerate(indexed_jobs)
    }
    prompt_items = [
        {
            "id": local_id,
            "title": str(job.get("job_title") or ""),
            "jd_excerpt": _source_excerpt(job),
        }
        for local_id, (_, job) in enumerate(indexed_jobs)
    ]
    response = _client().chat.completions.create(
        model=INFERENCE_MODEL,
        messages=[
            {
                "role": "system",
                "content": (
                    "You classify job functions from supplied evidence. "
                    "Return valid JSON only."
                ),
            },
            {"role": "user", "content": _classification_prompt(prompt_items)},
        ],
        temperature=0,
        max_tokens=(
            max(1600, len(indexed_jobs) * 180)
            if INFERENCE_PROVIDER != "local"
            else max(700, len(indexed_jobs) * 120)
        ),
    )
    content = response.choices[0].message.content or ""
    accepted = _parse_accepted_classifications(content, local_jobs)
    return {
        local_to_source_id[local_id]: result
        for local_id, result in accepted.items()
    }


def _normalize_source_facts(job: dict[str, Any]) -> None:
    seniority = normalize_job_seniority(job)
    job["seniority_level"] = seniority.seniority_level
    job["min_years_experience"] = (
        seniority.min_years_experience
        if seniority.min_years_experience is not None else ""
    )
    job["max_years_experience"] = (
        seniority.max_years_experience
        if seniority.max_years_experience is not None else ""
    )
    deterministic_band = normalize_job_career_band(job)
    if deterministic_band:
        job["career_band"] = deterministic_band
        job["career_band_source"] = "deterministic_title_or_role_domain"
        job["career_band_source_hash"] = source_content_hash(job)
        job.pop("career_band_evidence", None)
        job.pop("career_band_model", None)
        job.pop("career_band_provider", None)
        return

    current_model_band_is_fresh = (
        job.get("career_band") in VALID_CAREER_BANDS
        and job.get("career_band_source") == "model_grounded"
        and str(job.get("career_band_evidence") or "").strip()
        and job.get("career_band_source_hash") == source_content_hash(job)
    )
    if current_model_band_is_fresh:
        return

    job["career_band"] = ""
    job.pop("career_band_source", None)
    job.pop("career_band_source_hash", None)
    job.pop("career_band_evidence", None)
    job.pop("career_band_model", None)
    job.pop("career_band_provider", None)


def _write_jobs(json_path: Path, jobs: list[dict[str, Any]]) -> None:
    tmp_path = json_path.with_name("jobs.source-facts.tmp.json")
    tmp_path.write_text(
        json.dumps(jobs, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp_path.replace(json_path)

    csv_path = json_path.with_name("jobs.csv")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CANONICAL_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for job in jobs:
            row = dict(job)
            row["skills"] = _skills_to_csv(job.get("skills"))
            row["main_skills"] = ", ".join(job.get("main_skills") or [])
            row["side_skills"] = ""
            # Match writer.save_jobs — without this the human-facing CSV gets a
            # Python list repr, and this pass now rewrites every company's CSV.
            row["locations"] = " | ".join(job.get("locations") or [])
            writer.writerow(row)


def _find_run_files(run_date: str, company: str | None) -> list[Path]:
    normalized_date = run_date.replace("-", "_")
    if re.fullmatch(r"\d{8}", normalized_date):
        normalized_date = (
            f"{normalized_date[:4]}_{normalized_date[4:6]}_{normalized_date[6:]}"
        )
    if not re.fullmatch(r"\d{4}_\d{2}_\d{2}", normalized_date):
        raise ValueError("--run-date must be YYYYMMDD, YYYY-MM-DD, or YYYY_MM_DD")

    files = sorted(
        Path(OUTPUT_BASE).glob(f"*/Outputs/{normalized_date}/jobs.json")
    )
    if company:
        needle = company.casefold()
        files = [
            path for path in files
            if needle in path.parent.parent.parent.name.casefold()
        ]
    return [
        path for path in files
        if path.with_name("jobs.complete").exists()
    ]


def resolve_run(
    *,
    run_date: str,
    company: str | None,
    batch_size: int,
    workers: int,
    dry_run: bool,
    skip_model: bool = False,
) -> dict[str, Any]:
    files = _find_run_files(run_date, company)
    if not files:
        raise ValueError("No complete jobs.json files matched the requested run")

    audit: list[dict[str, str]] = []
    total_jobs = deterministic = model_resolved = unresolved = 0

    for file_number, json_path in enumerate(files, start=1):
        jobs = json.loads(json_path.read_text(encoding="utf-8"))
        if not isinstance(jobs, list):
            raise ValueError(f"Expected a JSON list in {json_path}")
        for job in jobs:
            _normalize_source_facts(job)

        pending = [
            (index, job)
            for index, job in enumerate(jobs)
            if job.get("career_band") not in VALID_CAREER_BANDS
        ]
        total_jobs += len(jobs)
        deterministic += len(jobs) - len(pending)

        if not dry_run and pending and not skip_model:
            batches = [
                pending[index:index + batch_size]
                for index in range(0, len(pending), batch_size)
            ]
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(_classify_batch, batch): batch
                    for batch in batches
                }
                for future in as_completed(futures):
                    batch = futures[future]
                    try:
                        accepted = future.result()
                    except Exception as exc:
                        log.warning(
                            "%s: source-fact batch failed (%s jobs): %s",
                            json_path.parent.parent.parent.name,
                            len(batch),
                            exc,
                        )
                        continue
                    for item_id, result in accepted.items():
                        job = jobs[item_id]
                        job["career_band"] = result["career_band"]
                        job["career_band_source"] = "model_grounded"
                        job["career_band_source_hash"] = source_content_hash(job)
                        job["career_band_evidence"] = result["evidence"]
                        job["career_band_model"] = INFERENCE_MODEL
                        job["career_band_provider"] = INFERENCE_PROVIDER
                        audit.append({
                            "job_id": str(job.get("job_id") or ""),
                            "job_title": str(job.get("job_title") or ""),
                            "company_name": str(job.get("company_name") or ""),
                            **result,
                        })
                    model_resolved += len(accepted)

        if not dry_run:
            # Outside the `pending` branch on purpose. `_normalize_source_facts`
            # stamps the provenance that `csv_importer` requires, including for
            # jobs the deterministic rules resolved on their own. Writing only
            # when the model ran left those rows unprovenanced on disk, and the
            # publish withheld every one of them.
            _write_jobs(json_path, jobs)

        file_unresolved = sum(
            job.get("career_band") not in VALID_CAREER_BANDS for job in jobs
        )
        unresolved += file_unresolved
        log.info(
            "[%s/%s] %s: %s jobs, %s model candidates, %s unresolved",
            file_number,
            len(files),
            json_path.parent.parent.parent.name,
            len(jobs),
            len(pending),
            file_unresolved,
        )

    report = {
        "run_date": run_date,
        "provider": INFERENCE_PROVIDER,
        "model": INFERENCE_MODEL,
        "files": len(files),
        "total_jobs": total_jobs,
        "deterministic": deterministic,
        "model_resolved": model_resolved,
        "unresolved": unresolved,
        "accepted_classifications": audit,
    }
    if not dry_run:
        logs_dir = Path(__file__).resolve().parent.parent / "logs"
        logs_dir.mkdir(exist_ok=True)
        report_path = logs_dir / (
            "source_matching_facts_"
            + datetime.now().strftime("%Y%m%d_%H%M%S")
            + ".json"
        )
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        report["report_path"] = str(report_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve truthful source-level career band and seniority facts",
    )
    parser.add_argument("--run-date", required=True)
    parser.add_argument("--company")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument(
        "--workers",
        type=int,
        default=int(os.getenv("SOURCE_FACT_WORKERS", "4")),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--skip-model",
        action="store_true",
        help=(
            "Stamp deterministic bands and provenance only; do not call the "
            "model for the remainder. Measured 2026-08-08: the model pass ran "
            "at ~2.7 calls/min and accepted ~7%% of candidates, so it costs "
            "hours to band a handful of jobs. Use this to publish the "
            "deterministic majority now and iterate on the rules."
        ),
    )
    parser.add_argument(
        "--allow-unresolved",
        action="store_true",
        help=(
            "Exit 0 even when some jobs keep no career band. The daily lane "
            "sets this because `csv_importer --publish-unclassified` publishes "
            "source-valid rows with a null band rather than guessing; they stay "
            "outside band-dependent matching until resolution improves. Omit it for a standalone run you want "
            "to fail loudly."
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    if args.batch_size < 1 or args.workers < 1:
        parser.error("--batch-size and --workers must be positive")
    try:
        report = resolve_run(
            run_date=args.run_date,
            company=args.company,
            batch_size=args.batch_size,
            workers=args.workers,
            dry_run=args.dry_run,
            skip_model=args.skip_model,
        )
    except ValueError as exc:
        parser.error(str(exc))
    log.info(
        "Source matching facts: %s total, %s deterministic, %s model-resolved, "
        "%s unresolved",
        report["total_jobs"],
        report["deterministic"],
        report["model_resolved"],
        report["unresolved"],
    )
    if report.get("report_path"):
        log.info("Audit report: %s", report["report_path"])
    if report["unresolved"]:
        log.warning(
            "%s jobs still have no career band. The publication-safe importer "
            "will expose them for browse with career_band=NULL while keeping "
            "them outside band-dependent matching. Extend deterministic rules "
            "only where the source evidence is unambiguous.",
            report["unresolved"],
        )
        if not args.allow_unresolved:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
