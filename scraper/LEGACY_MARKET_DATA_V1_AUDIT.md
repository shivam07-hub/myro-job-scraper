# Legacy Market Data V1 Audit

Date: 2026-05-07

Purpose: capture useful company intelligence from `Market Data_V1_of_Scrapers/` before treating that folder as historical reference. The active scraper should continue to use `KNOWN_PORTALS.md` plus reusable providers under `scraper/providers/`, not standalone notebooks/scripts.

## Runtime Dependency Check

- Active orchestration no longer calls `Market Data_V1_of_Scrapers/`.
- Active routing is `KNOWN_PORTALS.md` -> `portal_reader.py` -> `providers/registry.py` -> provider modules.
- Legacy company scripts are useful only as route hints. When a route is verified, move it into a reusable provider and document it in `KNOWN_PORTALS.md` and `RUN_HISTORY.md`.

## Recovered On 2026-05-07

| Company | Legacy signal | Active mechanism now |
|---|---|---|
| WESCO | Oracle HCM host `eklm.fa.us2.oraclecloud.com`, site `CX`, India location ID `300000000302954` | Added to ORACLE HCM section; `generic_json` now preserves Oracle site number in candidate URLs; targeted run saved 7 jobs |
| CMA CGM | Jobs2Web HTML route existed, but old `country=India` query was stale | Updated to `optionsFacetsDD_country=IN`; routed to `sap_jobs2web_html`; smoke test returned 4 India jobs with full JDs |
| Volvo Group | Jobs2Web HTML listing at `jobs.volvogroup.com/search/?locationsearch=India` | Routed to `sap_jobs2web_html`; smoke test returned 27 India jobs with full JDs |
| Michelin | Astro/CXF India criteria JSON on `jobs.michelin.in/job-offer-result-list` | Added `michelin_astro` provider; smoke test returned 19 India jobs with full JDs |

## Stale Or Rejected Legacy Signals

| Company | Legacy signal | Current decision |
|---|---|---|
| Microsoft | Old GCS endpoint `gcsservices.careers.microsoft.com/search/api/v1/search?...loc=India` | Stale: SSL hostname mismatch and `curl -k` returns an Azure test 404 page, not jobs JSON. Keep as JS-required until fresh XHR is found. |
| CMA CGM | Old `country=India` query | Stale: returns global jobs and US/Indiana false positives. Replaced with `optionsFacetsDD_country=IN`. |
| Market Data scripts overall | Standalone notebooks/scripts with bespoke output handling | Do not run directly. Promote only verified route details into providers. |

## Legacy Company Coverage

| Company | Status in active system after this audit | Notes |
|---|---|---|
| Accenture | Active | Workday direct route. |
| Air France | Broken | Firecrawl timeout; needs fresh route discovery. |
| Airbus | Active | Workday direct route. |
| Alstom | Active direct | `sap_jobs2web_html`. |
| American Express | Pending | Eightfold API returns 0 India jobs; Firecrawl fallback only. |
| Apple | Pending | JS-required; old API route stale. |
| AstraZeneca | Active fallback | Firecrawl working route. |
| Atlassian | Active direct | Custom JSON endpoint `/endpoint/careers/listings`. |
| Baker Hughes | Excluded/pending | No India Workday UUID found. |
| CMA CGM | Active direct | Promoted 2026-05-07 via Jobs2Web country facet. |
| CNHI | Active fallback | India-filtered search URL, Firecrawl route. |
| Capgemini | Active direct | Custom Azure API. |
| Chanel | Active | Workday direct route, low India count. |
| Cognizant | Active fallback | India XML/feed route documented; Firecrawl output historically low. |
| Continental | Active | SmartRecruiters route. |
| Dell | Active/pending validation | Workday tenant confirmed; keep in active Workday registry path. |
| Eli Lilly | Active fallback | Migrated from Workday to Phenom page; Firecrawl route. |
| Engie | Active fallback | Workday blocked/fallback route. |
| Fidelity Investments | Active | Workday direct route. |
| Goldman Sachs | Login-required | Do not automate until public route changes. |
| Google | Active fallback | Firecrawl route; direct route still worth future XHR inspection. |
| HCL Technologies | Active direct | Taleo/SAP Jobs2Web v1 REST route. |
| IBM | Login-required | Do not automate until public route changes. |
| Infosys | Active direct | Infosys gateway JSON route. |
| LDC (Louis Dreyfus) | Active | SmartRecruiters route. |
| L'Oreal | Active fallback | Phenom URL route via Firecrawl. |
| MSCI | Broken | Old careers domain 404; Workday slug unknown. |
| Mastercard | Excluded/pending | No India UUID found in Workday tenant. |
| Michelin | Active direct | Promoted 2026-05-07 via `michelin_astro`. |
| Microsoft | Pending | Legacy GCS route stale; keep JS-required. |
| Morgan Stanley | Pending | Eightfold API 403; Firecrawl fallback only. |
| Novartis | Active | Workday direct route. |
| Philips | Broken | Needs current India-filtered URL. |
| RTX | Excluded | Confirmed zero India jobs. |
| STMicroelectronics | Pending | Eightfold API 404; Firecrawl fallback only. |
| Salesforce | Active | Workday direct route. |
| Sanofi | Active | Workday direct route. |
| Schneider Electric | Active direct | Phenom/iCIMS JSON API. |
| ServiceNow | Active | SmartRecruiters route. |
| Shell | Active | Workday direct route. |
| Solvay | Excluded | Confirmed no India positions. |
| Stellantis | Active fallback | Firecrawl route. |
| Stripe | Active | Greenhouse route. |
| Syngenta | Excluded | SmartRecruiters returned 0 India postings. |
| Synopsys | Active fallback | Workday blocked/fallback route. |
| TCS | Deprioritized | Antibot/document block. |
| Technip Energies | Active direct | Oracle HCM finder route. |
| TotalEnergies | Pending | Avature JS-required route. |
| Volkswagen | Excluded | False India matches were Indiana, US. |
| Volvo Group | Active direct | Promoted 2026-05-07 via Jobs2Web HTML. |
| WESCO | Active direct | Promoted 2026-05-07 via Oracle HCM finder route. |
| Wells Fargo | Active | Workday direct route. |
| Wipro | Active direct | Taleo v1 REST route. |

## Cleanup Recommendation

`Market Data_V1_of_Scrapers/` is not required at runtime. Keep it only until this audit is accepted, then archive/delete the folder to avoid future agents mistaking notebooks for the source of truth. The source of truth after this audit is:

- `KNOWN_PORTALS.md` for company route status.
- `RUN_HISTORY.md` for evidence and command history.
- `scraper/providers/` for reusable implementation.
- `scraper/company_industries.json` for industry metadata.
