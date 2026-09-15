#!/usr/bin/env python3
"""
Phase 0 — Build the recruiter company universe from Tier-1/2 college pages.

Spends Firecrawl CLOUD credits (cloud_extract) — one-time discovery. For each
college recruiter-list page, LLM-extract the company names, normalize, and
dedupe across colleges into a seed file that feeds Phase 1 (free ATS resolver).

Run from scraper/:
    python -m discovery.phase0_discover                 # all sources
    python -m discovery.phase0_discover --limit 5       # first 5 sources (smoke)
    python -m discovery.phase0_discover --only "IIM"    # sources whose college matches

Outputs (in discovery/):
    seed_companies.json   canonical company -> {display, n_sources, colleges, kind_counts}
    seed_companies.csv    company, n_sources, colleges
    phase0_report.md      per-source extracted counts + run summary
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # import scraper modules
import firecrawl_client as fc  # noqa: E402

HERE = Path(__file__).resolve().parent
SOURCES_PATH = HERE / "college_sources.json"
SEED_JSON = HERE / "seed_companies.json"
SEED_CSV = HERE / "seed_companies.csv"
REPORT = HERE / "phase0_report.md"

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "companies": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Every distinct recruiter / hiring company name listed on the page",
        }
    },
    "required": ["companies"],
}
EXTRACT_PROMPT = (
    "This is a college placement / recruiters page. Extract the COMPLETE list of "
    "recruiter and hiring company names shown anywhere on the page (logo walls, tables, "
    "'past recruiters', 'top recruiters', sector-wise lists). Return ONLY company names "
    "as a flat array of strings. Do not include job titles, salary figures, sectors, "
    "student names, or the college's own name. One entry per company."
)

# Drops obvious non-company noise the extractor sometimes returns.
_NOISE = {
    "and many more", "and more", "others", "etc", "various", "n/a", "na",
    "top recruiters", "past recruiters", "recruiters", "more", "company",
}
# Suffixes stripped only for the dedup KEY (display form keeps the longest seen).
_SUFFIX_RE = re.compile(
    r"\b(private|pvt|limited|ltd|inc|incorporated|llc|llp|plc|corporation|corp|"
    r"company|co|group|holdings|technologies|technology|solutions|services|"
    r"consulting|india|global|international)\b",
    re.IGNORECASE,
)
_PUNCT_RE = re.compile(r"[^a-z0-9]+")


def norm_key(name: str) -> str:
    """Aggressive normalization used only for dedup grouping."""
    s = name.lower().strip()
    s = _SUFFIX_RE.sub(" ", s)
    s = _PUNCT_RE.sub(" ", s)
    return " ".join(s.split())


def clean_display(name: str) -> str:
    s = re.sub(r"\s+", " ", name).strip().strip(",;|-")
    return s


def is_valid(name: str) -> bool:
    s = name.strip().lower()
    if not s or s in _NOISE:
        return False
    if len(s) < 2 or len(name) > 80:
        return False
    if not re.search(r"[a-z]", s):  # must contain a letter
        return False
    return True


def load_sources(limit: int | None, only: str | None) -> list[dict]:
    data = json.loads(SOURCES_PATH.read_text(encoding="utf-8"))
    rows = data.get("sources", [])
    if only:
        rows = [r for r in rows if only.lower() in r.get("college", "").lower()]
    if limit:
        rows = rows[:limit]
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="only first N sources")
    ap.add_argument("--only", type=str, default=None, help="filter sources by college substring")
    args = ap.parse_args()

    sources = load_sources(args.limit, args.only)
    print(f"[phase0] {len(sources)} source pages\n")

    # canonical_key -> aggregate record
    agg: dict[str, dict] = {}
    per_source: list[dict] = []

    for i, src in enumerate(sources, 1):
        college, url, kind = src["college"], src["url"], src.get("kind", "?")
        print(f"[{i}/{len(sources)}] {college:40.40s} {kind:10.10s} {url}")
        data = fc.cloud_extract([url], EXTRACT_SCHEMA, EXTRACT_PROMPT)
        names = (data or {}).get("companies", []) or []
        kept = 0
        for raw in names:
            if not isinstance(raw, str):
                continue
            disp = clean_display(raw)
            if not is_valid(disp):
                continue
            key = norm_key(disp)
            if not key:
                continue
            rec = agg.setdefault(key, {"display": disp, "colleges": set(), "kinds": defaultdict(int)})
            # Keep the longest display form (usually most complete).
            if len(disp) > len(rec["display"]):
                rec["display"] = disp
            rec["colleges"].add(college)
            rec["kinds"][kind] += 1
            kept += 1
        print(f"        extracted {len(names)}, kept {kept}, unique-so-far {len(agg)}")
        per_source.append({"college": college, "url": url, "kind": kind,
                           "extracted": len(names), "kept": kept})

    # ── Write seed files ──────────────────────────────────────────────────────
    seed = {}
    for key, rec in sorted(agg.items(), key=lambda kv: -len(kv[1]["colleges"])):
        seed[key] = {
            "display": rec["display"],
            "n_sources": len(rec["colleges"]),
            "colleges": sorted(rec["colleges"]),
            "kind_counts": dict(rec["kinds"]),
        }
    SEED_JSON.write_text(json.dumps(seed, indent=2, ensure_ascii=False), encoding="utf-8")

    with SEED_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["company", "n_sources", "colleges"])
        for rec in seed.values():
            w.writerow([rec["display"], rec["n_sources"], "; ".join(rec["colleges"])])

    # ── Report ────────────────────────────────────────────────────────────────
    total_extracted = sum(s["extracted"] for s in per_source)
    lines = [
        f"# Phase 0 discovery — {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"- Sources processed: **{len(sources)}**",
        f"- Total raw names extracted: **{total_extracted}**",
        f"- Unique companies after dedup: **{len(seed)}**",
        "",
        "## Per-source",
        "",
        "| College | Kind | Extracted | Kept |",
        "|---|---|---|---|",
    ]
    for s in per_source:
        lines.append(f"| {s['college']} | {s['kind']} | {s['extracted']} | {s['kept']} |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\n[phase0] DONE — {len(seed)} unique companies")
    print(f"  {SEED_JSON}")
    print(f"  {SEED_CSV}")
    print(f"  {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
