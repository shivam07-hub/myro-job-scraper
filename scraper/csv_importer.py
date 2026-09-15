"""
csv_importer.py — Phase 3: upload source or enriched local JSON to Supabase.

Reads All_CSV_Outputs/*/Outputs/*/jobs.json and:
  1. Upserts core job fields to the `jobs` table (with lifecycle tracking).
  2. Resolves the flat `skills` list (or legacy main_skills fallback) → skill_ids.
  3. Logs skills that don't resolve (taxonomy drift signal).

`job_skills` is NOT written here any more. It belongs to True_Yodha's skill
engine — Stage A reads where in the JD a skill is named, Stage B judges how deep
— and a write from this side overwrote that read with a constant `is_primary`
and locked Stage A out of the job. See `_count_skill_drift`.

Usage:
    python csv_importer.py                        # all companies, latest date folder
    python csv_importer.py --company "Barclays"   # one company
    python csv_importer.py --all-dates            # all date folders, not just latest
    python csv_importer.py --dry-run              # print counts, no writes
    python csv_importer.py --source-only --run-date YYYY_MM_DD
                                                  # publish one completed run;
                                                  # queue Phase 2 enrichment lazily
    python csv_importer.py --dry-run --deactivate-missing
                                                  # inspect newest output date without writes
    python csv_importer.py --deactivate-missing --run-date 20260510
                                                  # opt-in stale-job decommission, one run date only
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import sys
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests
from supabase import create_client, Client

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

from environment import EnvironmentError_, load_environment, require

load_environment()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("csv_importer")

from config import OUTPUT_BASE  # noqa: E402
from enrichment_state import (  # noqa: E402
    CORE_ENRICHMENT_VERSION,
    has_core_enrichment_payload,
    source_content_hash,
)
from utils import company_slug  # noqa: E402
from job_career_band import VALID_CAREER_BANDS  # noqa: E402
from job_summary import extractive_job_summary  # noqa: E402
from schema import MIN_JOB_DESCRIPTION_LEN  # noqa: E402
from source_snapshot import finalize_source_snapshot, upsert_rows  # noqa: E402

_VALID_SENIORITY_LEVELS = frozenset({
    "intern", "entry", "mid", "senior", "lead", "executive",
})

_SOURCE_JOB_FIELDS = [
    "job_id", "job_title", "job_description",
    "industry", "company_name", "location", "apply_url",
    "source_url", "source_platform", "ingestion_source", "quality_status",
    "career_band",
    "batch_date",
    "location_raw", "location_city", "location_country", "location_mode", "location_quality",
    "locations",
    "date_posted", "seniority_level", "work_mode",
    "min_years_experience", "max_years_experience",
]

_ENRICHMENT_JOB_FIELDS = [
    "job_summary", "role_domain", "main_skills", "side_skills",
]

_FORWARD_ENRICHMENT_COLUMNS = {
    "source_content_hash",
    "enriched_source_hash",
    "job_content_hash",
    "enrichment_status",
    "enrichment_model",
    "enrichment_version",
    "enrichment_queued_at",
    "enrichment_priority_requested_at",
    "enrichment_started_at",
    "enriched_at",
    "enrichment_last_error",
}

_BATCH_SIZE = 200
_UNKNOWN_LOCATION_THRESHOLD = 0.10
_MAX_DEACTIVATION_RATE = 0.75
_LOCATION_PARSER_VERSION = "v1"
_DEFAULT_PROFILE_VERSION = "cv_profile_v1"
_SCRAPE_HANDOFF_BACKOFF_SECONDS = (0, 2, 5)


def _source_matching_facts_are_publishable(job: dict) -> bool:
    if not str(job.get("job_id") or "").strip():
        return False
    band = str(job.get("career_band") or "").strip()
    seniority = str(job.get("seniority_level") or "").strip()
    if band not in VALID_CAREER_BANDS:
        return False
    if seniority and seniority not in _VALID_SENIORITY_LEVELS:
        return False
    source = str(job.get("career_band_source") or "").strip()
    source_hash = str(job.get("career_band_source_hash") or "").strip()
    if (
        source not in {
            "deterministic_title_or_role_domain",
            "model_grounded",
        }
        or source_hash != source_content_hash(job)
    ):
        return False
    if source == "model_grounded":
        return all(
            str(job.get(field) or "").strip()
            for field in (
                "career_band_evidence",
                "career_band_model",
                "career_band_provider",
            )
        )
    return True


def _source_row_is_publishable(
    job: dict,
    *,
    publish_unclassified: bool = False,
) -> bool:
    """Separate source publication truth from optional matching readiness."""
    if _source_matching_facts_are_publishable(job):
        return True
    if not publish_unclassified or not str(job.get("job_id") or "").strip():
        return False
    if str(job.get("career_band") or "").strip():
        return False
    if any(
        str(job.get(field) or "").strip()
        for field in (
            "career_band_source",
            "career_band_source_hash",
            "career_band_evidence",
            "career_band_model",
            "career_band_provider",
        )
    ):
        return False
    seniority = str(job.get("seniority_level") or "").strip()
    return not seniority or seniority in _VALID_SENIORITY_LEVELS


def _validate_source_matching_facts(
    json_files: list[Path],
    *,
    publish_unclassified: bool = False,
) -> tuple[int, int, int, int]:
    """Reject an entire publication before writes if matching facts are invalid."""
    invalid_bands: list[tuple[Path, str, str]] = []
    invalid_provenance: list[tuple[Path, str, str]] = []
    invalid_seniority: list[tuple[Path, str, str]] = []
    missing_job_ids: list[tuple[Path, str, str]] = []
    total_jobs = 0
    publishable_rows = 0
    unclassified_keys: set[tuple[str, str]] = set()
    publishable_keys: set[tuple[str, str]] = set()

    for json_path in json_files:
        try:
            jobs = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"Could not read {json_path}: {exc}") from exc
        if not isinstance(jobs, list):
            raise ValueError(f"Expected a JSON job list in {json_path}")

        for job in jobs:
            if not isinstance(job, dict):
                raise ValueError(f"Expected job objects in {json_path}")
            total_jobs += 1
            title = str(job.get("job_title") or "<missing title>")
            if not str(job.get("job_id") or "").strip():
                missing_job_ids.append((json_path, title, ""))
            band = str(job.get("career_band") or "").strip()
            seniority = str(job.get("seniority_level") or "").strip()
            if band and band not in VALID_CAREER_BANDS:
                invalid_bands.append((json_path, title, band))
            elif band:
                source = str(job.get("career_band_source") or "").strip()
                source_hash = str(job.get("career_band_source_hash") or "").strip()
                provenance_valid = (
                    source in {
                        "deterministic_title_or_role_domain",
                        "model_grounded",
                    }
                    and source_hash == source_content_hash(job)
                )
                if source == "model_grounded":
                    provenance_valid = provenance_valid and all(
                        str(job.get(field) or "").strip()
                        for field in (
                            "career_band_evidence",
                            "career_band_model",
                            "career_band_provider",
                        )
                    )
                if not provenance_valid:
                    invalid_provenance.append((json_path, title, source))
            elif any(
                str(job.get(field) or "").strip()
                for field in (
                    "career_band_source",
                    "career_band_source_hash",
                    "career_band_evidence",
                    "career_band_model",
                    "career_band_provider",
                )
            ):
                invalid_provenance.append((json_path, title, "unclassified_with_claim"))
            if seniority and seniority not in _VALID_SENIORITY_LEVELS:
                invalid_seniority.append((json_path, title, seniority))
            if _source_row_is_publishable(
                job,
                publish_unclassified=publish_unclassified,
            ):
                publishable_rows += 1
                if not band:
                    unclassified_keys.add((
                        str(job.get("company_name") or ""),
                        str(job.get("job_id") or ""),
                    ))
                publishable_keys.add((
                    str(job.get("company_name") or ""),
                    str(job.get("job_id") or ""),
                ))

    unresolved_rows = total_jobs - publishable_rows
    if not publish_unclassified and (
        invalid_bands
        or invalid_provenance
        or invalid_seniority
        or missing_job_ids
        or unresolved_rows
    ):
        details = []
        for label, rows in (
            ("job_id", missing_job_ids),
            ("career_band", invalid_bands),
            ("career_band_source", invalid_provenance),
            ("seniority_level", invalid_seniority),
        ):
            for path, title, value in rows[:5]:
                details.append(
                    f"{label}={value!r} title={title!r} file={path}"
                )
        raise ValueError(
            "Source matching-fact preflight failed before Supabase writes: "
            f"{len(missing_job_ids)} missing job IDs; "
            f"{unresolved_rows} invalid/unresolved career bands; "
            f"{len(invalid_provenance)} invalid/stale career-band provenance; "
            f"{len(invalid_seniority)} invalid seniority levels. "
            + " | ".join(details)
        )
    duplicate_rows = publishable_rows - len(publishable_keys)
    return total_jobs, len(publishable_keys), duplicate_rows, len(unclassified_keys)


def _parse_batch_date(value: str | int | None) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if re.match(r"^\d{8}$", text):
        return int(text)
    normalized = text.replace("_", "-")
    if re.match(r"^\d{4}-\d{2}-\d{2}$", normalized):
        return int(normalized.replace("-", ""))
    return None

# ── Industry group mapping (10 super-categories) ──────────────────────────────

_INDUSTRY_GROUP: dict[str, str] = {
    "Technology":                   "Technology",
    "Semiconductors":               "Technology",
    "Software":                     "Technology",
    "Cloud":                        "Technology",
    "IT Services":                  "Consulting & Professional Services",
    "Consulting":                   "Consulting & Professional Services",
    "Legal":                        "Consulting & Professional Services",
    "BFSI":                         "BFSI",
    "Fintech":                      "BFSI",
    "Insurance":                    "BFSI",
    "Automotive":                   "Manufacturing & Industrial",
    "Manufacturing":                "Manufacturing & Industrial",
    "Engineering":                  "Manufacturing & Industrial",
    "Aerospace & Defense":          "Manufacturing & Industrial",
    "Energy":                       "Energy & Resources",
    "Oil & Gas":                    "Energy & Resources",
    "Chemicals":                    "Energy & Resources",
    "Pharmaceutical":               "Healthcare & Life Sciences",
    "Healthcare":                   "Healthcare & Life Sciences",
    "MedTech":                      "Healthcare & Life Sciences",
    "Biotechnology":                "Healthcare & Life Sciences",
    "Consumer Goods":               "Consumer & Retail",
    "Retail":                       "Consumer & Retail",
    "E-commerce & Retail":          "Consumer & Retail",
    "FMCG":                         "Consumer & Retail",
    "Food & Beverage":              "Consumer & Retail",
    "Media & Entertainment":        "Media & Telecom",
    "Telecom":                      "Media & Telecom",
    "Logistics":                    "Logistics & Supply Chain",
    "Shipping & Logistics":         "Logistics & Supply Chain",
    "Aviation":                     "Logistics & Supply Chain",
    "Conglomerate":                 "Diversified",
    "Real Estate":                  "Diversified",
    "Education":                    "Diversified",
    "Professional Services":        "Consulting & Professional Services",
}

# ── Canonical location parser (deterministic aliases) ─────────────────────────

@dataclass(frozen=True)
class NormalizedLocation:
    location: str | None
    location_raw: str | None
    location_city: str | None
    location_country: str | None
    location_mode: str
    location_quality: str
    locations: tuple[str, ...] = ()


_SPACE_RE = re.compile(r"\s+")
_MULTI_LOCATION_RE = re.compile(r"\b\d+\s*locations?\b|multiple locations|various locations")
_REMOTE_RE = re.compile(r"\bremote\b|\bwork from home\b|\bwfh\b|\bworldwide\b|\banywhere\b")
_HYBRID_RE = re.compile(r"\bhybrid\b")

_CITY_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bbangalore\b|\bbengaluru\b"), "Bengaluru"),
    (re.compile(r"\bhyderabad\b"), "Hyderabad"),
    (re.compile(r"\bmumbai\b|\bbombay\b"), "Mumbai"),
    (re.compile(r"\bpune\b"), "Pune"),
    (re.compile(r"\bchennai\b|\bmadras\b"), "Chennai"),
    (re.compile(r"\bnew delhi\b|\bdelhi\b|\bncr\b"), "Delhi NCR"),
    (re.compile(r"\bgurgaon\b|\bgurugram\b"), "Gurugram"),
    (re.compile(r"\bnoida\b"), "Noida"),
    (re.compile(r"\bkolkata\b|\bcalcutta\b"), "Kolkata"),
    (re.compile(r"\bahmedabad\b"), "Ahmedabad"),
)

_COUNTRY_ALIASES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bindia\b|(?:^|[,\s\-])in(?:$|[,\s\-])"), "India"),
    (re.compile(r"\busa\b|\bunited states\b|\bu\.s\.\b"), "United States"),
    (re.compile(r"\buk\b|\bunited kingdom\b"), "United Kingdom"),
    (re.compile(r"\bsingapore\b"), "Singapore"),
    (re.compile(r"\bcanada\b"), "Canada"),
    (re.compile(r"\bgermany\b"), "Germany"),
    (re.compile(r"\bfrance\b"), "France"),
)

_INDIA_CITIES = {
    "Bengaluru",
    "Hyderabad",
    "Mumbai",
    "Pune",
    "Chennai",
    "Delhi NCR",
    "Gurugram",
    "Noida",
    "Kolkata",
    "Ahmedabad",
}


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _SPACE_RE.sub(" ", value.strip())
    return cleaned or None


def _infer_mode(lower: str) -> str:
    if _HYBRID_RE.search(lower):
        return "hybrid"
    if _REMOTE_RE.search(lower):
        return "remote"
    return "unknown"


def _infer_city(lower: str, raw: str) -> str | None:
    for pattern, canonical in _CITY_ALIASES:
        if pattern.search(lower):
            return canonical

    token = re.split(r"[;,|]", raw, maxsplit=1)[0]
    token = re.split(r"\s+-\s+", token, maxsplit=1)[0].strip()
    if not token or re.search(r"\d", token):
        return None
    token_lower = token.lower()
    if any(word in token_lower for word in ("location", "remote", "hybrid", "worldwide", "anywhere")):
        return None
    return _SPACE_RE.sub(" ", token.title())


def _infer_country(lower: str) -> str | None:
    for pattern, canonical in _COUNTRY_ALIASES:
        if pattern.search(lower):
            return canonical
    return None


def _display_location(
    *,
    city: str | None,
    country: str | None,
    mode: str,
    quality: str,
    raw: str | None,
) -> str | None:
    if quality == "unknown":
        return raw
    if mode == "remote":
        return f"Remote - {country}" if country else "Remote"
    if mode == "hybrid":
        if city and country:
            return f"Hybrid - {city}, {country}"
        if city:
            return f"Hybrid - {city}"
        return f"Hybrid - {country}" if country else "Hybrid"
    if city and country:
        return f"{city}, {country}"
    return city or country or raw


def _canonical_city_list(raw_locations: list | tuple | None) -> list[str]:
    """Canonicalize a provider's per-city array into ordered, deduped city names."""
    out: list[str] = []
    for entry in raw_locations or []:
        if not isinstance(entry, str):
            continue
        s = _clean_text(entry)
        if not s:
            continue
        canonical = _infer_city(s.lower(), s)
        if canonical and canonical not in out:
            out.append(canonical)
    return out


def _normalize_location(
    value: str | None,
    raw_locations: list | tuple | None = None,
) -> NormalizedLocation:
    raw = _clean_text(value)
    if raw is None and not raw_locations:
        return NormalizedLocation(
            location="Unknown",
            location_raw=None,
            location_city=None,
            location_country=None,
            location_mode="unknown",
            location_quality="unknown",
            locations=(),
        )

    # Cities the provider enumerated (multi-location postings, firecrawl #6).
    multi = _canonical_city_list(raw_locations)

    if raw is None:
        # No scalar string, but the provider gave a city array — synthesize.
        lower = ""
        mode = "unknown"
        city = None
        country = None
        quality = "unknown"
    else:
        lower = raw.lower()
        mode = _infer_mode(lower)
        city = _infer_city(lower, raw)
        country = _infer_country(lower)
        if city in _INDIA_CITIES and not country:
            country = "India"

        if mode == "unknown" and _MULTI_LOCATION_RE.search(lower):
            quality = "unknown"
            city = None  # "N Locations" phrase carries no real city by itself
        elif mode == "unknown" and city is None and country is None:
            quality = "unknown"
        else:
            quality = "ok"

    # Recover cities from the array when the scalar parse failed / was a count phrase.
    if multi:
        if city is None:
            city = multi[0]
        if country is None:
            for entry in raw_locations or []:
                inferred = _infer_country((entry or "").lower()) if isinstance(entry, str) else None
                if inferred:
                    country = inferred
                    break
        if city in _INDIA_CITIES and not country:
            country = "India"
        if quality == "unknown" and city:
            quality = "ok"

    if mode == "unknown" and quality == "ok" and (city or country):
        mode = "onsite"

    # Final locations array: scalar primary city first, then the rest, deduped.
    locations: list[str] = []
    if city:
        locations.append(city)
    for c in multi:
        if c not in locations:
            locations.append(c)

    return NormalizedLocation(
        location=_display_location(city=city, country=country, mode=mode, quality=quality, raw=raw),
        location_raw=raw,
        location_city=city,
        location_country=country,
        location_mode=mode,
        location_quality=quality,
        locations=tuple(locations),
    )


def _valid_apply_url(url: str | None) -> str | None:
    if not url:
        return None
    if not url.startswith("http"):
        return None
    if re.search(r"\.(png|jpg|jpeg|gif|svg|webp|pdf)(\?|$)", url, re.IGNORECASE):
        return None
    return url


def _industry_group(industry: str | None) -> str | None:
    if not industry:
        return None
    return _INDUSTRY_GROUP.get(industry, "Diversified")


# ── Supabase client ────────────────────────────────────────────────────────────

def _supabase() -> Client:
    url = os.getenv("SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        log.error("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in scraper/.env")
        sys.exit(1)
    return create_client(url, key)


def _assert_location_audit_contract(run_id: str) -> None:
    """Read-only guard: fail before uploads if the run-audit table shape drifted."""
    url = (os.getenv("SUPABASE_URL", "") or "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        log.error("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in scraper/.env")
        sys.exit(1)

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/openapi+json",
    }
    try:
        response = requests.get(f"{url}/rest/v1/", headers=headers, timeout=30)
        response.raise_for_status()
        spec = response.json()
    except Exception as exc:
        log.error("Could not read Supabase OpenAPI schema for preflight: %s", exc)
        raise SystemExit(2) from exc

    schemas = spec.get("definitions") or spec.get("components", {}).get("schemas") or {}
    table = schemas.get("job_feed_run_audits") or schemas.get("public.job_feed_run_audits") or {}
    columns = table.get("properties") or {}
    required = {
        "run_id",
        "source",
        "parser_version",
        "total_rows",
        "unknown_location_rows",
        "unknown_location_rate",
        "top_unknown_aliases",
        "status",
    }
    missing = sorted(required - set(columns))
    if missing:
        log.error("job_feed_run_audits is missing required preflight columns: %s", ", ".join(missing))
        raise SystemExit(2)

    run_id_type = columns.get("run_id", {}).get("format") or columns.get("run_id", {}).get("type")
    if run_id_type == "uuid":
        try:
            uuid.UUID(run_id)
        except ValueError as exc:
            log.error("job_feed_run_audits.run_id expects uuid; generated run_id is invalid: %s", run_id)
            raise SystemExit(2) from exc
    log.info("Supabase audit contract preflight OK")


def _jobs_has_locations_column() -> bool:
    """Return True when live Supabase jobs exposes the locations[] column.

    _upsert_jobs sends `locations` on every row, so this MUST exist before real
    writes or the whole upsert batch fails (firecrawl #6).
    """
    url = (os.getenv("SUPABASE_URL", "") or "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return False

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/openapi+json",
    }
    try:
        response = requests.get(f"{url}/rest/v1/", headers=headers, timeout=30)
        response.raise_for_status()
        spec = response.json()
    except Exception:
        return False

    schemas = spec.get("definitions") or spec.get("components", {}).get("schemas") or {}
    table = schemas.get("jobs") or schemas.get("public.jobs") or {}
    return "locations" in (table.get("properties") or {})


def _jobs_has_job_content_hash_column() -> bool:
    """Return True when live Supabase jobs exposes the optional embedding-change signal."""
    url = (os.getenv("SUPABASE_URL", "") or "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return False

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/openapi+json",
    }
    try:
        response = requests.get(f"{url}/rest/v1/", headers=headers, timeout=30)
        response.raise_for_status()
        spec = response.json()
    except Exception:
        return False

    schemas = spec.get("definitions") or spec.get("components", {}).get("schemas") or {}
    table = schemas.get("jobs") or schemas.get("public.jobs") or {}
    return "job_content_hash" in (table.get("properties") or {})


def _jobs_missing_forward_enrichment_columns() -> list[str]:
    """Return async-enrichment columns absent from the live jobs Data API."""
    url = (os.getenv("SUPABASE_URL", "") or "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return sorted(_FORWARD_ENRICHMENT_COLUMNS)

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/openapi+json",
    }
    try:
        response = requests.get(f"{url}/rest/v1/", headers=headers, timeout=30)
        response.raise_for_status()
        spec = response.json()
    except Exception:
        return sorted(_FORWARD_ENRICHMENT_COLUMNS)

    schemas = spec.get("definitions") or spec.get("components", {}).get("schemas") or {}
    table = schemas.get("jobs") or schemas.get("public.jobs") or {}
    properties = table.get("properties") or {}
    return sorted(_FORWARD_ENRICHMENT_COLUMNS - set(properties))


# Card-data columns added for the job_summary + structured-chip work.
# They MUST exist before real writes. job_summary is sent only on first-fill
# rows; source_snapshot.upsert_rows groups those separately so omit-to-preserve
# cannot NULL an existing model summary.
_CARD_COLUMNS = (
    "job_summary", "date_posted", "seniority_level",
    "work_mode", "min_years_experience", "max_years_experience",
)

_PROFILE_COLUMNS = (
    "job_id", "profile_version", "generated_from_hash", "ideal_candidate_summary",
    "cv_positioning", "proof_points", "gap_risks", "project_suggestions",
    "resume_keywords", "interview_themes", "model_name",
)


def _candidate_profile_upload_disabled() -> bool:
    return (os.getenv("SKIP_CANDIDATE_PROFILE_UPLOAD", "").strip().lower()
            in {"1", "true", "yes"})


def _coerce_smallint(value) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return int(value)
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = float(text)
        except ValueError:
            return None
        if math.isfinite(parsed) and parsed.is_integer():
            return int(parsed)
    return None


def _jobs_missing_card_columns() -> list[str]:
    """Return card columns absent from live Supabase jobs (empty list = all present)."""
    url = (os.getenv("SUPABASE_URL", "") or "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return list(_CARD_COLUMNS)

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/openapi+json",
    }
    try:
        response = requests.get(f"{url}/rest/v1/", headers=headers, timeout=30)
        response.raise_for_status()
        spec = response.json()
    except Exception:
        return list(_CARD_COLUMNS)

    schemas = spec.get("definitions") or spec.get("components", {}).get("schemas") or {}
    table = schemas.get("jobs") or schemas.get("public.jobs") or {}
    props = table.get("properties") or {}
    return [c for c in _CARD_COLUMNS if c not in props]


def _job_candidate_profiles_missing_columns() -> list[str]:
    """Return profile columns absent from live Supabase (empty list = table ready)."""
    url = (os.getenv("SUPABASE_URL", "") or "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return list(_PROFILE_COLUMNS)

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/openapi+json",
    }
    try:
        response = requests.get(f"{url}/rest/v1/", headers=headers, timeout=30)
        response.raise_for_status()
        spec = response.json()
    except Exception:
        return list(_PROFILE_COLUMNS)

    schemas = spec.get("definitions") or spec.get("components", {}).get("schemas") or {}
    table = schemas.get("job_candidate_profiles") or schemas.get("public.job_candidate_profiles") or {}
    props = table.get("properties") or {}
    return [c for c in _PROFILE_COLUMNS if c not in props]


def _job_skill_entries(job: dict) -> list[dict]:
    """One flat bucket of needed skills → job_skills rows.

    There is no primary/side split: is_primary is always True and importance is
    carried by required_level (1-4). The structured `skills` list (model levels)
    is preferred; legacy main_skills/side_skills name lists are the fallback for
    older dump files (no model levels → default L2).
    """
    structured = job.get("skills")
    if isinstance(structured, list) and structured:
        result = []
        for item in structured:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                continue
            level = item.get("required_level")
            if not isinstance(level, int) or level not in (1, 2, 3, 4):
                level = 2
            result.append({
                "name": name,
                "is_primary": True,
                "required_level": level,
            })
        return result

    names = list(job.get("main_skills") or []) + list(job.get("side_skills") or [])
    return [
        {"name": skill, "is_primary": True, "required_level": 2}
        for skill in names if isinstance(skill, str) and skill.strip()
    ]


def _profile_array(profile: dict, key: str) -> list[str]:
    value = profile.get(key) or []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _candidate_profile_rows(jobs: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for job in jobs:
        job_id = job.get("job_id")
        profile = job.get("candidate_profile")
        profile_hash = job.get("candidate_profile_hash")
        if not job_id or not isinstance(profile, dict) or not profile or not profile_hash:
            continue
        summary = str(profile.get("ideal_candidate_summary") or "").strip()
        if not summary:
            continue
        rows.append({
            "job_id": job_id,
            "profile_version": job.get("candidate_profile_version") or _DEFAULT_PROFILE_VERSION,
            "generated_from_hash": profile_hash,
            "ideal_candidate_summary": summary,
            "cv_positioning": _profile_array(profile, "cv_positioning"),
            "proof_points": _profile_array(profile, "proof_points"),
            "gap_risks": _profile_array(profile, "gap_risks"),
            "project_suggestions": _profile_array(profile, "project_suggestions"),
            "resume_keywords": _profile_array(profile, "resume_keywords"),
            "interview_themes": _profile_array(profile, "interview_themes"),
            "model_name": job.get("candidate_profile_model") or None,
        })
    return rows


def _upsert_candidate_profiles(sb: Client, jobs: list[dict], dry_run: bool) -> int:
    rows = _candidate_profile_rows(jobs)
    if dry_run or not rows:
        return len(rows)
    if _candidate_profile_upload_disabled():
        return 0
    for i in range(0, len(rows), _BATCH_SIZE):
        upsert_rows(
            sb,
            "job_candidate_profiles",
            rows[i:i + _BATCH_SIZE],
            on_conflict="job_id",
            ignore_duplicates=False,
        )
    return len(rows)


# ── Skill ID cache ─────────────────────────────────────────────────────────────

def _build_skill_id_map(sb: Client) -> dict[str, int]:
    log.info("Loading skills table from Supabase...")
    skill_map: dict[str, int] = {}
    page = 0
    page_size = 1000
    while True:
        batch = (
            sb.table("skills")
            .select("id, taxonomy_key")
            .range(page * page_size, (page + 1) * page_size - 1)
            .execute()
        ).data or []
        for row in batch:
            if row.get("taxonomy_key") and row.get("id"):
                skill_map[row["taxonomy_key"]] = row["id"]
        if len(batch) < page_size:
            break
        page += 1
    log.info(f"Loaded {len(skill_map)} skills from taxonomy")
    return skill_map


# ── Job file discovery ─────────────────────────────────────────────────────────

def _find_json_files(
    company_filter: str | None,
    all_dates: bool,
    batch_date: int | None = None,
) -> list[Path]:
    base = Path(OUTPUT_BASE)
    if not base.exists():
        log.error(f"OUTPUT_BASE not found: {base}")
        return []

    result: list[Path] = []
    for company_dir in sorted(base.iterdir()):
        if not company_dir.is_dir():
            continue
        if company_filter and company_filter.lower() not in company_dir.name.lower():
            continue

        outputs = company_dir / "Outputs"
        if not outputs.exists():
            continue

        date_dirs = sorted(
            [d for d in outputs.iterdir() if d.is_dir()],
            reverse=True,
        )

        if batch_date is not None:
            for d in date_dirs:
                if _parse_batch_date(d.name) != batch_date:
                    continue
                p = d / "jobs.json"
                if p.exists():
                    result.append(p)
        elif all_dates:
            for d in date_dirs:
                p = d / "jobs.json"
                if p.exists():
                    result.append(p)
        else:
            for d in date_dirs:
                p = d / "jobs.json"
                if p.exists():
                    result.append(p)
                    break

    return result


# ── Core import logic ──────────────────────────────────────────────────────────

def _collision_safe_job_id(company: str, raw_job_id: str) -> str:
    return f"{company_slug(company).lower()}::{raw_job_id}"


def _existing_job_companies(sb: Client, job_ids: list[str]) -> dict[str, str]:
    existing: dict[str, str] = {}
    unique_ids = list(dict.fromkeys(job_ids))
    for index in range(0, len(unique_ids), 100):
        batch = unique_ids[index:index + 100]
        try:
            rows = (
                sb.table("jobs")
                .select("job_id,company_name")
                .in_("job_id", batch)
                .execute()
            ).data or []
        except (AttributeError, TypeError):
            # Lightweight unit-test fakes may only implement upsert.
            return {}
        for row in rows:
            if isinstance(row, dict) and row.get("job_id"):
                existing[str(row["job_id"])] = str(row.get("company_name") or "")
    return existing


def _namespace_cross_company_collisions(sb: Client, jobs: list[dict]) -> int:
    raw_ids = [str(job.get("job_id")) for job in jobs if job.get("job_id")]
    owners = _existing_job_companies(sb, raw_ids)
    changed = 0
    for job in jobs:
        raw_job_id = str(job.get("job_id") or "").strip()
        company = str(job.get("company_name") or "").strip()
        existing_company = owners.get(raw_job_id, "").strip()
        if not raw_job_id or not company or not existing_company:
            continue
        if existing_company.casefold() == company.casefold():
            continue
        safe_id = _collision_safe_job_id(company, raw_job_id)
        log.warning(
            "Cross-company job_id collision: %s is owned by %s; using %s for %s",
            raw_job_id,
            existing_company,
            safe_id,
            company,
        )
        job["job_id"] = safe_id
        changed += 1
    return changed


def _fetch_existing_summaries(sb: Client, job_ids: list[str]) -> dict[str, str]:
    """Map job_id → current job_summary. Missing ids are new rows."""
    out: dict[str, str] = {}
    for i in range(0, len(job_ids), _BATCH_SIZE):
        chunk = job_ids[i:i + _BATCH_SIZE]
        rows = (
            sb.table("jobs")
            .select("job_id,job_summary")
            .in_("job_id", chunk)
            .execute()
        ).data or []
        for row in rows:
            job_id = str(row.get("job_id") or "")
            if job_id:
                out[job_id] = str(row.get("job_summary") or "")
    return out


def _source_summary_for_insert(job: dict) -> str:
    existing = str(job.get("job_summary") or "").strip()
    if existing:
        return existing
    desc = str(job.get("job_description") or "")
    return extractive_job_summary(
        str(job.get("job_title") or ""),
        desc,
        metadata_only=len(desc.strip()) < MIN_JOB_DESCRIPTION_LEN,
    )


def _upsert_jobs(
    sb: Client,
    jobs: list[dict],
    batch_date: int | None,
    location_alias_counter: Counter[str],
    *,
    source_only: bool = False,
    supports_forward_enrichment: bool = False,
) -> tuple[int, int]:
    _namespace_cross_company_collisions(sb, jobs)
    rows = []
    unknown_location_rows = 0
    existing_summaries: dict[str, str] = {}
    if source_only:
        existing_summaries = _fetch_existing_summaries(
            sb,
            [str(job.get("job_id")) for job in jobs if job.get("job_id")],
        )
    supports_job_content_hash = (
        not source_only and _jobs_has_job_content_hash_column()
    )
    for job in jobs:
        if not job.get("job_id"):
            continue

        # Drop None always; drop "" only for smallint numeric columns (Postgres
        # rejects "" for smallint). Empty strings are kept for text columns to
        # preserve prior insert behavior (e.g. NOT NULL job_description).
        _INT_FIELDS = {"min_years_experience", "max_years_experience"}
        row = {}
        for f in _SOURCE_JOB_FIELDS:
            v = job.get(f)
            if f in _INT_FIELDS:
                v = _coerce_smallint(v)
                if v is None:
                    continue
            elif isinstance(v, float) and not math.isfinite(v):
                continue
            elif v is None:
                continue
            row[f] = v

        # NULL is a truthful matching state, not a publication failure. Include
        # it explicitly so a changed source cannot retain a stale prior band on
        # conflict; the database constraint permits NULL but rejects "".
        band = str(job.get("career_band") or "").strip()
        row["career_band"] = band if band in VALID_CAREER_BANDS else None

        carries_enrichment = has_core_enrichment_payload(job)
        if source_only:
            job_id = str(job.get("job_id") or "")
            if not str(existing_summaries.get(job_id) or "").strip():
                summary = _source_summary_for_insert(job)
                if summary:
                    row["job_summary"] = summary
        elif not source_only and carries_enrichment:
            for field in _ENRICHMENT_JOB_FIELDS:
                value = job.get(field)
                if value is not None:
                    row[field] = value
        row["job_title"] = job.get("job_title") or ""
        row["job_description"] = job.get("job_description") or ""
        row["company_name"] = job.get("company_name") or ""
        row["industry"] = job.get("industry") or "unknown"
        row["ingestion_source"] = job.get("ingestion_source") or "scraper"
        row["quality_status"] = job.get("quality_status") or "auto_extracted"
        normalized_location = _normalize_location(job.get("location"), job.get("locations"))

        # Derived fields
        row["industry_group"] = _industry_group(job.get("industry"))
        row["location"] = normalized_location.location
        row["location_raw"] = normalized_location.location_raw
        row["location_city"] = normalized_location.location_city
        row["location_country"] = normalized_location.location_country
        row["location_mode"] = normalized_location.location_mode
        row["location_quality"] = normalized_location.location_quality
        row["locations"] = list(normalized_location.locations)
        row["apply_url"]      = _valid_apply_url(job.get("apply_url"))
        if supports_forward_enrichment:
            row["source_content_hash"] = source_content_hash(job)
            if not source_only and carries_enrichment:
                row["enriched_source_hash"] = row["source_content_hash"]
                row["enrichment_status"] = "complete"
                row["enrichment_version"] = CORE_ENRICHMENT_VERSION
        if (not source_only and carries_enrichment
                and supports_job_content_hash and job.get("job_content_hash")):
            row["job_content_hash"] = job.get("job_content_hash")
        if normalized_location.location_quality == "unknown":
            unknown_location_rows += 1
            if normalized_location.location_raw:
                location_alias_counter[normalized_location.location_raw.lower()] += 1

        # Lifecycle: first_seen set only on insert; last_seen always updated
        effective_date = batch_date or job.get("batch_date")
        if effective_date:
            row["last_seen"]  = effective_date
            row["first_seen"] = effective_date  # ignored on conflict (see upsert below)
            row["is_active"]  = True

        rows.append(row)

    # Deduplicate by job_id — keep last occurrence
    seen_jobs: dict[str, dict] = {}
    for r in rows:
        seen_jobs[r["job_id"]] = r
    rows = list(seen_jobs.values())

    if not rows:
        return 0, 0

    for i in range(0, len(rows), _BATCH_SIZE):
        batch = rows[i:i + _BATCH_SIZE]
        # On conflict: update everything EXCEPT first_seen and is_active
        # (community owns is_active; first_seen is set once at insert)
        upsert_rows(
            sb,
            "jobs",
            batch,
            on_conflict="job_id",
            ignore_duplicates=False,
        )

    return len(rows), unknown_location_rows


def _count_skill_drift(
    jobs: list[dict],
    skill_id_map: dict[str, int],
    drift_counter: Counter,
) -> int:
    """Count skill names that do not resolve against the Lightcast taxonomy.

    This path does NOT write `job_skills`, and must not be made to. It used to
    upsert every row with `is_primary=True`, which is how 94.2% of 361,165 prod
    rows came to carry a constant where an importance signal belongs — read
    through company demand, every skill of every company looked like a 100%
    must-have.

    `job_skills` is owned by True_Yodha's skill engine: Stage A reads WHERE in
    the JD each skill is named (must-have / preferred / mentioned) and Stage B
    judges how deep. A write from here deletes their read, because
    `has_skill_floor` flips true on the row and Stage A never revisits the job.

    Drift counting stays: an unresolvable skill name is still the scrape's own
    signal about its enrichment vocabulary, and costs nothing to keep.
    """
    local_drift = 0

    for job in jobs:
        if not job.get("job_id"):
            continue

        for skill_entry in _job_skill_entries(job):
            skill = skill_entry["name"]
            if not skill_id_map.get(skill):
                drift_counter[skill] += 1
                local_drift += 1

    return local_drift


def _write_diagnostic(
    sb: Client,
    run_id: str,
    company: str,
    raw_jobs: int,
    saved_new: int,
    enriched: int,
    drift: int,
) -> None:
    enriched_pct = round(enriched / raw_jobs * 100) if raw_jobs else 0
    sb.table("scrape_diagnostics").insert({
        "run_id":       run_id,
        "scope":        "india",
        "company_name": company,
        "status":       "upload",
        "raw_jobs":     raw_jobs,
        "saved_new":    saved_new,
        "reason":       f"{enriched_pct}% enriched, {drift} skill drift",
    }).execute()


def _sync_baseline_ledger(company: str, jobs: list[dict], raw_jobs: int, run_id: str) -> None:
    """Forward-only sync of the official load count into baseline_ledger.json.

    This is the source of truth for the self-healing diagnostic's regression
    detection: next run, diagnose.py diffs the scrape against this last-good
    count. Only count>0 ever writes (a bad run is the regression signal, not a
    new baseline). Best-effort — never fail an import over the ledger.
    """
    try:
        from datetime import date
        from heal.baseline import load_ledger, save_ledger, update_ledger
        ledger = load_ledger()
        ats = (jobs[0].get("ats", "") if jobs else "") or ""
        if update_ledger(ledger, company, ats, raw_jobs, run_id, updated=date.today().isoformat()):
            save_ledger(ledger)
    except Exception:  # noqa: BLE001 — ledger sync must never break a load
        pass


def _write_location_audit(
    sb: Client,
    *,
    run_id: str,
    total_rows: int,
    unknown_location_rows: int,
    unknown_location_rate: float,
    top_unknown_aliases: list[dict[str, int]],
    status: str,
    message: str | None,
) -> None:
    sb.table("job_feed_run_audits").insert({
        "run_id": run_id,
        "source": "firecrawl_csv_importer",
        "parser_version": _LOCATION_PARSER_VERSION,
        "total_rows": total_rows,
        "unknown_location_rows": unknown_location_rows,
        "unknown_location_rate": unknown_location_rate,
        "top_unknown_aliases": top_unknown_aliases,
        "status": status,
        "message": message,
    }).execute()


def _fetch_active_jobs_for_company(sb: Client, company: str) -> list[dict]:
    rows: list[dict] = []
    page = 0
    page_size = 1000
    while True:
        batch = (
            sb.table("jobs")
            .select("job_id,job_title,company_name,batch_date,last_seen,is_active")
            .eq("company_name", company)
            .eq("is_active", True)
            .range(page * page_size, (page + 1) * page_size - 1)
            .execute()
        ).data or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        page += 1
    return rows


def _deactivate_missing_jobs(
    sb: Client,
    *,
    company: str,
    current_job_ids: set[str],
    batch_date: int,
    dry_run: bool,
    allow_large_deactivation: bool,
) -> dict:
    active_rows = _fetch_active_jobs_for_company(sb, company)
    missing = [row for row in active_rows if row.get("job_id") not in current_job_ids]
    missing_rate = (len(missing) / len(active_rows)) if active_rows else 0.0
    result = {
        "company": company,
        "active": len(active_rows),
        "current": len(current_job_ids),
        "missing": len(missing),
        "changed": 0,
        "blocked": False,
        "missing_rate": missing_rate,
    }
    if (
        missing
        and active_rows
        and missing_rate > _MAX_DEACTIVATION_RATE
        and not allow_large_deactivation
    ):
        result["blocked"] = True
        result["reason"] = (
            f"would deactivate {missing_rate:.1%} of active rows; "
            "rerun a full scrape or pass --allow-large-deactivation"
        )
        return result

    if dry_run or not missing:
        return result

    missing_ids = [row["job_id"] for row in missing if row.get("job_id")]
    for i in range(0, len(missing_ids), _BATCH_SIZE):
        chunk = missing_ids[i:i + _BATCH_SIZE]
        sb.table("jobs").update({"is_active": False}).in_("job_id", chunk).execute()

    version_rows = []
    for row in missing:
        old_snapshot = {**row, "is_active": True}
        new_snapshot = {**row, "is_active": False}
        version_rows.append({
            "job_id": row["job_id"],
            "company_name": company,
            "batch_date": batch_date,
            "change_type": "deactivate",
            "changed_fields": ["is_active"],
            "old_snapshot": old_snapshot,
            "new_snapshot": new_snapshot,
        })
    for i in range(0, len(version_rows), _BATCH_SIZE):
        sb.table("job_versions").insert(version_rows[i:i + _BATCH_SIZE]).execute()

    result["changed"] = len(missing)
    return result


def import_file(
    sb: Client,
    json_path: Path,
    skill_id_map: dict[str, int],
    drift_counter: Counter,
    unknown_location_counter: Counter[str],
    dry_run: bool,
    run_id: str = "",
    *,
    source_only: bool = False,
    supports_forward_enrichment: bool = False,
    publish_unclassified: bool = False,
) -> dict:
    try:
        jobs = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"path": str(json_path), "error": str(e)}

    if not isinstance(jobs, list) or not jobs:
        date_str = json_path.parent.name
        return {
            "path": str(json_path),
            "company": json_path.parent.parent.parent.name,
            "date": date_str,
            "batch_date": _parse_batch_date(date_str),
            "job_ids": set(),
            "jobs": 0,
            "withheld": 0,
            "unclassified": 0,
            "duplicates": 0,
            "profile_rows": 0,
            "drift": 0,
            "enriched": 0,
            "unknown_location_rows": 0,
        }

    company    = jobs[0].get("company_name", json_path.parent.parent.parent.name)
    date_str   = json_path.parent.name
    batch_date = _parse_batch_date(date_str) or _parse_batch_date(jobs[0].get("batch_date"))
    # Scraped row count, kept before any withholding: this — not the published
    # count — is what company health and the baseline ledger mean by "raw jobs".
    source_rows = len(jobs)
    withheld = 0
    duplicates = 0
    if publish_unclassified:
        eligible_jobs = [
            job for job in jobs
            if _source_row_is_publishable(job, publish_unclassified=True)
        ]
        withheld = source_rows - len(eligible_jobs)
        # Preserve the last source occurrence, matching an upsert's terminal state.
        jobs = list({
            str(job["job_id"]): job
            for job in eligible_jobs
        }.values())
        duplicates = len(eligible_jobs) - len(jobs)
    unclassified = sum(
        1
        for job in jobs
        if not str(job.get("career_band") or "").strip()
    )
    if not jobs:
        if withheld:
            log.warning(
                "  %s: all %d rows withheld — malformed source rows",
                company,
                withheld,
            )
        return {
            "path": str(json_path),
            "company": company,
            "date": date_str,
            "batch_date": batch_date,
            "job_ids": set(),
            "jobs": 0,
            "withheld": withheld,
            "unclassified": unclassified,
            "duplicates": duplicates,
            "profile_rows": 0,
            "drift": 0,
            "enriched": 0,
            "unknown_location_rows": 0,
        }
    enriched   = 0 if source_only else sum(1 for j in jobs if j.get("main_skills"))

    local_unknown = 0
    if not dry_run:
        jobs_written, local_unknown = _upsert_jobs(
            sb,
            jobs,
            batch_date,
            unknown_location_counter,
            source_only=source_only,
            supports_forward_enrichment=supports_forward_enrichment,
        )
    else:
        jobs_written = sum(1 for j in jobs if j.get("job_id"))
        for job in jobs:
            normalized = _normalize_location(job.get("location"), job.get("locations"))
            if normalized.location_quality == "unknown":
                local_unknown += 1
                if normalized.location_raw:
                    unknown_location_counter[normalized.location_raw.lower()] += 1

    if source_only:
        profile_rows_written = 0
        drift = 0
    else:
        drift = _count_skill_drift(jobs, skill_id_map, drift_counter)
        profile_rows_written = _upsert_candidate_profiles(sb, jobs, dry_run)

    if not dry_run and run_id:
        # source_rows, not len(jobs): withholding a row is a resolver gap, not a
        # hiring-volume drop, and the baseline ledger reads this as the scrape count.
        _write_diagnostic(sb, run_id, company, source_rows, jobs_written, enriched, drift)
        _sync_baseline_ledger(company, jobs, source_rows, run_id)

    return {
        "path": str(json_path),
        "company": company,
        "date": date_str,
        "batch_date": batch_date,
        "job_ids": {j.get("job_id") for j in jobs if j.get("job_id")},
        "jobs": jobs_written,
        "withheld": withheld,
        "unclassified": unclassified,
        "duplicates": duplicates,
        "profile_rows": profile_rows_written,
        "drift": drift,
        "enriched": enriched,
        "unknown_location_rows": local_unknown,
    }


# ── Myro intel-page refresh ─────────────────────────────────────────────────--

def _refresh_analytics_snapshot() -> None:
    """Tell the Myro backend to recompute its public intel snapshot after a load.

    Fire-and-forget: never raises, so a refresh failure cannot fail the import.
    Skipped silently if either env var is absent. Sends the secret in a header
    (not the query string) so it does not leak into HTTP access / proxy logs.
    """
    backend_url = (os.getenv("MYRO_BACKEND_URL", "") or "").rstrip("/")
    secret = (os.getenv("MYRO_ANALYTICS_REFRESH_SECRET", "") or "").strip()
    if not backend_url or not secret:
        log.info("Intel refresh skipped: MYRO_BACKEND_URL / MYRO_ANALYTICS_REFRESH_SECRET not set")
        return

    endpoint = f"{backend_url}/jobs/analytics/refresh-snapshot?force=true"
    try:
        resp = requests.post(
            endpoint,
            headers={"X-Myro-Refresh-Secret": secret},
            timeout=5,
        )
        if resp.status_code in (200, 202):
            log.info("Intel refresh: backend snapshot accepted (%s)", endpoint)
        else:
            log.warning(
                "Intel refresh: backend returned %s (%s) — snapshot may be stale",
                resp.status_code,
                endpoint,
            )
    except requests.RequestException as e:
        log.warning("Intel refresh failed (%s): %s — snapshot may be stale", endpoint, e)


def _stage_a_reachable() -> str | None:
    """Return why Stage A is unreachable, or None when the backend answers.

    Config presence is not the same claim as a live backend, and both faults
    used to surface only at the end of publish.  Any HTTP status counts as
    reachable — the hand-off endpoint authenticates separately, and this probe
    must not care how the base URL routes.
    """
    backend_url = (os.getenv("MYRO_BACKEND_URL", "") or "").rstrip("/")
    try:
        requests.get(backend_url, timeout=10)
    except requests.RequestException as exc:
        return f"{backend_url} did not answer ({exc.__class__.__name__})"
    return None


def _notify_scrape_landed(run_id: str) -> None:
    """Hand a published run to Myro's durable Stage A queue or fail the publish.

    Source rows are already committed when this runs, so retrying the failed
    daily-poll publish is safe: source upserts are idempotent and the immutable
    ``run_id`` is Myro's RQ correlation key. A false success here is not safe —
    it is the exact gap that left thousands of jobs invisible to the matcher.
    """
    backend_url = (os.getenv("MYRO_BACKEND_URL", "") or "").rstrip("/")
    token = (os.getenv("SCRAPE_WEBHOOK_TOKEN", "") or "").strip()
    if not backend_url or not token:
        raise RuntimeError(
            "Stage A hand-off requires MYRO_BACKEND_URL and SCRAPE_WEBHOOK_TOKEN"
        )

    endpoint = f"{backend_url}/internal/scrape/landed"
    last_error = "no response"
    for attempt, delay_seconds in enumerate(_SCRAPE_HANDOFF_BACKOFF_SECONDS, start=1):
        if delay_seconds:
            time.sleep(delay_seconds)
        try:
            resp = requests.post(
                endpoint,
                json={"run_id": run_id},
                headers={"X-Scrape-Token": token},
                timeout=15,
            )
        except requests.RequestException as exc:
            last_error = f"{exc.__class__.__name__}: {exc}"
            log.warning(
                "Stage A hand-off attempt %s/%s failed (%s): %s",
                attempt,
                len(_SCRAPE_HANDOFF_BACKOFF_SECONDS),
                endpoint,
                last_error,
            )
            continue

        if resp.status_code == 200:
            try:
                payload = resp.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict) and payload.get("skill_floor_enqueued") is True:
                log.info("Stage A hand-off accepted: run_id=%s", run_id)
                return
            last_error = "HTTP 200 without skill_floor_enqueued=true"
            break

        last_error = f"HTTP {resp.status_code}"
        log.warning(
            "Stage A hand-off attempt %s/%s returned %s (%s)",
            attempt,
            len(_SCRAPE_HANDOFF_BACKOFF_SECONDS),
            resp.status_code,
            endpoint,
        )
        if resp.status_code != 429 and resp.status_code < 500:
            break

    raise RuntimeError(
        f"Source rows published, but Myro did not accept Stage A for run {run_id}: "
        f"{last_error}. Re-run this publish; its upserts and hand-off are idempotent."
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 3: upload source or enriched jobs to Supabase")
    parser.add_argument("--company",   help="Filter by company slug (substring, case-insensitive)")
    parser.add_argument("--all-dates", action="store_true", help="Import all date folders, not just latest")
    parser.add_argument("--dry-run",   action="store_true", help="Count only — no writes to Supabase")
    parser.add_argument(
        "--source-only",
        action="store_true",
        help=(
            "Publish only source-owned fields and let the forward-only queue handle "
            "Phase 2 enrichment later"
        ),
    )
    parser.add_argument(
        "--run-date",
        help=(
            "Scope source-only publication or decommissioning to one output date "
            "(YYYYMMDD, YYYY-MM-DD, or YYYY_MM_DD)"
        ),
    )
    parser.add_argument(
        "--publish-unclassified",
        "--resolved-only",
        dest="publish_unclassified",
        action="store_true",
        help=(
            "Publish source-valid rows even when career_band cannot be proven; "
            "persist a truthful NULL band and exclude only malformed rows. "
            "--resolved-only remains as a deprecated compatibility alias"
        ),
    )
    parser.add_argument(
        "--deactivate-missing",
        action="store_true",
        help="After a successful import, mark active jobs missing from this run inactive for imported companies only",
    )
    parser.add_argument(
        "--allow-large-deactivation",
        action="store_true",
        help="Allow a company import to deactivate more than 75%% of currently active rows",
    )
    args = parser.parse_args()

    if args.source_only and args.all_dates:
        log.error("--source-only is forward-only and cannot be combined with --all-dates")
        raise SystemExit(2)
    if args.source_only and not args.run_date:
        log.error("--source-only requires --run-date so stale output folders cannot be republished")
        raise SystemExit(2)
    if args.publish_unclassified and not args.source_only:
        log.error("--publish-unclassified requires --source-only")
        raise SystemExit(2)
    if args.publish_unclassified and args.deactivate_missing:
        log.error("--publish-unclassified cannot be combined with --deactivate-missing")
        raise SystemExit(2)
    if args.deactivate_missing and args.all_dates:
        log.error("--deactivate-missing is only safe with the latest date folder, not --all-dates")
        raise SystemExit(2)
    if args.deactivate_missing and not args.dry_run and not args.run_date:
        log.error("Real deactivation writes require --run-date YYYYMMDD/YYYY-MM-DD/YYYY_MM_DD")
        raise SystemExit(2)

    deactivation_batch_date = _parse_batch_date(args.run_date)
    if args.run_date and deactivation_batch_date is None:
        log.error("--run-date must be YYYYMMDD, YYYY-MM-DD, or YYYY_MM_DD")
        raise SystemExit(2)

    # Config validity is knowable now; discovering it after the upsert costs a
    # full re-run.  A real publish also hands the run to Stage A at the very
    # end, so that capability is asserted here rather than at its call site.
    try:
        require("supabase")
        if not args.dry_run:
            require("stage_a")
    except EnvironmentError_ as exc:
        log.error("%s", exc)
        raise SystemExit(2)
    if not args.dry_run:
        unreachable = _stage_a_reachable()
        if unreachable:
            log.error(
                "Stage A backend unreachable: %s. Publication would commit source "
                "rows and then fail to enqueue the skill floor. Start the backend "
                "or correct MYRO_BACKEND_URL, then re-run.",
                unreachable,
            )
            raise SystemExit(2)

    sb = _supabase()
    skill_id_map = {} if args.source_only else _build_skill_id_map(sb)

    json_files = _find_json_files(
        args.company,
        args.all_dates,
        batch_date=deactivation_batch_date,
    )
    if not json_files:
        log.warning("No jobs.json files found. Did you run main.py first?")
        return

    if args.source_only:
        if deactivation_batch_date is None:
            log.error("--run-date must be YYYYMMDD, YYYY-MM-DD, or YYYY_MM_DD")
            raise SystemExit(2)
        before_count = len(json_files)
        json_files = [
            path for path in json_files
            if _parse_batch_date(path.parent.name) == deactivation_batch_date
            and path.with_name("jobs.complete").exists()
        ]
        log.info(
            "Source-only publication scoped to complete run date %s: %s/%s files",
            deactivation_batch_date,
            len(json_files),
            before_count,
        )
        if not json_files:
            log.error(
                "No complete jobs.json files found for source-only run date %s",
                deactivation_batch_date,
            )
            raise SystemExit(2)
    if args.deactivate_missing:
        if args.run_date and deactivation_batch_date is None:
            log.error("--run-date must be YYYYMMDD, YYYY-MM-DD, or YYYY_MM_DD")
            raise SystemExit(2)
        available_dates = {
            parsed for parsed in (_parse_batch_date(path.parent.name) for path in json_files)
            if parsed is not None
        }
        if deactivation_batch_date is None and available_dates:
            deactivation_batch_date = max(available_dates)
        if deactivation_batch_date is None:
            log.error("--deactivate-missing requires dated output folders")
            raise SystemExit(2)
        before_count = len(json_files)
        json_files = [
            path for path in json_files
            if _parse_batch_date(path.parent.name) == deactivation_batch_date
        ]
        log.info(
            "Deactivation scoped to run date %s: %s/%s files",
            deactivation_batch_date,
            len(json_files),
            before_count,
        )
        if not json_files:
            log.error("No jobs.json files found for deactivation run date %s", deactivation_batch_date)
            raise SystemExit(2)

    log.info(f"Files to import: {len(json_files)}")
    try:
        (
            matching_jobs,
            publishable_jobs,
            duplicate_jobs,
            unclassified_jobs,
        ) = _validate_source_matching_facts(
            json_files,
            publish_unclassified=args.publish_unclassified,
        )
    except ValueError as exc:
        log.error("%s", exc)
        raise SystemExit(2) from exc
    if args.publish_unclassified:
        log.info(
            "Publication-safe preflight OK: %s unique publishable, "
            "%s truthfully unclassified, %s malformed withheld, "
            "%s duplicate source rows collapsed",
            publishable_jobs,
            unclassified_jobs,
            matching_jobs - publishable_jobs - duplicate_jobs,
            duplicate_jobs,
        )
        if publishable_jobs == 0:
            log.error("No rows have publishable source matching facts")
            raise SystemExit(2)
    else:
        log.info(
            "Source matching-fact preflight OK: %s jobs with valid career bands",
            matching_jobs,
        )
    if args.dry_run:
        log.info("DRY RUN — no writes")
    if args.source_only:
        log.info("SOURCE-ONLY — jobs publish immediately; Phase 2 runs from the durable queue")

    run_label = f"upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_id = str(uuid.uuid4())
    log.info(f"Run ID: {run_id} ({run_label})")
    _assert_location_audit_contract(run_id)

    _missing_forward_cols = _jobs_missing_forward_enrichment_columns()
    supports_forward_enrichment = not _missing_forward_cols
    if supports_forward_enrichment:
        log.info("Forward-only enrichment columns contract OK")
    elif args.source_only:
        log.warning(
            "Forward-only enrichment columns are missing: %s",
            ", ".join(_missing_forward_cols),
        )
        if not args.dry_run:
            log.error(
                "Stopping before source-only writes. Review and apply "
                "scraper/sql/create_forward_enrichment_queue.sql first."
            )
            raise SystemExit(2)

    if _jobs_has_locations_column():
        log.info("jobs.locations[] contract OK")
    else:
        log.warning(
            "jobs.locations[] column is missing; dry-run can continue, "
            "but real uploads require scraper/sql/add_jobs_locations_array.sql"
        )
        if not args.dry_run:
            log.error(
                "Stopping before writes: _upsert_jobs sends locations[] on every row, "
                "so the upsert would fail. Run scraper/sql/add_jobs_locations_array.sql "
                "in the Supabase SQL editor first."
            )
            raise SystemExit(2)

    _missing_card_cols = _jobs_missing_card_columns()
    if not _missing_card_cols:
        log.info("jobs card columns (job_summary + chips) contract OK")
    else:
        log.warning(
            "jobs is missing card columns %s; dry-run can continue, "
            "but real uploads require scraper/sql/add_jobs_summary_cols.sql",
            ", ".join(_missing_card_cols),
        )
        if not args.dry_run:
            log.error(
                "Stopping before writes: _upsert_jobs sends %s on every row, "
                "so the upsert would fail. Run scraper/sql/add_jobs_summary_cols.sql "
                "in the Supabase SQL editor first.",
                ", ".join(_missing_card_cols),
            )
            raise SystemExit(2)

    if not args.source_only:
        _missing_profile_cols = _job_candidate_profiles_missing_columns()
        _skip_profile_upload = _candidate_profile_upload_disabled()
        if not _missing_profile_cols:
            if _skip_profile_upload:
                log.warning("job_candidate_profiles upload disabled by SKIP_CANDIDATE_PROFILE_UPLOAD=1")
            else:
                log.info("job_candidate_profiles contract OK")
        else:
            log.warning(
                "job_candidate_profiles is missing columns/table %s; dry-run can continue, "
                "but real profile uploads require scraper/sql/create_job_candidate_profiles.sql",
                ", ".join(_missing_profile_cols),
            )
            if _skip_profile_upload:
                log.warning("Skipping job_candidate_profiles upload for this run")
            elif not args.dry_run:
                log.error(
                    "Stopping before writes: enriched candidate profiles would fail to upload. "
                    "Run scraper/sql/create_job_candidate_profiles.sql in Supabase first."
                )
                raise SystemExit(2)

    drift_counter: Counter = Counter()
    unknown_location_counter: Counter[str] = Counter()
    imported_company_job_ids: dict[str, set[str]] = {}
    imported_company_batch_dates: dict[str, int] = {}
    total_jobs = total_withheld = total_unclassified = total_duplicates = 0
    total_drift = total_unknown_location_rows = 0
    t0 = time.time()

    for json_path in json_files:
        result = import_file(
            sb,
            json_path,
            skill_id_map,
            drift_counter,
            unknown_location_counter,
            args.dry_run,
            run_id,
            source_only=args.source_only,
            supports_forward_enrichment=supports_forward_enrichment,
            publish_unclassified=args.publish_unclassified,
        )
        if "error" in result:
            log.warning(f"  {result['path']}: {result['error']}")
            continue

        enriched = result.get("enriched", 0)
        enriched_pct = round(enriched / result["jobs"] * 100) if result["jobs"] else 0
        log.info(
            f"  {result['company']} [{result['date']}]: "
            f"{result['jobs']} jobs, "
            f"{enriched_pct}% enriched"
            + (f", {result['withheld']} withheld" if result.get("withheld") else "")
            + (f", {result['unclassified']} unclassified" if result.get("unclassified") else "")
            + (f", {result['duplicates']} duplicates collapsed" if result.get("duplicates") else "")
            + (f", {result['drift']} drift" if result['drift'] else "")
            + (f", {result['unknown_location_rows']} unknown locations" if result.get("unknown_location_rows") else "")
        )
        total_jobs       += result["jobs"]
        total_withheld   += result.get("withheld", 0)
        total_unclassified += result.get("unclassified", 0)
        total_duplicates += result.get("duplicates", 0)
        total_drift      += result.get("drift", 0)
        total_unknown_location_rows += result.get("unknown_location_rows", 0)
        if result.get("company") and result.get("jobs"):
            company = result["company"]
            imported_company_job_ids.setdefault(company, set()).update(result.get("job_ids", set()))
            if result.get("batch_date"):
                imported_company_batch_dates[company] = result["batch_date"]

    elapsed = time.time() - t0
    unknown_rate = (total_unknown_location_rows / total_jobs) if total_jobs else 0.0
    top_unknown_aliases = [
        {"alias": alias, "count": count}
        for alias, count in unknown_location_counter.most_common(20)
    ]
    status = "blocked" if unknown_rate > _UNKNOWN_LOCATION_THRESHOLD else "ok"
    message = None
    if status == "blocked":
        message = (
            f"Unknown location rate {unknown_rate:.2%} exceeded threshold "
            f"{_UNKNOWN_LOCATION_THRESHOLD:.2%}"
        )
        log.error(message)
    if not args.dry_run:
        _write_location_audit(
            sb,
            run_id=run_id,
            total_rows=total_jobs,
            unknown_location_rows=total_unknown_location_rows,
            unknown_location_rate=unknown_rate,
            top_unknown_aliases=top_unknown_aliases,
            status=status,
            message=message,
        )

    lifecycle_summary = finalize_source_snapshot(
        sb,
        feed_run_id=run_id,
        json_files=json_files,
        skill_id_map=skill_id_map,
        eligible_companies=set(imported_company_job_ids),
        quality_status=status,
        dry_run=args.dry_run,
        # Source-only jobs have not completed Phase 2 skill extraction. Writing
        # empty company-skill facts here would falsely mark real demand dormant.
        write_skill_facts=not args.source_only,
        eligible_job_ids=imported_company_job_ids,
        company_scope=args.company,
    )
    log.info(
        "Trusted lifecycle: complete=%s partial=%s failed=%s age_delist=%s",
        lifecycle_summary["complete"],
        lifecycle_summary["partial"],
        lifecycle_summary["failed"],
        lifecycle_summary.get("age_delist"),
    )

    total_missing = total_deactivated = blocked_deactivation = 0
    if args.deactivate_missing:
        if status == "blocked":
            log.error("Skipping deactivation because the import quality gate is blocked.")
        else:
            for company, job_ids in sorted(imported_company_job_ids.items()):
                batch_date = imported_company_batch_dates.get(company) or int(datetime.now().strftime("%Y%m%d"))
                result = _deactivate_missing_jobs(
                    sb,
                    company=company,
                    current_job_ids=job_ids,
                    batch_date=batch_date,
                    dry_run=args.dry_run,
                    allow_large_deactivation=args.allow_large_deactivation,
                )
                total_missing += result["missing"]
                total_deactivated += result["changed"]
                if result["blocked"]:
                    blocked_deactivation += 1
                    log.error(
                        "  %s: deactivation blocked — %s active, %s current, %s missing (%s)",
                        company,
                        result["active"],
                        result["current"],
                        result["missing"],
                        result.get("reason"),
                    )
                elif args.dry_run:
                    log.info(
                        "  %s: would deactivate %s missing active jobs (%s active, %s current)",
                        company,
                        result["missing"],
                        result["active"],
                        result["current"],
                    )
                else:
                    log.info(
                        "  %s: deactivated %s missing active jobs (%s active, %s current)",
                        company,
                        result["changed"],
                        result["active"],
                        result["current"],
                    )

    log.info("─" * 60)
    log.info(f"Done: {total_jobs} jobs published — {elapsed:.0f}s")
    if total_withheld:
        log.warning(
            "%s malformed source rows were withheld. Unclassified but otherwise "
            "valid jobs publish with career_band=NULL; these withheld rows need "
            "their identity, seniority, or provenance repaired.",
            total_withheld,
        )
    if total_unclassified:
        log.info(
            "%s source-valid jobs published with career_band=NULL. They remain "
            "browseable but make no career-band matching claim.",
            total_unclassified,
        )
    if total_duplicates:
        log.info("%s duplicate source rows collapsed before upsert.", total_duplicates)
    log.info(
        "Location quality: %s unknown rows (%s)",
        total_unknown_location_rows,
        f"{unknown_rate:.2%}",
    )

    if drift_counter:
        log.warning(f"Taxonomy drift: {total_drift} skill strings not in `skills` table")
        log.warning("Top 20 unresolved:")
        for skill, count in drift_counter.most_common(20):
            log.warning(f"  {count:4d}×  {skill!r}")

    if args.deactivate_missing:
        action = "would deactivate" if args.dry_run else "deactivated"
        count = total_missing if args.dry_run else total_deactivated
        log.info("Decommissioning: %s %s missing jobs across imported companies", action, count)
        if blocked_deactivation:
            log.error("Decommissioning blocked for %s companies; no inactive writes were made for those companies.", blocked_deactivation)

    if status == "blocked" or blocked_deactivation:
        raise SystemExit(2)

    # Clean, real load only — tell the Myro intel page to refresh its snapshot.
    if not args.dry_run:
        _refresh_analytics_snapshot()
        # A genuine publication hands its run id to Myro. Stage A is free and
        # queues immediately; user matching remains pull-driven.
        if total_jobs > 0:
            _notify_scrape_landed(run_id)


if __name__ == "__main__":
    main()
