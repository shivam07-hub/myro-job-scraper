#!/usr/bin/env python3
"""
Skill definition enricher — recurring, self-healing.

Fills public.skills.description from the Lightcast Open Skills public skill page.

Why this lives in firecrawl_Supabase (the scraper repo), not True_Yodha:
  It is a scraper. It reads the same Supabase the pipeline writes, fetches the
  canonical skill definition from Lightcast, and writes it back. True_Yodha only
  CONSUMES skills.description (skill cards + the Upskilling/Practice quiz anchor).

Why NOT Firecrawl:
  The full definition is in the server-rendered <meta name="description"> of every
  skill page — returned by a plain HTTP GET, no JS render. So this costs 0 Firecrawl
  credits. (Repo rule: "if a direct route exists, use it. Firecrawl is the fallback.")
  skill_type / tags would need a JS render and are intentionally out of scope here.

Why per-SKILL, not per job_skills edge:
  A description is intrinsic to the skill. public.skills is one row per skill and
  already holds lightcast_id / l1_domain / l2_cluster. Storing it on job_skills would
  duplicate each definition across hundreds of edges.

Recurring / self-healing contract:
  Default scope = the distinct skills actually referenced in job_skills (the universe
  a user can save & practice) that still have description IS NULL. As new jobs bring in
  new skills, the missing set grows; this job closes it on the next run.
  Threshold gate: by default it does real work only when >= --threshold skills are
  missing (so the weekly cron is a cheap no-op until ~50-100 new skills accrue).
  Pass --force to run regardless, or --all to cover the whole taxonomy (not just
  job-referenced skills).

Migration: run scraper/sql/add_skills_description.sql once before --write-supabase.

Usage:
  python skill_descriptions.py --dry-run                 # count the missing set, no fetch
  python skill_descriptions.py                           # fetch -> Excel only (no DB write)
  python skill_descriptions.py --write-supabase          # fetch -> Excel + update skills.description
  python skill_descriptions.py --force --limit 50        # ignore threshold, cap work
  python skill_descriptions.py --all --write-supabase    # whole 35k taxonomy (heavy)
"""
from __future__ import annotations

import argparse
import html
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

_ENV_PATH = Path(__file__).parent / ".env"
_SKILL_URL = "https://lightcast.io/open-skills/skills/{lightcast_id}/x"  # slug is cosmetic; id resolves
_META_RE = re.compile(r'<meta name="description" content="(.*?)"\s*/?>', re.S)
_BOILERPLATE = " Lightcast Skills is the industry standard for skills data."
_DEFAULT_THRESHOLD = 50
_REQUEST_PAUSE = 0.25  # polite delay between Lightcast GETs
_UA = "Mozilla/5.0 (compatible; MirrorSkillEnricher/1.0)"

_EXCEL_COLUMNS = [
    "lightcast_id",
    "l3_name",
    "l2_cluster",
    "l1_domain",
    "description",
    "info_url",
    "source",
    "fetched_at",
]


# ── env / supabase ────────────────────────────────────────────────────────────

def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if not _ENV_PATH.exists():
        sys.exit(f"missing env file: {_ENV_PATH}")
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    for required in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY"):
        if not env.get(required):
            sys.exit(f"missing {required} in {_ENV_PATH}")
    return env


def _sb_headers(key: str, *, write: bool = False) -> dict[str, str]:
    h = {"apikey": key, "Authorization": f"Bearer {key}"}
    if write:
        h["Content-Type"] = "application/json"
        h["Prefer"] = "return=minimal"
    return h


def referenced_skill_ids(base: str, headers: dict) -> set[str]:
    """All distinct skill_id present in job_skills (paginated)."""
    seen: set[str] = set()
    step, off = 10000, 0
    while True:
        r = requests.get(
            f"{base}/rest/v1/job_skills?select=skill_id",
            headers={**headers, "Range-Unit": "items", "Range": f"{off}-{off + step - 1}"},
            timeout=60,
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        seen.update(x["skill_id"] for x in rows)
        if len(rows) < step:
            break
        off += step
    return seen


def skills_missing_description(
    base: str, headers: dict, only_ids: set[str] | None, require_missing: bool = True
) -> list[dict]:
    """Skills with lightcast_id set.

    only_ids=None      -> whole taxonomy (--all)
    only_ids=set       -> restrict to those ids (the job-referenced universe)
    require_missing     -> add `description IS NULL` predicate (needs the migration).
                           Set False for an Excel-only run before the column exists.
    """
    cols = "id,lightcast_id,taxonomy_key,display_name,l1_domain,l2_cluster"
    miss = "&description=is.null" if require_missing else ""
    out: list[dict] = []
    if only_ids is None:
        step, off = 1000, 0
        while True:
            r = requests.get(
                f"{base}/rest/v1/skills"
                f"?select={cols}{miss}&lightcast_id=not.is.null&order=id",
                headers={**headers, "Range-Unit": "items", "Range": f"{off}-{off + step - 1}"},
                timeout=60,
            )
            r.raise_for_status()
            rows = r.json()
            if not rows:
                break
            out.extend(rows)
            if len(rows) < step:
                break
            off += step
        return out

    ids = list(only_ids)
    for i in range(0, len(ids), 100):
        batch = ids[i : i + 100]
        inlist = ",".join(f'"{x}"' for x in batch)
        r = requests.get(
            f"{base}/rest/v1/skills"
            f"?select={cols}&id=in.({inlist}){miss}&lightcast_id=not.is.null",
            headers=headers,
            timeout=60,
        )
        r.raise_for_status()
        out.extend(r.json())
    return out


# ── fetch + clean ───────────────────────────────────────────────────────────

def clean_description(raw: str) -> str:
    text = html.unescape(raw).strip()
    text = text.split(_BOILERPLATE)[0].strip()
    text = re.sub(r"\.{2,}$", ".", text).strip()  # "...." truncation join -> "."
    return text


def fetch_description(lightcast_id: str, *, retries: int = 3) -> tuple[str | None, str]:
    """Return (description, info_url). description is None on miss/empty."""
    url = _SKILL_URL.format(lightcast_id=lightcast_id)
    for attempt in range(retries):
        try:
            r = requests.get(url, headers={"User-Agent": _UA}, timeout=30)
            if r.status_code == 200:
                m = _META_RE.search(r.text)
                if not m:
                    return None, url
                desc = clean_description(m.group(1))
                return (desc or None), url
            if r.status_code in (429, 502, 503):
                time.sleep(1.5 * (attempt + 1))
                continue
            return None, url
        except requests.RequestException:
            time.sleep(1.0 * (attempt + 1))
    return None, url


# ── outputs ───────────────────────────────────────────────────────────────────

def write_table(rows: list[dict], path: Path) -> Path:
    """Write Excel; fall back to CSV if openpyxl is unavailable."""
    try:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "skill_definitions"
        ws.append(_EXCEL_COLUMNS)
        for row in rows:
            ws.append([row.get(c, "") for c in _EXCEL_COLUMNS])
        wb.save(path)
        return path
    except ImportError:
        import csv

        csv_path = path.with_suffix(".csv")
        with csv_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=_EXCEL_COLUMNS)
            w.writeheader()
            w.writerows({c: r.get(c, "") for c in _EXCEL_COLUMNS} for r in rows)
        return csv_path


def update_supabase(base: str, key: str, rows: list[dict]) -> int:
    headers = _sb_headers(key, write=True)
    now = datetime.now(timezone.utc).isoformat()
    written = 0
    for row in rows:
        if not row.get("description"):
            continue
        payload = {
            "description": row["description"],
            "description_source": "lightcast_meta",
            "description_fetched_at": now,
        }
        r = requests.patch(
            f"{base}/rest/v1/skills?id=eq.{row['skill_id']}",
            headers=headers,
            json=payload,
            timeout=30,
        )
        if r.status_code in (200, 204):
            written += 1
        else:
            print(f"  ! update failed {row['lightcast_id']}: {r.status_code} {r.text[:120]}")
    return written


# ── main ────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Recurring Lightcast skill-description enricher.")
    ap.add_argument("--dry-run", action="store_true", help="count the missing set, fetch nothing")
    ap.add_argument("--write-supabase", action="store_true", help="patch skills.description")
    ap.add_argument("--all", action="store_true", help="whole taxonomy, not just job-referenced skills")
    ap.add_argument("--force", action="store_true", help="run even if missing < threshold")
    ap.add_argument("--threshold", type=int, default=_DEFAULT_THRESHOLD,
                    help=f"min missing skills to trigger a real run (default {_DEFAULT_THRESHOLD})")
    ap.add_argument("--limit", type=int, default=0, help="cap skills fetched this run (0 = no cap)")
    ap.add_argument("--excel", type=str, default="", help="output path (default scraper/skill_definitions_<date>.xlsx)")
    ap.add_argument("--no-excel", action="store_true", help="skip the spreadsheet output")
    ap.add_argument("--ignore-db-description", action="store_true",
                    help="don't filter on skills.description (Excel-only run before the migration "
                         "exists); forces no DB write and ignores the threshold gate")
    args = ap.parse_args()
    if args.ignore_db_description:
        args.write_supabase = False
        args.force = True

    env = load_env()
    base = env["SUPABASE_URL"].rstrip("/")
    key = env["SUPABASE_SERVICE_KEY"]
    read_headers = _sb_headers(key)

    scope = "ALL taxonomy" if args.all else "job-referenced"
    print(f"── skill_descriptions ── scope={scope}")

    only_ids = None
    if not args.all:
        print("  collecting distinct skills in job_skills …")
        only_ids = referenced_skill_ids(base, read_headers)
        print(f"  {len(only_ids)} distinct skills referenced")

    try:
        missing = skills_missing_description(
            base, read_headers, only_ids, require_missing=not args.ignore_db_description
        )
    except requests.HTTPError as e:
        body = e.response.text if e.response is not None else ""
        if e.response is not None and e.response.status_code == 400 and "description" in body:
            print("✋ skills.description column not found. Run the migration first:")
            print("   scraper/sql/add_skills_description.sql  (Supabase SQL editor)")
            return 2
        raise
    print(f"  missing description: {len(missing)}")

    if not missing:
        print("✅ nothing to do — every in-scope skill already has a description.")
        return 0

    if not args.force and len(missing) < args.threshold:
        print(f"⏸  {len(missing)} < threshold {args.threshold} — skipping "
              f"(pass --force to run anyway). No-op exit.")
        return 0

    if args.limit:
        missing = missing[: args.limit]
        print(f"  capped to {len(missing)} this run (--limit)")

    if args.dry_run:
        print("  --dry-run: would fetch the above; no HTTP / no writes.")
        for s in missing[:10]:
            print(f"    - {s['lightcast_id']}  {s['taxonomy_key']}")
        if len(missing) > 10:
            print(f"    … +{len(missing) - 10} more")
        return 0

    rows: list[dict] = []
    hit = miss = 0
    fetched_at = datetime.now(timezone.utc).isoformat()
    for i, s in enumerate(missing, 1):
        desc, info_url = fetch_description(s["lightcast_id"])
        if desc:
            hit += 1
        else:
            miss += 1
        rows.append({
            "skill_id": s["id"],
            "lightcast_id": s["lightcast_id"],
            "l3_name": s["taxonomy_key"],
            "l2_cluster": s.get("l2_cluster") or "",
            "l1_domain": s.get("l1_domain") or "",
            "description": desc or "",
            "info_url": info_url,
            "source": "lightcast_meta" if desc else "miss",
            "fetched_at": fetched_at,
        })
        if i % 50 == 0 or i == len(missing):
            print(f"  fetched {i}/{len(missing)}  (hit={hit} miss={miss})")
        time.sleep(_REQUEST_PAUSE)

    coverage = hit / len(rows) * 100 if rows else 0
    print(f"  coverage: {hit}/{len(rows)} = {coverage:.1f}%  ({miss} had no usable meta)")

    if not args.no_excel:
        out = Path(args.excel) if args.excel else (
            Path(__file__).parent / f"skill_definitions_{datetime.now():%Y%m%d}.xlsx"
        )
        written_path = write_table(rows, out)
        print(f"  wrote {written_path}")

    if args.write_supabase:
        n = update_supabase(base, key, rows)
        print(f"  updated skills.description for {n} rows")
    else:
        print("  (no DB write — pass --write-supabase to persist)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
