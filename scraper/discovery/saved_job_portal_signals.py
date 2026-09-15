#!/usr/bin/env python3
"""Reconcile extension-saved jobs with the active scraper portal registry.

This command is deliberately read-only:

* reads durable ``job_applications`` and extension-created ``jobs`` rows;
* compares their company/ATS evidence with ``KNOWN_PORTALS.md`` via
  ``portal_reader.parse_portals()``;
* validates missing token-based ATS boards through the existing free probes;
* reports extension jobs whose native ATS ID already has a canonical scraper row;
* writes reviewable JSON/Markdown reports under ``logs/``.

It never changes Supabase and never edits ``KNOWN_PORTALS.md``. Promotion and
canonical saved-job relinking remain explicit, reviewed follow-up actions.

Run from ``scraper/``:

    python discovery/saved_job_portal_signals.py
    python discovery/saved_job_portal_signals.py --no-probe
    python discovery/saved_job_portal_signals.py --output-dir ../logs
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.parse import unquote, urlparse

import requests
from supabase import Client, create_client


HERE = Path(__file__).resolve().parent
SCRAPER_DIR = HERE.parent
REPO_ROOT = SCRAPER_DIR.parent
sys.path.insert(0, str(SCRAPER_DIR))

from discovery.ats_probes import PROBES, name_matches  # noqa: E402
from portal_reader import parse_portals  # noqa: E402


from environment import load_environment

load_environment()

PAGE_SIZE = 500
IN_BATCH_SIZE = 100
SUPPORTED_DISCOVERY_ATS = frozenset(PROBES)
GENERIC_SOURCE_HOSTS = frozenset(
    {
        "gmail.com",
        "mail.google.com",
        "outlook.live.com",
        "outlook.office.com",
    }
)
SHARED_ATS_HOSTS = frozenset(
    {
        "api.ashbyhq.com",
        "api.lever.co",
        "api.smartrecruiters.com",
        "boards-api.greenhouse.io",
        "boards.greenhouse.io",
        "careers.smartrecruiters.com",
        "job-boards.greenhouse.io",
        "jobs.ashbyhq.com",
        "jobs.lever.co",
        "jobs.smartrecruiters.com",
    }
)
COMPANY_SUFFIX_WORDS = frozenset(
    {
        "careers",
        "co",
        "company",
        "corp",
        "corporation",
        "group",
        "holdings",
        "inc",
        "incorporated",
        "jobs",
        "limited",
        "llc",
        "llp",
        "ltd",
        "plc",
        "private",
        "pvt",
        "the",
    }
)
SUSPICIOUS_COMPANY_PHRASES = (
    " by the client",
    "role in ",
    "visa sponsorship",
    "work from home",
)


@dataclass(frozen=True)
class AtsIdentity:
    ats: str
    token: str
    native_job_id: str
    evidence_host: str


@dataclass(frozen=True)
class SavedExtensionJob:
    extension_job_id: str
    company_name: str
    source_platform: str
    apply_url: str
    source_url: str
    saved_count: int
    latest_saved_at: str


@dataclass(frozen=True)
class CoverageMatch:
    company: str
    ats: str
    endpoint: str
    match_type: str


@dataclass
class SignalAssessment:
    extension_job_id: str
    company_name: str
    normalized_company: str
    source_platform: str
    evidence_host: str
    ats: str
    ats_token: str
    native_job_id: str
    saved_count: int
    latest_saved_at: str
    status: str
    reason: str
    covered_company: str = ""
    covered_ats: str = ""
    coverage_match_type: str = ""
    canonical_job_id: str = ""
    probe_total_jobs: int | None = None
    probe_india_jobs: int | None = None
    probe_board_name: str = ""
    probe_endpoint: str = ""


@dataclass
class PortalIndex:
    by_company: dict[str, list[dict[str, Any]]]
    by_host: dict[str, list[dict[str, Any]]]
    by_ats_token: dict[tuple[str, str], list[dict[str, Any]]]


ProbeFn = Callable[[requests.Session, str], dict[str, Any] | None]


def chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def fetch_all(query: Any) -> list[dict[str, Any]]:
    """Fetch a PostgREST query without silently stopping at the 1,000-row cap."""
    rows: list[dict[str, Any]] = []
    page = 0
    while True:
        response = query.range(page * PAGE_SIZE, (page + 1) * PAGE_SIZE - 1).execute()
        batch = response.data or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE:
            return rows
        page += 1


def supabase_client() -> Client:
    url = (os.getenv("SUPABASE_URL") or "").strip()
    key = (os.getenv("SUPABASE_SERVICE_KEY") or "").strip()
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_KEY are required in scraper/.env")
    return create_client(url, key)


def normalize_company(value: str) -> str:
    words = re.findall(r"[a-z0-9]+", (value or "").lower())
    while words and words[-1] in COMPANY_SUFFIX_WORDS:
        words.pop()
    return "".join(words)


def normalize_host(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _path_parts(url: str) -> tuple[str, list[str]]:
    try:
        parsed = urlparse(url)
    except ValueError:
        return "", []
    host = (parsed.hostname or "").lower().rstrip(".")
    parts = [unquote(part).strip() for part in parsed.path.split("/") if part.strip()]
    return host, parts


def _after(parts: list[str], marker: str) -> str:
    lowered = [part.lower() for part in parts]
    try:
        index = lowered.index(marker.lower())
    except ValueError:
        return ""
    return parts[index + 1] if index + 1 < len(parts) else ""


def extract_ats_identity(
    source_platform: str,
    apply_url: str,
    source_url: str,
) -> AtsIdentity | None:
    """Extract a public-board token and native job ID from captured URLs."""
    platform = (source_platform or "").strip().lower()
    for url in (apply_url, source_url):
        host, parts = _path_parts(url)
        if not host or not parts:
            continue

        if "greenhouse" in platform or host.endswith("greenhouse.io"):
            token = ""
            native_id = ""
            if host.startswith(("job-boards.", "boards.")):
                token = parts[0]
                native_id = _after(parts, "jobs")
            elif host.startswith("boards-api."):
                token = _after(parts, "boards")
            if token:
                return AtsIdentity("greenhouse", token.lower(), native_id, host)

        if "ashby" in platform or host.endswith("ashbyhq.com"):
            token = ""
            native_id = ""
            if host.startswith("jobs."):
                token = parts[0]
                native_id = parts[1] if len(parts) > 1 else ""
            elif host.startswith("api."):
                token = _after(parts, "job-board")
            if token:
                return AtsIdentity("ashby", token.lower(), native_id, host)

        if "lever" in platform or host.endswith("lever.co"):
            token = ""
            native_id = ""
            if host.startswith("jobs."):
                token = parts[0]
                native_id = parts[1] if len(parts) > 1 else ""
            elif host.startswith("api."):
                token = _after(parts, "postings")
            if token:
                return AtsIdentity("lever", token.lower(), native_id, host)

        if "smartrecruiters" in platform or host.endswith("smartrecruiters.com"):
            token = ""
            native_id = ""
            if host.startswith(("jobs.", "careers.")):
                token = parts[0]
                native_id = parts[1] if len(parts) > 1 else ""
            elif host.startswith("api."):
                token = _after(parts, "companies")
            if token:
                return AtsIdentity("smartrecruiters", token.lower(), native_id, host)
    return None


def _portal_token(portal: dict[str, Any]) -> str:
    token = str(portal.get("board_token") or portal.get("lever_slug") or "").strip()
    if token:
        return token.lower()
    identity = extract_ats_identity(
        str(portal.get("ats") or ""),
        str(portal.get("endpoint") or ""),
        str(portal.get("careers_url") or ""),
    )
    return identity.token if identity else ""


def build_portal_index(portals: list[dict[str, Any]]) -> PortalIndex:
    by_company: dict[str, list[dict[str, Any]]] = {}
    by_host: dict[str, list[dict[str, Any]]] = {}
    by_ats_token: dict[tuple[str, str], list[dict[str, Any]]] = {}

    for portal in portals:
        company_key = normalize_company(str(portal.get("company") or ""))
        if company_key:
            by_company.setdefault(company_key, []).append(portal)

        for url_key in ("endpoint", "careers_url"):
            host = normalize_host(str(portal.get(url_key) or ""))
            if host:
                by_host.setdefault(host, []).append(portal)

        ats = str(portal.get("ats") or "").lower()
        token = _portal_token(portal)
        if ats and token:
            by_ats_token.setdefault((ats, token), []).append(portal)

    return PortalIndex(
        by_company=by_company,
        by_host=by_host,
        by_ats_token=by_ats_token,
    )


def find_coverage(
    signal: SavedExtensionJob,
    identity: AtsIdentity | None,
    portal_index: PortalIndex,
) -> CoverageMatch | None:
    matches: list[dict[str, Any]] = []
    match_type = ""

    if identity:
        matches = portal_index.by_ats_token.get((identity.ats, identity.token), [])
        if matches:
            match_type = "ats_token"

    if not matches:
        for url in (signal.apply_url, signal.source_url):
            host = normalize_host(url)
            if host and host not in GENERIC_SOURCE_HOSTS and host not in SHARED_ATS_HOSTS:
                matches = portal_index.by_host.get(host, [])
                if matches:
                    match_type = "source_host"
                    break

    if not matches:
        matches = portal_index.by_company.get(normalize_company(signal.company_name), [])
        if matches:
            match_type = "company_name"

    if not matches:
        return None
    portal = matches[0]
    return CoverageMatch(
        company=str(portal.get("company") or ""),
        ats=str(portal.get("ats") or ""),
        endpoint=str(portal.get("endpoint") or ""),
        match_type=match_type,
    )


def is_invalid_capture(signal: SavedExtensionJob) -> tuple[bool, str]:
    company = (signal.company_name or "").strip()
    if not normalize_company(company):
        return True, "company name is empty or contains no usable identity"
    company_lower = company.lower()
    evidence_hosts = {
        host for host in (normalize_host(signal.apply_url), normalize_host(signal.source_url)) if host
    }
    if evidence_hosts and evidence_hosts.issubset(GENERIC_SOURCE_HOSTS):
        return True, "capture came only from a personal email host"
    if len(company) > 100 or any(phrase in company_lower for phrase in SUSPICIOUS_COMPANY_PHRASES):
        return True, "captured company value looks like job/email prose"
    return False, ""


def _identity_matches_company(company: str, identity: AtsIdentity, board_name: str) -> bool:
    if board_name and name_matches(company, board_name):
        return True
    company_key = normalize_company(company)
    token_key = normalize_company(identity.token)
    return bool(company_key and token_key and (company_key == token_key or token_key in company_key))


def assess_signals(
    signals: list[SavedExtensionJob],
    portal_index: PortalIndex,
    *,
    probe: bool = True,
    probe_functions: dict[str, ProbeFn] | None = None,
    canonical_job_ids: set[str] | None = None,
) -> list[SignalAssessment]:
    probe_functions = probe_functions or PROBES
    canonical_job_ids = canonical_job_ids or set()
    probe_cache: dict[tuple[str, str], dict[str, Any] | None] = {}
    assessments: list[SignalAssessment] = []

    with requests.Session() as session:
        for signal in signals:
            identity = extract_ats_identity(
                signal.source_platform,
                signal.apply_url,
                signal.source_url,
            )
            evidence_host = (
                identity.evidence_host
                if identity
                else normalize_host(signal.apply_url) or normalize_host(signal.source_url)
            )
            coverage = find_coverage(signal, identity, portal_index)
            invalid, invalid_reason = is_invalid_capture(signal)

            assessment = SignalAssessment(
                extension_job_id=signal.extension_job_id,
                company_name=signal.company_name,
                normalized_company=normalize_company(signal.company_name),
                source_platform=signal.source_platform,
                evidence_host=evidence_host,
                ats=identity.ats if identity else "",
                ats_token=identity.token if identity else "",
                native_job_id=identity.native_job_id if identity else "",
                saved_count=signal.saved_count,
                latest_saved_at=signal.latest_saved_at,
                status="needs_investigation",
                reason="no supported direct ATS identity was captured",
            )

            if identity and identity.native_job_id in canonical_job_ids:
                assessment.canonical_job_id = identity.native_job_id

            if coverage:
                assessment.status = "already_tracked"
                assessment.reason = (
                    f"active portal matched by {coverage.match_type}"
                    + (
                        "; native ATS job already has a canonical scraper row"
                        if assessment.canonical_job_id
                        else ""
                    )
                )
                assessment.covered_company = coverage.company
                assessment.covered_ats = coverage.ats
                assessment.coverage_match_type = coverage.match_type
                assessments.append(assessment)
                continue

            if invalid:
                assessment.status = "invalid_capture"
                assessment.reason = invalid_reason
                assessments.append(assessment)
                continue

            if not identity or identity.ats not in SUPPORTED_DISCOVERY_ATS:
                assessments.append(assessment)
                continue

            if not probe:
                assessment.reason = "supported ATS identity found; live validation was disabled"
                assessments.append(assessment)
                continue

            cache_key = (identity.ats, identity.token)
            if cache_key not in probe_cache:
                probe_fn = probe_functions.get(identity.ats)
                probe_cache[cache_key] = probe_fn(session, identity.token) if probe_fn else None
            hit = probe_cache[cache_key]
            if not hit:
                assessment.reason = "captured ATS board did not return a live public listing payload"
                assessments.append(assessment)
                continue

            assessment.probe_total_jobs = int(hit.get("total") or 0)
            assessment.probe_india_jobs = int(hit.get("india") or 0)
            assessment.probe_board_name = str(hit.get("board_name") or "")
            assessment.probe_endpoint = str(hit.get("endpoint") or "")

            if not _identity_matches_company(
                signal.company_name,
                identity,
                assessment.probe_board_name,
            ):
                assessment.reason = "live board identity does not safely match the captured company"
            elif assessment.probe_india_jobs <= 0:
                assessment.reason = "live board has no detected India jobs"
            else:
                assessment.status = "ready_to_promote"
                assessment.reason = (
                    "direct public ATS board validated with "
                    f"{assessment.probe_india_jobs} India jobs"
                )
            assessments.append(assessment)

    return assessments


def fetch_saved_extension_jobs(
    sb: Client,
    *,
    application_status: str = "saved",
) -> list[SavedExtensionJob]:
    applications = fetch_all(
        sb.table("job_applications")
        .select("job_id,created_at")
        .eq("status", application_status)
        .order("job_id")
    )
    saved_by_job: dict[str, list[str]] = {}
    for row in applications:
        job_id = str(row.get("job_id") or "")
        if job_id:
            saved_by_job.setdefault(job_id, []).append(str(row.get("created_at") or ""))

    if not saved_by_job:
        return []

    job_rows: list[dict[str, Any]] = []
    for batch in chunks(sorted(saved_by_job), IN_BATCH_SIZE):
        job_rows.extend(
            fetch_all(
                sb.table("jobs")
                .select(
                    "job_id,company_name,source_platform,apply_url,source_url,"
                    "ingestion_source"
                )
                .in_("job_id", batch)
                .eq("ingestion_source", "extension")
                .order("job_id")
            )
        )

    signals: list[SavedExtensionJob] = []
    for row in job_rows:
        job_id = str(row.get("job_id") or "")
        saved_dates = saved_by_job.get(job_id, [])
        signals.append(
            SavedExtensionJob(
                extension_job_id=job_id,
                company_name=str(row.get("company_name") or "").strip(),
                source_platform=str(row.get("source_platform") or "").strip(),
                apply_url=str(row.get("apply_url") or "").strip(),
                source_url=str(row.get("source_url") or "").strip(),
                saved_count=len(saved_dates),
                latest_saved_at=max(saved_dates, default=""),
            )
        )
    return sorted(signals, key=lambda signal: (signal.company_name.lower(), signal.extension_job_id))


def canonical_row_matches_signal(
    row: dict[str, Any],
    signal: SavedExtensionJob,
) -> bool:
    """Guard duplicate reporting against cross-company native-ID collisions."""
    if normalize_company(str(row.get("company_name") or "")) == normalize_company(
        signal.company_name
    ):
        return True

    signal_identity = extract_ats_identity(
        signal.source_platform,
        signal.apply_url,
        signal.source_url,
    )
    row_identity = extract_ats_identity(
        str(row.get("source_platform") or ""),
        str(row.get("apply_url") or ""),
        str(row.get("source_url") or ""),
    )
    return bool(
        signal_identity
        and row_identity
        and signal_identity.ats == row_identity.ats
        and signal_identity.token == row_identity.token
    )


def fetch_canonical_job_ids(sb: Client, signals: list[SavedExtensionJob]) -> set[str]:
    signals_by_native_id: dict[str, list[SavedExtensionJob]] = {}
    for signal in signals:
        identity = extract_ats_identity(
            signal.source_platform,
            signal.apply_url,
            signal.source_url,
        )
        if (
            identity
            and identity.native_job_id
            and identity.native_job_id != signal.extension_job_id
        ):
            signals_by_native_id.setdefault(identity.native_job_id, []).append(signal)

    native_ids = sorted(signals_by_native_id)
    if not native_ids:
        return set()

    canonical_ids: set[str] = set()
    for batch in chunks(native_ids, IN_BATCH_SIZE):
        rows = fetch_all(
            sb.table("jobs")
            .select(
                "job_id,company_name,source_platform,apply_url,source_url,"
                "ingestion_source"
            )
            .in_("job_id", batch)
            .order("job_id")
        )
        for row in rows:
            job_id = str(row.get("job_id") or "")
            if str(row.get("ingestion_source") or "") == "extension":
                continue
            if any(
                canonical_row_matches_signal(row, signal)
                for signal in signals_by_native_id.get(job_id, [])
            ):
                canonical_ids.add(job_id)
    return canonical_ids


def _proposal_row(assessment: SignalAssessment) -> str:
    date = datetime.now(UTC).strftime("%Y-%m-%d")
    india = assessment.probe_india_jobs or 0
    token = assessment.ats_token
    status = (
        f"⚠️ PROPOSED {date} from saved-job signal — direct "
        f"{assessment.ats.title()} API validated; {india} India jobs; "
        "review identity then change status to ✅ VALIDATED"
    )
    company = _markdown_cell(assessment.company_name)
    if assessment.ats == "greenhouse":
        return f"| {company} | https://job-boards.greenhouse.io/{token} | {token} | {india} | {status} |"
    if assessment.ats == "lever":
        return f"| {company} | https://jobs.lever.co/{token} | {token} | {india} | {status} |"
    if assessment.ats == "ashby":
        return f"| {company} | https://jobs.ashbyhq.com/{token} | {token} | {india} | {status} |"
    if assessment.ats == "smartrecruiters":
        return f"| {company} | https://careers.smartrecruiters.com/{token} | {token} | {india} | {status} |"
    return ""


def _markdown_cell(value: Any) -> str:
    return str(value or "").replace("\r", " ").replace("\n", " ").replace("|", r"\|")


def build_report(assessments: list[SignalAssessment]) -> dict[str, Any]:
    status_counts = Counter(assessment.status for assessment in assessments)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "read_only",
        "summary": {
            "extension_saved_jobs": len(assessments),
            "saved_interactions": sum(item.saved_count for item in assessments),
            "canonical_duplicates": sum(bool(item.canonical_job_id) for item in assessments),
            "status_counts": dict(sorted(status_counts.items())),
        },
        "assessments": [asdict(assessment) for assessment in assessments],
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Saved-job portal reconciliation",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "> Read-only report. No Supabase rows or `KNOWN_PORTALS.md` entries were changed.",
        "",
        "## Summary",
        "",
        f"- Extension-saved jobs: **{summary['extension_saved_jobs']}**",
        f"- Saved interactions: **{summary['saved_interactions']}**",
        f"- Canonical scraper duplicates found: **{summary['canonical_duplicates']}**",
    ]
    for status, count in summary["status_counts"].items():
        lines.append(f"- `{status}`: **{count}**")

    lines.extend(
        [
            "",
            "## Reconciliation results",
            "",
            "| Status | Company | ATS evidence | Host/token | Saved | Canonical job | Reason |",
            "|---|---|---|---|---:|---|---|",
        ]
    )
    for row in report["assessments"]:
        ats = row["ats"] or row["source_platform"] or "unknown"
        host_token = row["ats_token"] or row["evidence_host"] or "unknown"
        lines.append(
            f"| {_markdown_cell(row['status'])} | {_markdown_cell(row['company_name'])} | "
            f"{_markdown_cell(ats)} | `{_markdown_cell(host_token)}` | "
            f"{row['saved_count']} | `{_markdown_cell(row['canonical_job_id'] or '—')}` | "
            f"{_markdown_cell(row['reason'])} |"
        )

    ready = [
        SignalAssessment(**row)
        for row in report["assessments"]
        if row["status"] == "ready_to_promote"
    ]
    lines.extend(
        [
            "",
            "## Proposed registry rows",
            "",
            "These rows are evidence only and were **not** applied. Review the company/board "
            "identity, add the industry mapping if needed, then change the status to "
            "`✅ VALIDATED` when promoting.",
            "",
        ]
    )
    if not ready:
        lines.append("_No validated missing portal candidates._")
    else:
        for assessment in ready:
            lines.append(f"### {assessment.company_name} ({assessment.ats})")
            lines.extend(["", "```text", _proposal_row(assessment), "```", ""])

    duplicates = [
        row for row in report["assessments"] if row.get("canonical_job_id")
    ]
    lines.extend(
        [
            "",
            "## Canonical relink candidates",
            "",
            "These are report-only. Relinking must atomically preserve saved/application "
            "state and handle the `(user_id, job_id)` uniqueness constraint.",
            "",
        ]
    )
    if not duplicates:
        lines.append("_No extension/native duplicate pairs detected._")
    else:
        lines.extend(
            [
                "| Company | Extension job | Canonical job |",
                "|---|---|---|",
            ]
        )
        for row in duplicates:
            lines.append(
                f"| {_markdown_cell(row['company_name'])} | "
                f"`{_markdown_cell(row['extension_job_id'])}` | "
                f"`{_markdown_cell(row['canonical_job_id'])}` |"
            )

    return "\n".join(lines).rstrip() + "\n"


def write_reports(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"saved_job_portal_signals_{stamp}.json"
    md_path = output_dir / f"saved_job_portal_signals_{stamp}.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only reconciliation of extension-saved jobs and active scraper portals."
    )
    parser.add_argument(
        "--application-status",
        default="saved",
        help="job_applications status to inspect (default: saved)",
    )
    parser.add_argument(
        "--no-probe",
        action="store_true",
        help="do not call public ATS APIs; missing supported boards stay needs_investigation",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "logs",
        help="report directory (default: repository logs/, which is git-ignored)",
    )
    args = parser.parse_args()

    sb = supabase_client()
    signals = fetch_saved_extension_jobs(sb, application_status=args.application_status)
    canonical_ids = fetch_canonical_job_ids(sb, signals)
    portal_index = build_portal_index(parse_portals())
    assessments = assess_signals(
        signals,
        portal_index,
        probe=not args.no_probe,
        canonical_job_ids=canonical_ids,
    )
    report = build_report(assessments)
    json_path, md_path = write_reports(report, args.output_dir)

    summary = report["summary"]
    print(
        "saved_job_portal_signals: "
        f"jobs={summary['extension_saved_jobs']} "
        f"canonical_duplicates={summary['canonical_duplicates']} "
        f"statuses={summary['status_counts']}"
    )
    print(f"  json: {json_path}")
    print(f"  markdown: {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
