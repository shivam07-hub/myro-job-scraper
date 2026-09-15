#!/usr/bin/env python3
"""
Phase 1b — Turn resolved ATS hits into a reviewable promotion list. FREE.

Reads discovered_portals.csv + tracked_companies.json and splits hits into:
  - net-new      company not already in KNOWN_PORTALS
  - already      company already tracked (skip)
Filters to high-confidence and/or India-bearing boards, then emits ready-to-paste
KNOWN_PORTALS.md table rows per ATS for a human to review before promotion.

Run from scraper/:
    python discovery/promote_candidates.py                 # net-new, india>0 OR high-conf
    python discovery/promote_candidates.py --india-only     # only boards with India jobs
    python discovery/promote_candidates.py --include-review # include review-confidence

Output (discovery/):
    promote_rows.md   per-ATS markdown table stubs + counts
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CSV_IN = HERE / "discovered_portals.csv"
TRACKED = HERE / "tracked_companies.json"
OUT = HERE / "promote_rows.md"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--india-only", action="store_true")
    ap.add_argument("--include-review", action="store_true")
    args = ap.parse_args()

    tracked = {_norm(n) for n in json.loads(TRACKED.read_text(encoding="utf-8"))}
    rows = list(csv.DictReader(CSV_IN.open(encoding="utf-8")))

    net_new, already, skipped = [], 0, 0
    for r in rows:
        india = int(r.get("india") or 0)
        conf = r.get("confidence", "")
        if args.india_only and india == 0:
            skipped += 1; continue
        if conf == "review" and not args.include_review and india == 0:
            skipped += 1; continue
        if _norm(r["company"]) in tracked:
            already += 1; continue
        net_new.append(r)

    by_ats: dict[str, list[dict]] = {}
    for r in net_new:
        by_ats.setdefault(r["ats"], []).append(r)

    lines = [
        f"# Promotion candidates — {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"- Net-new companies (not in KNOWN_PORTALS): **{len({r['company'] for r in net_new})}**",
        f"- Already tracked (skipped): **{already}**",
        f"- Filtered out (low conf / no India): **{skipped}**",
        "",
        "> Review each row — `review` confidence means slug may be a collision. "
        "Verify board_name matches the company before promoting.",
        "",
    ]
    for ats in sorted(by_ats, key=lambda a: -len(by_ats[a])):
        hits = sorted(by_ats[ats], key=lambda h: (-int(h["india"] or 0), -int(h["total"] or 0)))
        lines.append(f"## {ats} — {len(hits)} net-new")
        lines.append("")
        lines.append("| Company | Slug | Total | India | Board name | Confidence | Endpoint |")
        lines.append("|---|---|---|---|---|---|---|")
        for h in hits:
            lines.append(
                f"| {h['company']} | `{h['slug']}` | {h['total']} | {h['india']} | "
                f"{h['board_name']} | {h['confidence']} | `{h['endpoint']}` |"
            )
        lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"net-new={len({r['company'] for r in net_new})} already={already} filtered={skipped}")
    print(f"  -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
