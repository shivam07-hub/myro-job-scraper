#!/usr/bin/env python3
"""
FREE Greenhouse/Lever/Ashby/SmartRecruiters board-directory harvester.

The scale lever toward 10k: these four ATS host tens of thousands of public boards.
Given a big candidate-token list, probe each, keep India-bearing boards that are NOT
already tracked, and emit ready-to-paste KNOWN_PORTALS rows. No Firecrawl credits.

Token feed: discovery/board_tokens.txt — one per line:
    ats:token        e.g.  greenhouse:zinnov   (probe just that ATS — precise/fast)
    token            e.g.  razorpay            (probe ALL four ATS — broader/slower)
    # comment / blank lines ignored

Tokens are best collected for FREE from `site:` web searches
(site:boards.greenhouse.io india, site:jobs.lever.co bengaluru, site:jobs.ashbyhq.com,
site:jobs.smartrecruiters.com india) — those return REAL slugs, so no 404 waste.

Run from scraper/:
    python discovery/harvest_boards.py                 # all tokens, india-bearing net-new
    python discovery/harvest_boards.py --all-hits      # include non-India + already-tracked
    python discovery/harvest_boards.py --workers 20

Output (discovery/):
    harvested_boards.csv     every hit (ats, slug, total, india, board_name, status)
    harvest_report.md        summary by ATS + net-new India count
    harvest_promote.md       per-ATS KNOWN_PORTALS row stubs for net-new India boards
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from discovery.ats_probes import PROBES, name_matches  # noqa: E402
import portal_reader as pr  # noqa: E402

TOKENS_IN = HERE / "board_tokens.txt"
OUT_CSV = HERE / "harvested_boards.csv"
REPORT = HERE / "harvest_report.md"
PROMOTE = HERE / "harvest_promote.md"

# 2b quality gate — Myro indexes EMPLOYERS, not listings. A board earns auto-promotion
# only if it maps to ONE identifiable hiring company. Recruitment agencies / aggregators /
# microtask boards hire for undisclosed clients, so they break the "explain what THIS
# company wants" promise and must never auto-promote. They are routed to status='review'
# (a human confirms single-employer) instead of the ready-to-paste net-new bucket.
# The tests below are cheap proxies for the true single-employer question:
#   1. name/slug carries an agency/staffing word, OR
#   2. very large board with a low India ratio (classic multi-client dump:
#      Squircle 1784, Capital Aim 474, Welocalize 543 — huge totals, sprawling clients).
POLLUTION_RE = re.compile(
    r"consult|staffing|\bstaff\b|advisory|recruit|manpower|outsourc|placement|marketplace",
    re.IGNORECASE,
)
HIGH_TOTAL = 400      # boards larger than this are almost always agency/aggregator directories
LOW_INDIA_RATIO = 0.20  # …and if <20% of that volume is India, it is not a single India employer


def looks_like_pollution(h: dict) -> bool:
    """True if a hit is likely a staffing/aggregator board (route to review, never auto-promote)."""
    if POLLUTION_RE.search(f"{h['slug']} {h.get('board_name') or ''}"):
        return True
    total = h.get("total") or 0
    if total > HIGH_TOTAL and (h.get("india") or 0) < LOW_INDIA_RATIO * total:
        return True
    return False


def existing_tokens() -> dict[str, set[str]]:
    """Tokens already in KNOWN_PORTALS, per ATS — the dedup guard."""
    tok = {a: set() for a in PROBES}
    for p in pr.parse_portals():
        ats = (p.get("ats") or "").lower()
        ep = p.get("endpoint") or ""
        if ats == "greenhouse":
            m = re.search(r"boards/([^/]+)/jobs", ep)
            if m:
                tok["greenhouse"].add(m.group(1).lower())
        elif ats == "lever":
            s = p.get("lever_slug") or ""
            if s:
                tok["lever"].add(s.lower())
        elif ats == "ashby":
            m = re.search(r"job-board/([^/?\s]+)", ep)
            if m:
                tok["ashby"].add(m.group(1).lower())
        elif ats == "smartrecruiters":
            m = re.search(r"companies/([^/]+)/postings", ep)
            if m:
                tok["smartrecruiters"].add(m.group(1).lower())
    return tok


def load_tokens() -> list[tuple[str | None, str]]:
    """Return [(ats|None, token)]; ats=None means try all four."""
    if not TOKENS_IN.exists():
        print(f"[harvest] no token file at {TOKENS_IN} — create it (see module docstring)")
        return []
    out, seen = [], set()
    for line in TOKENS_IN.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            ats, tok = line.split(":", 1)
            ats, tok = ats.strip().lower(), tok.strip().lower()
            ats = ats if ats in PROBES else None
        else:
            ats, tok = None, line.lower()
        key = (ats, tok)
        if tok and key not in seen:
            seen.add(key)
            out.append((ats, tok))
    return out


def probe_token(ats: str | None, token: str) -> list[dict]:
    hits = []
    targets = [ats] if ats else list(PROBES)
    with requests.Session() as sess:
        for a in targets:
            hit = PROBES[a](sess, token)
            if hit:
                hits.append(hit)
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-hits", action="store_true", help="include non-India and already-tracked")
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    tokens = load_tokens()
    if not tokens:
        return 1
    print(f"[harvest] probing {len(tokens)} candidate tokens …")
    have = existing_tokens()

    all_hits: list[dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(probe_token, a, t): (a, t) for a, t in tokens}
        for fut in as_completed(futs):
            done += 1
            for h in fut.result():
                tracked = h["slug"].lower() in have.get(h["ats"], set())
                if tracked:
                    h["status"] = "tracked"
                elif h["india"] > 0:
                    h["status"] = "review" if looks_like_pollution(h) else "india"
                else:
                    h["status"] = "no-india"
                all_hits.append(h)
            if done % 100 == 0 or done == len(tokens):
                print(f"  {done}/{len(tokens)}  hits={len(all_hits)}")

    all_hits.sort(key=lambda h: (h["ats"], -h["india"], -h["total"]))
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ats", "slug", "total", "india", "board_name", "status", "sample"])
        for h in all_hits:
            w.writerow([h["ats"], h["slug"], h["total"], h["india"], h["board_name"], h["status"], h["sample"][:60]])

    net_new = [h for h in all_hits if h["status"] == "india"]
    review = [h for h in all_hits if h["status"] == "review"]

    # report
    by_ats: dict[str, dict] = {}
    for h in all_hits:
        d = by_ats.setdefault(h["ats"], {"hits": 0, "india": 0, "net_new": 0, "review": 0})
        d["hits"] += 1
        d["india"] += 1 if h["india"] > 0 else 0
        d["net_new"] += 1 if h["status"] == "india" else 0
        d["review"] += 1 if h["status"] == "review" else 0
    lines = [
        f"# Board harvest — {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"- Candidate tokens probed: **{len(tokens)}**",
        f"- Total board hits: **{len(all_hits)}**",
        f"- Net-new India-bearing boards: **{len(net_new)}**",
        f"- Flagged for review (likely agency/aggregator — held back): **{len(review)}**",
        "",
        "| ATS | Hits | with India | net-new India | review |",
        "|---|---|---|---|---|",
    ]
    for ats, d in sorted(by_ats.items(), key=lambda kv: -kv[1]["net_new"]):
        lines.append(f"| {ats} | {d['hits']} | {d['india']} | {d['net_new']} | {d['review']} |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # promote stubs (KNOWN_PORTALS column formats per ATS)
    rows = net_new if not args.all_hits else all_hits
    plines = [f"# Harvest promotion stubs — {datetime.now():%Y-%m-%d %H:%M}", "",
              f"{len(net_new)} net-new India boards. Verify board_name before promoting generic slugs.", ""]
    fmt = {
        "greenhouse": lambda h: f"| {h['board_name'] or h['slug']} | https://boards.greenhouse.io/{h['slug']} | {h['slug']} | {h['india']} | ✅ HARVESTED {datetime.now():%Y-%m-%d} — Greenhouse API, {h['india']} India jobs |",
        "lever": lambda h: f"| {h['board_name'] or h['slug']} | https://jobs.lever.co/{h['slug']} | {h['slug']} | {h['india']} | ✅ HARVESTED {datetime.now():%Y-%m-%d} — Lever API, {h['india']} India roles |",
        "smartrecruiters": lambda h: f"| {h['board_name'] or h['slug']} | https://careers.smartrecruiters.com/{h['slug']} | {h['slug']} | {h['india']} | ✅ HARVESTED {datetime.now():%Y-%m-%d} — SR API country=in, {h['india']} India jobs |",
        "ashby": lambda h: f"| {h['board_name'] or h['slug']} | https://jobs.ashbyhq.com/{h['slug']} | Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/{h['slug']}` | Python `is_india()` on `location`/`secondaryLocations` | {h['india']} | ✅ HARVESTED {datetime.now():%Y-%m-%d} — Ashby API, {h['india']} India jobs |",
    }
    for ats in sorted({h["ats"] for h in rows}):
        grp = [h for h in rows if h["ats"] == ats]
        plines.append(f"## {ats} — {len(grp)}")
        plines.append("")
        for h in sorted(grp, key=lambda x: -x["india"]):
            plines.append(fmt[ats](h))
        plines.append("")
        if ats == "ashby":
            plines.append("> Ashby also needs `ats_overrides`+`endpoint_overrides` entries in portal_reader.py.")
            plines.append("")

    # Held-back boards: likely recruitment agency / aggregator / microtask (multi-client).
    # Myro indexes single employers only — a human must confirm each is ONE real hiring
    # company before promoting. No paste-ready stub is emitted on purpose.
    if review:
        plines.append("---")
        plines.append("")
        plines.append(f"## REVIEW — {len(review)} held back (confirm SINGLE real employer before promoting)")
        plines.append("")
        plines.append("| ats | slug | total | india | board_name | sample |")
        plines.append("|---|---|---|---|---|---|")
        for h in sorted(review, key=lambda x: (-x["total"], -x["india"])):
            plines.append(
                f"| {h['ats']} | {h['slug']} | {h['total']} | {h['india']} | "
                f"{h['board_name'] or ''} | {h['sample'][:50]} |"
            )
        plines.append("")
    PROMOTE.write_text("\n".join(plines), encoding="utf-8")

    print(f"\n[harvest] DONE — {len(all_hits)} hits, {len(net_new)} net-new India boards")
    print(f"  {OUT_CSV}\n  {REPORT}\n  {PROMOTE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
