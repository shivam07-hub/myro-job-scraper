#!/usr/bin/env python3
"""
Shared, tested probes for the four token-based public ATS APIs. FREE (no Firecrawl).

Used by both resolve_ats.py (college seed → ATS) and harvest_boards.py (bulk board
directory harvest). One home for the request shape, India detection, and the hit dict
so the two callers can never drift.

A "hit" dict:
    {ats, slug, endpoint, total, india, board_name, sample}
or None on miss / error.
"""
from __future__ import annotations

import re

import requests

TIMEOUT = 8
UA = {"User-Agent": "Mozilla/5.0 (portal-discovery; +trueyodha)"}

INDIA_RE = re.compile(
    r"\b(india|bengaluru|bangalore|mumbai|delhi|gurgaon|gurugram|noida|hyderabad|"
    r"chennai|pune|kolkata|ahmedabad|kochi|cochin|trivandrum|chandigarh|jaipur|"
    r"indore|coimbatore|nagpur|vadodara|mysuru|mysore|thiruvananthapuram|"
    r"\bIN\b)\b",
    re.IGNORECASE,
)


def probe_greenhouse(sess, slug):
    try:
        r = sess.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
                     headers=UA, timeout=TIMEOUT)
        if r.status_code != 200:
            return None
        jobs = r.json().get("jobs", [])
        if not jobs:
            return None
        meta = sess.get(f"https://boards-api.greenhouse.io/v1/boards/{slug}", headers=UA, timeout=TIMEOUT)
        bname = meta.json().get("name", "") if meta.status_code == 200 else ""
        india = sum(1 for j in jobs if INDIA_RE.search(str(j.get("location", {}).get("name", ""))))
        return dict(ats="greenhouse", slug=slug,
                    endpoint=f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
                    total=len(jobs), india=india, board_name=bname,
                    sample=jobs[0].get("title", ""))
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
        india = sum(1 for j in jobs
                    if INDIA_RE.search(str(j.get("categories", {}).get("location", "")) + " " + str(j.get("country", ""))))
        return dict(ats="lever", slug=slug,
                    endpoint=f"https://api.lever.co/v0/postings/{slug}?mode=json",
                    total=len(jobs), india=india, board_name="",
                    sample=jobs[0].get("text", ""))
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
        india = sum(1 for j in jobs if INDIA_RE.search(str(j.get("location", "")) + " " + str(j.get("address", ""))))
        return dict(ats="ashby", slug=slug,
                    endpoint=f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
                    total=len(jobs), india=india, board_name=str(data.get("name", "") or slug),
                    sample=jobs[0].get("title", ""))
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
        india = sum(1 for j in content if INDIA_RE.search(str(j.get("location", {})).lower()))
        bname = (content[0].get("company") or {}).get("name", "") if content else ""
        return dict(ats="smartrecruiters", slug=slug,
                    endpoint=f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?country=in&limit=100&offset=0",
                    total=data.get("totalFound", len(content)), india=india, board_name=bname,
                    sample=content[0].get("name", ""))
    except Exception:
        return None


PROBES = {
    "greenhouse": probe_greenhouse,
    "lever": probe_lever,
    "ashby": probe_ashby,
    "smartrecruiters": probe_smartrecruiters,
}


def name_matches(company: str, board_name: str) -> bool:
    a = re.sub(r"[^a-z0-9]", "", company.lower())
    b = re.sub(r"[^a-z0-9]", "", (board_name or "").lower())
    if not b:
        return False
    return a in b or b in a or a[:6] == b[:6]
