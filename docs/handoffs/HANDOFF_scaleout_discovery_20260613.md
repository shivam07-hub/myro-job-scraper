# Handoff — Scale-out company discovery (2026-06-13)

Goal from user: grow tracked companies toward **10,000**, targeting recruiters from
Tier-1/2 engineering + management colleges. Burn the expiring Firecrawl **cloud**
credits on what only credits can do. (Question-bank work was handed to Codex.)

## What was built — `scraper/discovery/`

Two-stage, mostly-free pipeline. Only Stage 0 spends credits.

| File | Stage | Cost | What it does |
|---|---|---|---|
| `college_sources.json` | — | — | 41 college recruiter-list URLs (official full-list pages + careers360/collegedunia/shiksha aggregators), tagged tier/type/kind |
| `phase0_discover.py` | 0 | **cloud credits** | `cloud_extract` each page → recruiter company names → normalize + dedup → `seed_companies.{json,csv}` + `phase0_report.md` |
| `resolve_ats.py` | 1 | FREE | probe Greenhouse/Lever/Ashby/SmartRecruiters public APIs with slug candidates + India scan + collision guard → `discovered_portals.csv` + `resolve_report.md` |
| `promote_candidates.py` | 1b | FREE | token+name dedup vs current KNOWN_PORTALS → per-ATS promotable row stubs → `promote_rows.md` |

New helper added: `firecrawl_client.cloud_extract(urls, schema, prompt)` — routes LLM
extraction to the paid cloud key (the existing `extract()` only hits the default/Docker app).

Run order (from `scraper/`):
```bash
python -m discovery.phase0_discover            # credits — grow seed
python discovery/resolve_ats.py --workers 16   # free — resolve to ATS
python discovery/promote_candidates.py --india-only   # free — net-new stubs
```

## Results

- Phase 0: 41 sources → **1,146 unique companies** (`seed_companies.json`).
- Resolve: **93 matched to a public ATS, 32 with India jobs, 104 board hits.**
- Promoted **18 net-new India-hiring companies** to KNOWN_PORTALS (274 → **292 active**),
  all validated end-to-end through production `dispatch_scrape`:
  - Greenhouse: Zinnov(65), Tekion(41), WorldQuant(6), Da Vinci Derivatives(1)
  - SmartRecruiters: Refyne(10), Arista Networks(8), Cars24, NoBroker, Lendingkart,
    Newton School, Leucine, Intervue, GreyCampus, Carbynetech, AdaptNXT(2)
  - Lever: Safe Security(13), Auxia(5)
  - Ashby: Lyric(13) — also needed `ats`/`endpoint` entries in `portal_reader.py` dicts
- **Parked `⚠️` (in doc, NOT active — identity unverified):** TSMG (lever, 3326 total → likely
  staffing), Genesis (lever, generic slug), Verve (greenhouse, "Verve" ≠ confirmed "Verve Consulting").

## Key learnings (read before extending)

1. **College seed → token-ATS yield is small and diminishing** (~18 net-new per ~1,150 seed).
   The most-cited college recruiters are big names on Workday/Darwinbox/Taleo — not token boards.
   The token-ATS wins live in the startup/scale-up tail.
2. **Dedup MUST be by `(ats, token)`, not company name.** Suffixes ("Inc", "Technologies")
   create false net-new (e.g. "Hevo Data Inc" vs tracked `hevodata`). Promoting dupes re-creates
   the generic-duplicate-masking bug the heal system guards against. `promote_candidates.py`
   uses parser-derived tokens — keep it that way.
3. **Slug collisions are real** — `tcs`→"Thornbury Community Services", `linkedin`→"LI Test Company".
   Always confirm board name before promoting; short/generic slugs default to `review`.
4. **Ashby is hardcoded** in `portal_reader.py` (`ats_overrides` + `endpoint_overrides`); a
   KNOWN_PORTALS row alone routes to `ats=custom`.

## Update — board-directory harvester built (the 10k lever, FREE)

`discovery/ats_probes.py` (shared probes) + `discovery/harvest_boards.py`:
feed candidate tokens (`board_tokens.txt`), probe all 4 ATS, India-filter, dedup vs
live portals, emit `harvest_promote.md` stubs. Tokens collected FREE via `site:` searches
(`site:boards.greenhouse.io india`, `site:jobs.lever.co bengaluru`, etc.) → REAL slugs.

First run: **29 tokens → 23 net-new India boards (~80% conversion).** Promoted 15 clean
product companies (Brillio 80, AHEAD 62, Beghou 54, NETGEAR 22, Atomicwork 21, LinkedIn 18,
6sense 17, Coupa 11, Pebl 8, Meltplan 6, Redpin 4, Resilinc 3, Truecaller 2, SentiLink 2,
Binance 1). All validated via `dispatch_scrape`.

**Total session: 274 → 307 active portals (+33).**

### Quality gate is the next must-build for the harvester
SmartRecruiters + some Lever surface staffing/aggregator/microtask boards that must NOT be
promoted (pollute the candidate DB): Squircle IT (1784 jobs), Capital Aim ("back-office
Indore freshers", 474), TMI Group (recruitment agency), Welocalize (localization microtasks,
543), Weekday (jobs marketplace, not one employer). For now filtered by hand. Add an auto
gate: very-high `total` + board-name regex (`consulting|staffing|advisory|recruitment|
manpower|outsourc`) → status `review`, not `india`.

### To actually reach 10k (free, repeatable)
Run `site:` token collection broadly (ATS × sector × city × many queries) → thousands of
tokens → `harvest_boards.py` → quality-gate → promote. No credits. The engine is built;
it just needs a bigger token feed + the quality gate.

## Recommended next steps (the actual 10k path)

- **FREE volume play (does NOT need credits — do this for 10k):** harvest Greenhouse/Lever/Ashby
  board-directory listings at scale, India-filter via existing providers. These public APIs host
  20k+ boards globally. Not college-gated.
- **Credit-bound, highest value while credits live:** `diagnose.py --probe-crack` on the 33
  NEEDS_CRACK companies (Uber, Walmart, UBS, Amdocs, consulting cluster) — durable named endpoints.
- Verify the 3 parked rows (TSMG/Genesis/Verve) or delete them.
- Add industry mappings for the 18 new companies to `company_industries.json` (currently warn-only).
