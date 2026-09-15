"""Read-only Supabase contract probe for the jobs feed.

The probe compares the live Supabase REST/OpenAPI schema against the local
scraper contract and writes sanitized reports under ../logs/. It never prints
or persists Supabase credentials, never fetches job_description bodies, and
never writes to Supabase.

Usage:
    cd scraper
    python3 supabase_contract_probe.py
    python3 supabase_contract_probe.py --skip-row-scan
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from environment import load_environment

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
_LOG_DIR = _ROOT / "logs"
_TABLES = (
    "jobs",
    "job_skills",
    "skills",
    "job_reports",
    "scrape_diagnostics",
    "job_feed_run_audits",
    "job_versions",
)
_JOBS_SCAN_COLUMNS = (
    "job_id",
    "job_title",
    "company_name",
    "industry",
    "industry_group",
    "role_domain",
    "location",
    "location_city",
    "location_country",
    "location_mode",
    "location_quality",
    "apply_url",
    "batch_date",
    "first_seen",
    "last_seen",
    "is_active",
    "report_count",
    "main_skills",
    "side_skills",
)
_PAGE_SIZE = 1000


def _load_env() -> tuple[str, str]:
    load_environment()
    url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_KEY") or ""
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in scraper/.env")
    return url, key


def _session(key: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({"apikey": key, "Authorization": f"Bearer {key}"})
    return session


def _get(session: requests.Session, base_url: str, path: str, **kwargs: Any) -> requests.Response:
    response = session.get(f"{base_url}{path}", timeout=30, **kwargs)
    response.raise_for_status()
    return response


def _openapi_schema(session: requests.Session, base_url: str) -> dict[str, Any]:
    response = _get(
        session,
        base_url,
        "/rest/v1/",
        headers={"Accept": "application/openapi+json"},
    )
    spec = response.json()
    return spec.get("definitions") or spec.get("components", {}).get("schemas") or {}


def _table_columns(openapi: dict[str, Any], table: str) -> dict[str, dict[str, Any]]:
    schema = openapi.get(table) or openapi.get(f"public.{table}") or {}
    required = set(schema.get("required", []) or [])
    columns: dict[str, dict[str, Any]] = {}
    for name, meta in (schema.get("properties") or {}).items():
        columns[name] = {
            "type": meta.get("format") or meta.get("type") or meta.get("$ref") or "unknown",
            "required": name in required,
            "default": meta.get("default"),
        }
    return columns


def _exact_count(session: requests.Session, base_url: str, table: str, params: dict[str, str] | None = None) -> int | None:
    query = {"select": "*"}
    if params:
        query.update(params)
    response = _get(
        session,
        base_url,
        f"/rest/v1/{table}",
        params=query,
        headers={"Prefer": "count=exact", "Range": "0-0"},
    )
    content_range = response.headers.get("content-range") or response.headers.get("Content-Range") or ""
    if "/" not in content_range:
        return None
    total = content_range.rsplit("/", 1)[1]
    return None if total == "*" else int(total)


def _paged_rows(
    session: requests.Session,
    base_url: str,
    table: str,
    *,
    select: str,
    page_size: int = _PAGE_SIZE,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        response = _get(
            session,
            base_url,
            f"/rest/v1/{table}",
            params={"select": select},
            headers={"Range": f"{start}-{start + page_size - 1}"},
        )
        batch = response.json() or []
        rows.extend(batch)
        if len(batch) < page_size:
            break
        start += page_size
    return rows


def _local_contract() -> dict[str, Any]:
    sys.path.insert(0, str(_HERE))
    from csv_importer import _JOB_FIELDS  # noqa: PLC2701 - intentional contract probe
    from schema import CANONICAL_FIELDS

    importer_source = (_HERE / "csv_importer.py").read_text(encoding="utf-8")
    importer_run_id_type = "uuid" if "uuid.uuid4()" in importer_source else "text_label"
    importer_written_fields = set(_JOB_FIELDS)
    importer_written_fields.update(
        {
            "industry_group",
            "location",
            "location_raw",
            "location_city",
            "location_country",
            "location_mode",
            "location_quality",
            "apply_url",
            "first_seen",
            "last_seen",
            "is_active",
        }
    )

    sql_columns: dict[str, dict[str, str]] = defaultdict(dict)
    for path in sorted((_HERE / "sql").glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        for table_match in re.finditer(
            r"create\s+table\s+if\s+not\s+exists\s+public\.(\w+)\s*\((.*?)\);",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            table = table_match.group(1)
            body = table_match.group(2)
            for raw_line in body.splitlines():
                line = raw_line.strip().rstrip(",")
                if not line or line.startswith("--"):
                    continue
                name_type = re.match(r"([a-zA-Z_][\w]*)\s+([a-zA-Z][\w\s\[\]]*)", line)
                if name_type and name_type.group(1).lower() not in {"constraint", "primary", "unique", "foreign", "check"}:
                    sql_columns[table][name_type.group(1)] = _compact_type(name_type.group(2))

        for alter_match in re.finditer(
            r"alter\s+table\s+public\.(\w+)\s+(.*?);",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        ):
            table = alter_match.group(1)
            body = alter_match.group(2)
            for add_match in re.finditer(
                r"add\s+column\s+if\s+not\s+exists\s+([a-zA-Z_][\w]*)\s+([a-zA-Z][\w\s\[\]]*)",
                body,
                flags=re.IGNORECASE,
            ):
                sql_columns[table][add_match.group(1)] = _compact_type(add_match.group(2))

    return {
        "canonical_fields": list(CANONICAL_FIELDS),
        "csv_importer_job_fields": list(_JOB_FIELDS),
        "csv_importer_written_fields": sorted(importer_written_fields),
        "csv_importer_run_id_type": importer_run_id_type,
        "sql_columns": {table: dict(columns) for table, columns in sql_columns.items()},
    }


def _compact_type(value: str) -> str:
    value = re.split(r"\s+(?:not|null|default|primary|references|check)\b", value.strip(), maxsplit=1, flags=re.IGNORECASE)[0]
    return re.sub(r"\s+", " ", value).lower()


def _normalize_type(value: str | None) -> str:
    if not value:
        return "unknown"
    aliases = {
        "character varying": "text",
        "timestamp with time zone": "timestamptz",
        "bigint": "bigint",
        "bigserial": "bigint",
        "int2": "integer",
        "smallint": "integer",
        "serial": "integer",
        "boolean": "boolean",
    }
    normalized = _compact_type(value)
    return aliases.get(normalized, normalized)


def _jobs_health(session: requests.Session, base_url: str) -> dict[str, Any]:
    rows = _paged_rows(session, base_url, "jobs", select=",".join(_JOBS_SCAN_COLUMNS))
    fields = list(_JOBS_SCAN_COLUMNS)
    nulls: Counter[str] = Counter()
    empties: Counter[str] = Counter()
    by_batch: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    by_company: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])

    for row in rows:
        for field in fields:
            value = row.get(field)
            if value is None:
                nulls[field] += 1
            elif value == "" or value == []:
                empties[field] += 1

        batch_key = str(row.get("batch_date") or "<null>")
        company_key = str(row.get("company_name") or "<null>")
        for bucket in (by_batch[batch_key], by_company[company_key]):
            bucket[0] += 1
            if not row.get("role_domain"):
                bucket[1] += 1
            if not row.get("location_country"):
                bucket[2] += 1
            if row.get("location_quality") == "unknown":
                bucket[3] += 1

    total = len(rows)
    completeness = {
        field: {
            "present": total - nulls[field] - empties[field],
            "missing": nulls[field] + empties[field],
            "null": nulls[field],
            "empty": empties[field],
        }
        for field in fields
    }

    description_null = _exact_count(session, base_url, "jobs", {"job_description": "is.null"})
    description_empty = _exact_count(session, base_url, "jobs", {"job_description": "eq."})
    apply_url_null = _exact_count(session, base_url, "jobs", {"apply_url": "is.null"})
    active_false = _exact_count(session, base_url, "jobs", {"is_active": "eq.false"})

    return {
        "rows_scanned": total,
        "field_completeness": completeness,
        "job_description_null": description_null,
        "job_description_empty": description_empty,
        "apply_url_null": apply_url_null,
        "active_false": active_false,
        "top_companies": Counter(str(r.get("company_name") or "<null>") for r in rows).most_common(20),
        "batch_dates": Counter(str(r.get("batch_date") or "<null>") for r in rows).most_common(20),
        "location_quality": dict(Counter(str(r.get("location_quality") or "<null>") for r in rows)),
        "location_mode": dict(Counter(str(r.get("location_mode") or "<null>") for r in rows)),
        "location_country": Counter(str(r.get("location_country") or "<null>") for r in rows).most_common(20),
        "role_domain": Counter(str(r.get("role_domain") or "<null>") for r in rows).most_common(20),
        "industry_group": Counter(str(r.get("industry_group") or "<null>") for r in rows).most_common(20),
        "batch_gaps": {k: v for k, v in sorted(by_batch.items(), reverse=True)},
        "company_gaps_top": dict(sorted(by_company.items(), key=lambda item: item[1][1], reverse=True)[:20]),
    }


def _job_skills_health(session: requests.Session, base_url: str) -> dict[str, Any]:
    rows = _paged_rows(session, base_url, "job_skills", select="job_id,is_primary")
    distinct_jobs = Counter(row["job_id"] for row in rows if row.get("job_id"))
    primary_jobs = {row["job_id"] for row in rows if row.get("job_id") and row.get("is_primary") is True}
    return {
        "rows_scanned": len(rows),
        "distinct_job_ids": len(distinct_jobs),
        "jobs_with_primary_skill": len(primary_jobs),
        "avg_skills_per_job": round(len(rows) / len(distinct_jobs), 2) if distinct_jobs else 0,
        "top_skills_per_job": distinct_jobs.most_common(10),
    }


def _drift(live: dict[str, Any], local: dict[str, Any]) -> dict[str, Any]:
    jobs_columns = set(live["tables"].get("jobs", {}).get("columns", {}))
    canonical = set(local["canonical_fields"])
    importer = set(local["csv_importer_job_fields"])
    importer_written = set(local["csv_importer_written_fields"])
    sql_columns = local["sql_columns"]

    sql_type_drift: list[dict[str, str]] = []
    missing_sql_columns: list[dict[str, str]] = []
    for table, columns in sql_columns.items():
        live_columns = live["tables"].get(table, {}).get("columns", {})
        for name, expected_type in columns.items():
            live_meta = live_columns.get(name)
            if not live_meta:
                missing_sql_columns.append({"table": table, "column": name, "expected_type": expected_type})
                continue
            live_type = _normalize_type(live_meta.get("type"))
            expected = _normalize_type(expected_type)
            if expected != live_type:
                sql_type_drift.append({
                    "table": table,
                    "column": name,
                    "expected_type": expected,
                    "live_type": live_type,
                })

    audit_run_id = live["tables"].get("job_feed_run_audits", {}).get("columns", {}).get("run_id", {})
    hard_warnings: list[str] = []
    if _normalize_type(audit_run_id.get("type")) == "uuid" and local.get("csv_importer_run_id_type") != "uuid":
        hard_warnings.append(
            "job_feed_run_audits.run_id is uuid but csv_importer writes upload_YYYYMMDD_HHMMSS strings"
        )

    return {
        "jobs_missing_canonical_fields": sorted(canonical - jobs_columns),
        "jobs_extra_live_columns": sorted(jobs_columns - canonical),
        "csv_importer_fields_not_in_live_jobs": sorted(importer - jobs_columns),
        "live_jobs_columns_not_written_by_importer": sorted(jobs_columns - importer_written),
        "sql_missing_live_columns": missing_sql_columns,
        "sql_type_drift": sql_type_drift,
        "hard_warnings": hard_warnings,
    }


def _write_reports(report: dict[str, Any]) -> tuple[Path, Path]:
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = _LOG_DIR / f"supabase_contract_probe_{stamp}.json"
    md_path = _LOG_DIR / f"supabase_contract_probe_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, md_path


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Supabase Contract Probe",
        "",
        f"- Generated: `{report['generated_at']}`",
        f"- Supabase host: `{report['supabase_host']}`",
        f"- Row scan: `{'yes' if report['row_scan_enabled'] else 'no'}`",
        "",
        "## Tables",
        "",
        "| Table | Rows | Columns |",
        "|---|---:|---:|",
    ]
    for table, data in report["tables"].items():
        lines.append(f"| `{table}` | {data.get('row_count')} | {len(data.get('columns', {}))} |")

    drift = report["drift"]
    lines.extend([
        "",
        "## Drift",
        "",
    ])
    if drift["hard_warnings"]:
        lines.append("### Hard Warnings")
        lines.append("")
        for warning in drift["hard_warnings"]:
            lines.append(f"- {warning}")
        lines.append("")

    lines.extend([
        f"- Jobs missing canonical fields: `{', '.join(drift['jobs_missing_canonical_fields']) or 'none'}`",
        f"- Importer fields not in live jobs: `{', '.join(drift['csv_importer_fields_not_in_live_jobs']) or 'none'}`",
        f"- SQL missing live columns: `{len(drift['sql_missing_live_columns'])}`",
        f"- SQL type drift: `{len(drift['sql_type_drift'])}`",
    ])
    if drift["sql_type_drift"]:
        lines.extend(["", "| Table | Column | Expected | Live |", "|---|---|---|---|"])
        for item in drift["sql_type_drift"]:
            lines.append(
                f"| `{item['table']}` | `{item['column']}` | `{item['expected_type']}` | `{item['live_type']}` |"
            )

    jobs_health = report.get("jobs_health")
    if jobs_health:
        lines.extend([
            "",
            "## Jobs Health",
            "",
            f"- Rows scanned: `{jobs_health['rows_scanned']}`",
            f"- Empty job descriptions: `{jobs_health['job_description_empty']}`",
            f"- Null job descriptions: `{jobs_health['job_description_null']}`",
            f"- Null apply URLs: `{jobs_health['apply_url_null']}`",
            f"- Inactive rows: `{jobs_health['active_false']}`",
            "",
            "| Field | Present | Missing | Null | Empty |",
            "|---|---:|---:|---:|---:|",
        ])
        for field, stats in jobs_health["field_completeness"].items():
            lines.append(
                f"| `{field}` | {stats['present']} | {stats['missing']} | {stats['null']} | {stats['empty']} |"
            )
        lines.extend([
            "",
            "### Batch Gaps",
            "",
            "| Batch | Rows | No role_domain | No location_country | Unknown location |",
            "|---|---:|---:|---:|---:|",
        ])
        for batch, values in list(jobs_health["batch_gaps"].items())[:20]:
            total, no_role, no_country, unknown_location = values
            lines.append(f"| `{batch}` | {total} | {no_role} | {no_country} | {unknown_location} |")

    skills_health = report.get("job_skills_health")
    if skills_health:
        lines.extend([
            "",
            "## Job Skills Health",
            "",
            f"- Rows scanned: `{skills_health['rows_scanned']}`",
            f"- Distinct jobs with skills: `{skills_health['distinct_job_ids']}`",
            f"- Jobs with primary skill: `{skills_health['jobs_with_primary_skill']}`",
            f"- Avg skills per covered job: `{skills_health['avg_skills_per_job']}`",
        ])

    lines.append("")
    return "\n".join(lines)


def build_report(skip_row_scan: bool = False) -> dict[str, Any]:
    base_url, key = _load_env()
    session = _session(key)
    openapi = _openapi_schema(session, base_url)

    live: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "supabase_host": urlparse(base_url).netloc,
        "row_scan_enabled": not skip_row_scan,
        "tables": {},
    }
    for table in _TABLES:
        live["tables"][table] = {
            "row_count": _exact_count(session, base_url, table),
            "columns": _table_columns(openapi, table),
        }

    local = _local_contract()
    live["local_contract"] = local
    live["drift"] = _drift(live, local)
    if not skip_row_scan:
        live["jobs_health"] = _jobs_health(session, base_url)
        live["job_skills_health"] = _job_skills_health(session, base_url)
    return live


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only Supabase jobs contract probe")
    parser.add_argument("--skip-row-scan", action="store_true", help="Only inspect OpenAPI schema and exact counts")
    args = parser.parse_args()

    report = build_report(skip_row_scan=args.skip_row_scan)
    json_path, md_path = _write_reports(report)
    print(f"Supabase contract probe written:")
    print(f"  JSON: {json_path}")
    print(f"  MD:   {md_path}")
    warnings = report["drift"].get("hard_warnings") or []
    if warnings:
        print("Hard warnings:")
        for warning in warnings:
            print(f"  - {warning}")


if __name__ == "__main__":
    main()
