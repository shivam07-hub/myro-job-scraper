# REPORT — Stale dirty `job_title` rows (pre-fix legacy, never delisted)

**From:** Myro (True_Yodha) — surfaced during dashboard visual QA, 2026-06-21
**Severity:** Low-to-medium (cosmetic on live job cards, but consumer-facing)
**TL;DR:** 127 jobs have a contaminated `job_title` (escaped `\n`, backslashes, `###`, concatenated Location / Employment Type). **The parser is already fixed** — zero dirty titles in any crawl since 2026-04-30. These are **legacy rows from the old parser that were never re-crawled, so never delisted**, and they still render raw on Myro job cards. Action = clean up / re-scrape ~10 companies; verify the ATS title parser guard.

---

## Evidence it is stale (not a current scraper bug)

Query run against prod Supabase (`gipvxuugajkugntwkeiz`) on 2026-06-21:

| metric | value |
|---|---|
| total jobs | 42,787 |
| active jobs | 34,959 |
| **dirty titles** | **127** |
| dirty **and** `is_active` | 117 |
| dirty seen in last 14 days | **0** |
| newest dirty `last_seen` | **20260430** |
| newest job `last_seen` (any) | 20260604 |

No dirty title has been crawled in ~7 weeks. The contamination stops cleanly at 2026-04-30 → the title parser fix landed ~end of April. **Fresh data is clean.**

## Why they are still served

Per `CLAUDE.md → is_active ownership`: decommissioning (`csv_importer.py --deactivate-missing --run-date`) only compares companies **present in that run date**; companies absent from a run are never touched. These ~10 companies have not been re-scraped since 2026-04-30, so they were never compared against a newer run → never delisted → still `is_active = true` → still matchable → render raw on Myro cards.

## The pattern

`job_title` absorbed the ATS card text block: real title + `\n\n` + location, sometimes + employment type / markdown `###`. Examples (verbatim):

- `Senior Software Engineer - Parametric\n\nMumbai, Maharashtra, India\n\…` (Morgan Stanley / Eightfold)
- `Member Of Technical Staff - HBM Verification\n\nHyderabad, Telangana, …` (Micron / Eightfold)
- `Consulting\ \ ### Project Management Consultant\ \ Location:IndiaEmployment Type:Full time employment` (Vector Consulting)

## Affected portals (the 127 rows)

| source host | dirty rows | still active | null markers | last_seen |
|---|---|---|---|---|
| deshawindia.com | 67 | 67 | 0 | 20260429 |
| morganstanley.eightfold.ai | 20 | 10 | 10 | 20260428 |
| ats.rippling.com | 18 | 18 | 0 | 20260429 |
| micron.eightfold.ai | 10 | 10 | 0 | 20260430 |
| vehere.com | 5 | 5 | 0 | 20260430 |
| strategyand.pwc.com | 2 | 2 | 0 | 20260429 |
| vectorconsulting.in | 2 | 2 | 0 | 20260429 |
| dxctechnology…myworkdayjobs.com | 1 | 1 | 0 | 20260428 |
| blackbrix.com | 1 | 1 | 0 | 20260429 |
| accenture…myworkdayjobs.com | 1 | 1 | 0 | 20260430 |

Eightfold (`*.eightfold.ai`) + D.E. Shaw dominate. The 10 Morgan Stanley rows also have **NULL freshness markers** (`first_seen`/`last_seen` NULL) — they would never delist under a `last_seen`-based rule.

## Recommended actions (in your existing model)

1. **Preferred — re-scrape the ~10 affected companies with the current parser.** A re-run overwrites the dirty title with a clean one AND refreshes freshness; if a listing is genuinely gone, `--deactivate-missing --run-date YYYYMMDD` delists it. No new code. Companies: D.E. Shaw, Morgan Stanley, Micron, the Rippling-hosted co(s), Vehere, Strategy& (PwC), Vector Consulting, DXC, Blackbrix, Accenture.
2. **Immediate stopgap (optional) — one-off SQL** to truncate the title at the first contamination marker for these 127 rows (`split_part` on `\n` / `\\` / `###` / `Location:` / `Employment Type`), so cards read clean before a re-scrape.
3. **NULL-marker rows** (10 Morgan Stanley) — set `is_active = false` directly, or backfill markers; they're invisible to `last_seen` delisting.
4. **Verify the ATS title parser guard** for Eightfold / D.E. Shaw / Rippling / Workday (`CLAUDE.md → ATS ROUTING`): confirm the title extractor never captures the location/description block. Appears already fixed (no dirty since 2026-04-30) — please confirm + document the guard so it can't regress.

## Detection query (reusable — should return 0 after fix)

```sql
SELECT count(*) AS dirty_titles,
       count(*) FILTER (WHERE is_active) AS dirty_and_active
FROM jobs
WHERE job_title ~ '[\\]|###|Location:|Employment Type';
```

## Myro side (True_Yodha) — defensive, separate follow-up

Myro will add a card-side title sanitizer so any contaminated title (these stale rows until cleaned, or any future regression) renders clean regardless of source. That is a Myro frontend follow-up and does **not** replace cleaning the data here — a clean `job_title` at source is still the source of truth for matching, search, and the newsletter.
