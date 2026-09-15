# PROPOSAL (needs approval) — Capture the Workday requisition ID into `job_id`

**Date:** 2026-06-21
**Status:** APPROVED + IMPLEMENTED 2026-06-21. Decisions: (1) approved; (2)
forward-only, no historical remap; (3) `requisition_id` column deferred.
Code: `utils.workday_req_id()` + `providers/workday.py`; tests:
`tests/test_workday_req_id.py` (4 passed). Live-verified on 3M — 110 jobs, 0
hash, all carry real `R01…` ids.
**Companion:** `2026-06-21-job-id-not-captured.md` (root-cause analysis)

---

## Problem (one line)

Every Workday tenant stores a hash instead of the company's requisition ID,
because the provider reads a field the Workday CXS list endpoint never returns.

## Scope of impact

- **19,133 rows (44.7% of 42,787)** currently carry the `md5(title|url)[:16]`
  fallback hash. Workday tenants are the dominant share (Barclays, State Street,
  DBS, DXC, Deutsche Bank, Target, Maersk, Intel, NXP, Autodesk, 3M, Chanel,
  Thomson Reuters, Lloyds, KLA — all 100% hash).
- The real requisition ID is already in each posting's `bulletFields[0]` and at
  the `_R…` tail of `externalPath`/`apply_url`. No new fetch, no Firecrawl
  credits.

## Root cause

`scraper/providers/workday.py`
```python
# line 171
jid = p.get('jobReqId') or ''          # CXS list endpoint has no 'jobReqId' key -> always ''
# line 185-186
bf  = p.get('bulletFields') or []
bu  = bf[1] if len(bf) > 1 else None    # [0] (the requisition id) is dropped
# line 188
'job_id': jid or job_hash(p.get('title', ''), url),   # -> always hashes
```

## Proposed change

Add a small, tested helper for requisition-id precedence and use it for `jid`.

```python
# utils.py  (new helper, single tested home)
import re
_REQ_TAIL = re.compile(r'_([A-Za-z]{1,5}\d{4,})$')   # _R01165624, _JR123456, etc.

def workday_req_id(posting: dict, external_path: str) -> str | None:
    """Requisition id for a Workday CXS posting: bulletFields[0] -> _R… tail."""
    bf = posting.get('bulletFields') or []
    if bf and isinstance(bf[0], str) and bf[0].strip():
        return bf[0].strip()
    m = _REQ_TAIL.search(external_path or '')
    return m.group(1) if m else None
```

```python
# workday.py  (replace the jid line)
jid = p.get('jobReqId') or workday_req_id(p, ext) or ''
```

Everything else (the `bu` business-unit read, the final
`jid or job_hash(...)` fallback) stays — the hash remains only as a true
last resort.

## Guarantees / discipline

- **Forward-only.** No backfill of existing rows (matches the project's data
  philosophy). Correctness applies from the next scrape onward; `csv_importer`
  upserts on `job_id`, so recovered ids will INSERT as the canonical row and the
  old hash row ages out via the normal lifecycle.
  - *Open question for you:* do we want a one-time migration to remap historical
    Workday hash rows to their req id, or strictly forward-only? Recommend
    forward-only (simpler, consistent with policy).
- **No behavior change for non-Workday providers.**
- **No new network calls, no Firecrawl credits.**

## Tests (added with the change)

- Unit: `workday_req_id` returns `bulletFields[0]` when present; falls back to the
  `_R…` tail; returns `None` when neither exists.
- Regression: a recorded Workday CXS posting fixture yields a non-hash `job_id`
  (guards against the field-name regression recurring).

## Verification plan (before merge)

1. `python main.py --company "3M" --skip-enrich` — confirm `job_id` now equals the
   `R0…` shown in `apply_url` for sampled rows.
2. Repeat for one more Workday tenant (e.g. Intel) to confirm the helper
   generalizes across tenants.
3. `csv_importer.py --company "3M" --dry-run` — confirm counts/no drift.

## Risk

Low. Single-field derivation from data already in the response; gated by tests;
falls back to today's behavior (hash) if a posting truly lacks both signals.

## Optional follow-on (separate decision, not blocking)

Persist the requisition id as its own column (`requisition_id`) distinct from the
dedup `job_id`, so the dedup key can stay stable while we still expose the
recruiter-facing id. Distinguish ATS *posting id* from *requisition id* where the
ATS separates them (e.g. Greenhouse `requisition_id`).

---

**Decision needed from you:**
1. Approve the Workday `job_id` fix as scoped above? (Y/N)
2. Forward-only, or also one-time historical remap? (recommend forward-only)
3. Add the optional `requisition_id` column now, or defer? (recommend defer)
