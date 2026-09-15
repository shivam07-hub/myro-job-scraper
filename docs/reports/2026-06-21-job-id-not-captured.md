# Why we often don't capture the company's real Job ID (requisition ID)

**Date:** 2026-06-21
**Context:** Triggered by the True_Yodha "Share a job" feature. The intent was to
share the job's ID so the recipient could search it on the company career page —
the way a requisition ID is used during recruitment. Investigation showed our
`job_id` is *not* reliably the company's requisition ID, so the share feature now
sends the role title + direct apply link instead.

---

## TL;DR

- `jobs.job_id` is **not** guaranteed to be the company's recruitment-facing
  requisition ID. It is *either* the ATS-native id (when the API returns one)
  *or* an internal fallback hash `md5(title|url)[:16]`.
- **44.7% of live rows (19,133 / 42,787)** carry the 16-char hash, i.e. no
  company id at all.
- The worst offender is **Workday**: every Workday tenant is **100% hash**
  (Barclays, State Street, DBS Bank, DXC, Deutsche Bank, Target, Maersk, Intel,
  NXP, Autodesk, 3M, Chanel, Thomson Reuters, Lloyds, KLA…). Root cause is a
  single wrong field name in the provider.
- The real requisition ID is **not lost** — for Workday it sits in the
  `apply_url` tail (`…_R01165624`) and in the API's `bulletFields`. We just don't
  read it into `job_id`.

---

## What `job_id` actually is

`job_id` is the dedup key. Every provider sets it with the same pattern: use the
ATS-native id if present, otherwise fall back to a content hash.

`scraper/utils.py:56`
```python
def job_hash(title: str, url: str) -> str:
    return hashlib.md5(f"{title}|{url}".encode()).hexdigest()[:16]
```

So a value like `0583408bbd9b17ef` (16 hex chars) is the fallback hash — it means
"this ATS gave us no id for this posting." It is internal-only and matches nothing
a recruiter or candidate could search on the company's site.

## Evidence from the live DB (project `gipvxuugajkugntwkeiz`)

```sql
select count(*) total,
  count(*) filter (where job_id ~ '^[0-9a-f]{16}$') hash_rows,
  round(100.0*count(*) filter (where job_id ~ '^[0-9a-f]{16}$')/count(*),1) pct
from jobs;
-- total=42787  hash_rows=19133  pct=44.7
```

Companies that are 100% hash (≥50 jobs each) — note these are all Workday tenants:

| Company | Jobs | % hash |
|---|---:|---:|
| Barclays | 1307 | 100 |
| State Street | 1080 | 100 |
| DBS Bank | 1034 | 100 |
| DXC Technology | 787 | 100 |
| Deutsche Bank | 704 | 100 |
| Target | 660 | 100 |
| Maersk | 628 | 100 |
| Intel | 611 | 100 |
| NXP Semiconductors | 600 | 100 |
| Autodesk | 593 | 100 |
| 3M | 533 | 100 |
| Chanel | 503 | 100 |

## Root cause — Workday provider reads a field the API doesn't return

`scraper/providers/workday.py:171`
```python
jid = p.get('jobReqId') or ''
...
'job_id': jid or job_hash(p.get('title', ''), url),   # line 188
```

The Workday **CXS list endpoint** (`/jobs` search response) does **not** include a
`jobReqId` key on each posting. Each posting object exposes:

- `title`
- `externalPath` — e.g. `/job/IN-Delhi-New-Delhi/Regulatory-Affairs-Manager---Transportation-Safety-business_R01165624`
- `bulletFields` — typically `["R01165624", …]` (the requisition ID is `bulletFields[0]`)
- `locationsText`, `postedOn`, …

Because `p.get('jobReqId')` is always `None`, `jid` is always empty, so **every**
Workday posting falls through to `job_hash(...)`. Meanwhile the provider already
reads `bulletFields` but uses index `[1]` as `business_unit` and ignores `[0]`:

`scraper/providers/workday.py:185-186`
```python
bf = p.get('bulletFields') or []
bu = bf[1] if len(bf) > 1 else None   # [0] (the req id) is dropped
```

The requisition ID is therefore captured in `apply_url` (the `_R…` tail) but never
promoted into `job_id`.

## Other providers

The same "native id else hash" pattern is used everywhere; the difference is
whether the ATS returns a usable id:

- **Greenhouse** (`str(p.get('id', job_hash(...)))`), **Lever**
  (`p.get('id')`), **SmartRecruiters** (`p.get('id')`), **Eightfold**
  (`pos.get('id')`) — these return a stable ATS id, so the hash fallback rarely
  fires. Caveat: an ATS *posting id* (e.g. Greenhouse numeric `id`) is not always
  the same string as the human-facing **requisition ID** a recruiter quotes; some
  ATSes expose that separately (e.g. Greenhouse `requisition_id`).
- **Workday** — broken as above (the bulk of the hash rows).

So the 44.7% is dominated by Workday, with a long tail from any posting where the
ATS genuinely returned no id.

## Why this matters

A requisition ID is the canonical handle in recruitment: it's how a role is
referenced in the ATS, in referrals, on the job page, and in candidate↔recruiter
conversations. Without it we cannot:

- let a user (or someone they shared the job with) look the role up on the
  company's own career site,
- de-duplicate against the same req across our scrape and the company's feed,
- give recruiters/candidates a stable reference,
- reliably map our row back to the live posting after the apply URL rots.

## What we shipped now (True_Yodha share feature)

Given the above, the Share button does **not** send `job_id`. It sends the role
title + the **direct `apply_url`** (which, for Workday, also contains the real
`_R…` requisition ID in the link). If the apply link has expired, the role title
is the fallback handle. See `frontend/lib/job-share.ts` → `shareJobRole()`.

## Proposed remedy (NOT yet implemented — needs approval per CHANGE DISCIPLINE)

Forward-only (no backfill), per the project's data philosophy:

1. **Workday:** derive the requisition ID from `bulletFields[0]`, and/or parse the
   `_R\d+` (more generally `_[A-Z]+\d+`) tail of `externalPath`/`apply_url`. Use
   that as `job_id` when present; keep the hash only as a last resort. This single
   fix recovers ~all 19k hash rows going forward.
2. Add a tiny `req_id` helper shared by providers so the "native id → requisition
   id → hash" precedence is one tested place (mirrors the `_paginate.py` seam).
3. Consider persisting the requisition ID as its own column (`requisition_id`)
   distinct from the dedup `job_id`, so the dedup key can stay stable while we
   still expose the recruiter-facing id. Distinguish ATS *posting id* from
   *requisition id* where the ATS separates them (e.g. Greenhouse).
4. Add a regression check: assert Workday postings yield a non-hash `job_id`.

Impact estimate: fixes the 12 100%-hash companies above immediately and the bulk
of the 44.7% overall, with zero new Firecrawl credits (data is already in the
existing API responses / apply URLs).
