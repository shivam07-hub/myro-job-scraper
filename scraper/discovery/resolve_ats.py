#!/usr/bin/env python3
"""
Phase 1 — Resolve seed companies to public-API ATS boards. FREE (no Firecrawl).

For each company in seed_companies.json, generate candidate slugs and probe the
four token-based public ATS APIs the scraper already supports:

    Greenhouse      https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
    Lever           https://api.lever.co/v0/postings/{slug}?mode=json
    Ashby           https://api.ashbyhq.com/posting-api/job-board/{slug}
    SmartRecruiters https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100

A hit means we can ingest that company with an EXISTING provider, no cracking.
Confidence is downgraded to 'review' when the board's own name does not look
like the company name (guards against slug collisions, e.g. a generic 'amazon').

Run from scraper/:
    python -m discovery.resolve_ats                 # all seed companies
    python -m discovery.resolve_ats --limit 40      # smoke
    python -m discovery.resolve_ats --workers 16

Output (discovery/):
    discovered_portals.csv   one row per (company, ats) hit, ready for review
    resolve_report.md        summary by ATS + confidence
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
SEED_JSON = HERE / "seed_companies.json"
OUT_CSV = HERE / "discovered_portals.csv"
REPORT = HERE / "resolve_report.md"

TIMEOUT = 8
UA = {"User-Agent": "Mozilla/5.0 (portal-discovery; +trueyodha)"}

_INDIA = re.compile(
    r"\b(india|bengaluru|bangalore|mumbai|delhi|gurgaon|gurugram|noida|hyderabad|"
    r"chennai|pune|kolkata|ahmedabad|kochi|cochin|trivandrum|chandigarh|jaipur|"
    r"indore|coimbatore|nagpur|vadodara|mysuru|mysore|thiruvananthapuram)\b",
    re.IGNORECASE,
)
_SUFFIX = re.compile(
    r"\b(private|pvt|limited|ltd|inc|incorporated|llc|llp|plc|corporation|corp|"
    r"company|co|group|holdings|the)\b", re.IGNORECASE,
)


def slug_candidates(display: str) -> list[str]:
    base = display.lower().strip()
    base = _SUFFIX.sub(" ", base)
    base = re.sub(r"&", " and ", base)
    words = re.sub(r"[^a-z0-9 ]+", " ", base).split()
    if not words:
        return []
    nospace = "".join(words)
    hyphen = "-".join(words)
    cands = [nospace, hyphen]
    if len(words) > 1:
        cands.append(words[0])              # first word (e.g. 'razorpay')
    # de-dup preserve order
    seen, out = set(), []
    for c in cands:
        if c and c not in seen and 2 <= len(c) <= 40:
            seen.add(c); out.append(c)
    return out


def _name_matches(company: str, board_name: str) -> bool:
    a = re.sub(r"[^a-z0-9]", "", company.lower())
    b = re.sub(r"[^a-z0-9]", "", (board_name or "").lower())
    if not b:
        return False
    return a in b or b in a or a[:6] == b[:6]


def probe_greenhouse(sess, slug):
    try:
        r = sess.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
                     headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        jobs = r.json().get("jobs", [])
        if not jobs:
            return None
        locs = " ".join(str(j.get("location", {}).get("name", "")) for j in jobs)
        meta = sess.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}",
                        headers=UA, timeout=TIMEOUT)
        bname = meta.json().get("name", "") if meta.status_code == 200 else ""
        india = sum(1 for j in jobs if _INDIA.search(str(j.get("location", {}).get("name", ""))))
        return dict(ats="greenhouse", slug=slug,
                    endpoint=f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
                    total=len(jobs), india=india, board_name=bname,
                    sample=(jobs[0].get("title", "") if jobs else ""))
    except Exception:
        return None


def probe_lever(sess, slug):
    try:
        r = sess.get(f"https://api.lever.co/v0/postings/{slug}?mode=json", headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        jobs = r.json()
        if not isinstance(jobs, list) or not jobs:
            return None
        india = sum(1 for j in jobs if _INDIA.search(str(j.get("categories", {}).get("location", "")) + " " + str(j.get("country", ""))))
        return dict(ats="lever", slug=slug,
                    endpoint=f"https://api.lever.co/v0/postings/{slug}?mode=json",
                    total=len(jobs), india=india, board_name="",
                    sample=(jobs[0].get("text", "") if jobs else ""))
    except Exception:
        return None


def probe_ashby(sess, slug):
    try:
        r = sess.get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}", headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        jobs = data.get("jobs", [])
        if not jobs:
            return None
        india = sum(1 for j in jobs if _INDIA.search(str(j.get("location", "")) + " " + str(j.get("address", ""))))
        return dict(ats="ashby", slug=slug,
                    endpoint=f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
                    total=len(jobs), india=india, board_name=str(data.get("name", "") or slug),
                    sample=(jobs[0].get("title", "") if jobs else ""))
    except Exception:
        return None


def probe_smartrecruiters(sess, slug):
    try:
        r = sess.get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100",
                     headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        data = r.json()
        content = data.get("content", [])
        if not content:
            return None
        india = sum(1 for j in content if _INDIA.search(str(j.get("location", {})).lower()))
        return dict(ats="smartrecruiters", slug=slug,
                    endpoint=f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?country=in&limit=100&offset=0",
                    total=data.get("totalFound", len(content)), india=india, board_name="",
                    sample=(content[0].get("name", "") if content else ""))
    except Exception:
        return None


PROBES = [probe_greenhouse, probe_lever, probe_ashby, probe_smartrecruiters]


def resolve_one(company: str, colleges: list[str]) -> list[dict]:
    hits = []
    with requests.Session() as sess:
        for probe in PROBES:
            for slug in slug_candidates(company):
                hit = probe(sess, slug)
                if hit:
                    conf = "high" if (hit["india"] > 0 or _name_matches(company, hit["board_name"]) or hit["slug"] == slug_candidates(company)[0]) else "review"
                    # collisions: short single-word slugs are risky unless board name confirms
                    if len(slug) <= 4 and not _name_matches(company, hit["board_name"]):
                        conf = "review"
                    hit.update(company=company, colleges="; ".join(colleges), confidence=conf)
                    hits.append(hit)
                    break  # first slug hit for this ATS wins
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    seed = json.loads(SEED_JSON.read_text(encoding="utf-8"))
    companies = [(rec["display"], rec.get("colleges", [])) for rec in seed.values()]
    if args.limit:
        companies = companies[:args.limit]
    print(f"[resolve] probing {len(companies)} companies x4 ATS …")

    all_hits: list[dict] = []
    done = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(resolve_one, c, cols): c for c, cols in companies}
        for fut in as_completed(futs):
            done += 1
            hits = fut.result()
            all_hits.extend(hits)
            if done % 50 == 0 or done == len(companies):
                print(f"  {done}/{len(companies)}  hits={len(all_hits)}")

    fields = ["company", "ats", "slug", "endpoint", "total", "india", "board_name",
              "sample", "confidence", "colleges"]
    all_hits.sort(key=lambda h: (h["ats"], -h["india"], -h["total"]))
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for h in all_hits:
            w.writerow({k: h.get(k, "") for k in fields})

    by_ats: dict[str, dict] = {}
    for h in all_hits:
        d = by_ats.setdefault(h["ats"], {"hits": 0, "india": 0, "high": 0})
        d["hits"] += 1
        d["india"] += 1 if h["india"] > 0 else 0
        d["high"] += 1 if h["confidence"] == "high" else 0
    matched_companies = len({h["company"] for h in all_hits})
    india_companies = len({h["company"] for h in all_hits if h["india"] > 0})

    lines = [
        f"# Phase 1 ATS resolution — {datetime.now():%Y-%m-%d %H:%M}",
        "",
        f"- Companies probed: **{len(companies)}**",
        f"- Companies matched to >=1 public ATS: **{matched_companies}**",
        f"- Companies with detected India jobs: **{india_companies}**",
        f"- Total board hits: **{len(all_hits)}**",
        "",
        "## By ATS",
        "",
        "| ATS | Hits | with India jobs | high-confidence |",
        "|---|---|---|---|",
    ]
    for ats, d in sorted(by_ats.items(), key=lambda kv: -kv[1]["hits"]):
        lines.append(f"| {ats} | {d['hits']} | {d['india']} | {d['high']} |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\n[resolve] DONE — {matched_companies} companies matched, {india_companies} with India jobs")
    print(f"  {OUT_CSV}\n  {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
