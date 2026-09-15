from __future__ import annotations

"""Build a route and hiring inventory from KNOWN_PORTALS.md.

Default mode is metadata-only. Probe mode samples providers without enrichment.
Firecrawl/JS routes are skipped unless --include-js is passed intentionally.
"""

import argparse
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from config import PORTALS_PATH
from portal_reader import parse_portals
from providers.base import ScrapeReason
from providers.registry import probe_scrape

_LOG = logging.getLogger("mirror.inventory")


ROUTE_ORDER = (
    "cracked",
    "js_required",
    "active_watch",
    "broken",
    "blocked",
    "excluded",
    "deprioritized",
    "unknown",
)


@dataclass(frozen=True)
class InventorySelection:
    company_names: list[str]
    source_index_by_company: dict[str, int]


def classify_route_state(status: str, js_required: bool = False) -> str:
    """Convert free-form KNOWN_PORTALS status text into a stable bucket."""
    s = status or ""
    lower = s.lower()
    if "✅" in s or "cracked" in lower or "working" in lower:
        return "cracked"
    if "⬇" in s or "deprioritized" in lower or "deprioritised" in lower:
        return "deprioritized"
    if "🔴" in s or "no india" in lower or "skip" in lower or "excluded" in lower:
        return "excluded"
    if "⚠" in s or "broken" in lower or "404" in lower:
        return "broken"
    if "blocked" in lower or "antibot" in lower or "login" in lower:
        return "blocked"
    if "🟡" in s or js_required:
        return "js_required" if js_required else "active_watch"
    return "unknown"


def _status_note(status: str) -> str:
    note = (status or "").strip()
    return note[:240] + ("..." if len(note) > 240 else "")


def _sample_title(job: dict[str, Any]) -> str:
    return str(job.get("title") or job.get("job_title") or "").strip()


def _job_url(job: dict[str, Any]) -> str:
    return str(job.get("job_url") or job.get("apply_url") or "").strip()


def looks_like_navigation_job(job: dict[str, Any]) -> bool:
    """Detect obvious page chrome that Firecrawl can mistake for a job card."""
    title = _sample_title(job).casefold()
    url = _job_url(job).casefold()
    return title in {"skip to content", "skip to main content"} or "#skiptocontent" in url


def classify_probe_state(jobs: list[dict[str, Any]], reason: str | ScrapeReason) -> str:
    if jobs:
        return "hiring"
    reason_value = reason.value if isinstance(reason, ScrapeReason) else str(reason)
    if reason_value in {ScrapeReason.SUCCESS.value, ScrapeReason.NO_JOBS.value}:
        return "no_open_jobs"
    if reason_value in {ScrapeReason.API_BLOCKED.value, ScrapeReason.TIMEOUT.value}:
        return "blocked"
    return reason_value


_WEAK_TITLES = {
    "apply now",
    "career listings",
    "development",
    "discover more",
    "experience team candidates",
    "explore jobs",
    "filter by",
    "job openings",
    "more details",
    "more filters +",
    "see details",
    "us verification",
    "view role",
}

_INDIA_LOCATION_WORD_RE = re.compile(
    r"\b(india|bengaluru|bangalore|hyderabad|mumbai|pune|chennai|delhi|gurugram|gurgaon|noida|kolkata)\b",
    re.IGNORECASE,
)
_US_STATE_IN_TITLE_RE = re.compile(r"\b(?:FT|PT)?\s*IN\s+[A-Z][A-Za-z]+")


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip().casefold()


def annotate_quality(row: dict[str, Any]) -> dict[str, Any]:
    """Add conservative sample-quality flags without hiding the raw probe result."""
    annotated = dict(row)
    titles = [str(t).strip() for t in annotated.get("sample_titles", []) if str(t).strip()]
    urls = [str(u).strip() for u in annotated.get("sample_apply_urls", []) if str(u).strip()]
    company = _norm_title(str(annotated.get("company", "")))
    flags: set[str] = set()

    for title in titles:
        norm = _norm_title(title)
        if company and norm == company:
            flags.add("company_name_as_title")
        if norm in _WEAK_TITLES or norm.startswith("apply now ") or norm.startswith("icon"):
            flags.add("weak_title")
        if _US_STATE_IN_TITLE_RE.search(title) and not _INDIA_LOCATION_WORD_RE.search(title):
            flags.add("possible_us_state_in_title")

    if any("#" in url for url in urls):
        flags.add("anchor_or_listing_url")

    if (annotated.get("job_count_sample") or 0) and not (annotated.get("sample_with_jd") or 0):
        flags.add("missing_jd")

    annotated["quality_flags"] = sorted(flags)
    if annotated.get("probe_state") == "hiring":
        annotated["sample_quality"] = "needs_review" if flags else "usable"
    elif annotated.get("probe_state") == "not_probed":
        annotated["sample_quality"] = "not_probed"
    else:
        annotated["sample_quality"] = "no_usable_sample"
    return annotated


def _base_row(portal: dict[str, Any]) -> dict[str, Any]:
    status = str(portal.get("status") or "")
    js_required = bool(portal.get("js_required"))
    return {
        "company": portal.get("company", ""),
        "ats": portal.get("ats", ""),
        "industry": portal.get("industry", ""),
        "endpoint": portal.get("endpoint", ""),
        "careers_url": portal.get("careers_url", ""),
        "route_state": classify_route_state(status, js_required),
        "probe_state": "not_probed",
        "job_count_sample": None,
        "sample_titles": [],
        "sample_apply_urls": [],
        "sample_with_jd": 0,
        "sample_quality": "not_probed",
        "quality_flags": [],
        "needs_docker": js_required,
        "fallback_reason": "",
        "notes": _status_note(status),
    }


def _probe_row(
    row: dict[str, Any],
    portal: dict[str, Any],
    *,
    include_js: bool,
    sample_size: int,
) -> None:
    if row["needs_docker"] and not include_js:
        row["probe_state"] = "skipped_needs_docker"
        row["fallback_reason"] = "js_required_route"
        row.update(annotate_quality(row))
        return

    try:
        result = probe_scrape(
            portal,
            _LOG,
            max_jobs=sample_size,
            validate_mode=False,
            allow_firecrawl=include_js,
        )
    except Exception as exc:  # keep inventory resilient across one bad portal
        row["probe_state"] = "error"
        row["fallback_reason"] = f"{type(exc).__name__}: {exc}"
        row.update(annotate_quality(row))
        return

    if result.fallback_policy:
        row["probe_state"] = "fallback_needs_docker"
        row["needs_docker"] = True
        row["fallback_reason"] = result.fallback_reason or result.fallback_policy or "fallback_requested"
        row.update(annotate_quality(row))
        return

    jobs = [job for job in result.jobs or [] if not looks_like_navigation_job(job)]
    row["job_count_sample"] = len(jobs)
    row["sample_titles"] = [_sample_title(j) for j in jobs if _sample_title(j)][:sample_size]
    row["sample_apply_urls"] = [_job_url(j) for j in jobs if _job_url(j)][:sample_size]
    row["sample_with_jd"] = sum(1 for j in jobs if len(str(j.get("raw_jd_text") or j.get("job_description") or "")) >= 100)

    row["probe_state"] = classify_probe_state(jobs, result.reason)
    row.update(annotate_quality(row))


def build_inventory(
    *,
    probe: bool = False,
    include_js: bool = False,
    sample_size: int = 3,
    company_filter: str = "",
    company_names: list[str] | None = None,
    ats_filter: str = "",
    scope: str = "india",
    limit: int = 0,
    offset: int = 0,
    progress: bool = False,
    source_index_by_company: dict[str, int] | None = None,
) -> dict[str, Any]:
    portals = parse_portals()
    if company_names is not None:
        wanted = set(company_names)
        portals = [p for p in portals if p.get("company", "") in wanted]
        order = {company: idx for idx, company in enumerate(company_names)}
        portals.sort(key=lambda p: order.get(str(p.get("company", "")), len(order)))
    if company_filter:
        needle = company_filter.lower()
        portals = [p for p in portals if needle in p.get("company", "").lower()]
    if ats_filter:
        portals = [p for p in portals if p.get("ats", "").lower() == ats_filter.lower()]
    if offset:
        portals = portals[offset:]
    if limit:
        portals = portals[:limit]

    rows: list[dict[str, Any]] = []
    total = len(portals)
    for idx, portal in enumerate(portals, start=1):
        portal = dict(portal)
        portal["india_only"] = scope == "india"
        row = _base_row(portal)
        company = str(row["company"])
        if source_index_by_company and company in source_index_by_company:
            row["inventory_index"] = source_index_by_company[company]
        else:
            row["inventory_index"] = offset + idx - 1
        if probe:
            if progress:
                print(f"[{idx}/{total}] {row['company']} [{row['ats']}]", flush=True)
            _probe_row(row, portal, include_js=include_js, sample_size=sample_size)
        else:
            row.update(annotate_quality(row))
        rows.append(row)

    return {
        "meta": {
            "generated_at": datetime.now().isoformat(),
            "portals_path": str(PORTALS_PATH),
            "probe": probe,
            "include_js": include_js,
            "sample_size": sample_size,
            "scope": scope,
            "company_filter": company_filter,
            "company_names": company_names or [],
            "ats_filter": ats_filter,
            "limit": limit,
            "offset": offset,
        },
        "summary": summarize_rows(rows),
        "rows": rows,
    }


def _split_csv_filter(value: str) -> set[str]:
    return {part.strip() for part in value.split(",") if part.strip()}


def select_inventory_rows(
    path: Path,
    *,
    probe_states: set[str] | None = None,
    route_states: set[str] | None = None,
    needs_docker_only: bool = False,
    company_filter: str = "",
    limit: int = 0,
    offset: int = 0,
) -> InventorySelection:
    """Select exact companies from a previous report for controlled re-probes."""
    data = json.loads(path.read_text(encoding="utf-8"))
    indexed_rows: list[tuple[int, dict[str, Any]]] = []
    for source_position, row in enumerate(data.get("rows", [])):
        raw_index = row.get("inventory_index")
        source_index = source_position if raw_index is None else int(raw_index)
        indexed_rows.append((source_index, row))

    if probe_states:
        indexed_rows = [(i, r) for i, r in indexed_rows if str(r.get("probe_state", "")) in probe_states]
    if route_states:
        indexed_rows = [(i, r) for i, r in indexed_rows if str(r.get("route_state", "")) in route_states]
    if needs_docker_only:
        indexed_rows = [(i, r) for i, r in indexed_rows if bool(r.get("needs_docker"))]
    if company_filter:
        needle = company_filter.lower()
        indexed_rows = [(i, r) for i, r in indexed_rows if needle in str(r.get("company", "")).lower()]
    if offset:
        indexed_rows = indexed_rows[offset:]
    if limit:
        indexed_rows = indexed_rows[:limit]

    company_names: list[str] = []
    source_index_by_company: dict[str, int] = {}
    for source_index, row in indexed_rows:
        company = str(row.get("company", "")).strip()
        if not company or company in source_index_by_company:
            continue
        company_names.append(company)
        source_index_by_company[company] = source_index

    return InventorySelection(
        company_names=company_names,
        source_index_by_company=source_index_by_company,
    )


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_route = Counter(row["route_state"] for row in rows)
    by_probe = Counter(row["probe_state"] for row in rows)
    by_quality = Counter(row.get("sample_quality", "unknown") for row in rows)
    by_ats = Counter(row["ats"] for row in rows)
    by_industry = Counter(row["industry"] or "Unknown" for row in rows)
    return {
        "total_active_portals": len(rows),
        "route_state": {k: by_route.get(k, 0) for k in ROUTE_ORDER if by_route.get(k, 0)},
        "probe_state": dict(sorted(by_probe.items())),
        "sample_quality": dict(sorted(by_quality.items())),
        "ats": dict(sorted(by_ats.items())),
        "industry": dict(sorted(by_industry.items())),
        "hiring_sampled": sum(1 for row in rows if row["probe_state"] == "hiring"),
        "needs_docker": sum(1 for row in rows if row["needs_docker"]),
    }


def _md_table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "_None._\n"
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        out.append("| " + " | ".join(_escape_md(str(cell)) for cell in row) + " |")
    return "\n".join(out) + "\n"


def _escape_md(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render_markdown(inventory: dict[str, Any]) -> str:
    meta = inventory["meta"]
    summary = inventory["summary"]
    rows = inventory["rows"]
    hiring = [r for r in rows if r["probe_state"] == "hiring"]
    needs_docker = [r for r in rows if r["needs_docker"] or r["probe_state"] in {"skipped_needs_docker", "fallback_needs_docker"}]
    no_jobs = [r for r in rows if r["probe_state"] == "no_open_jobs"]
    direct_backlog = [r for r in rows if r["route_state"] != "cracked" and not r["needs_docker"]]

    parts = [
        "# Portal Inventory Report",
        "",
        f"Generated: `{meta['generated_at']}`",
        f"Probe mode: `{meta['probe']}`; include JS/Firecrawl: `{meta['include_js']}`; sample size: `{meta['sample_size']}`; scope: `{meta['scope']}`",
        "",
        "## Summary",
        "",
        _md_table(
            ["Metric", "Value"],
            [
                ["Active portals", summary["total_active_portals"]],
                ["Sampled as hiring", summary["hiring_sampled"]],
                ["Needs Docker/Firecrawl", summary["needs_docker"]],
            ],
        ),
        "## Route State",
        "",
        _md_table(["Route State", "Count"], [[k, v] for k, v in summary["route_state"].items()]),
        "## ATS Mix",
        "",
        _md_table(["ATS", "Count"], [[k, v] for k, v in summary["ats"].items()]),
        "## Hiring In Sample",
        "",
        _md_table(
            ["Company", "ATS", "Jobs Sampled", "Quality", "Flags", "Titles"],
            [[
                r["company"],
                r["ats"],
                r["job_count_sample"],
                r.get("sample_quality", ""),
                ", ".join(r.get("quality_flags", [])),
                "; ".join(r["sample_titles"]),
            ] for r in hiring],
        ),
        "## Needs Docker Or Fresh JS/XHR",
        "",
        _md_table(
            ["Company", "ATS", "Probe State", "Reason"],
            [[r["company"], r["ats"], r["probe_state"], r["fallback_reason"] or r["notes"]] for r in needs_docker],
        ),
        "## Direct Routes With No Jobs In Sample",
        "",
        _md_table(["Company", "ATS", "Notes"], [[r["company"], r["ats"], r["notes"]] for r in no_jobs]),
        "## Direct Backlog",
        "",
        _md_table(["Company", "ATS", "Route State", "Notes"], [[r["company"], r["ats"], r["route_state"], r["notes"]] for r in direct_backlog]),
        "## All Active Portals",
        "",
        _md_table(
            ["Company", "ATS", "Industry", "Route", "Probe", "Needs Docker"],
            [[r["company"], r["ats"], r["industry"], r["route_state"], r["probe_state"], r["needs_docker"]] for r in rows],
        ),
    ]
    return "\n".join(parts).rstrip() + "\n"


def merge_inventory_files(paths: list[Path]) -> dict[str, Any]:
    """Merge batch JSON reports into one deduplicated inventory."""
    merged: dict[tuple[int, str], dict[str, Any]] = {}
    source_files: list[str] = []
    include_js = False
    scopes: set[str] = set()
    sample_sizes: set[str] = set()

    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        source_files.append(str(path))
        meta = data.get("meta", {})
        include_js = include_js or bool(meta.get("include_js"))
        if meta.get("scope"):
            scopes.add(str(meta["scope"]))
        if meta.get("sample_size") is not None:
            sample_sizes.add(str(meta["sample_size"]))
        offset = int(meta.get("offset") or 0)
        for i, row in enumerate(data.get("rows", [])):
            idx = int(row.get("inventory_index", offset + i))
            merged[(idx, row.get("company", ""))] = annotate_quality(row)

    rows = [row for _, row in sorted(merged.items(), key=lambda item: (item[0][0], item[0][1]))]
    return {
        "meta": {
            "generated_at": datetime.now().isoformat(),
            "probe": "merged",
            "include_js": include_js,
            "sample_size": ",".join(sorted(sample_sizes)) if sample_sizes else "mixed",
            "scope": ",".join(sorted(scopes)) if scopes else "mixed",
            "source_files": source_files,
        },
        "summary": summarize_rows(rows),
        "rows": rows,
    }


def write_reports(inventory: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    json_path = output_dir / f"portal_inventory_{ts}.json"
    md_path = output_dir / f"portal_inventory_{ts}.md"
    json_path.write_text(json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8")
    md_path.write_text(render_markdown(inventory), encoding="utf-8")
    return json_path, md_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a KNOWN_PORTALS route/hiring inventory")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--probe", action="store_true", help="Sample providers to detect current hiring")
    mode.add_argument("--no-probe", action="store_true", help="Metadata-only inventory (default)")
    parser.add_argument("--include-js", action="store_true", help="Allow Firecrawl/JS-required routes during probe mode")
    parser.add_argument("--merge", nargs="+", default=[], help="Merge existing portal_inventory_*.json reports")
    parser.add_argument("--from-inventory", default="", help="Select exact companies from a previous inventory JSON")
    parser.add_argument("--probe-states", default="", help="Comma-separated probe states to select with --from-inventory")
    parser.add_argument("--route-states", default="", help="Comma-separated route states to select with --from-inventory")
    parser.add_argument("--needs-docker-only", action="store_true", help="With --from-inventory, select rows marked needs_docker")
    parser.add_argument("--sample-size", type=int, default=3, help="Maximum jobs sampled per company in probe mode")
    parser.add_argument("--company", default="", help="Company substring filter")
    parser.add_argument("--ats", default="", help="ATS/provider exact filter")
    parser.add_argument("--scope", choices=["india", "global"], default="india")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of parsed portals for batched probes")
    parser.add_argument("--offset", type=int, default=0, help="Skip the first N parsed portals for batched probes")
    parser.add_argument("--quiet", action="store_true", help="Suppress per-company probe progress")
    parser.add_argument("--output-dir", default="../logs", help="Directory for JSON/Markdown reports")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.merge:
        inventory = merge_inventory_files([Path(p) for p in args.merge])
        json_path, md_path = write_reports(inventory, Path(args.output_dir))
        summary = inventory["summary"]
        print(f"Portal inventory written: {json_path}")
        print(f"Portal inventory markdown: {md_path}")
        print(f"Active portals: {summary['total_active_portals']}")
        print(f"Hiring sampled: {summary['hiring_sampled']}")
        print(f"Needs Docker/Firecrawl: {summary['needs_docker']}")
        return

    probe = bool(args.probe)
    if args.include_js and not probe:
        raise SystemExit("--include-js only makes sense with --probe")
    if args.sample_size < 1:
        raise SystemExit("--sample-size must be >= 1")
    if args.limit < 0 or args.offset < 0:
        raise SystemExit("--limit and --offset must be >= 0")
    if (args.probe_states or args.route_states or args.needs_docker_only) and not args.from_inventory:
        raise SystemExit("--probe-states, --route-states, and --needs-docker-only require --from-inventory")

    company_names = None
    source_index_by_company = None
    build_limit = args.limit
    build_offset = args.offset
    if args.from_inventory:
        selection = select_inventory_rows(
            Path(args.from_inventory),
            probe_states=_split_csv_filter(args.probe_states) or None,
            route_states=_split_csv_filter(args.route_states) or None,
            needs_docker_only=args.needs_docker_only,
            company_filter=args.company,
            limit=args.limit,
            offset=args.offset,
        )
        if not selection.company_names:
            raise SystemExit("No rows matched --from-inventory selection")
        company_names = selection.company_names
        source_index_by_company = selection.source_index_by_company
        build_limit = 0
        build_offset = 0

    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    inventory = build_inventory(
        probe=probe,
        include_js=args.include_js,
        sample_size=args.sample_size,
        company_filter=args.company,
        company_names=company_names,
        ats_filter=args.ats,
        scope=args.scope,
        limit=build_limit,
        offset=build_offset,
        progress=probe and not args.quiet,
        source_index_by_company=source_index_by_company,
    )
    if args.from_inventory:
        inventory["meta"]["from_inventory"] = args.from_inventory
        inventory["meta"]["probe_states"] = args.probe_states
        inventory["meta"]["route_states"] = args.route_states
        inventory["meta"]["needs_docker_only"] = args.needs_docker_only
        inventory["meta"]["selection_limit"] = args.limit
        inventory["meta"]["selection_offset"] = args.offset
    json_path, md_path = write_reports(inventory, Path(args.output_dir))
    summary = inventory["summary"]
    print(f"Portal inventory written: {json_path}")
    print(f"Portal inventory markdown: {md_path}")
    print(f"Active portals: {summary['total_active_portals']}")
    print(f"Hiring sampled: {summary['hiring_sampled']}")
    print(f"Needs Docker/Firecrawl: {summary['needs_docker']}")


if __name__ == "__main__":
    main()
