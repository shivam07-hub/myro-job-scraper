#!/usr/bin/env python3
"""diagnose.py — self-healing diagnostic over a scrape run.

Replaces the hand-written HANDOFF_skipped_companies_*.md: ingest a run_summary,
classify every 0/low company into the A-E failure buckets, and emit a generated
handoff. Probing/fix-proposal (Slice 2) lands behind --probe.

    python diagnose.py                      # classify latest run, print + write report
    python diagnose.py --run <run_id>       # a specific run_summary
    python diagnose.py --bucket REGRESSION  # only show one bucket
    python diagnose.py --json               # machine-readable verdicts

Classify is cheap and network-free, so main.py can call render_report() at the
end of every scrape. Heavy probing stays opt-in here.
"""

from __future__ import annotations

import argparse
import glob
import json
import os

from heal.baseline import load_ledger
from heal.classifier import (
    BUCKET_ORDER,
    NEEDS_CRACK,
    OK,
    PARAM_SUSPECT,
    REGRESSION,
    Verdict,
    bucket_counts,
    classify_run,
)

LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "logs")
WORKDAY_REGISTRY = os.path.join(os.path.dirname(__file__), "workday_registry.json")

_BUCKET_BLURB = {
    "INCOMPLETE_SNAPSHOT": "Provider returned rows but did not finish; quarantine and retry.",
    "REGRESSION": "Bucket A — were cracked, now 0/dropped. Cheapest wins; re-test endpoint + diff provider.",
    "PARAM_SUSPECT": "Bucket E — single direct route returned 0; verify id/param/facet.",
    "COOKIE_NEEDED": "Bucket D — Darwinbox; needs CF cookies in env.",
    "NEEDS_CRACK": "Bucket C — JS-opaque / ats=other; re-crack via Firecrawl Cloud, save endpoint.",
    "BLOCKED_EXPECTED": "Bucket B — known CF-blocked Workday; expected 0.",
    "LOW_COUNT": "Below the floor but non-zero; verify filter vs genuinely low hiring.",
}


def load_blocked_tenants(path: str = WORKDAY_REGISTRY) -> set[str]:
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return {k for k, v in data.items() if isinstance(v, dict) and v.get("blocked")}


def find_run_summary(run_id: str | None) -> str:
    if run_id:
        hits = glob.glob(os.path.join(LOGS_DIR, f"run_summary_*{run_id}*.json"))
        if not hits:
            # The filename timestamp is written when the report closes and is
            # intentionally different from the checkpoint/run_id inside it.
            # Resolve the documented --run contract against persisted content.
            for candidate in glob.glob(os.path.join(LOGS_DIR, "run_summary_*.json")):
                try:
                    with open(candidate, encoding="utf-8") as f:
                        if str(json.load(f).get("run_id") or "") == run_id:
                            hits.append(candidate)
                except (OSError, ValueError, TypeError):
                    continue
        if not hits:
            raise FileNotFoundError(f"no run_summary matching run_id={run_id}")
        return max(hits, key=os.path.getmtime)
    hits = glob.glob(os.path.join(LOGS_DIR, "run_summary_*.json"))
    if not hits:
        raise FileNotFoundError(f"no run_summary_*.json in {LOGS_DIR}")
    return max(hits, key=os.path.getmtime)


def diagnose(run_id: str | None = None) -> tuple[dict, list[Verdict]]:
    path = find_run_summary(run_id)
    with open(path, encoding="utf-8") as f:
        run_summary = json.load(f)
    baseline = load_ledger()
    blocked = load_blocked_tenants()
    verdicts = classify_run(run_summary, baseline, blocked)
    return run_summary, verdicts


PROBE_BUCKETS = (REGRESSION, PARAM_SUSPECT)


def run_probes(verdicts: list[Verdict], baseline: dict[str, dict], log_=None) -> list:
    """Re-test the cheap-win buckets (regression + param-suspect) against their
    live routes. Returns ProbeResult list. Needs network; no Docker for the
    cookie-free direct routes these buckets contain."""
    from heal.probe import probe_company
    from portal_reader import parse_portals

    portals = {p["company"]: p for p in parse_portals()}
    results = []
    for v in verdicts:
        if v.bucket not in PROBE_BUCKETS:
            continue
        portal = portals.get(v.company)
        if not portal:
            continue
        bl = baseline.get(v.company, {}).get("last_good_count")
        results.append(probe_company(portal, bl, log=log_))
    return results


def propose_fixes(verdicts: list[Verdict], crack: bool = False, crack_limit: int = 5,
                  crack_delay: float = 0.0, log_=None):
    """Build reviewable fix proposals (never applied).

    DEDUP_GENERIC proposals are free (static analysis of the parsed portals).
    With crack=True, also run the Firecrawl-cloud discovery probe on NEEDS_CRACK
    companies (spends credits; cached) and propose row stubs. crack_delay spaces
    the Firecrawl calls to stay under the plan's per-minute rate limit (the free
    plan allows 6/min — use ~11s).
    """
    import time

    from heal.propose import propose_crack_stub, propose_dedup_fixes
    from portal_reader import parse_portals

    portals = {p["company"]: p for p in parse_portals()}
    proposals = propose_dedup_fixes(list(portals.values()))

    if crack:
        from heal.probe import probe_company_firecrawl
        crackable = [v for v in verdicts if v.bucket == NEEDS_CRACK][:crack_limit]
        for i, v in enumerate(crackable):
            portal = portals.get(v.company)
            if not portal:
                continue
            r = probe_company_firecrawl(portal)
            if r.verdict == "CANDIDATE_FOUND" and r.candidate_urls:
                ev = f"Firecrawl map hit; india_signal={r.india_signal}"
                proposals.append(propose_crack_stub(v.company, r.careers_url, r.candidate_urls[0], ev))
            if crack_delay and i < len(crackable) - 1:
                time.sleep(crack_delay)
    return proposals


def render_report(run_summary: dict, verdicts: list[Verdict], probes: list | None = None) -> str:
    """Markdown handoff — the generated replacement for the manual file."""
    rid = run_summary.get("run_id", "?")
    counts = bucket_counts([v for v in verdicts if v.is_failure])
    lines = [
        f"# Self-healing diagnosis — run `{rid}`",
        "",
        f"Scope: {run_summary.get('scope', '?')} · processed {run_summary.get('processed', '?')} · "
        f"skipped {run_summary.get('skipped', '?')} · saved {run_summary.get('total_new', '?')}",
        "",
        "Generated by `diagnose.py` from the run_summary + baseline ledger. "
        "Buckets map to the old hand-written handoff sections.",
        "",
        "## Bucket totals",
        "",
        "| Bucket | Companies |",
        "|---|---|",
    ]
    for b in BUCKET_ORDER:
        if b == OK:
            continue
        lines.append(f"| {b} | {counts.get(b, 0)} |")
    lines.append("")

    for b in BUCKET_ORDER:
        if b == OK:
            continue
        group = [v for v in verdicts if v.bucket == b]
        if not group:
            continue
        lines += [f"## {b}", "", f"_{_BUCKET_BLURB.get(b, '')}_", ""]
        lines += ["| Company | ATS | This | Last good | Evidence | Action |", "|---|---|---|---|---|---|"]
        for v in group:
            lg = "—" if v.last_good_count is None else str(v.last_good_count)
            lines.append(
                f"| {v.company} | {v.ats} | {v.this_count} | {lg} | {v.evidence} | {v.suggested_action} |"
            )
        lines.append("")

    if probes:
        lines += ["## Probe results (live re-test)", "",
                  "| Company | ATS | Verdict | Now | Baseline | Suggested fix |",
                  "|---|---|---|---|---|---|"]
        for p in probes:
            bl = "—" if p.baseline_count is None else str(p.baseline_count)
            lines.append(f"| {p.company} | {p.ats} | {p.verdict} | {p.this_count} | {bl} | {p.suggested_fix} |")
        lines.append("")
    return "\n".join(lines)


def print_summary(run_summary: dict, verdicts: list[Verdict]) -> None:
    counts = bucket_counts([v for v in verdicts if v.is_failure])
    rid = run_summary.get("run_id", "?")
    total_fail = sum(counts.values())
    print(f"\n  Diagnosis — run {rid}: {total_fail} companies need attention")
    for b in BUCKET_ORDER:
        if b == OK or not counts.get(b):
            continue
        print(f"    {b:<18} {counts[b]:>3}   {_BUCKET_BLURB.get(b, '')}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Self-healing diagnostic over a scrape run")
    ap.add_argument("--run", help="run_id to diagnose (default: latest run_summary)")
    ap.add_argument("--bucket", help="filter output to one bucket")
    ap.add_argument("--json", action="store_true", help="emit verdicts as JSON")
    ap.add_argument("--probe", action="store_true",
                    help="live re-test the regression + param-suspect routes (network)")
    ap.add_argument("--propose", action="store_true",
                    help="emit reviewable fix diffs (free dedup analysis) -> logs/proposed_fixes_*.md")
    ap.add_argument("--probe-crack", action="store_true",
                    help="run Firecrawl-cloud discovery on NEEDS_CRACK companies (spends credits)")
    ap.add_argument("--crack-limit", type=int, default=5, help="max NEEDS_CRACK companies to probe")
    ap.add_argument("--crack-delay", type=float, default=0.0,
                    help="seconds between Firecrawl calls to respect the plan rate limit (free=6/min -> ~11)")
    ap.add_argument("--no-write", action="store_true", help="don't write the markdown report")
    args = ap.parse_args()

    run_summary, verdicts = diagnose(args.run)
    if args.bucket:
        verdicts = [v for v in verdicts if v.bucket == args.bucket.upper()]

    probes = None
    if args.probe:
        probes = run_probes(verdicts, load_ledger())

    if args.json:
        payload: object = [v.__dict__ for v in verdicts]
        if probes is not None:
            payload = {
                "verdicts": [v.__dict__ for v in verdicts],
                "probes": [p.__dict__ for p in probes],
            }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return

    print_summary(run_summary, verdicts)

    if probes is not None:
        print(f"\n  Probed {len(probes)} routes:")
        for p in probes:
            print(f"    {p.verdict:<12} {p.company:<22} now={p.this_count:<4} base={p.baseline_count}")
    report = render_report(run_summary, verdicts, probes)
    rid = run_summary.get("run_id", "latest")
    if not args.no_write:
        out = os.path.join(LOGS_DIR, f"diagnosis_{rid}.md")
        with open(out, "w", encoding="utf-8") as f:
            f.write(report + "\n")
        print(f"\n  report -> {os.path.relpath(out)}")

    if args.propose or args.probe_crack:
        from heal.propose import render_proposals
        proposals = propose_fixes(verdicts, crack=args.probe_crack, crack_limit=args.crack_limit,
                                  crack_delay=args.crack_delay)
        print(f"\n  Proposed fixes: {len(proposals)} (review — not applied)")
        for p in proposals:
            print(f"    {p.kind:<14} {p.company}")
        if not args.no_write:
            pout = os.path.join(LOGS_DIR, f"proposed_fixes_{rid}.md")
            with open(pout, "w", encoding="utf-8") as f:
                f.write(render_proposals(proposals) + "\n")
            print(f"  proposals -> {os.path.relpath(pout)}")


if __name__ == "__main__":
    main()
