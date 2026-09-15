# Codex Handoff — ATS Crack Session
**Date:** 2026-04-30  
**Repo:** `/Users/incognito/firecrawl_Supabase`  
**Goal:** Crack 8 company career portals — get direct ATS API access for each, persist to registries so every future run gets jobs automatically.

**Status:** Historical handoff. The targeted crack session is complete; do not use this file as the active task list. Current operating guidance lives in `CLAUDE.md`, current portal status lives in `KNOWN_PORTALS.md`, and chronological evidence lives in `RUN_HISTORY.md`.

---

## Current Agent Policy — Company Count Tracking

Official company job-count and scraper-health tracking happens **only after final Supabase load** for each company.

- Treat scrape-only counts as provisional local evidence only.
- During Phase 1 scrape-only runs, prefer `SCRAPE_DIAGNOSTICS_DISABLED=1` so provisional counts do not write to Supabase diagnostics.
- After enrichment and real `csv_importer.py` upload, use importer-written diagnostics as the source of truth.
- Per loaded company, report `raw_jobs`, `saved_new`, enriched percent, skill drift, unknown location rows, and status/reason.
- If a company fails before final load, track it as a pipeline issue, not as official hiring-volume history.

---

## Current Agent Policy — Change Discipline

Prefer running and reusing the existing pipeline code, configuration, CLI flags, scripts, and diagnostics before changing implementation.

- Do not write or modify code by default during scraper runs or pipeline iteration.
- First try existing commands, env flags, providers, importer dry-runs, logs, and Supabase diagnostics.
- Only propose a code change after a concrete failure is observed and the existing code/config cannot handle it safely.
- Before writing code, discuss the failure, root cause, options, and tradeoffs with the user, then wait for explicit approval.
- User-requested documentation updates are allowed, but implementation files should stay untouched unless approved.

---

## Token-Expiry Handoff (2026-05-13)

This section is the important fresh handoff from the latest Codex session. Weekly token budget was close to expiry, so the key state is captured here explicitly for Claude to continue from.

### Operating rule for the current crack-hunt phase

- **Do not block on tests.**
- If an endpoint **looks like the correct ATS/XHR endpoint**, capture it in `KNOWN_PORTALS.md`, `portal_reader.py`, and/or the relevant provider/registry and **move forward immediately**.
- **Testing is deferred.** The current priority is to capture as many durable endpoints / domains / site numbers / location IDs / ATS routes as possible.
- If `main.py` hangs or a full smoke run is flaky, that is **not** a blocker for promotion during this phase.

### Firecrawl usage model now approved

- Firecrawl cloud was actually used in this session, not just Docker.
- Discovery should now follow: **`map -> selective scrape -> save direct route`**
- Implementation lives in:
  - [CLAUDE.md](/Users/incognito/firecrawl_Supabase/CLAUDE.md)
  - [scraper/firecrawl_client.py](/Users/incognito/firecrawl_Supabase/scraper/firecrawl_client.py)
  - [scraper/discover_endpoints.py](/Users/incognito/firecrawl_Supabase/scraper/discover_endpoints.py)
- `map_site()` is now cached. Use Firecrawl as a microscope for discovery, not as the end-state architecture.

### Durable wins from this session

Promoted or clarified direct routes:

| Company | Route | Notes |
|---------|-------|-------|
| American Express | `ats=oracle` | Migrated off broken Eightfold assumption; Oracle Candidate Experience on `egug.fa.us2.oraclecloud.com`, `siteNumber=CX_1`, India `locationId=300000000228786` |
| STMicroelectronics | `ats=eightfold` | Direct Eightfold works with `domain=stmicroelectronics.com` |
| GMR Group | `ats=sap_jobs2web_html` | Direct HTML route at `careers.gmrgroup.in/search/?q=&locationsearch=india` |
| HP (HPE) | `ats=phenom_ssr` | Correct search route uses `qcountry=India` |
| HiLabs | `ats=hilabs_careers` | Jobs embedded in `self.__next_f.push` under `groupedByPlaceAndDepartments.india["All Job Listing"]` |
| Black Brix | `ats=blackbrix_jobs` | WordPress Job Openings HTML route |

### Fresh discovery signals not yet fully promoted

| Company | Signal captured | Next move |
|---------|-----------------|-----------|
| Meta | Firecrawl cloud can read `https://www.metacareers.com/jobs/?locations[0]=India` | Capture GraphQL/XHR request; do not wait for tests |
| Vehere Interactive | Firecrawl cloud surfaced durable `/positions/...` detail URLs; direct HTTP still Cloudflare 403 | Save reusable route/provider pattern even if direct verification stays blocked |
| Mondee Holdings | Ashby board confirmed at `https://jobs.ashbyhq.com/mondee` | Find real posting API slug if it exists; board may currently be empty |
| Oliver Wyman | India listings visible via Phenom SSR | Capture the full JD/detail source; do not block on a clean end-to-end scrape |
| Morgan Stanley / Micron / Qualcomm / HSBC / PMI | Eightfold/PCSX or hosted shells still unresolved | Capture domains, downstream APIs, or browser XHR clues as soon as they appear |

### Extra note on American Express

- The route is worth trusting even if the outer full-run orchestration is imperfect.
- Live proof captured this session:
  - Oracle finder route returned `TotalJobsCount=73` for India.
  - Capped run saved 5 India jobs.
- `generic_json.py` was improved so Oracle `findReqs` routes paginate with offsets instead of stopping at page 1.

---

## Progress Update (2026-05-07)

Market Data V1 has been harvested into active mechanisms where verified. Do not run legacy notebooks/scripts directly.

| Company | Current Provider Route | Status |
|---------|-------------------------|--------|
| WESCO | `ats=oracle` (`finder=findReqs`, site `CX`) | ✅ cracked |
| CMA CGM | `ats=sap_jobs2web_html` (`optionsFacetsDD_country=IN`) | ✅ cracked |
| Volvo Group | `ats=sap_jobs2web_html` (`locationsearch=India`) | ✅ cracked |
| Michelin | `ats=michelin_astro` (`jobs.michelin.in` Astro/CXF criteria JSON) | ✅ cracked |

Validation signal:
- Direct provider smoke test returned CMA CGM `4`, Volvo Group `27`, and Michelin `19` India jobs with non-empty detail JDs.
- WESCO targeted run saved `7` jobs.
- Microsoft legacy GCS endpoint was tested and rejected as stale; keep Microsoft JS-required until fresh XHR discovery.

---

## Progress Update (2026-05-02)

Most targets in this handoff are now moved off Workday assumptions and routed to the right providers.

| Company | Current Provider Route | Status |
|---------|-------------------------|--------|
| HCL Technologies | `ats=taleo` (`/services/recruiting/v1/jobs`) | ✅ cracked |
| Intuit | `ats=talentbrew` | ✅ cracked |
| ADP | `ats=talentbrew` | ✅ cracked |
| Adobe | `ats=phenom_ssr` | ✅ cracked |
| Siemens | `ats=siemens_externaljobs` | ✅ cracked |
| Thomson Reuters | `ats=workday` | ✅ cracked |
| ABB | `ats=phenom_ssr` | ✅ cracked |
| Cisco | `ats=phenom_ssr` | ✅ cracked |
| Tech Mahindra | `ats=custom_aspnet` | ✅ cracked |
| Atlassian | `ats=custom` (`/endpoint/careers/listings`) | ✅ cracked |
| Nykaa | `ats=skima_careers` | ✅ cracked |
| Procter & Gamble | `ats=phenom_ssr` | ✅ cracked |
| H&M | `ats=hm_wp_jobs` (`/wp-json/hm/v1/sr/jobs/search`) | ✅ cracked |
| EY India (general) | `ats=yello` | ✅ cracked |
| EY India Experienced | `ats=sap_jobs2web_html` | ✅ cracked (sample run complete) |
| PepsiCo | `ats=pepsico_jobs_api` | ✅ cracked |
| Alstom | `ats=sap_jobs2web_html` | ✅ cracked |
| Deloitte India (BrassRing) | `ats=deloitte_usi` | ✅ cracked |
| Monitor Deloitte | `ats=sap_jobs2web_html` | ✅ cracked (sample run complete) |
| Deloitte India | `ats=deloitte_usi` | ✅ cracked |

Latest EY experienced validation run:
- Command: `python main.py --company "EY India Experienced" --skip-enrich --company-cap 200`
- Result: `200 raw` scraped, `102` saved after quality filters.
- Drop reason observed: many postings have description text only as `Requisition Id : <id>`.

Latest PepsiCo validation run:
- Command: `python main.py --company "PepsiCo" --skip-enrich --company-cap 500`
- Result: `206 raw` scraped, `206` saved.
- Endpoint used: `GET https://www.pepsicojobs.com/api/jobs?page=N&sortBy=relevance&descending=false&internal=false&country=India`

Latest Alstom validation run:
- Command: `python main.py --company "Alstom" --skip-enrich --company-cap 200`
- Result: `200 raw` scraped, `196` saved.
- Endpoint used: `GET https://jobsearch.alstom.com/search/?createNewAlert=false&q=&locationsearch=india&optionsFacetsDD_country=&optionsFacetsDD_department=&optionsFacetsDD_shifttype=&startrow=N`

Latest Deloitte USI validation run:
- Command: `python main.py --company "Deloitte India (BrassRing)" --skip-enrich --company-cap 300`
- Result: `268 raw` scraped, `267` saved (`1` dropped by quality gate: `desc_too_short_1chars`).
- Endpoint used: `GET https://usijobs.deloitte.com/en_US/careersUSI/SearchJobs?jobRecordsPerPage=10&jobOffset=N`

Latest Monitor Deloitte validation run:
- Command: `python main.py --company "Monitor Deloitte" --skip-enrich --company-cap 300`
- Result: `300 raw` scraped, `293` saved (`2` post-scrape drops: `missing_job_title`; `5` pre-enrich drops: short descriptions).
- Endpoint used: `GET https://southasiacareers.deloitte.com/search/?createNewAlert=false&q=&locationsearch=india&optionsFacetsDD_city=&optionsFacetsDD_customfield2=&startrow=N`

Latest Deloitte India validation run:
- Command: `python main.py --company "Deloitte India" --skip-enrich --company-cap 300`
- Result: `268 raw` scraped, `267` saved (`1` pre-enrich drop: `desc_too_short_1chars`).
- Endpoint used: `GET https://apply.deloitte.com/en_US/careersUSI/SearchJobs/?jobRecordsPerPage=10&jobOffset=N`

Latest Cisco validation signal:
- Source cURL URL: `https://careers.cisco.com/global/en/search-results?qcountry=India`
- Embedded payload confirmed in HTML: `phApp.ddo.eagerLoadRefineSearch.data.jobs` (10 jobs/page).
- India filter confirmed in payload: `ui_selections.country=["India"]`; `aggregations.country.India=226`.
- Pagination confirmed via `from=10&s=1`; job records include `jobId/reqId`, `title`, `location`, `descriptionTeaser`, `applyUrl`.

Latest Tech Mahindra validation signal:
- Old URL `https://www.techmahindra.com/en-in/careers/` is 404; new live route is `https://www.techmahindra.com/careers/`.
- Main careers page links out to `https://careers.techmahindra.com/` (`Join Us`).
- Listing page contains direct detail links: `JobDetails.aspx?JobCode=...`.
- Detail pages include full `Job Description`, `Location`, and apply controls; route is scrapeable without auth.

Latest Atlassian validation signal:
- Source cURL URL: `https://www.atlassian.com/company/careers/all-jobs?team=Interns%2CGraduates&location=&search=`
- Bundled careers code points production listings to `GET /endpoint/careers/listings`.
- Live endpoint verified: `https://www.atlassian.com/endpoint/careers/listings` returns JSON array (`82` jobs in snapshot).
- Job records include `id`, `title`, `locations[]`, `overview`, `responsibilities`, `qualifications`, `applyUrl`.
- Parser support added in `scraper/providers/generic_json.py` for `locations[]`, sectioned JD fields, and `applyUrl`.

Latest Nykaa validation signal:
- Source cURL URL: `https://careers.nykaa.com/`
- Listing is server-rendered HTML on first response (UUID links, no JS API dependency).
- Pagination confirmed with `?page=N` and `data-last-page=2` in current snapshot.
- Detail pages `/{job_uuid}` contain full JD in `.job-description-panel`.
- Provider added: `scraper/providers/skima_careers.py`; targeted run result: `11 raw`, `11 saved`.

Latest Procter & Gamble validation signal:
- Source cURL URL: `https://www.pgcareers.com/in/en/search-results?m=3&location=MUMBAI%2C%20India`
- Embedded payload confirmed in HTML: `phApp.ddo.eagerLoadRefineSearch.data.jobs`.
- Snapshot country facet shows India jobs are available (`India=23`).
- Routed in parser as `ats=phenom_ssr` with endpoint `https://www.pgcareers.com/in/en/search-results?qcountry=India`.
- Targeted run result: `23 raw`, `23 saved`.

Latest H&M validation signal:
- Source URL: `https://career.hm.com/in-en/search/?l=cou%3Ain`
- Direct jobs API route: `POST https://career.hm.com/in-en/wp-json/hm/v1/sr/jobs/search?_locale=user`
- India filter payload: `{"locations":["cou:in"],"page":N}`
- API returns `jobs[]` + `total`; snapshot observed `total=111` India jobs.
- Routed in parser as `ats=hm_wp_jobs`; no manual DevTools cURL required upfront.
- Targeted run: `python main.py --company "H&M" --skip-enrich --company-cap 300` → `111 raw`, `111 saved`.

---

## Architecture: "Crack Once, Reuse Forever"

This is a weekly India job scraper. 164 companies configured in `KNOWN_PORTALS.md`. Each company maps to an ATS provider (`workday`, `smartrecruiters`, `greenhouse`, etc.). When an ATS API endpoint is cracked, it is written to a registry file — **never rediscovered again**.

### Three registries (the permanent stores):
| File | What it holds |
|------|---------------|
| `scraper/workday_registry.json` | Per Workday tenant: `india_facet_param`, `india_uuid`, `blocked` flag |
| `scraper/generic_registry.json` | Per company: which JSON field names worked for items/title/id |
| `scraper/company_industries.json` | Company → Industry string |

### Workday scrape flow:
1. `portal_reader.py` reads `KNOWN_PORTALS.md` → builds `Portal` TypedDict per company
2. `WorkdayProvider.scrape()` in `providers/workday.py`:
   - Checks `workday_registry.json` for existing `india_uuid`
   - If missing: POSTs empty `{"appliedFacets": {}, "limit": 1, "offset": 0}` to CXS endpoint → walks facet JSON for `descriptor == "india"` UUID
   - With UUID: POSTs `{"appliedFacets": {"locationCountry": ["<UUID>"]}, "limit": 20, "offset": 0}` → pages through all jobs
   - Writes UUID to `workday_registry.json` on first discovery
3. If CF blocks the POST: marks `blocked=true` in registry → falls back to Firecrawl

### CXS endpoint pattern:
```
POST https://<tenant>.wd<N>.myworkdayjobs.com/wday/cxs/<tenant>/<career_site>/jobs
Content-Type: application/json

{"appliedFacets": {"locationCountry": ["<INDIA_UUID>"]}, "limit": 20, "offset": 0, "searchText": ""}
```

---

## Human-in-the-Loop Workflow

The human opens each career URL in Chrome → filters to India → watches Network → XHR tab for the POST to `*.myworkdayjobs.com` or SAP SuccessFactors. They paste the cURL or key params here. You implement + test + persist.

**For each company, you need to:**
1. Confirm the CXS endpoint URL (tenant + career_site slug)
2. Extract India UUID from the `appliedFacets` body OR from the empty-POST facet discovery response
3. Write the entry to `workday_registry.json`
4. Update `KNOWN_PORTALS.md` to remove `⚠️` / `🟡` status
5. Run `python main.py --company "<Company Name>"` to verify ≥5 jobs returned

---

## Completed Target Companies (Historical)

All targets in this section were either cracked or moved to their correct provider route by 2026-05-02. The details below are preserved as evidence/context, not as open work.

### 1. HCL Technologies (Workday)
- **Career URL:** https://careers.hcltech.com/go/India/9553955/
- **Known tenant:** `hcltech.wd3.myworkdayjobs.com`
- **Career_site slug:** UNKNOWN — likely `HCLTech_Careers`, `HCL_Careers`, or `hcltech`
- **Status in `KNOWN_PORTALS.md`:** `⚠️ career site name unconfirmed`
- **Status in `workday_registry.json`:** empty `{}`
- **What human provides:** Right-click the jobs XHR POST → Copy as cURL → paste here
- **What you do:**
  - Extract `career_site` slug from URL path
  - Extract India UUID from `appliedFacets.locationCountry[0]`
  - Write to `workday_registry.json`: `{"hcltech": {"india_facet_param": "locationCountry", "india_uuid": "<UUID>"}}`
  - Update `KNOWN_PORTALS.md` HCL Technologies row: fill in career_site slug + UUID, change status to ✅
  - Test: `python main.py --company "HCL Technologies"`

### 2. Intuit (TalentBrew / Avature feed)
- **Career URL:** https://jobs.intuit.com/location/india-jobs/27595/1269750/2
- **ATS reality:** Not Workday for this flow (`jobs.intuit.com` is TalentBrew; page metadata shows ATS=Avature feed)
- **Status in `workday_registry.json`:** not required for Intuit anymore
- **What human provides:** Optional only — if troubleshooting, capture XHR `POST /search-jobs/resultspost` from jobs.intuit.com
- **What you do:**
  - Use direct paginated location URL path `/location/india-jobs/27595/1269750/2/{page}`
  - Fetch per-job JD from `/job/.../{job_id}` page JSON-LD + `search-job-apply-url` meta
  - Test: `python main.py --company "Intuit"`

### 3. ADP (Happydance / TalentBrew-style)
- **Career URL:** https://jobs.adp.com/en/jobs/?mylocation=India&orderby=0&page=1&pagesize=20&rType=0&radius=100
- **ATS reality:** Not Workday in this flow (jobs.adp.com is server-rendered Happydance pages)
- **Status in `workday_registry.json`:** not required for ADP anymore
- **What human provides:** Optional only — if troubleshooting, copy page request cURL for `GET /en/jobs/?mylocation=India...` (not cookielaw.org)
- **What you do:**
  - Use India query URL above; paginate with `page=N`
  - Follow per-job detail URLs: `/en/jobs/{job_id}/{slug}/`
  - Extract JD from `Description` section and apply URL from `Apply Now` (`recruiting.adp.com`)
  - Test: `python main.py --company "ADP"`

### 4. Adobe (Phenom SSR)
- **Career URL:** https://careers.adobe.com/us/en/search-results
- **ATS reality:** Not Workday CXS for listing. Adobe careers runs Phenom SSR (`refNum=ADOBUS`, `content-us.phenompeople.com`).
- **Status in `workday_registry.json`:** not required for Adobe anymore
- **What human provides:** Optional only — if troubleshooting, capture `jobwidgetsettings` / search page request cURL from careers.adobe.com
- **What you do:**
  - Use search page SSR data (`phApp.ddo.eagerLoadRefineSearch.data.jobs`) for listings
  - Follow job detail pages at `/us/en/job/{jobSeqNo}` and extract full JD from JobPosting JSON-LD
  - Filter India via `country/location` in listing payload
  - Test: `python main.py --company "Adobe"` (or provider standalone if main is unavailable)

### 5. Siemens (Siemens ExternalJobs, not Workday)
- **Career URL:** https://jobs.siemens.com/en_US/externaljobs/SearchJobs/?42386=%5B812053%5D&42386_format=17546&listFilterMode=1&folderRecordsPerPage=6&
- **ATS reality:** Siemens uses server-rendered ExternalJobs pages (`/SearchJobs`, `/JobDetail/{id}`), not Workday CXS for this flow.
- **Status in `workday_registry.json`:** not required for Siemens anymore
- **What human provides:** Optional only — if troubleshooting, provide SearchJobs cURL (with India filter `42386=[812053]`)
- **What you do:**
  - Paginate with `folderOffset` + `folderRecordsPerPage`
  - Parse listing cards for detail links (`/JobDetail/{job_id}`)
  - Fetch detail page for full JD + apply URL (`/ApplicationMethods?folderId={job_id}`)
  - Test: `python main.py --company "Siemens"`

### 6. Thomson Reuters (Workday)
- **Career URL:** https://thomsonreuters.com/en/careers/job-search-results.html → filter India
- **Confirmed tenant:** `thomsonreuters.wd5.myworkdayjobs.com`
- **Confirmed career_site slug:** `External_Career_Site`
- **Status in `workday_registry.json`:** ✅ cracked 2026-05-01
- **Cracked details:**
  - Endpoint: `POST /wday/cxs/thomsonreuters/External_Career_Site/jobs`
  - India facet: `Location_Country`
  - India UUID: `c4f78be1a8f14da0ab49ce1162348a5e`
  - Facet count observed: `67`

### 7. ABB (Phenom SSR, not Workday)
- **Career URL:** https://careers.abb/global/en/search-results?keywords=india
- **ATS reality:** ABB uses Phenom SSR (`refNum=ABB1GLOBAL`) for listing flow, not Workday CXS.
- **Status in `workday_registry.json`:** not required for ABB
- **Cracked details:**
  - Listing payload is embedded in page HTML: `phApp.ddo.eagerLoadRefineSearch.data.jobs`
  - Detail pages: `/global/en/job/{jobId}/{title}` (JobPosting JSON-LD has full JD)
  - India facet count observed in payload: `country.India = 261`
  - Provider route: `ats=phenom_ssr`
  - Test: `python main.py --company "ABB"`

### 8. EY India (Yello / Recsolu — different workflow)
- **Career URL:** https://eyglobal.yello.co/job_boards/c1riT--B2O-KySgYWsZO1Q
- **ATS reality:** EY India listing is on Yello (Recsolu), not SuccessFactors OData.
- **Cracked details (2026-05-02):**
  - Search API: `GET https://eyglobal.yello.co/job_boards/c1riT--B2O-KySgYWsZO1Q/search`
  - India filter: `filters=30009` (Country/Region = India)
  - Pagination: `page_number=N`
  - Full JD: detail page `/jobs/{token}?job_board_id=...`
  - Provider route: `ats=yello` (`providers/yello.py`)
  - Test: `python main.py --company "EY India"`

---

## KNOWN_PORTALS.md Workday Table Format (for reference)

```markdown
| Company | Career URL | Tenant | Instance | Career Site | India Location ID | Notes |
|---------|-----------|--------|----------|-------------|-------------------|-------|
| HCL Technologies | https://careers.hcltech.com/go/India/9553955/ | hcltech | wd3 | <FILL> | <UUID> | ✅ cracked YYYY-MM-DD |
```

The `India Location ID` column value gets written to `workday_registry.json` as `india_uuid`.

---

## workday_registry.json Format

```json
{
  "Accenture": {
    "india_facet_param": "locationCountry",
    "india_uuid": "bc33aa3152ec42d4995f4791a106ed09"
  },
  "Engie": {
    "blocked": true
  }
}
```

Key = `company` field from `KNOWN_PORTALS.md` (exact match, case-sensitive).  
`india_facet_param` is almost always `locationCountry`. Occasionally `locationRegionStateIso2`.

---

## Files to Edit

No active edits remain from this handoff. Provider code and portal/industry mappings were already added during the crack session.

---

## Historical Test Commands

```bash
cd /Users/incognito/firecrawl_Supabase/scraper

# Test one company at a time — Docker must be running, LM Studio OFF
python main.py --company "HCL Technologies"
python main.py --company "Intuit"
python main.py --company "ADP"
python main.py --company "Adobe"
python main.py --company "Siemens"
python main.py --company "Thomson Reuters"
python main.py --company "ABB"
python main.py --company "EY India"

# Success = log shows jobs scraped/saved and jobs.json written under:
# All_CSV_Outputs_thru_firecrawl/<Company_Name>/Outputs/YYYY_MM_DD/jobs.json
```

---

## What NOT to Do

- Do NOT call any cloud AI API — LM Studio only at `http://localhost:1234/v1`
- Do NOT use `crawl()` from Firecrawl — banned in this project
- Do NOT add fields outside the canonical schema in `scraper/schema.py`
- Do NOT amend existing registry entries unless you have a verified replacement route

---

## Session Context

This handoff no longer blocks enrichment/upload. For the current weekly run, use the commands in `CLAUDE.md`:

```bash
# Phase 1 — Docker on, LM Studio off
python main.py --skip-enrich --scope global --global-cap 2000

# Phase 2 — LM Studio on, Docker off
python main.py --enrich-only

# Phase 3 — Supabase upsert
python csv_importer.py
```
