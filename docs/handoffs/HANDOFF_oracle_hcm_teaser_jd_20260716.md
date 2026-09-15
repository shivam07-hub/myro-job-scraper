# HANDOFF — Oracle HCM scraper stores 195-char teaser as full JD (2026-07-16)

## Symptom (user-visible, prod)

Shivam (mit20) opened scraped job `336649` — *Multi-Cloud Sales Specialist, India North Region · Oracle* — in Myro's CV Playground. The Job Description drawer showed **3 lines** ("Oracle is looking for an experienced Multi-Cloud Database Sales Specialist…"), and requirement extraction produced junk ("2 requirements extracted"). Re-importing the SAME posting via the Myro extension (`ext_8b8e9fd92a2678d92d13`, same `source_url`) yielded the full 5,259-char JD and 13 real requirements. The scraped teaser materially degrades matching, coverage, and tailoring for every Oracle HCM job.

## Evidence (prod Supabase, 2026-07-16)

| job_id | ingestion | jd_len | note |
|---|---|---|---|
| 336649 (North) | scraper | **195** | identical teaser text |
| 333830 (West) | scraper | **195** | identical teaser text |
| 334839 (South) | scraper | **195** | identical teaser text |
| 333829 / 334128 / 333831 (older dupes) | scraper | **195** | identical teaser text |
| ext_8b8e9fd92a2678d92d13 (same req 336649) | extension | **5259** | full JD from rendered page |

All six scraped Oracle Multi-Cloud rows carry byte-identical 195-char `job_description` — the requisition's `ShortDescriptionStr`.

Likely NOT limited to this posting: every job ingested via the Oracle HCM list API has the same ceiling. Check breadth with:

```sql
SELECT count(*) FROM jobs
WHERE source_platform = 'Oracle' AND ingestion_source = 'scraper'
  AND length(job_description) < 600;
```

## Root cause (code)

`scraper/providers/generic_json.py`:

1. Oracle portals are read from the **list** endpoint
   `…/hcmRestApi/resources/latest/recruitingCEJobRequisitions?…finder=findReqs;…`
   (see `portal_reader.py:552` and the stored `source_url` on the rows).
   That endpoint's `requisitionList[]` items contain **`ShortDescriptionStr` only** —
   `ExternalDescriptionStr` is NOT present in the list payload.
2. `_parse_oracle_job()` (generic_json.py:253) maps
   `_jd = strip_html(ExternalDescriptionStr or ShortDescriptionStr or jobDescription)`
   → always resolves to the teaser.
3. The existing fallback `_fetch_oracle_html_jd()` (og:description scrape) only fires
   when `_jd` is **empty** — ShortDescriptionStr is non-empty, so it never runs.
   And og:description is itself a teaser, so it wouldn't fix this anyway.

## Verified fix path (live-tested 2026-07-16)

Oracle HCM exposes a public, unauthenticated **detail** endpoint:

```
GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails
    ?expand=all&onlyData=true
    &finder=ById;siteNumber={SITE},Id="{REQ_ID}"
```

Live result for `Id="336649"`, `siteNumber=CX_45001` on `eeho.fa.us2.oraclecloud.com`:

| field | len |
|---|---|
| `ExternalDescriptionStr` | **6465** (full JD, HTML) |
| `CorporateDescriptionStr` | 1690 (boilerplate "About Oracle") |
| `ShortDescriptionStr` | 196 (the teaser we currently store) |
| `ExternalQualificationsStr` | 25 (near-empty here, varies by req) |

Recommended change in the `oracle_nested` branch of `_parse_json_response`:

- After mapping each list item, call the detail endpoint per job and set
  `raw_jd_text = strip_html(ExternalDescriptionStr [+ ExternalQualificationsStr + ExternalResponsibilitiesStr when non-empty])`.
- Keep `ShortDescriptionStr` as `job_summary` material — it is a genuinely good card
  summary; the bug is storing it as the *description*.
- Keep `_fetch_oracle_html_jd` as last-ditch fallback only.
- Cost: +1 request/job. Gate on fingerprint change (only detail-fetch new/changed reqs)
  if volume matters; Oracle India lists ~100–300 reqs/run.
- Same `User-Agent: Mozilla/5.0` header requirement as the list call.

## Backfill

After the fix ships, backfill existing Oracle rows (same detail endpoint, keyed by
`job_id` = requisition Id + `siteNumber` parsed from `apply_url`). The 6 Multi-Cloud
rows above are the proof set. Breadth SQL already run 2026-07-16: **3,030 of 4,581** scraped Oracle rows (66%) have jd_len < 600 — this is fleet-wide, not one posting.

## Cross-repo note (Myro side, informational)

Myro's `jd_coverage` / requirement extraction runs on `jobs.job_description` — a 195-char
teaser produces 2 garbage requirements vs 13 real ones from the full JD. No Myro-side fix
needed; this is purely an ingestion-quality issue. Diagnosed in the True_Yodha session
2026-07-16 (Shivam's Oracle dream-job case study).
