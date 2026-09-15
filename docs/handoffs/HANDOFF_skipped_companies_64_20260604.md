> **SUPERSEDED 2026-06-07 — this is now auto-generated.** The bucketing in this
> file is produced by `scraper/diagnose.py` from any run_summary + the baseline
> ledger. Run `python diagnose.py --probe` to regenerate
> `logs/diagnosis_<run_id>.md` with live route re-tests. Kept for reference; do
> not hand-maintain. Probe of this run's Bucket A: NVIDIA/Micron/Qualcomm routes
> are RECOVERED (PCSX healthy — the "drift" hypothesis was wrong); HSBC/Mphasis/
> Persistent are real routing regressions (restore eightfold/ripplehire/zwayam routes).

# HANDOFF — 64 Skipped Companies (India refresh `run_id=20260604_103837_270373`)

**Date:** 2026-06-04
**Run:** `--skip-enrich --scope india` resume run; 186 processed, **64 returned 0 India jobs**, 12,655 jobs saved.
**Source data:** `logs/run_summary_20260604_160727_010785.json` (`unresolved` + `low_count` arrays).
**Goal of this handoff:** investigate *why* each skipped, fix the regressions, and re-crack the JS-opaque ones using the now-saved Firecrawl Cloud key.

## Firecrawl Cloud key (saved for discovery)
- Stored in `scraper/.env` as `FIRECRAWL_CLOUD_API_KEY=fc-ab7c695e61eb4b079d77b7ef03bb3585` (gitignored).
- Current scrape config is **local Docker** (`FIRECRAWL_URL=http://localhost:3002`, `FIRECRAWL_API_KEY=local`) — unchanged.
- To run cloud discovery: blank `FIRECRAWL_URL`, set `FIRECRAWL_API_KEY=${FIRECRAWL_CLOUD_API_KEY}` (see comment block in `.env`).
- Discipline reminder (CLAUDE.md): map → selective scrape → **capture the durable direct endpoint into KNOWN_PORTALS.md**. Don't leave Firecrawl as the final route.

---

## Bucket A — HIGH PRIORITY regressions (were cracked, now 0)
These previously worked; routing/provider/param drift suspected. Fix first — cheap wins.

| Company | ATS in run | Prior known-good | Likely cause | Action |
|---|---|---|---|---|
| **NVIDIA** | pcsx | ✅ 201 India jobs (2026-05-15), `location=india` cookie-free | PCSX param/casing/domain drift | Re-test `GET jobs.nvidia.com/api/pcsx/search?domain=nvidia.com&query=&location=india&start=0`; check `india` vs `India` casing |
| **Micron Technology** | pcsx | ✅ 294 India jobs (2026-05-15), `location=India` | same | Re-test `micron.eightfold.ai/api/pcsx/search?domain=micron.com&location=India` |
| **HSBC** | other | ✅ Eightfold direct API, domain=hsbc.com, 250 India jobs | routed to `other` not eightfold/pcsx — KNOWN_PORTALS row regressed | Confirm KNOWN_PORTALS HSBC row + provider override; restore Eightfold/PCSX route |
| **Mphasis** | custom | ✅ RippleHire `mphasis.ripplehire.com` 500+ India | routed `custom` not ripplehire | Restore `ats=ripplehire` route |
| **Persistent Systems** | custom + zwayam (DUP) | ✅ Zwayam `apipersistent.zwayam.com` 300+ | duplicate portal rows; `custom` one returns 0 | De-dup KNOWN_PORTALS; keep zwayam row only |
| PayPal / Infineon / Lam Research | pcsx | (PCSX tenants) | same PCSX drift as NVIDIA/Micron | Batch re-test PCSX param/casing across all 5 |

> Strong hypothesis: a single PCSX provider change (location casing or `domain` param) broke NVIDIA+Micron+PayPal+Infineon+Lam together. Check `scraper/providers/pcsx.py` git diff since 2026-05-15.

## Bucket B — Known CF-blocked Workday (expected; need Firecrawl)
Confirmed `blocked=true` per CLAUDE.md or empty India facet. Not bugs — but candidates for Firecrawl-cloud listing.
`Engie`, `GE Aerospace`, `Bank of America`, `Ford`, `Medtronic`, `Inspire Brands`, `Hitachi Vantara` (confirmed blocked) · `Synopsys`, `Dell`, `Lloyds Banking Group`, `EA (Electronic Arts)`, `CGI`, `Carelon Global Solutions` (verify India UUID/facet vs CF block).

## Bucket C — `ats=other` / JS-opaque (re-crack via Firecrawl Cloud → save endpoint)
No direct route configured; Docker-off + local Firecrawl → 0. Best ROI for the cloud key.
`Uber`, `Walmart`, `Amdocs`, `Virtusa`, `Mu Sigma`, `Ola Electric`, `Syneriq Global`, `Mondee Holdings`, `HCL Software`, `Sanas`, `Mankind Pharma`, `Coromandel International`
Consulting/Finance/Realty (many fresher-relevant): `BDO India`, `EY Parthenon`, `Kearney`, `L.E.K. Consulting`, `Oliver Wyman`, `Simon-Kucher & Partners`, `Strategy& (PwC)`, `Takshashila Consulting`, `Avendus Capital`, `Premji Invest`, `UBS`, `SBI Mutual Fund`, `Integrow Asset Management`, `IndusInd Bank`, `FinIQ`, `CK Birla Group`, `Lodha Ventures`, `Lodha Group`, `Arvind SmartSpaces`, `Tata Administrative Services`.

## Bucket D — Darwinbox (need CF cookies)
`IIFL Finance`, `Flipkart` — provider built; needs `DARWINBOX_CF_BM` + `DARWINBOX_SESSION` env (browser devtools → `alljobs` POST → Copy as cURL; cookies expire ~30 min, IP-bound).

## Bucket E — Single-ATS 0 (verify each route/param)
| Company | ATS | Check |
|---|---|---|
| Societe Generale | smartrecruiters | company-id / `?country=in` correctness |
| Standard Chartered Bank | taleo | confirmed CF-ish blocked; Firecrawl |
| Syngene | sap_jobs2web_html | `locationsearch=india` param + JD drop rate |
| CNHI | sap | India filter |
| TotalEnergies | avature | JS / Firecrawl |
| Schneider Electric | phenom_api | tenant/endpoint (was active earlier) |
| Waaree Group | waaree_static | static snapshot stale? |
| Stellantis | custom | route |
| Black Brix | blackbrix_jobs | provider output |

---

## Suggested order of work
1. **PCSX regression** (Bucket A, 5 companies, one likely root cause) — highest ROI, likely one-line fix.
2. **HSBC / Mphasis / Persistent routing regressions** — KNOWN_PORTALS row + override repair + de-dup.
3. **Bucket C re-cracks via Firecrawl Cloud** — capture endpoints into KNOWN_PORTALS (fresher-relevant consulting/finance first).
4. **Bucket E** param verification.
5. Bucket B/D = accept as blocked unless Firecrawl/cookies pursued.

**Do not** record official company counts for these until a real `csv_importer.py` load (per COMPANY RUN HEALTH TRACKING).
