    # KNOWN_PORTALS.md — Careers Portal Registry
**Last verified: 2026-05-14.** Crack session history → `RUN_HISTORY.md`.

Each entry: Company | Human Careers URL | ATS Platform | Scraping API / Endpoint | India Filter Param | Status | Notes

---

## HOW TO READ THIS FILE

| Column | Meaning |
|--------|---------|
| **Careers URL** | Human-visible page — what you'd visit in a browser |
| **ATS** | Underlying platform (Workday, Greenhouse, SmartRecruiters, etc.) |
| **Scraping Endpoint** | The actual API/URL to hit programmatically |
| **India Filter** | How to narrow to India jobs in the API |
| **Status** | `✅ working` / `⚠️ broken` / `🔴 no-india-jobs` / `🟡 js-required` / `🔒 login-required` |

---

## DISCOVERY CAPTURE — MANAGEMENT RECRUITER ATS ENDPOINTS
*Captured with Firecrawl cloud on 2026-05-21. This section is intentionally non-active: rows here preserve endpoints and evidence from paid discovery credits. Promoted rows appear again in their proper ATS sections/provider registry; parked rows stay here for the next cracking pass.*
*Raw saved artifacts: `logs/firecrawl_ats_discovery_mgmt_recruiters_20260521_raw.json`, `logs/firecrawl_ats_discovery_mgmt_recruiters_20260521_scrapes.json`, `logs/firecrawl_ats_discovery_mgmt_recruiters_20260521_validated.json`.*

| Company | Careers URL | ATS / Platform | Durable Endpoint / Route | Status |
|---------|-------------|----------------|--------------------------|--------|
| Asian Paints | https://careers.asianpaints.com/ | SAP Jobs2Web HTML | `GET https://careers.asianpaints.com/search/?q=&locationsearch=india&startrow=N` | ✅ promoted 2026-05-21 — SAP section/provider registry; full JD validated |
| Bajaj Auto | https://careers.bajajauto.com/BajajAutoCreditLimited/ | SAP Jobs2Web HTML | `GET https://careers.bajajauto.com/BajajAutoCreditLimited/search/?q=&locationsearch=india&startrow=N` | ✅ promoted 2026-05-21 — BACL board; main Bajaj Auto corporate scope still optional to verify |
| AB InBev | https://abinbev.wd1.myworkdayjobs.com/IND | Workday CXS | `POST https://abinbev.wd1.myworkdayjobs.com/wday/cxs/abinbev/IND/jobs` | ✅ promoted 2026-05-21 — Workday section/provider registry; CXS detail JDs work. Also found `https://ab-inbev-gcc.sensehq.com/careers` with 10 SSR GCC jobs |
| Mondelez | https://mdlz.wd3.myworkdayjobs.com/External | Workday CXS | `POST https://mdlz.wd3.myworkdayjobs.com/wday/cxs/mdlz/External/jobs` with `searchText=India` | ✅ promoted 2026-05-21 — Workday section/provider registry; CXS detail JDs work |
| Kraft Heinz | https://heinz.wd1.myworkdayjobs.com/KraftHeinz_Careers | Workday CXS | `POST https://heinz.wd1.myworkdayjobs.com/wday/cxs/heinz/KraftHeinz_Careers/jobs` with `searchText=India` | ✅ promoted 2026-05-21 — Workday section/provider registry; CXS detail JDs work |
| Tata Consumer Products | https://careers.tataconsumer.com/content/People/ | SAP Jobs2Web HTML | `GET https://careers.tataconsumer.com/search/?q=&locationsearch=india&startrow=N` | ✅ promoted 2026-05-21 — SAP provider now accepts bare `IN` listing locations |
| Sun Pharma | https://careers.sunpharma.com/ | SAP Jobs2Web HTML | `GET https://careers.sunpharma.com/search/?q=&locationsearch=india&startrow=N` | ✅ promoted 2026-05-21 — SAP section/provider registry. Do not use `jobs.sunpharma.com`; that TalentBrew board is US/CA scoped |
| Syngene | https://careers.syngeneintl.com/viewalljobs/ | SAP Jobs2Web HTML | `GET https://careers.syngeneintl.com/search/?q=&locationsearch=india&startrow=N` | ✅ promoted 2026-05-21 — SAP section/provider registry; Bangalore jobs with full JDs |
| Axis Bank | https://www.axis.bank.in/careers | RippleHire | `POST https://axisbank.ripplehire.com/candidate/candidatejobsearch`; detail `GET /candidate/candidatejobdetail`; token `WIXhCuz0XRZ7H0GZCwjJ` | ✅ promoted 2026-05-21 — RippleHire provider supports `jobVoList` plus detail JD fetch |
| Tata Steel | https://www.tatasteel.com/careers/work-with-us/tata-steel-india-careers/ | RippleHire | `POST https://tatasteel.ripplehire.com/candidate/candidatejobsearch`; detail `GET /candidate/candidatejobdetail`; token `kYAz91uy1lFDi6FeSiRZ` | ✅ promoted 2026-05-21 — RippleHire provider supports `jobVoList` plus detail JD fetch |
| Kotak Mahindra Bank | https://hcbt.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs | Oracle HCM Candidate Experience | `GET https://hcbt.fa.em2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions?...finder=findReqs;siteNumber=CX_1001,...` | ✅ promoted 2026-05-21 — Oracle CE route works; alternate site numbers: `CX` and `CX_1` |
| HDFC Ergo | https://hdfcergocareers.peoplestrong.com/ | PeopleStrong Candidate Portal | Rendered route `https://hdfcergocareers.peoplestrong.com/job/joblist`; likely API `POST /api/cp/rest/altone/jobs/v1?offset=N&limit=M` | 📌 parked 2026-05-21 — Firecrawl renders joblist/details with full JD; direct PeopleStrong API still returns 500/session-expired until payload/session shape is solved |
| NPCI | https://careers.npci.org.in/jobs/Careers | Zoho Recruit SSR HTML | `GET https://careers.npci.org.in/jobs/Careers`; `page_id=190737000000336688` | ✅ promoted 2026-05-21 — Zoho provider builds company-specific apply URLs |
| ClearTax / Clear | https://www.clear.in/s/careers | Darwinbox | `POST https://clear.darwinbox.in/ms/candidateapi/job/alljobs?companyId=main` | 📌 parked 2026-05-21 — Firecrawl rendered Darwinbox page says 27 open jobs; direct API is Cloudflare 403 without browser cookies |
| Juspay | https://juspay.io/careers | Astro SSR embedded jobs | `GET https://juspay.io/careers` | ✅ promoted 2026-05-21 — custom Astro parser extracts embedded jobs and JD text |
| Waaree Group | https://www.waaree.com/careers/ | Static careers page | `GET https://www.waaree.com/careers/` | ✅ promoted 2026-05-21 — rendered/static provider parses 3 on-page roles |
| Policybazaar | https://www.policybazaar.com/careers/ | Static careers form | `POST https://www.policybazaar.com/careers/submitformdetails.php` | 📌 static categories only 2026-05-21 — no discrete job API found; page exposes generic role categories and resume upload form |
| Dabur | https://www.dabur.com/join-us/explore-opportunities | Custom careers page | `GET https://www.dabur.com/join-us/explore-opportunities` | 📌 parked 2026-05-21 — Firecrawl now renders the page, but it currently reports no matching jobs |
| Amul / GCMMF | https://careers.amul.in/ | Custom ASP.NET | `GET https://careers.amul.in/WebForms/Web_Curr_Vacancies.aspx` | 📌 partial 2026-05-21 — map found current-vacancies/detail pages, but direct page currently shows warning/popup shell and no parseable vacancy table |
| Lava International | https://www.lavamobiles.com/career | Next.js/custom | `GET https://www.lavamobiles.com/career/joblist` | 📌 partial 2026-05-21 — joblist route found; JS/API still needs bundle inspection |
| Modelama Exports | https://www.modelama.com/careers | Adrenalin CandidateMAX | `https://peoplesync.myadrenalin.com/CandidateMAX/#/?CompanyID=MODELAMA` | 📌 blocked 2026-05-21 — Firecrawl-rendered CandidateMAX returns internal system error |

---

## WORKDAY COMPANIES
*API pattern: `POST https://{tenant}.{instance}.myworkdayjobs.com/wday/cxs/{tenant}/{career_site}/jobs`*
*Body: `{"appliedFacets": {"<facet_param>": ["<india_uuid>"]}, "limit": 20, "offset": 0, "searchText": ""}`*
*Note: facet_param varies per tenant — scraper auto-discovers it alongside the India UUID.*
*Some tenants return 303 (Cloudflare) — scraper falls back to Firecrawl automatically.*

| Company | Careers URL | Tenant | Instance | Career Site | India Jobs | Status |
|---------|-------------|--------|----------|-------------|-----------|--------|
| Accenture | https://www.accenture.com/us-en/careers | accenture | wd103 | AccentureCareers | ~800+ | ✅ working |
| Airbus | https://www.airbus.com/en/careers | ag | wd3 | Airbus | ~150 | ✅ working |
| Chanel | https://cc.wd3.myworkdayjobs.com/ChanelCareers | cc | wd3 | ChanelCareers | 1 | ✅ working (1 India job only) |
| CrowdStrike | https://crowdstrike.wd5.myworkdayjobs.com/crowdstrikecareers | crowdstrike | wd5 | crowdstrikecareers | 66 | ✅ CRACKED 2026-05-21 — Workday CXS works cookie-free at `/wday/cxs/crowdstrike/crowdstrikecareers/jobs`; provider fetched 66 India jobs with full JDs |
| Workday | https://workday.wd5.myworkdayjobs.com/Workday | workday | wd5 | Workday | 3+ validated | ✅ CRACKED 2026-05-21 — Workday CXS works cookie-free at `/wday/cxs/workday/Workday/jobs`; registry stores India UUID (`Location_Country`); live probe fetched India roles with full CXS JDs |
| Sprinklr | https://sprinklr.wd1.myworkdayjobs.com/careers | sprinklr | wd1 | careers | 3+ validated | ✅ CRACKED 2026-05-21 — direct Workday CXS works with India facet from registry; live probe returned India jobs with full JDs |
| Automation Anywhere | https://automationanywhere.wd5.myworkdayjobs.com/AutomationAnywhereJobs | automationanywhere | wd5 | AutomationAnywhereJobs | 3+ validated | ✅ CRACKED 2026-05-21 — direct Workday CXS route works despite stale public Jobvite link; registry stores India UUID; full JDs fetched |
| Vanguard Group | https://vanguard.wd5.myworkdayjobs.com/vanguard_external | vanguard | wd5 | vanguard_external | 5+ validated | ✅ CRACKED 2026-05-21 — no India facet needed; registry uses `searchText=India` and Python `is_india()` filter; live probe fetched India roles with full JDs |
| KLA Corporation | https://kla.wd1.myworkdayjobs.com/Search | kla | wd1 | Search | 3+ validated | ✅ CRACKED 2026-05-21 — direct Workday CXS route works with registry `Country` India UUID; full JDs fetched |
| Carrier Global | https://carrier.wd5.myworkdayjobs.com/jobs | carrier | wd5 | jobs | 3+ validated | ✅ CRACKED 2026-05-21 — direct Workday CXS route works with registry `location_Country` India UUID; full JDs fetched |
| AB InBev | https://abinbev.wd1.myworkdayjobs.com/IND | abinbev | wd1 | IND | 33 | ✅ CRACKED 2026-05-21 — discovery promoted; direct Workday CXS route with `searchText=India`; detail CXS JDs work |
| Mondelez | https://mdlz.wd3.myworkdayjobs.com/External | mdlz | wd3 | External | 141 | ✅ CRACKED 2026-05-21 — discovery promoted; direct Workday CXS route with `searchText=India`; detail CXS JDs work |
| Kraft Heinz | https://heinz.wd1.myworkdayjobs.com/KraftHeinz_Careers | heinz | wd1 | KraftHeinz_Careers | 70 | ✅ CRACKED 2026-05-21 — discovery promoted; direct Workday CXS route with `searchText=India`; detail CXS JDs work |
| Genpact | https://genpact.wd108.myworkdayjobs.com/External_Careers | genpact | wd108 | External_Careers | 5+ validated | ✅ CRACKED 2026-05-22 — Firecrawl revealed Workday tenant from `careers.genpact.com`; direct CXS works with `searchText=india`; detail CXS JDs work |
| ThoughtSpot | https://thoughtspot.wd5.myworkdayjobs.com/careers | thoughtspot | wd5 | careers | 3+ validated | ✅ CRACKED 2026-05-22 — Firecrawl search surfaced Workday tenant; direct CXS works with registry `searchText=India`; detail CXS JDs work; no Firecrawl needed |
| Cohesity | https://cohesity.wd5.myworkdayjobs.com/Cohesity_Careers | cohesity | wd5 | Cohesity_Careers | 3+ validated | ✅ CRACKED 2026-05-22 — Firecrawl search surfaced Workday tenant; direct CXS works with `locationCountry` India UUID; detail CXS JDs work; no Firecrawl needed |
| Engie | https://jobs.engie.com | engie | wd3 | ENGIE | ? | ✅ working — Firecrawl fallback uses careers_url (fixed 2026-04-11) |
| Fidelity Investments | https://jobs.fidelity.com | fmr | wd1 | FidelityCareers | ~80 | ✅ working |
| Mastercard | https://careers.mastercard.com/us/en/search-results | ⚠️ NOT_WORKDAY | wd1 | ⚠️ | ? | 🔴 ATS corrected 2026-05-14 — NOT Workday; confirmed TalentBrew (PHPPPE_ACT/PHPPPE_GCC/PLAY_SESSION cookies); moved to BFSI section; `ats=talentbrew`; India URL: `?LocationPath=1269750` |
| Novartis | https://www.novartis.com/careers | novartis | wd3 | Novartis_Careers | ~115 | ✅ working — career_site slug corrected 2026-04-12; broad mode fetches all India jobs |
| Salesforce | https://www.salesforce.com/company/careers/locations/india/ | salesforce | wd12 | External_Career_Site | ~169 | ✅ working — 169 India jobs scraped 2026-04-11 |
| Sanofi | https://www.sanofi.com/en/careers | sanofi | wd3 | SanofiCareers | ~300+ | ✅ working |
| Shell | https://www.shell.com/careers | shell | wd3 | ShellCareers | ~188 | ✅ working |
| Synopsys | https://careers.synopsys.com/ | synopsys | wd1 | SynopsysCareers | ? | ✅ working — Firecrawl fallback uses careers_url (fixed 2026-04-11) |
| Wells Fargo | https://www.wellsfargojobs.com/en/jobs/ | wf | wd1 | WellsFargoJobs | ~300+ | ✅ working |
| Philips | https://www.careers.philips.com/global/en | philips | wd3 | jobs-and-careers | ~48 | ✅ working — uses locationHierarchy1 facet (not locationCountry); facet + UUIDs in workday_registry.json |
| BrowserStack | https://www.browserstack.com/careers | browserstack | wd3 | External | 3+ validated | ✅ CRACKED 2026-05-22 — no India facet UUID, but direct Workday CXS works with registry `searchText=India`; Python `is_india()` filter returns India remote/Mumbai roles with full JDs; no Firecrawl needed |
| Baker Hughes | https://careers.bakerhughes.com/global/en/search-results?qcountry=India | bakerhughes | wd5 | BakerHughes | ? | 🔴 no India UUID — India facet not found in tenant; skip |
| Dell | https://jobs.dell.com/en-us/search-jobs/India | dell | wd1 | External | ? | ✅ Workday tenant confirmed via XHR inspection 2026-04-16 |
| Deutsche Bank | https://careers.db.com | db | wd3 | DBWebsite | ~521 | ✅ cracked 2026-04-29 — Country facet UUID in workday_registry.json; 521 India jobs |
| MSCI | https://careers.msci.com/job-search | ⚠️ NOT_WORKDAY | — | — | — | ✅ CRACKED 2026-05-15 — NOT Workday; Algolia search (appId=RVMOB42DFH, apiKey=629e647c6a9a8b542fb1022001313a7e, index=production__mscicare2201__sort-rank); 29 India jobs (Mumbai 25, Coimbatore 2, Pune 2); full JD in `description` field; apply_url → globalcareers-msci.icims.com; `ats=msci_algolia` in portal_reader.py; no auth needed |
| Coca-Cola | https://www.coca-colacompany.com/careers | coke | wd1 | coca-cola-careers | 68 | ✅ CRACKED 2026-05-13 — searchText="india" mode (no India UUID needed); override in workday_registry.json; is_india() Python filter applied |
| Nike | https://careers.nike.com/jobs?q=india | nike | wd1 | nke | 46 | ✅ CRACKED 2026-05-13 — searchText="india" mode (no India UUID in tenant); override in workday_registry.json; is_india() Python filter applied |
| Intel | https://jobs.intel.com/en/search | intel | wd1 | External | ~84 | ✅ working — searchText="india" mode (no India UUID in tenant); override in workday_registry.json; is_india() Python filter applied |
| State Street | https://careers.statestreet.com | statestreet | wd1 | Global | 351 | ✅ working — 351 India jobs scraped with full JDs via CXS; probed 2026-04-19 |
| DBS Bank | https://www.dbs.com/dbstechindia/index.html | dbs | wd3 | DBS_Careers | 285 | ✅ working — 285 India jobs scraped with full JDs via CXS; probed 2026-04-19 |
| BlackBerry | https://www.blackberry.com/us/en/company/careers | bb | wd3 | BlackBerry | 5+ | ✅ CRACKED 2026-05-07 — India UUID in `workday_registry.json` (`Country=c4f78be1...`); inventory probe returned live India jobs; targeted run scraped 5 raw with 5/5 JDs |
| Lloyds Banking Group | https://www.lloydsbankinggroup.com/careers | lbg | wd3 | LBG_Careers | ~128 total | 🟡 Workday CXS confirmed wd3/LBG_Careers — India UUID TBD; probed 2026-04-19 |
| EA (Electronic Arts) | https://www.ea.com/careers | ea | wd5 | EA_Global | ? | 🟡 Workday confirmed via FC scrape — CXS returns 401; Firecrawl fallback via careers_url; probed 2026-04-19 |
| GE Aerospace | https://www.gecareers.com | ge | wd5 | GE_ExternalSite | ? | 🟡 Workday confirmed via FC scrape — CXS returns 422 (Cloudflare); Firecrawl fallback via careers_url; probed 2026-04-19 |
| Medtronic | https://www.medtronic.com/en-us/about/careers.html | medtronic | wd3 | MedtronicCareers | ? | 🟡 Workday confirmed via FC scrape — CXS returns 422 (Cloudflare); Firecrawl fallback via careers_url; probed 2026-04-19 |
| Bank of America | https://careers.bankofamerica.com | bankofamerica | wd1 | Global | ? | 🟡 Workday confirmed via FC scrape — CXS returns 422 (Cloudflare); Firecrawl fallback via careers_url; probed 2026-04-19 |
| Inspire Brands | https://careers.inspirebrands.com | inspirebrands | wd1 | InspireBrandsCareers | ? | 🟡 Workday confirmed via FC scrape — CXS returns 422 (Cloudflare); Firecrawl fallback via careers_url; probed 2026-04-19 |
| Ford | https://www.ford.com/careers/ | fordcareers | wd12 | Ford_Careers | ? | 🟡 Workday confirmed via FC scrape — CXS 422; FC fallback via `https://fordcareers.wd12.myworkdayjobs.com/en-US/Ford_Careers?q=india`; probed 2026-04-19 |
| Hitachi Vantara | https://hitachivantara.wd3.myworkdayjobs.com/HitachiVantaraCareers | hitachivantara | wd3 | HitachiVantaraCareers | ? | 🟡 Workday confirmed — CXS 422 blocked; FC fallback via en-US URL with India filter; probed 2026-04-19 |
| Thomson Reuters | https://thomsonreuters.com/en/careers.html | thomsonreuters | wd5 | External_Career_Site | 67 | ✅ cracked 2026-05-01 — CXS POST confirmed from browser (`/wday/cxs/thomsonreuters/External_Career_Site/jobs`); India facet `Location_Country=c4f78be1a8f14da0ab49ce1162348a5e` |
| CGI | https://www.cgi.com/en/careers | cgicareers | wd3 | CGI | ? | 🟡 Workday confirmed (`cgicareers.wd3/CGI`) — CXS 422; FC fallback via careers_url; probed 2026-04-19 |
| Samsung | https://sec.wd3.myworkdayjobs.com/Samsung_Careers | sec | wd3 | Samsung_Careers | ? | ✅ Workday CXS confirmed from browser XHR — tenant=sec, career_site=Samsung_Careers, India facet=locations UUID=0c974e8c1228010867596ab21b3c3469; added to workday_registry.json 2026-05-14 |
| Carelon Global Solutions | https://www.carelonglobal.in/careers | elevancehealth | wd1 | carelonglobal_in | ? | 🟡 Workday confirmed (`elevancehealth.wd1/carelonglobal_in`) — only 7 total jobs, no India UUID found; FC fallback via careers_url; probed 2026-04-19 |
| Target | https://careers.target.com/jobs | target | wd5 | TargetCareers | ~265 | ✅ working — searchText="india" mode (no India UUID in tenant); override in workday_registry.json; is_india() Python filter applied |
| Broadcom | https://careers.broadcom.com/careers?query=&location=India | broadcom | wd1 | ⚠️ career_site unconfirmed | ? | 🟡 Workday suspected — all career_site slugs 404; broadcom.wd1 tenant confirmed; correct slug TBD (try: External, BroadcomCareers, BCICareers); FC-blocked; probed 2026-04-19 |
| 3M | https://www.3m.com/3M/en_US/careers-us/ | 3m | wd1 | Search | 81 | ✅ working — 81 India jobs, 100% JD; facet=Location_Country; scraped 2026-04-19 |
| NXP Semiconductors | https://careers.nxp.com | nxp | wd3 | careers | 161 | ✅ working — 161 India jobs, 100% JD; facet=Location_Country; scraped 2026-04-19 |
| Autodesk | https://careers.autodesk.com | autodesk | wd1 | Ext | 111 | ✅ working — 111 India jobs, 100% JD; facet=locationCountry; scraped 2026-04-19 |
| Roche | https://careers.roche.com | roche | wd3 | roche-ext | 1 | 🔴 only 1 India job — low volume, skip; locations facet uuid=54c59631...; verified 2026-04-19 |
| ING Bank | https://careers.ing.com | ing | wd3 | ICSGBLCOR | 0 | 🔴 no India locations in ICSGBLCOR portal; skip; verified 2026-04-19 |
| Barclays | https://search.jobs.barclays | barclays | wd3 | External_Career_Site_Barclays | 500+ | ✅ working — 500 India jobs (cap), 100% JD; 12 India office UUIDs via locations facet; scraped 2026-04-19 |
| Maersk | https://www.maersk.com/careers/vacancies | maersk | wd3 | Maersk_Careers | 97 | ✅ working — 97 India jobs, 100% JD; 26 India office UUIDs via locations facet; scraped 2026-04-19 |
| DXC Technology | https://careers.dxc.com | dxctechnology | wd1 | DXCJobs | 211 | ✅ working — 211 India jobs, 100% JD; facet=locationCountry; scraped 2026-04-19 |
| Juniper Networks | https://www.juniper.net/us/en/company/careers.html | ⚠️ HPE merger Jan 2024 | — | — | ? | ⚠️ Acquired by HPE (closed Jan 2024) — careers likely redirect to HPE Workday (`hpe.wd3`); verify if Juniper-branded portal still active or redirect to HPE; probed 2026-04-19 |

---

## SMARTRECRUITERS COMPANIES
*API pattern: `GET https://api.smartrecruiters.com/v1/companies/{company_id}/postings?country=in&limit=100&offset=0`*
*Country param: `in` = India. Also try `?q=&location=India`*

| Company | Careers URL | SmartRecruiters ID | India Jobs | Status |
|---------|-------------|-------------------|-----------|--------|
| Continental | https://www.continental.com/en/career/ | continental | ~400+ | ✅ working |
| LDC (Louis Dreyfus) | https://www.ldc.com/global/en/careers/ | LouisDreyfusCompany | ~100+ | ✅ working |
| ServiceNow | https://careers.servicenow.com/locations/apj/india/ | servicenow | ~200+ | ✅ working |
| Zomato | https://careers.smartrecruiters.com/Zomato1 | Zomato1 | 1 | ⬇️ low-priority — `totalFound: 1` confirmed via API 2026-04-19; genuine single India role, not a scraper failure |
| Bosch | https://jobs.bosch.com/en?pages=1&country=in | BoschGroup | 100 | ✅ working — 100 India jobs, 100% JD; scraped 2026-04-19 |
| Visa | https://corporate.visa.com/en/jobs/?q=&location=India | Visa | 2 | ✅ SmartRecruiters ID `Visa` confirmed — 2 India jobs; probed 2026-04-19 |
| Societe Generale | https://careers.societegenerale.com/en/search | SocieteGenerale4 | ? | ✅ no_country_filter — `country=in` returns 0 for this tenant; portal fetches all postings, is_india() Python filter applied; fixed 2026-04-19 |
| Freshworks | https://careers.smartrecruiters.com/freshworks | freshworks | 4 | ✅ working — 4 India jobs; Chennai/Bengaluru; scraped 2026-04-19 |
| Publicis Sapient | https://careers.publicissapient.com | PublicisSapient | 0 | ↪️ moved 2026-05-20 — not SmartRecruiters; use active AEM/Solr row in CUSTOM / PROPRIETARY APIs |
| Dr. Reddy's | https://careers.drreddys.com | DrReddysLaboratoriesLtdSBX | 142 | ✅ cracked 2026-04-29 — slug found via smrtr.io shortlink redirect on career page; 142 India jobs; API public, no auth; SmartRecruiters Attrax (Springboard) platform |
| Syngenta | https://jobs.syngenta.com/?country=IN | SyngentaGroup | 47 | ✅ CRACKED 2026-05-15 — SR company ID was wrong before (was `Syngenta`, correct is `SyngentaGroup`); 47 India jobs; standard SR API works with `country=in`; full JD in jobAd.sections.jobDescription |
| Western Digital | https://jobs.smartrecruiters.com/WesternDigital | WesternDigital | 3+ validated | ✅ CRACKED 2026-05-21 — standard SmartRecruiters API works with `country=in`; detail endpoint provides `jobAd.sections.jobDescription`; live probe fetched India roles with full JDs |
| Refyne | https://careers.smartrecruiters.com/refyne | refyne | 10 | ✅ DISCOVERED 2026-06-13 via college Phase 0 → resolve_ats; SR API `country=in`, 10 India jobs; JD in `jobAd.sections.jobDescription` |
| Cars24 | https://careers.smartrecruiters.com/cars24 | cars24 | 1 | ✅ DISCOVERED 2026-06-13 via resolve_ats; SR API, 1 India job |
| NoBroker | https://careers.smartrecruiters.com/nobroker | nobroker | 1 | ✅ DISCOVERED 2026-06-13 via resolve_ats; SR API, 1 India job |
| Lendingkart | https://careers.smartrecruiters.com/lendingkart | lendingkart | 1 | ✅ DISCOVERED 2026-06-13 via resolve_ats; SR API, 1 India job |
| Newton School | https://careers.smartrecruiters.com/newtonschool | newtonschool | 1 | ✅ DISCOVERED 2026-06-13 via resolve_ats; SR API, 1 India job |
| Leucine | https://careers.smartrecruiters.com/leucine | leucine | 1 | ✅ DISCOVERED 2026-06-13 via resolve_ats; SR API, 1 India job |
| Intervue | https://careers.smartrecruiters.com/intervue | intervue | 1 | ✅ DISCOVERED 2026-06-13 via resolve_ats; SR API, 1 India job |
| GreyCampus (Odin School) | https://careers.smartrecruiters.com/greycampus | greycampus | 1 | ✅ DISCOVERED 2026-06-13 via resolve_ats; SR API, 1 India job |
| Carbynetech | https://careers.smartrecruiters.com/carbynetech | carbynetech | 1 | ✅ DISCOVERED 2026-06-13 via resolve_ats; SR API, 1 India job |
| AdaptNXT Technology Solutions | https://careers.smartrecruiters.com/adaptnxttechnologysolutions | adaptnxttechnologysolutions | 2 | ✅ DISCOVERED 2026-06-13 via resolve_ats; SR API, 2 India jobs |
| Arista Networks | https://careers.smartrecruiters.com/aristanetworks | aristanetworks | 8 | ✅ DISCOVERED 2026-06-13 via college Phase 0 → resolve_ats; SR API `country=in`, 8 India jobs; board confirmed "Arista Networks" |
| LinkedIn | https://jobs.smartrecruiters.com/LinkedIn3 | LinkedIn3 | 18 | ✅ HARVESTED 2026-06-13 (board-directory harvest) — SR API `country=in`, 18 India jobs; JD in `jobAd.sections.jobDescription` |
| H&M | https://careers.smartrecruiters.com/HMGroup | HMGroup | 131 | ✅ RECRACKED 2026-08-13 — direct SmartRecruiters board replaces the now-403 WordPress proxy; `country=in` returns 131 current India jobs with detail JDs |

---

## GREENHOUSE COMPANIES
*API pattern: `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true`*
*Filter: check `location.name` field for India cities in the response*

| Company | Careers URL | Board Token | India Jobs | Status |
|---------|-------------|-------------|-----------|--------|
| General Atlantic | https://www.generalatlantic.com/careers/ | generalatlantic | 0 | 🔴 0 India jobs — Greenhouse board confirmed but no India listings found; moved to end of registry |
| Stripe | https://stripe.com/in/jobs | stripe | ~20 | ✅ working |
| Storable | https://www.storable.com/careers | storable | ? | 🟡 Greenhouse board confirmed active (boards.greenhouse.io/storable); India jobs TBD; probed 2026-04-19 |
| CyberArk | https://www.cyberark.com/careers | cyberark | ? | ⚠️ Greenhouse board "cyberark" is no longer active as of 2026-04-19; careers.cyberark.com antibot-blocked — find new ATS or skip |
| InMobi | https://www.inmobi.com/company/careers/ | inmobi | 50 | ✅ CRACKED 2026-05-20 — careers pages expose Greenhouse links; direct API `https://boards-api.greenhouse.io/v1/boards/inmobi/jobs?content=true`; live probe returned 85 global jobs, 50 India-filtered through the existing Greenhouse provider |
| Databricks | https://www.databricks.com/company/careers/open-positions | databricks | 80 | ✅ CRACKED 2026-05-21 — direct Greenhouse API works (`boards-api.greenhouse.io/v1/boards/databricks/jobs?content=true`); Gatsby page data also embeds Greenhouse jobs/offices; 80 India jobs with full JDs |
| Anthropic | https://www.anthropic.com/careers | anthropic | 5 | ✅ CRACKED 2026-05-21 — direct Greenhouse API works; India roles visible in `location.name`; full JDs in `content` |
| Postman | https://www.postman.com/company/careers/ | postman | 12 | ✅ CRACKED 2026-05-21 — direct Greenhouse API works; India roles visible in `location.name`; full JDs in `content` |
| Zuora | https://www.zuora.com/about/careers/ | zuora | 13 | ✅ CRACKED 2026-05-21 — direct Greenhouse API works; India roles visible in `location.name`; full JDs in `content` |
| Cloudflare | https://www.cloudflare.com/careers/jobs/ | cloudflare | 12 | ✅ CRACKED 2026-05-21 — direct Greenhouse API works; board uses generic location labels, so provider enables content/title India matching and infers India city from JD text |
| Point72 | https://point72.com/careers/ | point72 | 38 | ✅ CRACKED 2026-05-21 — direct Greenhouse API works; India roles visible in `location.name`; full JDs in `content` |
| Figma | https://www.figma.com/careers/ | figma | 3 | ✅ CRACKED 2026-05-22 — Firecrawl search surfaced Greenhouse board; direct API returns Bengaluru roles with full JDs in `content`; no Firecrawl needed |
| GitLab | https://about.gitlab.com/jobs/ | gitlab | 27 | ✅ CRACKED 2026-05-22 — direct Greenhouse API works; remote India roles visible in `location.name`; full JDs in `content` |
| Druva | https://www.druva.com/about/careers/ | druva | 12 | ✅ CRACKED 2026-05-22 — direct Greenhouse API works; India roles visible in `location.name`; full JDs in `content` |
| Sumo Logic | https://www.sumologic.com/company/careers/ | sumologic | 18 | ✅ CRACKED 2026-05-22 — direct Greenhouse API works; Bengaluru/Noida India roles with full JDs |
| Netskope | https://www.netskope.com/company/careers | netskope | 16 | ✅ CRACKED 2026-05-22 — direct Greenhouse API works; India roles visible in `location.name`; full JDs in `content` |
| HackerRank | https://www.hackerrank.com/careers/ | hackerrank | 20 | ✅ CRACKED 2026-05-22 — direct Greenhouse API works; Bangalore/India roles visible in `location.name`; full JDs in `content` |
| Observe.ai | https://www.observe.ai/careers | observeai | 10 | ✅ CRACKED 2026-05-22 — direct Greenhouse API works; Bengaluru roles visible in `location.name`; full JDs in `content` |
| ClickHouse | https://clickhouse.com/company/careers | clickhouse | 10 | ✅ CRACKED 2026-05-22 — direct Greenhouse API works; India remote roles visible in `location.name`; full JDs in `content` |
| DAT Freight & Analytics | https://www.dat.com/company/careers | datsolutions | 3 | ✅ CRACKED 2026-05-22 — direct Greenhouse API works; Bengaluru engineering roles visible in `location.name`; full JDs in `content` |
| Energy Exemplar | https://www.energyexemplar.com/careers | energyexemplarllc | 18 | ✅ CRACKED 2026-05-22 — direct Greenhouse API works; Bengaluru/Pune India roles with full JDs |
| AlphaSense India | https://www.alpha-sense.com/careers/ | alphasenseindia | 44 | ✅ CRACKED 2026-05-22 — direct Greenhouse API works; India board uses city-only locations, existing `is_india()` city filter handles them; full JDs in `content` |
| Bluevine India | https://www.bluevine.com/careers/ | bluevineindia | 12 | ✅ CRACKED 2026-05-22 — direct Greenhouse API works; Bengaluru roles with full JDs |
| Kaseya | https://www.kaseya.com/careers/ | kaseya | 36 | ✅ CRACKED 2026-05-22 — direct Greenhouse API works; Bangalore/Pune India roles with full JDs |
| NICE | https://www.nice.com/careers | nice | 86 | ✅ CRACKED 2026-05-22 — direct Greenhouse API works; India roles visible in `location.name`; full JDs in `content` |
| Ivalua | https://www.ivalua.com/company/careers/ | ivalua | 5 | ✅ CRACKED 2026-05-22 — direct Greenhouse API works; Pune India roles with full JDs |
| Abacus Insights | https://abacusinsights.com/careers/ | abacusinsights | 14 | ✅ CRACKED 2026-05-22 — direct Greenhouse API works; Pune India roles with full JDs |
| MongoDB | https://www.mongodb.com/company/careers | mongodb | 51 | ✅ CRACKED 2026-05-21 — direct Greenhouse API works; 51 India jobs with full JDs |
| Rubrik | https://www.rubrik.com/company/careers | rubrik | 49 | ✅ CRACKED 2026-05-21 — direct Greenhouse API works; 49 India jobs with full JDs |
| Zscaler | https://www.zscaler.com/careers | zscaler | 112 | ✅ CRACKED 2026-05-21 — direct Greenhouse API works; 112 India jobs with full JDs |
| Twilio | https://www.twilio.com/en-us/company/jobs | twilio | 20 | ✅ CRACKED 2026-05-21 — direct Greenhouse API works; 20 India jobs with full JDs |
| Okta | https://www.okta.com/company/careers | okta | 93 | ✅ CRACKED 2026-05-21 — direct Greenhouse API works; 93 India jobs with full JDs |
| Pure Storage | https://www.purestorage.com/company/careers.html | purestorage | 68 | ✅ CRACKED 2026-05-21 — direct Greenhouse API works; 68 India jobs with full JDs |
| Datadog | https://www.datadoghq.com/careers | datadog | 12 | ✅ CRACKED 2026-05-21 — direct Greenhouse API works; 12 India jobs with full JDs |
| Elastic | https://www.elastic.co/careers | elastic | 7 | ✅ CRACKED 2026-05-21 — direct Greenhouse API works; 7 India jobs with full JDs |
| Airbnb | https://careers.airbnb.com | airbnb | 15 | ✅ working — 15 India jobs, 100% JD; scraped 2026-04-19 |
| Razorpay | https://razorpay.com/jobs/ | razorpaysoftwareprivatelimited | 46 | ✅ working — 46 India jobs, 100% JD; scraped 2026-04-19 |
| PhonePe | https://www.phonepe.com/careers/ | phonepe | 43 | ✅ working — 43 India jobs, 100% JD; scraped 2026-04-19 |
| Thoughtworks | https://www.thoughtworks.com/careers | thoughtworks | 2 | ✅ working — 2 India jobs, 100% JD; scraped 2026-04-19 |
| Mozilla | https://www.mozilla.org/en-US/careers/listings/ | mozilla | 0 | 🔴 0 India jobs — 47 global Greenhouse jobs confirmed (boards.greenhouse.io/mozilla) but none India-located; probed 2026-04-26 |
| Groww | https://groww.in/careers | groww | 15 | ✅ CRACKED 2026-06-04 — direct Greenhouse API works; India-only board (Bengaluru); full JDs in `content` |
| HighRadius | https://www.highradius.com/careers/ | highradius | 60 | ✅ CRACKED 2026-06-04 — direct Greenhouse API works; ~60 India jobs (Hyderabad-heavy), 80 global; full JDs in `content` |
| Zinnov | https://boards.greenhouse.io/zinnov | zinnov | 65 | ✅ DISCOVERED 2026-06-13 via college Phase 0 → resolve_ats; direct Greenhouse API, 65 India jobs (Bengaluru/Hyderabad/Chennai); full JDs in `content`; validated through existing provider |
| Tekion | https://boards.greenhouse.io/tekion | tekion | 0 | ↪️ moved 2026-08-13 — Greenhouse board now 404; use the active Ashby row below |
| WorldQuant | https://boards.greenhouse.io/worldquant | worldquant | 6 | ✅ DISCOVERED 2026-06-13 via college Phase 0 → resolve_ats; direct Greenhouse API, 6 India jobs; board name confirmed "WorldQuant"; full JDs in `content` |
| Da Vinci Derivatives | https://boards.greenhouse.io/davinciderivatives | davinciderivatives | 1 | ✅ DISCOVERED 2026-06-13 via resolve_ats; Greenhouse board confirmed "Da Vinci"; 1 India job; full JD in `content` |
| Verve | https://boards.greenhouse.io/verve | verve | 3 | ⚠️ DISCOVERED 2026-06-13 — Greenhouse board "Verve" (3 India); seed labeled "Verve Consulting" but board identity ambiguous (may be Verve Group ad-tech); verify owner before trusting |
| Atomicwork | https://boards.greenhouse.io/atomicwork | atomicwork | 21 | ✅ HARVESTED 2026-06-13 (board-directory harvest) — Greenhouse API, 21 India jobs; board "Atomicwork Inc"; full JDs in `content` |
| 6sense | https://boards.greenhouse.io/6sense | 6sense | 17 | ✅ HARVESTED 2026-06-13 — Greenhouse API, 17 India jobs; full JDs in `content` |
| Meltplan | https://boards.greenhouse.io/meltplan | meltplan | 6 | ✅ HARVESTED 2026-06-13 — Greenhouse API, 6 India jobs; full JDs in `content` |
| Redpin (Currencies Direct) | https://boards.greenhouse.io/currenciesdirect | currenciesdirect | 4 | ✅ HARVESTED 2026-06-13 — Greenhouse API, board "Redpin", 4 India jobs; full JDs in `content` |
| Truecaller | https://boards.greenhouse.io/truecaller | truecaller | 2 | ✅ HARVESTED 2026-06-13 — Greenhouse API, 2 India jobs; full JDs in `content` |
| Celonis | https://www.celonis.com/careers/jobs/ | celonis | 32 | ✅ VALIDATED 2026-07-12 via career-ops audit — direct Greenhouse API; India locations and full JDs in `content` |
| Glean | https://www.glean.com/careers | gleanwork | 26 | ✅ VALIDATED 2026-07-12 via career-ops audit — direct Greenhouse API; India locations and full JDs in `content` |
| Boomi | https://boomi.com/company/careers/ | boomilp | 26 | ✅ VALIDATED 2026-07-12 via career-ops audit — direct Greenhouse API; India locations and full JDs in `content` |
| Hightouch | https://hightouch.com/careers | hightouch | 2 | ✅ VALIDATED 2026-07-12 via career-ops audit — direct Greenhouse API; India locations and full JDs in `content` |
| Hootsuite | https://careers.hootsuite.com/ | hootsuite | 1 | ✅ VALIDATED 2026-07-12 via career-ops audit — direct Greenhouse API; India location and full JD in `content` |

---

## ASHBY COMPANIES
*API pattern: `GET https://api.ashbyhq.com/posting-api/job-board/{board_token}`*
*Filter: check primary and `secondaryLocations` for India; `descriptionPlain` contains the full JD.*

| Company | Careers URL | Board Token | India Jobs | Status |
|---------|-------------|-------------|-----------|--------|
| Deepgram | https://deepgram.com/careers | deepgram | 2 | ✅ VALIDATED 2026-07-12 via career-ops audit — direct Ashby Posting API; India roles with full JDs |
| Zapier | https://zapier.com/jobs | zapier | 3 | ✅ VALIDATED 2026-07-12 via career-ops audit — direct Ashby Posting API; India roles with full JDs |
| Tekion | https://tekion.com/careers | tekion | 79 global | ✅ RECRACKED 2026-08-13 — public Ashby Posting API replaces retired Greenhouse board; India filter and full `descriptionPlain` handled by the shared provider |
| ElevenLabs | https://elevenlabs.io/careers | elevenlabs | 16 | ⚠️ REVIEW — India appears mainly in secondary/multi-location eligibility; do not promote until location semantics are manually confirmed |

---

## LEVER COMPANIES
*API pattern: `GET https://api.lever.co/v0/postings/{company}?mode=json`*
*Returns all active jobs as JSON array. Filter by `location` field for India cities.*
*India-founded companies below: no filter needed — all postings are India.*

| Company | Careers URL | Lever Slug | India Jobs | Status |
|---------|-------------|-----------|-----------|--------|
| Spotify | https://www.lifeatspotify.com/jobs | spotify | 2 | ✅ working — ATS is Lever (jobs.lever.co/spotify); 2 India jobs (Gurgaon + Mumbai); lifeatspotify.com WP front-end confirmed; probed 2026-04-26 |
| Meesho | https://meesho.io/jobs | meesho | 52 | ✅ working — 52 India jobs, 100% JD; scraped 2026-04-19 |
| CRED | https://careers.cred.club/openings | cred | 7 | ✅ working — 7 India jobs, 100% JD; scraped 2026-04-19 |
| Paytm | https://paytm.com/careers | paytm | 203 | ✅ working — 203 India jobs, 96% JD; scraped 2026-04-19 |
| Mindtickle | https://www.mindtickle.com/careers/ | mindtickle | 25 | ✅ CRACKED 2026-05-22 — direct Lever API works; India roles visible in `categories.location`; full JDs in `descriptionPlain`; no Firecrawl needed |
| Zeta | https://www.zeta.tech/careers/ | zeta | 14 | ✅ CRACKED 2026-05-22 — direct Lever API works; Bangalore/Hyderabad India roles visible in `categories.location`; full JDs in `descriptionPlain`; no Firecrawl needed |
| JumpCloud | https://jumpcloud.com/careers | jumpcloud | 11 | ✅ CRACKED 2026-05-22 — direct Lever API works; India remote roles visible in `categories.location`; full JDs in `descriptionPlain`; no Firecrawl needed |
| Zimperium | https://www.zimperium.com/careers/ | zimperium | 5 | ✅ CRACKED 2026-05-22 — direct Lever API works; Bengaluru India roles visible in `categories.location`; full JDs in `descriptionPlain`; no Firecrawl needed |
| Hevo Data | https://hevodata.com/careers/ | hevodata | 34 | ✅ CRACKED 2026-05-22 — direct Lever API works; India roles visible in `categories.location`; full JDs in `descriptionPlain`; no Firecrawl needed |
| Acceldata | https://www.acceldata.io/careers | acceldata | 22 | ✅ CRACKED 2026-05-22 — direct Lever API works; India roles visible in `categories.location`; full JDs in `descriptionPlain`; no Firecrawl needed |
| Onehouse | https://www.onehouse.ai/careers | Onehouse | 5 | ✅ CRACKED 2026-05-22 — direct Lever API works; India roles visible in `categories.location`; full JDs in `descriptionPlain`; no Firecrawl needed |
| Dream Sports (Dream11) | https://www.dreamsports.group/careers/ | dreamsports | 22 | ✅ CRACKED 2026-06-04 — direct Lever API works; India-only (Mumbai/Bengaluru/Delhi); full JDs in `descriptionPlain` |
| FamPay | https://fampay.in/careers | fampay | 18 | ✅ CRACKED 2026-06-04 — direct Lever API works; all Bengaluru; full JDs in `descriptionPlain` |
| Fi Money (Epifi) | https://fi.money/careers | epifi | 4 | ✅ CRACKED 2026-06-04 — direct Lever API works; all Bangalore; full JDs in `descriptionPlain`; low volume but India-only |
| Safe Security | https://jobs.lever.co/safe | safe | 13 | ✅ DISCOVERED 2026-06-13 via college Phase 0 → resolve_ats; direct Lever API, 13 India roles in `categories.location`; full JDs in `descriptionPlain` |
| Auxia | https://jobs.lever.co/auxia | auxia | 5 | ✅ DISCOVERED 2026-06-13 via resolve_ats; direct Lever API, 5 India roles; full JDs in `descriptionPlain` |
| TSMG | https://jobs.lever.co/tsmg | tsmg | 12 | ⚠️ DISCOVERED 2026-06-13 — Lever board `tsmg` exists (12 India of 3326 total; likely staffing/aggregator); verify company identity before trusting |
| Genesis Colors | https://jobs.lever.co/genesis | genesis | 3 | ⚠️ DISCOVERED 2026-06-13 — Lever board `genesis` (generic slug, 3 India roles); company identity UNVERIFIED; verify board owner before trusting |
| Brillio | https://jobs.lever.co/brillio-2 | brillio-2 | 80 | ✅ HARVESTED 2026-06-13 (board-directory harvest) — Lever API, 80 India roles in `categories.location`; full JDs in `descriptionPlain` |
| AHEAD | https://jobs.lever.co/thinkahead | thinkahead | 62 | ✅ HARVESTED 2026-06-13 — Lever API, 62 India roles; full JDs in `descriptionPlain` |
| Beghou Consulting | https://jobs.lever.co/beghouconsulting | beghouconsulting | 54 | ✅ HARVESTED 2026-06-13 — Lever API, 54 India roles; full JDs in `descriptionPlain` |
| Coupa | https://jobs.lever.co/coupa | coupa | 11 | ✅ HARVESTED 2026-06-13 — Lever API, 11 India roles; full JDs in `descriptionPlain` |
| Resilinc | https://jobs.lever.co/resilinc | resilinc | 3 | ✅ HARVESTED 2026-06-13 — Lever API, 3 India roles; full JDs in `descriptionPlain` |
| Binance | https://jobs.lever.co/binance | binance | 1 | ✅ HARVESTED 2026-06-13 — Lever API, 1 India role; full JDs in `descriptionPlain` |

---

## EIGHTFOLD AI COMPANIES
*API pattern: `GET https://{tenant}.eightfold.ai/api/apply/v2/jobs?query=&count=20&start=0&location=India&domain={api_domain}`*
*JD fetch: `GET https://{tenant}.eightfold.ai/api/apply/v2/jobs/{id}?domain={api_domain}`*
*Note: API uses `count`+`start` params (NOT `num`). Companies with API Domain set use direct API; others fall back to Firecrawl.*

| Company | Careers URL | Eightfold Domain | API Domain | Status |
|---------|-------------|-----------------|------------|--------|
| Netflix | https://explore.jobs.netflix.net/careers | netflix.eightfold.ai | netflix.com | ✅ cracked 2026-04-29 — direct API working; 7 India jobs |
| STMicroelectronics | https://stmicroelectronics.eightfold.ai/careers?location=India&hl=en | stmicroelectronics.eightfold.ai | stmicroelectronics.com | ✅ CRACKED 2026-05-13 — Eightfold API works with `domain=stmicroelectronics.com`; 4 India jobs in live probe; full JD via `/api/apply/v2/jobs/{id}`; no Firecrawl needed |
| Philip Morris International | https://join.pmicareers.com/gb/en/search-results | join.pmicareers.com | | ↪️ moved 2026-05-20 — NOT Eightfold; use active Phenom SSR row below |
| HSBC | https://hsbc.eightfold.ai/careers?location=India&hl=en | hsbc.eightfold.ai | hsbc.com | ✅ CRACKED 2026-05-13 — direct Eightfold API works; domain=hsbc.com; 250 India jobs confirmed |
| Citibank | https://jobs.citi.com/search-jobs/India | citi.eightfold.ai | | ✅ CRACKED 2026-05-08 — route via Radancy/TalentBrew HTML (`ats=talentbrew`); direct listing + JSON-LD detail pages; Eightfold API remains 403 |

---

## ICIMS CUSTOM CAREER SITES
*API pattern: `GET https://{careers_domain}/api/jobs?country=India&page=N&limit=100&sortBy=relevance&descending=false&internal=false`*
*Response: `{"jobs": [{"data": {...}}], "totalCount": N}` — full JD included, 100 jobs/page with limit param, no auth required.*

| Company | Careers URL | India Jobs | Status |
|---------|-------------|-----------|--------|
| AMD | https://careers.amd.com/careers-home/jobs | 304 | ✅ cracked 2026-04-29 — full JD; no auth; 100/page; ats=icims_custom |
| Keysight Technologies | https://jobs.keysight.com/external/jobs | 109 | ✅ cracked 2026-04-29 — same iCIMS pattern; icims_location_param=location; no auth |

---

## DARWINBOX COMPANIES
*API: `POST https://{tenant}.darwinbox.in/ms/candidateapi/job/alljobs?companyId=main`*
*Body: `{"companyId":"main","page":N,"sort_option":"new","limit":50}`*
*CF requirement: set `DARWINBOX_CF_BM` + `DARWINBOX_SESSION` env vars (from browser, expires 30min) → fallback Firecrawl*

| Company | Careers URL | India Jobs | Status |
|---------|-------------|-----------|--------|
| IIFL Finance | https://iifl.darwinbox.in/ms/candidate/careers | 41 | ✅ cracked 2026-04-29 — API found; full JD; CF cookie required; ats=darwinbox |
| Flipkart | https://flipkart.darwinbox.com/ms/candidate/careers | ? | 🟡 Darwinbox confirmed — CF protected; verify India job count |

---

## MYNEXTHIRE COMPANIES
*API: `POST https://{tenant}.mynexthire.com/employer/careers/reqlist/get`*
*Body: `{"source":"careers","code":"","filterByBuId":-1,"filterByCustomField":{"career_page_category":"{cat}"}}`*
*Iterates all categories: Technology, Business, Operations, etc. No auth required.*

| Company | Careers URL | Tenant Domain | India Jobs | Status |
|---------|-------------|--------------|-----------|--------|
| Swiggy | https://careers.swiggy.com | swiggy.mynexthire.com | 83 | ✅ cracked 2026-04-30 — no auth; Technology(10)+Business(73); full JD in jdDisplay; ats=mynexthire |

---

## SPIRE2GROW COMPANIES
*API: `GET https://io.spire2grow.com/ies/v1/p/requisition/_search?page=N&size=100`*
*Required headers: `Workspaceid`, `Workflowid`, `Origin`*
*Response: `{"entities":[...],"total":N}` — full JD in jobDescription; no auth required.*

| Company | Careers URL | Workspace ID | Workflow ID | India Jobs | Status |
|---------|-------------|-------------|------------|-----------|--------|
| Myntra | https://jobs.myntra.com | MYNTRA-93as3 | WFU_1777489282823000 | 16 | ✅ cracked 2026-04-30 — Spire2Grow IES ATS; no auth; full JD; all India jobs; ats=spire2grow |

---

## ZWAYAM COMPANIES
*API: `POST https://apic2.zwayam.com/jobs/search` (multipart/form-data) — default; company-specific subdomains override via `API URL` column*
*Fields: filterCri (JSON), domain, companyId (base64)*
*Response: Elasticsearch hits in data.data[]; _source has jobTitle, location, shortDescription*

| Company | Careers URL | Zwayam Domain | Company ID (b64) | API URL | India Jobs | Status |
|---------|-------------|--------------|-----------------|---------|-----------|--------|
| Rakuten India | https://rakuten.openings.co | rakuten.openings.co | MTUxMjQ= | | 10 | ✅ cracked 2026-04-30 — Zwayam ATS; no auth; full JD in shortDescription; India-only portal; ats=zwayam |
| Persistent Systems | https://careers.persistent.com | careers.persistent.com | MTQ5Nzc= | https://apipersistent.zwayam.com/jobs/search | 300+ | ✅ CRACKED 2026-05-14 — company-specific Zwayam subdomain `apipersistent.zwayam.com`; companyId=14977 (MTQ5Nzc=); global API, India filtered client-side; ats=zwayam |
| CRISIL | https://career.crisil.com/crisil/ | career.crisil.com | MTU0Mzg= | https://public.zwayam.com/jobs/search | 655 | ✅ CRACKED 2026-05-20 — Angular shell exposes Zwayam config; `POST /jobs/search` with `filterCri`, `domain=career.crisil.com`, `companyId=MTU0Mzg=` returned 655 jobs; India-heavy portal |

---

## RIPPLEHIRE COMPANIES
*API: `POST https://{host}/candidate/candidatejobsearch` (form-encoded)*
*Session: GET `/candidate/?token={token}&source=CAREERSITE` first to acquire JSESSIONID*
*Fields: careerSiteUrlParams (JSON with page/search/token/source/pagesize/location), lang=en*
*Response: `response.docs[]` — jobTitle, location, jobid, jobUrl, shortDescription*

| Company | Careers URL | RippleHire Host | Token | India Jobs | Status |
|---------|-------------|----------------|-------|-----------|--------|
| Mphasis | https://careers.mphasis.com | mphasis.ripplehire.com | ty4DfyWddnOrtpclQeia | 500+ | ✅ CRACKED 2026-05-14 — POST /candidatejobsearch; JSESSIONID acquired via GET; India filtered client-side; ats=ripplehire |
| Axis Bank | https://www.axis.bank.in/careers | axisbank.ripplehire.com | WIXhCuz0XRZ7H0GZCwjJ | 10570 | ✅ CRACKED 2026-05-21 — discovery promoted; `jobVoList` listing plus `/candidate/candidatejobdetail` full JD supported |
| Tata Steel | https://www.tatasteel.com/careers/work-with-us/tata-steel-india-careers/ | tatasteel.ripplehire.com | kYAz91uy1lFDi6FeSiRZ | 31 | ✅ CRACKED 2026-05-21 — discovery promoted; `jobVoList` listing plus `/candidate/candidatejobdetail` full JD supported |

---

## TALEO COMPANIES
*Classic TBE: `POST https://{careers_domain}/services/jobs/search/` with `{"locationsearch":"india","recordsperpage":100}`*
*v1 REST: `POST https://{careers_domain}/services/recruiting/v1/jobs` with `{"location":"india","pageNumber":N}` — auto-detected from endpoint path `/recruiting/v1/`.*
*JD: fetched from individual HTML page `/job/{urltitle}/{id}/`. No auth required.*

| Company | Careers URL | India Jobs | Status |
|---------|-------------|-----------|--------|
| ANZ Bank | https://careers.anz.com | 7 | ✅ cracked 2026-04-30 — Oracle Taleo TBE; no auth; JD from HTML page fetch; ats=taleo |
| Wipro | https://careers.wipro.com/services/recruiting/v1/jobs | 9176 | ✅ CRACKED 2026-04-30 — Taleo v1 REST; no auth; `location=india`; paginated 10/page; JD from HTML job page; ats=taleo; taleo_use_location=True |
| HCL Technologies | https://careers.hcltech.com/services/recruiting/v1/jobs | 42 | ✅ cracked 2026-04-30 — SAP SuccessFactors/Jobs2Web v1 REST; JD URL format is `/job/{urltitle}/{id}-en_US` (plain `/id/` redirects to error page); full JDs now extracted |

---

## MCKINSEY COMPANIES
*API: `GET https://gateway.mckinsey.com/apigw-x0cceuow60/v1/api/jobs/search?countries=India&pageSize=200&lang=en`*
*No auth required. Origin header: `https://www.mckinsey.com`. JD in whoYouWillWorkWith + whatYouWillDo + yourBackground.*

| Company | Careers URL | India Jobs | Status |
|---------|-------------|-----------|--------|
| McKinsey & Company | https://www.mckinsey.com/careers/search-jobs?countries=India | 46 | ✅ cracked 2026-04-30 — custom gateway API; no auth; full JD from 3 fields; ats=mckinsey |

---

## CUSTOM / PROPRIETARY APIs

| Company | Careers URL | ATS / Platform | Scraping Endpoint | India Filter | India Jobs | Status |
|---------|-------------|----------------|------------------|-------------|-----------|--------|
| Amazon | https://www.amazon.jobs | Custom (AWS Jobs) | `GET https://www.amazon.jobs/en/search.json?base_query=&loc_query=India&country=IND&result_limit=100` | `country=IND` param | ~2,963 | ✅ working — clean JSON API |
| Publicis Sapient | https://careers.publicissapient.com | AEM/Solr + iCIMS apply | `GET https://careers.publicissapient.com/apps/ps-rebrand/careersJobsearch?searchType=/search&lang=en&facetFields=countryName,region,city,experienceLevel,teams,typeOfEmployment,remote&q=&country=India&location_q=India` | `country=India&location_q=India` plus Python `is_india()` | 14 | ✅ CRACKED 2026-05-20 — direct JSON search + server-rendered `/job-details/{jobId-slug}` pages for full JD; routed to `ats=publicis_sapient` |
| ARM Holdings | https://careers.arm.com | TalentBrew (Radancy) | `GET https://careers.arm.com/search-jobs/India?orgIds=33099&alp=1269750&alt=2` | `orgIds=33099`, `alp=1269750` (India location ID) in URL | 38 | ✅ REVALIDATED 2026-05-20 — endpoint returns 38 India jobs; provider supports current `a.job-card__title[data-job-id]` listing markup and JSON-LD detail JDs |
| Atlassian | https://www.atlassian.com/company/careers/all-jobs?team=Interns%2CGraduates&location=&search= | Atlassian Careers API (iCIMS-backed) | `GET https://www.atlassian.com/endpoint/careers/listings` | Python `is_india()` on `locations[]` strings | 1 | ✅ CRACKED 2026-05-02 — direct JSON array (82 global jobs in snapshot); fields include `id`, `title`, `locations`, `overview`, `responsibilities`, `qualifications`, `applyUrl`; no auth required |
| Apple | https://jobs.apple.com/en-in/search | Apple Jobs API | `POST https://jobs.apple.com/api/v1/search` | Python `is_india()` on `locations[]`; JD via `GET /api/v1/jobDetails/{positionId}` | ~100+ | ✅ CRACKED 2026-05-08 — direct JSON API; routed to `ats=apple_jobs`; no Firecrawl needed |
| Cognizant | https://careers.cognizant.com/india-en/jobs | XML Feed | `GET https://careers.cognizant.com/india-en/jobs/xml/?rss=true` | Python `is_india()` on city/state/country | 437 | ✅ CRACKED 2026-05-08 — public XML feed with full descriptions; routed to `ats=cognizant_xml`; no Firecrawl needed |
| Google | https://www.google.com/about/careers/applications/jobs/results/?location=India | Google Careers embedded HTML | `GET https://www.google.com/about/careers/applications/jobs/results/?location=India&page=N` | `location=India` param + Python `is_india()` on embedded locations | 371 | ✅ CRACKED 2026-05-11 — user-supplied careers URL works without cookies; HTML embeds full job records in `AF_initDataCallback`; paginate with `page=N` until empty; routed to `ats=google_careers`; no Firecrawl needed |
| Infosys | https://career.infosys.com/joblist | Custom (Infosys gateway) | `GET https://intapgateway.infosysapps.com/careersci/search/intapjbsrch/getCareerSearchJobs?sourceId=1,21&searchText=ALL` | India-only portal (all 1285 jobs are India) | 1285 | ✅ CRACKED 2026-04-29 — flat JSON array, no auth; fields: postingTitle/referenceCode/postingDescription/location/createdOn/unit; JD in listing (no separate fetch needed); apply_url=career.infosys.com/jobdesc?referenceCode={code}; india_only=False |
| IntouchCX | https://www.intouchcx.com/careers/ | IntouchCX WP JSON + Dayforce/legacy apply | `GET https://www.intouchcx.com/wp-json/intouchcx/v1/jobs?country=India` | `country=India` param | 40 | ✅ CRACKED 2026-05-10 — user-supplied WP JSON feed; listing fields are `job`, `link`, `location`; full JD fetched from `apply.intouchcx.com/{id}` `.application-body` or Dayforce SSR `__NEXT_DATA__.props.pageProps.jobData`; routed to `ats=intouchcx`; no Firecrawl needed |
| TVS Next | https://tvsnext.keka.com/careers/ | Keka Hire | `GET https://tvsnext.keka.com/careers/api/jobs/default/active` | India-only board; `jobLocations[].countryName == "India"` | 26 | ✅ WIRED 2026-08-13 — first-class `keka` provider reads the public listing JSON, full HTML JD, department, locations, and direct `/jobdetails/{id}` apply page |
| Goldman Sachs | https://higher.gs.com/roles | Custom (higher.gs.com / api-higher.gs.com GraphQL) | `POST https://api-higher.gs.com/gateway/api/v1/graphql` — HTML listing at `https://higher.gs.com/results?page=1&sort=RELEVANCE` | Python `is_india()` on `locations[].country/city`; global API, no server-side India filter | 100+ | ✅ CRACKED 2026-05-14 — GraphQL API confirmed public (no auth); fetches all roles globally, filters India in Python; routed to `ats=goldman_higher` |
| IBM | https://www.ibm.com/in-en/careers/search?field_keyword_05%5B0%5D=India | IBM Custom + Workday (ibm.wd3) | `www.ibm.com/in-en/careers/search?field_keyword_05[0]=India` | India param = `field_keyword_05[0]=India` | 2000+ | ⚠️ 2026-05-15 — IBM has own custom career portal at ibm.com (Akamai-blocked, 0 bytes); underlying ATS is Workday ibm.wd3 but career_site slug unknown + CF-blocked; `CISESSIONIDPR07A` = IBM custom session; blocked from both custom portal and Workday CXS |
| ICICI Bank | https://careers.icici.bank.in/CareerApplicant/career/job-listing/ | Custom TurboHire .NET SPA | API base: `careers.icici.bank.in/CareerApplicantApi/` — `GET Career/Groups` → 9 groups (g_id=28 Digital&Tech); `GET Career/getMobileJd/{jobId}` → full JD (title/location/responsibilities/qualifications); `POST Career/Search/1` → listing endpoint confirmed in JS but returns `{}` — correct body params unknown; need DevTools XHR capture of group click to get listing body | 1000+ | ⚠️ PARTIAL — JD endpoint confirmed working; listing endpoint blocked; Bearer token = literal "Bearer token" (public API, no real auth); binfo=btoa(btoa(browserVersion)), platform=btoa(btoa("web")); needs listing XHR capture |
| L'Oréal | https://careers.loreal.com/en_US/jobs/SearchJobs?3_110_3=18031 | TalentBrew (NOT Phenom) | `https://careers.loreal.com/en_US/jobs/SearchJobs?3_110_3=18031` | 9 | ✅ CRACKED 2026-05-13 — India facet param `3_110_3=18031`; 9 India jobs (Mumbai/Pune); CF-blocked on direct HTTP (FC required for listing); job detail at `/en_US/jobs/JobDetail/{slug}/{id}`; ats=talentbrew |
| Microsoft | https://careers.microsoft.com/v2/global/en/locations/india.html | Microsoft Careers PCSX + apply API | `GET https://apply.careers.microsoft.com/api/pcsx/search?domain=microsoft.com&query=&location=India&start=0&hl=en` | `location=India` param + `standardizedLocations=["IN"]` / Python `is_india()` | 158 | ✅ CRACKED 2026-05-11 — user-supplied location page works without cookies; full search comes from PCSX `/api/pcsx/search` pagination (`start += 10`); JD via `GET https://apply.careers.microsoft.com/api/apply/v2/jobs/{id}?domain=microsoft.com`; routed to `ats=microsoft_careers`; no Firecrawl needed |
| Confluent | https://careers.confluent.io | Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/confluent` | Python `is_india()` on `location` / `secondaryLocations`; full JD in `descriptionPlain` / `descriptionHtml` | 15 | ✅ CRACKED 2026-05-21 — public Ashby API returned 52 global jobs, 15 India/remote-India jobs; routed to `ats=ashby`; no Firecrawl needed |
| Rippling | https://www.rippling.com/careers/open-roles | Rippling custom ATS / Next.js SSR | `GET https://www.rippling.com/careers/open-roles` → `__NEXT_DATA__.props.pageProps.jobs.items`; detail pages at `https://ats.rippling.com/rippling/jobs/{uuid}` → `__NEXT_DATA__.props.pageProps.apiData.jobPost` | `locations[].countryCode == "IN"` | 90 | ✅ CRACKED 2026-05-21 — listing and detail pages are direct HTTP/SSR; detail payload includes `description`, `workLocations`, `department`, `employmentType`; routed to `ats=rippling`; no Firecrawl needed |
| Snowflake | https://careers.snowflake.com/us/en | Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/snowflake` | Python `is_india()` on `location` / `secondaryLocations`; full JD in `descriptionPlain` / `descriptionHtml` | 13 | ✅ CRACKED 2026-05-21 — public Ashby API returned 408 global jobs, 13 India jobs; routed to `ats=ashby`; no Firecrawl needed |
| UiPath | https://www.uipath.com/careers | Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/uipath` | Python `is_india()` on `location` / `secondaryLocations`; full JD in `descriptionPlain` / `descriptionHtml` | 6 | ✅ CRACKED 2026-05-21 — public Ashby API returned active India roles; routed to `ats=ashby`; no Firecrawl needed |
| Airwallex | https://www.airwallex.com/careers | Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/airwallex` | Python `is_india()` on `location` / `secondaryLocations`; full JD in `descriptionPlain` / `descriptionHtml` | 16 | ✅ CRACKED 2026-05-22 — direct Ashby API works; Bengaluru/India roles with full JDs; no Firecrawl needed |
| Notion | https://www.notion.com/careers | Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/notion` | Python `is_india()` on `location` / `secondaryLocations`; full JD in `descriptionPlain` / `descriptionHtml` | 2 | ✅ CRACKED 2026-05-22 — direct Ashby API works; India roles with full JDs; no Firecrawl needed |
| Atlan | https://atlan.com/careers | Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/atlan` | Python `is_india()` on `location` / `secondaryLocations`; full JD in `descriptionPlain` / `descriptionHtml` | 2 | ✅ CRACKED 2026-05-22 — direct Ashby API works; India roles with full JDs; no Firecrawl needed |
| Cartesia | https://cartesia.ai/careers | Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/cartesia` | Python `is_india()` on `location` / `secondaryLocations`; full JD in `descriptionPlain` / `descriptionHtml` | 4 | ✅ CRACKED 2026-05-22 — direct Ashby API works; India/Bengaluru roles with full JDs; no Firecrawl needed |
| Fermi AI | https://jobs.ashbyhq.com/Fermi%20AI | Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/Fermi%20AI` | Python `is_india()` on `location` / `secondaryLocations`; full JD in `descriptionPlain` / `descriptionHtml` | 12 | ✅ CRACKED 2026-05-22 — direct Ashby API works; India roles with full JDs; no Firecrawl needed |
| Flagright | https://www.flagright.com/careers | Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/flagright.com` | Python `is_india()` on `location` / `secondaryLocations`; full JD in `descriptionPlain` / `descriptionHtml` | 4 | ✅ CRACKED 2026-05-22 — direct Ashby API works; India/Bangalore roles with full JDs; no Firecrawl needed |
| Skylo Technologies | https://www.skylo.tech/careers | Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/skylo` | Python `is_india()` on `location` / `secondaryLocations`; full JD in `descriptionPlain` / `descriptionHtml` | 5 | ✅ CRACKED 2026-05-22 — direct Ashby API works; Bengaluru roles with full JDs; no Firecrawl needed |
| Lyric | https://jobs.ashbyhq.com/lyric | Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/lyric` | Python `is_india()` on `location` / `secondaryLocations`; full JD in `descriptionPlain` / `descriptionHtml` | 13 | ✅ DISCOVERED 2026-06-13 via resolve_ats; direct Ashby API, 13 India jobs; no Firecrawl needed |
| NETGEAR | https://jobs.ashbyhq.com/netgear | Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/netgear` | Python `is_india()` on `location` / `secondaryLocations`; full JD in `descriptionPlain` / `descriptionHtml` | 22 | ✅ HARVESTED 2026-06-13 (board-directory harvest) — Ashby API, 22 India jobs |
| Pebl | https://jobs.ashbyhq.com/pebl | Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/pebl` | Python `is_india()` on `location` / `secondaryLocations`; full JD in `descriptionPlain` / `descriptionHtml` | 8 | ✅ HARVESTED 2026-06-13 — Ashby API, 8 India jobs |
| SentiLink | https://jobs.ashbyhq.com/sentilink | Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/sentilink` | Python `is_india()` on `location` / `secondaryLocations`; full JD in `descriptionPlain` / `descriptionHtml` | 2 | ✅ HARVESTED 2026-06-13 — Ashby API, 2 India jobs |
| Sarvam AI | https://www.sarvam.ai/careers | Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/sarvam` | Python `is_india()` on `location` / `secondaryLocations`; full JD in `descriptionPlain` / `descriptionHtml` | 56 | ✅ CRACKED 2026-06-04 — direct Ashby API works; India-only board (50 Bengaluru, 6 Delhi); AI foundation-model startup; no Firecrawl needed |
| Skyflow | https://www.skyflow.com/careers | Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/skyflow` | Python `is_india()` on `location` / `secondaryLocations` (incl. "Remote - India"); full JD in `descriptionPlain` / `descriptionHtml` | 13 | ✅ CRACKED 2026-06-04 — direct Ashby API works; 13/13 India-tagged; Bangalore data-privacy SaaS; no Firecrawl needed |
| Cognition | https://cognition.ai/careers | Ashby | `GET https://api.ashbyhq.com/posting-api/job-board/cognition` | Python `is_india()` on `location` / `secondaryLocations`; full JD in `descriptionPlain` / `descriptionHtml` | 2 | ✅ CRACKED 2026-05-22 — direct Ashby API works; India roles with full JDs; no Firecrawl needed |
| Costco Wholesale | https://www.costcodigital.com/ | Talent500 | `GET https://prod-warmachine.talent500.co/api/jobs/?company_slug=costco` + detail `GET /api/jobs/{id}/` | `country.name == India` | 22 | ✅ CRACKED 2026-05-21 — Costco Digital India roles exposed through Talent500 public API; detail API returns full role summary/JD; routed to `ats=talent500`; no Firecrawl needed |
| NPCI | https://careers.npci.org.in/jobs/Careers | Zoho Recruit SSR HTML | `GET https://careers.npci.org.in/jobs/Careers` | India-only board; embedded jobs JSON; page_id `190737000000336688` | 14 | ✅ CRACKED 2026-05-21 — discovery promoted; generalized Zoho provider builds company-specific apply URLs |
| Juspay | https://juspay.io/careers | Astro SSR embedded jobs | `GET https://juspay.io/careers` | Python `is_india()` on embedded job location | 2 India / 7 global | ✅ CRACKED 2026-05-21 — discovery promoted; custom Astro parser extracts embedded jobs and JD text |
| Waaree Group | https://www.waaree.com/careers/ | Static rendered careers page | `GET https://www.waaree.com/careers/` | India static roles on page | 3 | ✅ CRACKED 2026-05-21 — discovery promoted; provider parses rendered on-page roles; no discrete ATS API exists; Firecrawl/rendered scrape required when local TLS/browser cannot read page |
| Stellantis | https://www.stellantis.com/en/careers | Custom | careers page | JS-rendered | 3 | ✅ working via Firecrawl — 3 India jobs extracted + enriched 2026-04-11 |
| TCS | https://www.tcs.com/careers | iBegin (custom) | `GET https://ibegin.tcs.com/iBegin/...` — inspect XHR | — | 0 | ⬇️ deprioritized — career page shows no visible jobs; antibot block (document_antibot); investigated 2026-04-30 |
| Capgemini | https://www.capgemini.com/in-en/careers/job-search/ | Custom Azure API | `GET https://cg-jobstream-api.azurewebsites.net/api/job-search?country_code=in-en&page=1&size=100` | country_code=in-en | 921 | ✅ CRACKED 2026-04-30 — no auth; full JD in description field; apply_job_url included; ats=custom |
| ZS Associates | https://jobs.zs.com/all/jobs | Custom (iCIMS) | `GET https://jobs.zs.com/api/jobs?page=1&country=India&sortBy=relevance&descending=false&internal=false` | country=India | 89 | ✅ CRACKED 2026-04-30 — no auth; full JD in jobs[].data.description; slug → apply URL; ats=custom |

---

## SAP SUCCESSFACTORS / JOBS2WEB COMPANIES
*API pattern varies — most return HTML, route through Firecrawl*

| Company | Careers URL | ATS | Scraping Endpoint | India Jobs | Status |
|---------|-------------|-----|------------------|-----------|--------|
| Alstom | https://jobsearch.alstom.com | SAP SuccessFactors / Jobs2Web (HTML) | `GET https://jobsearch.alstom.com/search/?createNewAlert=false&q=&locationsearch=india&optionsFacetsDD_country=&optionsFacetsDD_department=&optionsFacetsDD_shifttype=&startrow=N` | `locationsearch=india` | ✅ CRACKED 2026-05-02 — routed to `ats=sap_jobs2web_html`; direct HTML table parse + per-job detail JD extraction; run validated with 196 saved jobs |
| Monitor Deloitte | https://southasiacareers.deloitte.com/go/Deloitte-India/718244/ | SAP SuccessFactors / Jobs2Web (HTML) | `GET https://southasiacareers.deloitte.com/search/?createNewAlert=false&q=&locationsearch=india&optionsFacetsDD_city=&optionsFacetsDD_customfield2=` | ~1,772 | ✅ CRACKED 2026-05-02 — direct paginated HTML listing (`startrow=N`) + detail `/job/.../{id}` pages with full JD (`data-careersite-propertyid=\"description\"`) and apply URL; routed to `ats=sap_jobs2web_html` |
| GMR Group | https://careers.gmrgroup.in | SAP SuccessFactors / Jobs2Web (HTML) | `GET https://careers.gmrgroup.in/search/?q=&locationsearch=india&startrow=N` | 7+ | ✅ CRACKED 2026-05-13 — direct Jobs2Web HTML table parse + per-job detail JD extraction; targeted provider probe returned full JDs; routed to `ats=sap_jobs2web_html` |
| CMA CGM | https://jobs.cmacgm-group.com | SAP SuccessFactors / Jobs2Web (HTML) | `GET https://jobs.cmacgm-group.com/search/jobs?optionsFacetsDD_country=IN&startrow=N&sortColumn=referencedate&sortDirection=desc` | 4 | ✅ CRACKED 2026-05-07 — recovered from Market Data V1; old `country=India` URL is stale and returns global/US false positives; direct Jobs2Web HTML route uses country facet `optionsFacetsDD_country=IN` + per-job detail JDs; routed to `ats=sap_jobs2web_html` |
| CNHI | https://join.cnh.com | SAP SuccessFactors / JS SPA | `https://join.cnh.com/search/?q=india` | India-filtered search URL | ✅ working — careers.cnh.com + join.cnh.com both live; India filter via q=india; Firecrawl extract; updated 2026-04-28 |
| Volvo Group | https://www.volvogroup.com/en/careers | SAP SuccessFactors / Jobs2Web (HTML) | `GET https://jobs.volvogroup.com/search/?q=&locationsearch=India&startrow=N` | 27 | ✅ CRACKED 2026-05-07 — recovered from Market Data V1; direct Jobs2Web HTML table parse + per-job detail JD extraction; routed to `ats=sap_jobs2web_html` |
| Deloitte India | https://apply.deloitte.com/en_US/careersUSI/SearchJobs | Avature SearchJobs HTML (USI mirror) | `GET https://apply.deloitte.com/en_US/careersUSI/SearchJobs/?jobRecordsPerPage=10&jobOffset=N` | India feed (268 listings in latest snapshot) | ✅ CRACKED 2026-05-03 — direct paginated HTML listings + JobDetail pages with JSON-LD JD and apply URL; routed to `ats=deloitte_usi` |
| EY India | https://eyglobal.yello.co/job_boards/c1riT--B2O-KySgYWsZO1Q | Yello (Recsolu) | `GET https://eyglobal.yello.co/job_boards/c1riT--B2O-KySgYWsZO1Q/search?query=&filters=30009&page_number=N` | Country/Region filter id `30009` (India) | ✅ CRACKED 2026-05-02 — direct JSON listing (`/search`) + full JD on `/jobs/{token}` detail pages; ats=yello |
| EY India Experienced | https://careers.ey.com/ey/search/?createNewAlert=false&q=india&optionsFacetsDD_country=IN | SAP SuccessFactors / Jobs2Web (HTML) | `GET https://careers.ey.com/ey/search/?createNewAlert=false&q=india&optionsFacetsDD_customfield1=&optionsFacetsDD_country=IN&optionsFacetsDD_city=&startrow=N` | `optionsFacetsDD_country=IN` | ✅ CRACKED 2026-05-02 — `ats=sap_jobs2web_html`; detail JDs parsed from `data-careersite-propertyid=\"description\"`; quality gate drops postings where JD is only requisition-id stub |
| PepsiCo | https://www.pepsicojobs.com/main/jobs?location=India | PepsiCo Jobs API (JSON) | `GET https://www.pepsicojobs.com/api/jobs?page=1&sortBy=relevance&descending=false&internal=false&country=India` | `country=India` | ✅ CRACKED 2026-05-02 — direct paginated JSON listing (`jobs[].data`) includes full JD (`description`) + apply URL (`apply_url`); routed to `ats=pepsico_jobs_api` |
| Teradyne | https://jobs.teradyne.com | SAP SuccessFactors / Jobs2Web (HTML) | `GET https://jobs.teradyne.com/search/?q=&locationsearch=india&startrow=N` | 3+ validated | ✅ CRACKED 2026-05-21 — direct Jobs2Web HTML listing and detail pages work; routed to `ats=sap_jobs2web_html`; no Firecrawl needed |
| McDonald's GCC | https://jobs.mcdonalds.com/search/?q=&locationsearch=india | SAP SuccessFactors / Jobs2Web (HTML) | `GET https://jobs.mcdonalds.com/search/?q=&locationsearch=india&startrow=N` | 3+ validated | ✅ CRACKED 2026-05-21 — direct Jobs2Web HTML route works for corporate/GCC India roles; detail pages provide full JDs; routed to `ats=sap_jobs2web_html`; no Firecrawl needed |
| Asian Paints | https://careers.asianpaints.com/ | SAP SuccessFactors / Jobs2Web (HTML) | `GET https://careers.asianpaints.com/search/?q=&locationsearch=india&startrow=N` | 3+ validated | ✅ CRACKED 2026-05-21 — discovery promoted; direct Jobs2Web HTML route and detail JDs work |
| Bajaj Auto | https://careers.bajajauto.com/BajajAutoCreditLimited/ | SAP SuccessFactors / Jobs2Web (HTML) | `GET https://careers.bajajauto.com/BajajAutoCreditLimited/search/?q=&locationsearch=india&startrow=N` | 68 BACL URLs found | ✅ CRACKED 2026-05-21 — discovery promoted; BACL Jobs2Web board returns detail JDs; main corporate board still optional to verify |
| Tata Consumer Products | https://careers.tataconsumer.com/content/People/ | SAP SuccessFactors / Jobs2Web (HTML) | `GET https://careers.tataconsumer.com/search/?q=&locationsearch=india&startrow=N` | 50/page | ✅ CRACKED 2026-05-21 — discovery promoted; provider now accepts bare `IN` location token |
| Sun Pharma | https://careers.sunpharma.com/ | SAP SuccessFactors / Jobs2Web (HTML) | `GET https://careers.sunpharma.com/search/?q=&locationsearch=india&startrow=N` | 3+ validated | ✅ CRACKED 2026-05-21 — discovery promoted; do not use US/CA `jobs.sunpharma.com` TalentBrew board |
| Syngene | https://careers.syngeneintl.com/viewalljobs/ | SAP SuccessFactors / Jobs2Web (HTML) | `GET https://careers.syngeneintl.com/search/?q=&locationsearch=india&startrow=N` | 3+ validated | ✅ CRACKED 2026-05-21 — discovery promoted; direct Jobs2Web HTML route returns Bangalore jobs with full JDs |

---

## ORACLE HCM COMPANIES
*API pattern (basic): `GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?limit=25&offset=0&onlyData=true`*
*API pattern (finder/cracked): `?onlyData=true&expand=requisitionList.workLocation,...&finder=findReqs;siteNumber={Site Number},facetsList=LOCATIONS%3B...,limit=25,locationId={India Location ID},sortBy=POSTING_DATES_DESC`*
*Response shape (finder): nested — jobs at `items[0].requisitionList[]`; fields: `Id`, `Title`, `PrimaryLocation`*

| Company | Careers URL | Oracle Host | Site Number | India Location ID | India Jobs | Status |
|---------|-------------|------------|-------------|------------------|-----------|--------|
| Technip Energies | https://www.technipenergies.com/careers/ | hcxg.fa.em2.oraclecloud.com | CX_1 | 300000000345142 | 9+ | ✅ CRACKED 2026-04-29 — finder=findReqs India locationId confirmed; response nested at `items[0].requisitionList[]` |
| American Express | https://careers.americanexpress.com/en/sites/CX_1/jobs | egug.fa.us2.oraclecloud.com | CX_1 | 300000000228786 | 73 | ✅ CRACKED 2026-05-13 — Oracle Candidate Experience (`recruitingCEJobRequisitions?finder=findReqs`) discovered from live page source + Firecrawl cloud; India facet `locationsFacet -> India (Id=300000000228786)`; `TotalJobsCount=73` live |
| Kotak Mahindra Bank | https://hcbt.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1001/jobs | hcbt.fa.em2.oraclecloud.com | CX_1001 | | 7557 | ✅ CRACKED 2026-05-21 — discovery promoted; Oracle CE finder route works without locationId; `PrimaryLocation` is India-heavy; alternate sites `CX`, `CX_1` |
| EXL Digital | https://www.exlservice.com/careers | fa-ewjt-saasfaprod1.fa.ocs.oraclecloud.com | | | ? | 🔴 API auth-gated — base URL returns 200 but count=0 items=0 even without India filter; public API not exposed; route via Firecrawl scrape |
| JP Morgan Chase | https://careers.jpmorgan.com | jpmc.fa.oraclecloud.com | CX_1001 | 300000000289360 | 25+ | ✅ CRACKED 2026-04-29 — finder=findReqs India locationId confirmed; response nested at `items[0].requisitionList[]` |
| Honeywell | https://careers.honeywell.com/us/en | ibqbjb.fa.ocs.oraclecloud.com | CX_1 | 300000000469485 | 392 | ✅ CRACKED 2026-04-29 — 392 India jobs; JD empty (ShortDescriptionStr/ExternalDescriptionStr absent); `items[0].requisitionList[]` |
| KPMG India | https://home.kpmg/in/en/home/careers.html | ejgk.fa.em2.oraclecloud.com | CX_1 | 300000000296042 | 752 | ✅ CRACKED 2026-05-13 — finder=findReqs India locationId=300000000296042; 752 India jobs; JD empty in list API (JS-rendered candidate experience at oraclecloud.com/hcmUI/CandidateExperience); response at `items[0].requisitionList[]` |
| Texas Instruments | https://careers.ti.com | edbz.fa.us2.oraclecloud.com | CX | 300000000361484 | 114 | ✅ cracked 2026-04-29 — finder=findReqs+locationId; 114 India jobs; JD empty in list API (ExternalDescriptionStr absent) |
| Nokia | https://jobs.nokia.com | fa-evmr-saasfaprod1.fa.ocs.oraclecloud.com | CX_1 | 300000000471745 | 261 | ✅ cracked 2026-04-29 — finder=findReqs+locationId; 261 India jobs; JD=ShortDescriptionStr (477–770 chars) |
| BNY Mellon | https://www.bny.com/corporate/global/en/about-us/careers | eofe.fa.us2.oraclecloud.com | CX_3001 | 300000000378365 | 15+ | ✅ CRACKED 2026-04-29 — finder=findReqs India locationId confirmed; response nested at `items[0].requisitionList[]`; Chennai/Pune GCC |
| WESCO | https://www.wesco.com/us/en/careers.html | eklm.fa.us2.oraclecloud.com | CX | 300000000302954 | 7 | ✅ CRACKED 2026-05-07 — recovered from Market Data V1; Oracle HCM finder=findReqs with India locationId; response nested at `items[0].requisitionList[]`; targeted run saved 7 jobs; candidate URL uses `/sites/CX/job/{Id}` |
| Vertiv | https://egup.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/requisitions | egup.fa.us2.oraclecloud.com | CX | 300000000269771 | 3+ validated | ✅ CRACKED 2026-05-21 — Oracle CE finder endpoint works with India locationId; response nested at `items[0].requisitionList[]`; live probe fetched India roles and JDs |
| Adani Group | https://www.adani.com/careers | eibd.fa.em2.oraclecloud.com | CX_2027 | | ? | ✅ CRACKED 2026-04-30 — finder=findReqs; India-only portal (no locationId needed); is_india() Python filter applied; response nested at `items[0].requisitionList[]` |
| Adani Solar | https://www.adani.com/careers | eibd.fa.em2.oraclecloud.com | CX_2033 | | ? | ✅ CRACKED 2026-04-30 — same Oracle host; India-only; no locationId |
| Adani Power Transmission | https://www.adani.com/careers | eibd.fa.em2.oraclecloud.com | CX_2023 | | ? | ✅ CRACKED 2026-04-30 — same Oracle host; India-only; no locationId |
| Adani Thermal Power | https://www.adani.com/careers | eibd.fa.em2.oraclecloud.com | CX_3003 | | ? | ✅ CRACKED 2026-04-30 — same Oracle host; India-only; no locationId |
| Adani Gas | https://www.adani.com/careers | eibd.fa.em2.oraclecloud.com | CX_2025 | | 61 | ✅ CRACKED 2026-04-30 — same Oracle host; India-only; no locationId |
| Oracle | https://careers.oracle.com/en/sites/jobsearch | eeho.fa.us2.oraclecloud.com | CX_45001 | | 5+ | ✅ CRACKED 2026-05-13 — Oracle CE confirmed via XHR cURL; uses `location=India` text param (not locationId); endpoint override in portal_reader.py; India jobs live (Bengaluru/Hyderabad) |
| Icertis | https://iaaviz.fa.ocs.oraclecloud.com/hcmUI/CandidateExperience/en/sites/Jobs-at-Icertis/ | iaaviz.fa.ocs.oraclecloud.com | Jobs-at-Icertis | | 19 | ✅ CRACKED 2026-05-22 — Firecrawl search surfaced Oracle CE site; direct finder endpoint works with `location=India` text param; routed through endpoint override; most listings include JD/short description; no Firecrawl needed |

---

## iCIMS COMPANIES
*API: iCIMS REST not publicly documented — inspect XHR on careers page for `sc` (site config ID)*
*Typical search URL: `https://{company}.icims.com/jobs/search?ss=1&in_iframe=1&hashed=-1&mobile=false&country=IN&location=india`*

| Company | Careers URL | iCIMS Tenant | India Jobs | Status |
|---------|-------------|-------------|-----------|--------|
| Aon | https://jobs.aon.com/jobs?location=India&woe=12&regionCode=IN&stretchUnit=MILES&stretch=10&page=1 | Jibe / iCIMS Custom JSON | 32 | ✅ CRACKED 2026-05-15 — cookie-free JSON API works: `GET https://jobs.aon.com/api/jobs?country=India&page=1&sortBy=relevance&descending=false&internal=false&limit=100`; response shape is `jobs[].data` + `totalCount=32`; full JD in `jobs[].data.description`; `apply_url` points to `india-careers-aon.icims.com`; existing `ats=icims_custom` route works with default `country=India` filter; no Firecrawl/session cookies needed |
| JAGGAER | https://incareers-jaggaer.icims.com/jobs/search?ss=1&hashed=-435832948&mobile=false&country=IN&in_iframe=1 | Classic iCIMS HTML | 7 | ✅ CRACKED 2026-05-21 — official careers page links India to `incareers-jaggaer.icims.com`; iframe listing is server-rendered with `li.iCIMS_JobCardItem`, `IN-Hyderabad` location, job IDs, category, and full Overview/JD in the card; routed to `ats=icims_html`; no Firecrawl needed |

---

## PHENOM REST API COMPANIES
*Direct paginated JSON API with location + category filters. Full JDs included in response.*
*API pattern: `GET {API Endpoint}&page=N` — paginate until jobs array empty*

| Company | Careers URL | API Endpoint | Status |
|---------|-------------|-------------|--------|
| Schneider Electric | https://www.se.com/en/careers/ | `https://careers.se.com/api/jobs?location=India&categories=Digital+Innovation+%26+Technology&pageSize=10` | ✅ working — Phenom/iCIMS JSON REST API; ~132 India IT jobs; verified 2026-04-02 |
| BCG | https://careers.bcg.com/global/en/locations/india | `https://careers.bcg.com/global/en/search-results?keywords=india` | ✅ CRACKED 2026-05-08 — Phenom SSR HTML embeds `phApp.ddo.eagerLoadRefineSearch.data.jobs`; direct detail pages provide JSON-LD JDs; routed to `ats=phenom_ssr` |
| HP (HPE) | https://careers.hpe.com/us/en/search-results?qcountry=India | `https://careers.hpe.com/us/en/search-results?qcountry=India` | ✅ CRACKED 2026-05-13 — Phenom SSR embedded listings; `qcountry=IN` returned 0 but `qcountry=India` returns 363 India jobs in live probe; direct detail pages provide full JSON-LD JDs; routed to `ats=phenom_ssr` |
| Procter & Gamble | https://www.pgcareers.com/in/en/search-results?qcountry=India | `https://www.pgcareers.com/in/en/search-results?qcountry=India` | ✅ CRACKED 2026-05-02 — Phenom SSR HTML with embedded `phApp.ddo.eagerLoadRefineSearch.data.jobs`; country facet India=23 in snapshot; routed to `ats=phenom_ssr` (no Firecrawl needed) |
| Godrej Consumer Products | https://careers.godrejindustries.com/in/en/search-results?qcountry=India | `https://careers.godrejindustries.com/in/en/search-results?qcountry=India` | ✅ CRACKED 2026-05-20 — Phenom SSR `phApp.ddo.eagerLoadRefineSearch.data.jobs`; detail pages work at `/in/en/job/{jobSeqNo}` and expose JobPosting JSON-LD; routed to `ats=phenom_ssr` |
| Philip Morris International | https://join.pmicareers.com/gb/en/search-results | `https://join.pmicareers.com/gb/en/search-results` | ✅ CRACKED 2026-05-20 — Phenom SSR on unfiltered URL; `location=India` returns 0, so provider filters India in Python; detail pages expose JobPosting JSON-LD; routed to `ats=phenom_ssr` |
| Oliver Wyman | https://careers.marsh.com/global/en/oliver-wyman-search | `https://careers.marsh.com/global/en/oliver-wyman-search` | ✅ CRACKED 2026-06-09 — Phenom SSR on Marsh McLennan host; 19 India jobs (Gurgaon/Hyderabad) in live probe; provider filters India in Python; discovered via Firecrawl map of NEEDS_CRACK; routed to `ats=phenom_ssr` |

---

## PHENOM CX (PCSX) COMPANIES
*API: `GET https://{base}/api/pcsx/search?domain={domain}&query=&location=india&start={N}` — 10/page, no auth*
*JD: per-job HTML at `{base}/careers/job/{id}` → JSON-LD `<script type="application/ld+json">` — server-rendered, no JS*
*Pagination: `start` param increments by 10. Stop when `start >= data.count`.*

| Company | Careers URL | Base URL | Domain | India Jobs | Status |
|---------|-------------|----------|--------|-----------|--------|
| Haleon | https://careers.haleon.com | https://careers.haleon.com | haleon.com | 25 | ✅ cracked 2026-04-29 — pcsx list API + JSON-LD per-job JD; 6482 chars/job; no auth |
| Morgan Stanley | https://morganstanley.eightfold.ai/careers?location=INDIA&domain=morganstanley.com | https://morganstanley.eightfold.ai | morganstanley.com | 124 | ✅ CRACKED 2026-05-13 — PCSX search API on Eightfold host; 124 India jobs; India cities confirmed (Mumbai); no auth |
| Qualcomm | https://careers.qualcomm.com/careers?location=India&domain=qualcomm.com | https://careers.qualcomm.com | qualcomm.com | 625 | ✅ REVALIDATED 2026-05-20 — PCSX search API still works cookie-free at `start=0`, deep page `start=350`, and terminal page `start=620`; current count 625; JD via JSON-LD at `/careers/job/{id}` |
| NVIDIA | https://jobs.nvidia.com/careers?start=0&location=india&pid=893394950580&sort_by=distance&filter_include_remote=1 | https://jobs.nvidia.com | nvidia.com | 199 | ✅ REVALIDATED 2026-05-20 — PCSX search works cookie-free/provider-style: `GET /api/pcsx/search?domain=nvidia.com&query=&location=india&start=0`; deep pagination ok through `start=190`; current `pcsx` provider fetched JDs from `/careers/job/{id}` |
| PayPal | https://paypal.eightfold.ai/careers?location=india&domain=paypal.com | https://paypal.eightfold.ai | paypal.com | 7 | ✅ CRACKED 2026-05-21 — PCSX search works cookie-free: `GET /api/pcsx/search?domain=paypal.com&query=&location=india&start=0`; per-job HTML at `/careers/job/{id}` has full JSON-LD JDs; old `/api/apply/v2/jobs` returns 403 |
| Infineon Technologies | https://jobs.infineon.com/careers?location=india&domain=infineon.com | https://jobs.infineon.com | infineon.com | 3+ validated | ✅ CRACKED 2026-05-21 — PCSX search works cookie-free with `location=india`; per-job HTML has JSON-LD JDs; routed to `ats=pcsx` |
| Lam Research | https://careers.lamresearch.com/careers?location=india&domain=lamresearch.com | https://careers.lamresearch.com | lamresearch.com | 3+ validated | ✅ CRACKED 2026-05-21 — PCSX search works cookie-free with `location=india`; per-job HTML has JSON-LD JDs; routed to `ats=pcsx` |
| Micron Technology | https://micron.eightfold.ai/careers?domain=micron.com&start=0&location=India&pid=40670343&sort_by=distance&filter_include_remote=1 | https://micron.eightfold.ai | micron.com | 288 | ✅ REVALIDATED 2026-05-20 — PCSX search works cookie-free/provider-style: `GET /api/pcsx/search?domain=micron.com&query=&location=india&start=0`; deep pagination ok through `start=280`; current `pcsx` provider fetched JDs from `/careers/job/{id}`; old Eightfold apply API assumption remains retired |

---

## PINPOINT ATS COMPANIES
*API pattern: `GET https://{domain}/en/postings.json?location_id[]=<india_id>`*
*Returns `{"data": [...]}` — full JD in `description` field, no auth required.*
*India location IDs vary per tenant — enumerate via GET /en/postings.json (no filter) and filter names containing "India".*

| Company | Careers URL | Base URL | India Location IDs | India Jobs | Status |
|---------|-------------|----------|-------------------|-----------|--------|
| Align Technology | https://jobs.aligntech.com/en/search-job | https://jobs.aligntech.com | 40427,40404,40480,40518,40520,40522 | 44 | ✅ cracked 2026-04-29 — Pinpoint ATS; 6 India location IDs; full JD; no auth |

---

## SENSEHQ COMPANIES
*ATS: SenseHQ Next.js SSR — jobs embedded in `__NEXT_DATA__.props.pageProps.jobsData.rows[]`*
*Fields: `id`, `title`, `location`, `description_external`, `department`, `job_type`*
*No pagination — all jobs in single page load.*

| Company | Careers URL | India Jobs | Status |
|---------|-------------|-----------|--------|
| Marico | https://marico.sensehq.com/careers | 8 | ✅ CRACKED 2026-05-13 — SenseHQ Next.js SSR; 8 India jobs (mostly manufacturing); jobsData.rows[] in NEXT_DATA; no auth; low priority — small volume |

---

## AVATURE COMPANIES
*Avature requires JavaScript rendering — no clean JSON API. Use Firecrawl.*

| Company | Careers URL | India Jobs | Status |
|---------|-------------|-----------|--------|
| TotalEnergies | https://jobs.totalenergies.com/en_US/careers/SearchJobs/ | TalentBrew (Radancy) | ⬇️ deprioritised 2026-06-09 — TalentBrew board confirmed (not CF-blocked, returns job cards) but France/HQ-scoped: unfiltered + Firecrawl-discovered facet `707=[42257,42253]` both show 0 India / 10 France. India hiring not on this board. Revisit only if a real India location facet is found |

---

## OTHER PLATFORMS

| Company | Careers URL | ATS | Notes | Status |
|---------|-------------|-----|-------|--------|
| Air France | https://recrutement.airfrance.com | Custom | French-language portal | ⚠️ broken — Firecrawl crawl timeout (95s) as of 2026-04-11 |
| AstraZeneca | https://careers.astrazeneca.com/search-jobs/India | Radancy / TalentBrew | URL-based India filter; listing `data-total-pages`; detail pages provide JSON-LD JDs | ✅ CRACKED 2026-05-08 — routed to `ats=talentbrew`; no Firecrawl needed |
| ADP | https://jobs.adp.com/en/jobs/?mylocation=India&orderby=0&page=1&pagesize=20&rType=0&radius=100 | Happydance / TalentBrew-style | Direct India query URL; paginate via `page=N`; per-job detail URL `/en/jobs/{job_id}/{slug}/`; apply link from `recruiting.adp.com` button | ✅ cracked 2026-05-01 — ats=talentbrew; no Workday UUID needed; direct HTML scrape with India filter |
| H&M | https://career.hm.com/in-en/search/?l=cou%3Ain | HM Careers API (retired WordPress proxy) | `POST https://career.hm.com/in-en/wp-json/hm/v1/sr/jobs/search?_locale=user` | ↪️ retired 2026-08-13 — proxy now returns 403; replaced by the active SmartRecruiters `HMGroup` row |
| Intuit | https://jobs.intuit.com/location/india-jobs/27595/1269750/2 | TalentBrew (Avature feed) | Direct India country facet URL (no Workday UUID needed); paginated path `/.../2/{page}`; JD + apply URL from job detail page | ✅ cracked 2026-05-01 — ats=talentbrew; no auth; direct HTML/JSON-LD scrape |
| Adobe | https://careers.adobe.com/us/en/search-results | Phenom SSR (`ADOBUS`) | Search/listing is server-rendered via `phApp.ddo.eagerLoadRefineSearch`; full JD in job page JSON-LD at `/us/en/job/{jobSeqNo}` | ✅ cracked 2026-05-01 — ats=phenom_ssr; Workday CXS not required |
| ABB | https://careers.abb/global/en/search-results?keywords=india | Phenom SSR (`ABB1GLOBAL`) | Search page embeds `phApp.ddo.eagerLoadRefineSearch.data.jobs`; full JD available on detail pages `/global/en/job/{jobId}/{title}` with JobPosting JSON-LD | ✅ cracked 2026-05-02 — ats=phenom_ssr; no Workday UUID needed |
| Siemens | https://jobs.siemens.com/en_US/externaljobs/SearchJobs/?42386=%5B812053%5D&42386_format=17546&listFilterMode=1&folderRecordsPerPage=6& | Siemens ExternalJobs | India filter is `42386=[812053]`; paginate via `folderOffset`; fetch full JD from `/en_US/externaljobs/JobDetail/{job_id}` and apply URL from `/ApplicationMethods?folderId={job_id}` | ✅ cracked 2026-05-01 — ats=siemens_externaljobs; no Workday UUID needed |
| Eli Lilly | https://careers.lilly.com/us/en/india | Phenom People | India-filtered URL — Phenom SSR page embeds listing JSON; apply URLs point to Workday candidate pages | ✅ CRACKED 2026-05-08 — routed to `ats=phenom_ssr`; direct listing + JSON-LD JD extraction; no Firecrawl needed |
| Cisco | https://careers.cisco.com/global/en/search-results?qcountry=India | Phenom SSR (`CISCISGLOBAL`) | Direct India URL (`qcountry=India`); parse listings from `phApp.ddo.eagerLoadRefineSearch.data.jobs`; paginate via `from={offset}&s=1`; use `jobId/reqId`, `title`, `location`, `descriptionTeaser`, `applyUrl` | ✅ cracked 2026-05-02 — direct SSR route; Docker inventory 2026-05-08 also sampled 3 usable India jobs/JDs |
| Michelin | https://jobs.michelin.in/job-offer-result-list | Michelin Astro/CXF | India criteria JSON on `jobLocation` facets | ✅ CRACKED 2026-05-07 — recovered from Market Data V1; current India careers site is server-rendered Astro/CXF at `jobs.michelin.in`; provider applies legacy India `criteria` JSON, paginates `page=N`, and fetches full JD from detail pages; routed to `ats=michelin_astro` |
| Philips | https://www.careers.philips.com/global/en | Phenom / TalentBrew | India filter in URL | ⚠️ broken — Firecrawl crawled generic homepage (no India listing); needs India-filtered URL 2026-04-11 |
| SAP | https://jobs.sap.com | SAP (own platform) | `GET https://jobs.sap.com/search/?q=&locationsearch=India` | 🟡 js-required | ⚠️ broken — Firecrawl crawl timeout (95s) as of 2026-04-11 |
| Tech Mahindra | https://www.techmahindra.com/careers/ | Custom ASP.NET WebForms | Main site `Join Us` points to `https://careers.techmahindra.com/`; listings include `JobDetails.aspx?JobCode=...` links with full JD on detail page; filter India jobs via location text in listing/detail | ✅ cracked 2026-05-02 — old `/en-in/careers/` path is 404; use `/careers/` |
| Palo Alto Networks | https://jobs.paloaltonetworks.com/en/location/india-jobs/47263/1269750/2 | Radancy / TalentBrew | Direct India page has `data-total-job-results="104"` and job cards at `/en/job/{city}/{slug}/47263/{job_id}`; detail pages provide reusable HTML/JD route | ✅ CRACKED 2026-05-21 — routed to `ats=talentbrew`; provider supports section29 listing markup and JSON-LD detail JDs; no Firecrawl needed |
| Cargill | https://careers.cargill.com/en/search-jobs/India/23251/2/1269750/20/79/50/2 | TalentBrew (Radancy) | Direct India page has `data-total-job-results="83"` and plain job anchors at `/en/job/{city}/{slug}/23251/{job_id}`; detail pages provide reusable HTML/JD route | ✅ CRACKED 2026-05-21 — routed to `ats=talentbrew`; provider supports bare `h3` + `job-location` listing markup; no Firecrawl needed |
| Boeing | https://jobs.boeing.com/location/india-jobs/185/1269750/2/1 | Radancy / TalentBrew | Direct India location page has job cards at `/job/{city}/{slug}/185/{job_id}`; detail pages provide JSON-LD JDs | ✅ CRACKED 2026-05-22 — Firecrawl map found current India location URL; routed to `ats=talentbrew`; live provider probe returned India jobs with full JDs |
| Whatfix | https://whatfix101.hire.trakstar.com/ | Trakstar Hire / Recruiterbox | Server-rendered listing cards at `.js-careers-page-job-list-item`; detail pages under `/jobs/{id}/` provide full JDs | ✅ CRACKED 2026-05-22 — Firecrawl search surfaced Trakstar board; routed to `ats=trakstar`; direct HTML listing + detail fetch works without Firecrawl |
| MoEngage | https://www.moengage.com/careers/ | Trakstar Hire / Recruiterbox | Server-rendered listing cards at `li.js-careers-page-job-list-item` on `https://moengage.hire.trakstar.com/`; detail pages under `/jobs/{id}/` provide full JDs; `is_india()` on card location text | ✅ CRACKED 2026-06-04 — routed to `ats=trakstar`; 25 cards, India/Bengaluru/Mumbai; same markup as Whatfix; no Firecrawl needed |
| Exotel | https://exotel.com/careers/ | Trakstar Hire / Recruiterbox | Server-rendered listing cards at `li.js-careers-page-job-list-item` on `https://exotel.hire.trakstar.com/` (also exotel.recruiterbox.com); detail pages under `/jobs/{id}/` provide full JDs; `is_india()` on card location text | ✅ CRACKED 2026-06-04 — routed to `ats=trakstar`; 25 cards, Bengaluru/Gurugram/Mumbai; no Firecrawl needed |
| Uber | https://www.uber.com/careers/list/ | Custom | Firecrawl map found `/careers/list/159606`, but the detail now returns Uber's not-found page; no repeatable listing API identified | ⚠️ PARKED 2026-06-11 — stale discovery lead; revisit only with a browser XHR contract |
| Mondee Holdings | https://jobs.ashbyhq.com/mondee | Ashby (expired board) | Ashby posting API returns `organization: null` / 404 | 🔴 CLOSED 2026-06-11 — expired board with no active public portal |
| Nutanix | https://careers.nutanix.com/en/locations/india/ | DirectEmployers / JobSyndicate RSS | `GET https://nutanix.dejobs.org/jobs/feed/rss?location=India` | RSS title prefix `(IND-...)` / India feed | 82 | ✅ CRACKED 2026-05-21 — careers.nutanix.com is Cloudflare-blocked to direct HTTP, but dejobs RSS is public, contains full descriptions and stable detail URLs; routed to `ats=dejobs_rss`; no Firecrawl needed |
| Syneriq Global | https://www.syneriqglobal.com | Custom | No dedicated careers page found — small company; check LinkedIn or main site footer | 🟡 js-required — no careers page detected; probed 2026-04-19 |
| ZF Lifetec | https://www.zf.com/global/en/careers | SAP SuccessFactors (suspected) | zf.com antibot-blocked; zf-lifetec.com/career.html is 404 — parent ZF Group uses SAP SF | ⚠️ blocked — antibot on zf.com; zf-lifetec.com has no careers page; re-probe via zf.com direct browser visit |
| HMIE | https://hmie.in | Custom | hmie.in/careers and hmie.in/jobs both 404 — no independent career portal found | 🔴 no career portal — Hyundai Motor India Engineering hires via parent or LinkedIn; skip |
| Meta | https://www.metacareers.com/jobs | Custom (Relay GraphQL) | `GET /jobs` → page `lsd` token → `POST /api/graphql/` `doc_id=29615178951461218` `variables={"search_input":{}}` → `data.job_search_with_featured_jobs.all_jobs[]` (full global list, 457 in snapshot, no pagination); India filtered in Python on `locations[]` (`offices=["India"]` returns 0). Full JD from detail page `GET /jobs/{id}/` JobPosting JSON-LD. No auth/Docker/Firecrawl. | ✅ CRACKED 2026-06-07 — routed to `ats=meta_graphql` (`providers/meta_graphql.py`); smoke-verified 10 India jobs with full JDs |
| Walmart | https://careers.walmart.com/results?q=india | Custom Next.js SPA | Direct/Firecrawl listing is a JS shell; cloud map returns US detail pages despite `q=india` | ⚠️ PARKED 2026-06-11 — needs durable browser listing XHR; no guessed route promoted |
| DE Shaw | https://www.deshawindia.com/careers | D.E. Shaw Next.js SSR | Embedded `__NEXT_DATA__.props.pageProps.regularJobs`; full JD in `jobDescription`; apply redirect via `/recruit/jobs/Ads/Link/{jobUrl}` | ✅ CRACKED 2026-05-08 — routed to `ats=deshaw_india`; 76 public India roles in live probe; no Firecrawl needed |
| Adidas | https://jobs.adidas-group.com/search/?q=&optionsFacetsDD_country=IN | SAP SuccessFactors / Jobs2Web (HTML) | `GET https://jobs.adidas-group.com/search/?q=&optionsFacetsDD_country=IN&startrow=N` | `optionsFacetsDD_country=IN` | 7 | ✅ CRACKED 2026-05-13 — SAP Jobs2Web HTML at jobs.adidas-group.com; 7 India jobs; routed to `ats=sap_jobs2web_html` |
| LTIMindtree | https://careers.ltimindtree.com/search/?createNewAlert=false&q=&locationsearch=india | SAP Jobs2Web HTML | India-filtered URL returns ~2 India jobs; parse direct table cards and detail pages | ✅ CRACKED 2026-05-08 — routed to `ats=sap_jobs2web_html`; no Firecrawl needed |
| Genpact | https://careers.genpact.com | Workday | Active route recorded in WORKDAY COMPANIES section | ↪️ moved 2026-05-22 — use Workday row above |
| Amdocs | https://www.amdocs.com/about/careers | Workday (suspected) | `https://amdocs.wd3.myworkdayjobs.com` — Workday CXS 422 blocked; SmartRecruiters 0 results | 🟡 Workday tenant `amdocs.wd3` confirmed but CXS blocked and career_site slug TBD; FC fallback; probed 2026-04-19 |
| Zoho | https://careers.zohocorp.com/jobs/careers | Zoho Recruit (self-hosted) | `https://careers.zohocorp.com/jobs/careers` — Zoho uses own Zoho Recruit product; Chennai HQ | ⬇️ deprioritized — only 2 India jobs visible 2026-04-30 |
| Tata Elxsi | https://www.tataelxsi.com/careers/job-openings | Tata Elxsi HTML | Server-rendered listing cards at `/careers/job-openings?page=N`; full JD/apply URL on detail pages | ✅ CRACKED 2026-05-08 — routed to `ats=tata_elxsi`; live direct probe returned India jobs with JDs; no Firecrawl needed |
| Virtusa | https://www.virtusa.com/careers | Virtusa CMS + Firecrawl Cloud | Cloud map enumerates stable India detail URLs ending in `creqNNN` / `job-NNN`; cached batch scrape supplies full JDs | ✅ CRACKED 2026-06-11 — routed to `ats=virtusa_firecrawl`; live probe returned India requisitions |
| Mu Sigma | https://www.mu-sigma.com/careers | LinkedIn / email | Official careers page directs candidates to LinkedIn; internships use resume email | 🔴 CLOSED 2026-06-11 — no automatable public job feed |
| InMobi | https://www.inmobi.com/company/careers/ | Greenhouse | Board token `inmobi`; active route recorded in GREENHOUSE COMPANIES section | ↪️ moved 2026-05-20 — use Greenhouse row above |
| Ola Electric | https://olacareers.turbohire.co/dashboardv2?orgId=e0c1eb37-eb7a-4ca4-bcc5-d59ce4ce9212&type=0 | TurboHire | Public token endpoint `/api/token/noauth`; filtered listing endpoint `/api/careerpagev2/filteredjobs?orgId=...&pageType=0` currently returns 0 | ⬇️ VERIFIED 2026-06-11 — ATS/API identified, no active public jobs; promote when the API returns listings |
| Telefonica | https://www.telefonica.com/en/careers/ | Custom/SAP SF | Europe/LatAm focused — India presence minimal; no confirmed India GCC | ⚠️ India presence unclear — Telefónica Tech has some India ops; verify India jobs before adding; probed 2026-04-19 |
| Credit Suisse | — | MERGED → UBS | Acquired by UBS (March 2023); no standalone portal | 🔴 Merged into UBS — use UBS entry; careers.credit-suisse.com redirects to UBS; skip |

---

## CONSULTING COMPANIES
*ATS varies — most route through Firecrawl extract until direct API is confirmed.*

| Company | Careers URL | ATS | Status |
|---------|-------------|-----|--------|
| Bain & Company | https://careers.bain.com/jobs/SearchJobs/india/?folderRecordsPerPage=10&folderOffset=0 | ExternalJobs (SilkRoad) | ✅ CRACKED 2026-05-13 — 96 India jobs; listing JS-rendered (FC required); JD at `/jobs/FolderDetail/{slug}/{id}` via FC scrape; paginate via folderOffset=0,10,20...; NOT Workday |
| Nestlé | https://www.nestle.in/jobs/search-jobs | SAP SuccessFactors / Jobs2Web (HTML) | ✅ CRACKED 2026-05-13 — SAP Jobs2Web HTML at `jobdetails.nestle.com`; `locationsearch=india` filter; 31 India jobs across 4 pages (10/page, startrow=0/10/20/30); job detail at `/job/{city-slug}/{id}/` via direct HTTP; JD in `data-careersite-propertyid="description"`; apply URL `/talentcommunity/apply/{id}/?locale=en_US`; routed to `ats=sap_jobs2web_html`; endpoint override in `portal_reader.py:_SAP_ENDPOINT_OVERRIDES` — **Fallback**: `www.nestle.in/jobs/search-jobs?keyword=&country=IN` is CF+Akamai-protected HTML; already stored as `careers_url` so Firecrawl Docker fallback uses it automatically |
| BDO India | https://www.bdo.in/en-gb/careers/new-job-openings | Kentico Careers API | Listing page bootstraps `apiEndpointName`; direct `/api/en-gb/Careers/{widget}/Get?currentPage=N&pageSize=N` returns 32 current roles. Cloud map is fallback only | ✅ CRACKED 2026-06-11 — routed to `ats=bdo_firecrawl`; stable references, apply URLs and posting metadata |
| EY Parthenon | https://www.ey.com/en_in/careers/parthenon | MERGED → EY India | Parthenon opportunities use EY's existing recruiting routes | ↪️ MERGED 2026-06-11 — use EY India route; no duplicate scraper |
| Kearney | https://kearney.recsolu.com/job_boards/1 | Yello / Recsolu | Public `/job_boards/1/search` JSON plus detail pages; India filter discovered by provider | ✅ CRACKED 2026-06-11 — routed to `ats=yello`; live board currently has 0 India roles |
| L.E.K. Consulting | https://www.lek.com/careers | TAL.NET | Public appcentre Atom feed is live, but the current feed contains no India roles | ⬇️ VERIFIED 2026-06-11 — no active India jobs; do not spend Firecrawl credits |
| Deloitte India (BrassRing) | https://usijobs.deloitte.com/en_US/careersUSI/SearchJobs?jobRecordsPerPage=10&jobOffset=0 | Avature SearchJobs HTML (USI) | ✅ CRACKED 2026-05-03 — direct paginated HTML listings (`SearchJobs?jobOffset=N`) + detail pages (`/JobDetail/.../{id}`) with JSON-LD JD (`JobPosting.description`) and apply URL (`/Login?jobId={id}`); routed to `ats=deloitte_usi` |
| Practus | https://roibypractus.com/people-careers/ | Custom | ⬇️ low-priority — small boutique consulting firm; likely genuine low job count; deprioritised 2026-04-19 |
| Praxis Global Alliance | https://www.praxisga.com/career | Custom | ⬇️ low-priority — small boutique firm; deprioritised 2026-04-19 |
| PwC India | https://www.pwc.in/careers/experienced-jobs.html | Workday (pwc.wd3 / Global_Experienced_Careers) | ✅ CRACKED 2026-05-13 — searchText="india" mode; 221 India jobs; override in workday_registry.json as "PwC India"; JD at `pwc.wd3.myworkdayjobs.com`; ats=workday |
| Simon-Kucher & Partners | https://simon-kucher.csod.com/ux/ats/careersite/6/home/?c=simon-kucher | Cornerstone OnDemand | Bootstrap page provides anonymous JWT; direct `/services/x/career-site/v1/search` and requisition detail APIs | ✅ CRACKED 2026-06-11 — routed to `ats=cornerstone`; 141 global roles, currently 0 India |
| Strategy& (PwC) | https://www.strategyand.pwc.com/gx/en/careers.html | MERGED → PwC India | Strategy& careers resolve into PwC recruiting | ↪️ MERGED 2026-06-11 — use existing PwC India Workday route |
| Takshashila Consulting | https://tkc.firm.in/career.html | Email-only | Static page accepts applications at `hiring@tkc.firm.in`; no vacancy feed | 🔒 CLOSED 2026-06-11 — email-only |
| TransformationX | https://transformationx.com/join-us/ | Custom | ⬇️ low-priority — small boutique firm; deprioritised 2026-04-19 |
| Vector Consulting Group | https://www.vectorconsulting.in/careers/career-listings/ | Vector Next.js SSR | ✅ CRACKED 2026-05-08 — embedded `__NEXT_DATA__.props.pageProps.jobsData.dataset`; 2 India roles with full JD sections; routed to `ats=vector_consulting`; no Firecrawl needed |
| Black Brix | https://blackbrix.com/job-openings/ | WordPress Job Openings HTML | ✅ CRACKED 2026-05-13 — direct server-rendered listing cards + detail page JD/apply form; targeted run saved 1 Kolkata role with 2.4k-char JD; routed to `ats=blackbrix_jobs` |

---

## BFSI — INVESTMENT BANKING & ASSET MANAGEMENT

| Company | Careers URL | ATS | Notes | Status |
|---------|-------------|-----|-------|--------|
| ARGA Investment Management | https://www.argainvest.com | None (email: resumes@argainvest.com) | No public portal | 🔒 email-only |
| Arpwood Capital | https://www.arpwood.com/careers | Custom | Small boutique IB | ⬇️ low-priority — small firm, genuine low job count; deprioritised 2026-04-19 |
| Avendus Capital | https://avendus.darwinbox.in/ms/candidatev2/main/careers/allJobs | Darwinbox | Official site resolves to Darwinbox; requests require fresh Cloudflare/session cookies | ⚠️ PARKED 2026-06-11 — ATS identified, no durable cookie-free listing route |
| Claypond Capital | — | None (LinkedIn / email) | Manipal Group family office | 🔒 no public portal |
| Everstone Capital | — | None (LinkedIn) | PE firm — no dedicated portal | 🔒 no public portal |
| O3 Capital | http://www.o3capital.com | None (email: careers@o3capital.com) | Boutique IB | 🔒 email-only |
| Premji Invest | https://premjiinvest.zohorecruit.in/jobs/Careers | Zoho Recruit | SSR-embedded jobs plus company-specific detail/apply URLs | ✅ CRACKED 2026-06-11 — routed to `ats=zoho_recruit`; live probe returned 3 roles |
| Standard Chartered Bank | https://jobs.standardchartered.com/services/recruiting/v1/jobs | Taleo v1 | 530 India jobs; POST + keywords=india; no auth | ✅ CRACKED 2026-04-30 — ats=taleo taleo_v1=True; per-job JD via /job/{urltitle}/{id}/; totalJobs=530 |
| UBS | https://jobs.ubs.com/TGnewUI/Search/Home/Home?partnerid=25008&siteid=5012 | BrassRing TGNewUI | Bootstrap supplies CSRF/session values; `PowerSearchJobs` returns India jobs with full JDs | ✅ CRACKED 2026-06-11 — routed to `ats=ubs_brassring`; live API returned 19 India roles |
| SBI Mutual Fund | https://app1397.workline.hr/Cportal/GeneralOpening.aspx | Workline | Public `GetCurrentopening` JSON plus server-rendered CandidatePortal detail pages | ✅ CRACKED 2026-06-11 — routed to `ats=workline`; live probe returned full JDs |
| Integrow Asset Management | https://www.integrowamc.com/career/ | Custom | India AMC | 🟡 js-required |
| Moody's | https://careers.moodys.com/en/search-jobs/India/49841/2/1269750/22/79/50/2 | TalentBrew (Radancy) | OrganizationIds=49841; LocationPath=1269750 (India); path-paginated; results endpoint `/en/search-jobs/results`; routed via _ATS_OVERRIDES + _OTHER_ENDPOINT_OVERRIDES in portal_reader.py | ✅ CRACKED 2026-05-14 — TalentBrew confirmed from browser XHR; ats=talentbrew |
| Mastercard | https://careers.mastercard.com/us/en/search-results?LocationPath=1269750 | TalentBrew (Radancy) | LocationPath=1269750 = India filter; `PHPPPE_ACT`/`PHPPPE_GCC`/`PLAY_SESSION` cookies confirm TalentBrew; NOT Workday; ats=talentbrew; routed via _ATS_OVERRIDES + _OTHER_ENDPOINT_OVERRIDES in portal_reader.py | 🟡 CRACKED 2026-05-14 — TalentBrew confirmed; India URL inferred; needs validation run |

---

## BFSI — BANKING & FINANCE

| Company | Careers URL | ATS | Notes | Status |
|---------|-------------|-----|-------|--------|
| Bank of India | https://bankofindia.bank.in/career | Custom | PSU bank — limited listings | ⬇️ low-priority — PSU bank with infrequent tech openings; deprioritised 2026-04-19 |
| Credila (HDFC Credila) | https://www.credila.com/careers | Darwinbox | Firecrawl surfaced `https://mycredila.darwinbox.in/ms/candidate/careers`; direct Darwinbox API still requires fresh Cloudflare cookies (`DARWINBOX_CF_BM` + `DARWINBOX_SESSION`) | ⚠️ ATS identified 2026-05-22 — not cleanly reachable without browser cookies |
| CRISIL | https://www.crisil.com/en/home/careers.html | Zwayam | `companyId=MTU0Mzg=`, domain `career.crisil.com`, API `https://public.zwayam.com/jobs/search`; active route recorded in ZWAYAM COMPANIES section | ↪️ moved 2026-05-20 — use Zwayam row above |
| IndusInd Bank | https://app1100.workline.hr/careers/ | Workline | ATS identified, but public listing method returns `not authorized` | ⚠️ PARKED 2026-06-11 — needs repeatable browser token/XHR flow |
| L&T Finance | https://www.ltfs.com/careers.html | Custom | NBFC | ⬇️ low-priority — small NBFC, limited tech roles; deprioritised 2026-04-19 |
| Navi Technologies | https://navi.com/careers/jobs | TurboHire (partial) | Found TurboHire shell `https://navi.turbohire.co/dashboardv2?orgId=3e818601-0baa-429c-b6f8-4b21903ae0e6&type=0`, API base `https://api.turbohire.co`, public detail route pattern; listing XHR still unknown | ⬇️ deprioritized 2026-05-20 — needs browser Network/XHR capture before provider work |
| FinIQ | https://www.finiq.com/JobsPage/jobs.html | Static HTML + `jobs.js` | Direct campus/openings table; current snapshot has no India full-time roles and one Nashik engineering internship programme | ✅ VERIFIED 2026-06-11 — direct static route retained |

---

## CONGLOMERATES

| Company | Careers URL | ATS | Notes | Status |
|---------|-------------|-----|-------|--------|
| Aditya Birla Group | https://careers.adityabirla.com/job-search | Custom (aditya_birla) | India-only; 793 jobs; static Bearer token; per-job JD fetch /api/v3/job/{jobCode} | ✅ CRACKED 2026-04-30 — ats=aditya_birla; Bearer token static (no auth flow); pagination via offset |
| CK Birla Group | https://www.ckabirlagroup.com/workingwithus | LinkedIn-only | Official Working With Us page links LinkedIn jobs, not a public ATS | 🔴 CLOSED 2026-06-11 — no automatable public feed |
| Lodha Ventures | https://www.instahyre.com/jobs-at-lodha-ventures/ | Instahyre | Lodha family ventures arm | 🟡 js-required |
| Tata Administrative Services | https://www.tata.com/careers/programs/tas | Campus programme | Seasonal programme distributed through selected placement committees | 🔴 CLOSED 2026-06-11 — private/campus intake, not a public job feed |
| ITC Limited | https://recruitment.itcportal.com/jobs/Careers | Zoho Recruit (SSR HTML) | `page_id=48611000000181149`; 62 India jobs embedded in SSR HTML as entity-encoded JSON array; fields: Posting_Title, Job_Description, City, State, Country, id; apply URL /recruit/SingleJobDetail.na?sys_id={id}&page_id=48611000000181149 | ✅ CRACKED 2026-05-13 — routed to ats=zoho_recruit; provider at providers/zoho_recruit.py |

---

## CONSUMER GOODS (FMCG)


| Company | Careers URL | ATS | Notes | Status |
|---------|-------------|-----|-------|--------|
| Coromandel International | https://www.coromandel.biz/careers/ | Custom | Agri-inputs; part of Murugappa Group | 🟡 js-required |
| Godrej Consumer Products | https://careers.godrejindustries.com/in/en/search-results?qcountry=India | Phenom SSR | Active route recorded in PHENOM REST API COMPANIES section | ↪️ moved 2026-05-20 — use Phenom SSR row above |
| Godrej Industries (parent) | https://www.godrejcareers.com/ | Unknown | `godrejcareers.com` is separate from `godrejindustries.com`; Akamai 403 on direct requests 2026-05-15; may be internal/intranet portal for Godrej conglomerate employees | ⚠️ blocked — Akamai 403; investigate if public career portal exists or if it redirects to individual group company portals |
| United Breweries | https://careers.theheinekencompany.com/India/ | Workday (Heineken) | Part of Heineken Group | ⬇️ low-priority — FMCG, low tech hiring; check if tenant=heineken wd3 if re-activating; deprioritised 2026-04-19 |
| Wipro Consumer Care | https://wiproconsumercare.com/campus/ | Custom | Separate from Wipro IT — consumer FMCG division | ⬇️ low-priority — consumer goods arm, not tech; deprioritised 2026-04-19 |
| Unilever | https://careers.unilever.com/en/location/india-jobs/34155/1269750/2 | TalentBrew (TMP/Radancy) | company_id=34155; 2 India pages (path-paged /2 then /3); listing JS-rendered (FC fallback needed); job detail `/en/job/{city}/{slug}/34155/{job_id}` direct HTTP with JSON-LD JD | ✅ CRACKED 2026-05-13 — routed to ats=talentbrew; endpoint override in portal_reader.py |

---

## CONSUMER SERVICES & E-COMMERCE

| Company | Careers URL | ATS | Notes | Status |
|---------|-------------|-----|-------|--------|
| Nykaa | https://careers.nykaa.com | Skima Careers (SSR HTML) | Direct HTML listing + `?page=N` pagination + per-job UUID detail page with full JD panel | ✅ CRACKED 2026-05-02 — no auth/cookies required; 11 India jobs observed; routed to `ats=skima_careers` |

---

## INFORMATION TECHNOLOGY (IT) — NEW ADDITIONS

*Note: Wipro, TCS, Infosys, Cognizant, HCL Technologies are in existing sections.*

| Company | Careers URL | ATS | Notes | Status |
|---------|-------------|-----|-------|--------|
| HCL Software | https://www.hcl-software.com/careers | LinkedIn-only | Official Apply Now action resolves to LinkedIn company jobs | 🔴 CLOSED 2026-06-11 — no automatable public feed |
| HiLabs | https://www.hilabs.com/careers/all-open-positions?location=india | Next.js SSR payload | Health-tech AI | ✅ CRACKED 2026-05-13 — jobs embedded in `self.__next_f.push` under `groupedByPlaceAndDepartments.india["All Job Listing"]`; targeted run saved 3 India jobs with 2.8k-3.3k-char JDs; routed to `ats=hilabs_careers` |
| Sanas | https://ats.rippling.com/sanas/jobs | Rippling | Current Next.js board stores listings under dehydrated query state; detail pages contain full JD | ✅ CRACKED 2026-06-11 — routed to `ats=rippling`; live probe returned India role with full JD |
| Vehere Interactive | https://vehere.com/company/careers/ | WordPress/custom positions (partial) | Firecrawl surfaced durable `/positions/...` detail URLs; direct page and WP REST requests remain Cloudflare 403 without fresh browser cookie | ⬇️ deprioritized 2026-05-20 — use only if a browser session/XHR capture provides a durable non-Firecrawl route |

---

## RETAIL, PHARMA & REAL ESTATE — NEW ADDITIONS

| Company | Careers URL | ATS | Notes | Status |
|---------|-------------|-----|-------|--------|
| Bluestone Jewellery | https://www.bluestone.com/career | Custom | Online jewellery retail | ⬇️ low-priority — small e-commerce, low tech job volume; deprioritised 2026-04-19 |
| Mankind Pharma | https://www.mankindpharma.com/career/ | Static careers page | Official page states the company is currently not hiring | ⬇️ VERIFIED 2026-06-11 — no active positions |
| Welspun | https://www.welspuncorp.com/career.php | Custom | Textiles & infrastructure | ⬇️ low-priority — non-tech sector, low hiring volume; deprioritised 2026-04-19 |
| Arvind SmartSpaces | https://www.arvindsmartspaces.com/careers/ | Custom | Real estate developer | 🟡 js-required |
| Lodha Group | https://lodhacareers.peoplestrong.com | PeopleStrong | Public listing and basic-detail APIs; rendered detail fallback only when API text is incomplete | ✅ CRACKED 2026-06-11 — routed to `ats=peoplestrong`; live listing returned 27 roles |

---

## 🔒 LOGIN-REQUIRED PORTALS
*These portals require user authentication to view or apply for jobs.*
*Do not attempt to scrape job listings. Users are directed to the careers page to log in.*
*Scraper records a stub entry with the careers URL only.*

| Company | Careers URL | Notes | Last Verified |
|---------|-------------|-------|---------------|
| ARGA Investment Management | https://www.argainvest.com | Email-only: resumes@argainvest.com — no public job portal | 2026-04-12 |
| Claypond Capital | — | No public portal — apply via LinkedIn or email directly (Manipal Group family office) | 2026-04-12 |
| Everstone Capital | — | No public portal — openings posted on LinkedIn only | 2026-04-12 |
| O3 Capital | http://www.o3capital.com | Email-only: careers@o3capital.com — boutique IB | 2026-04-12 |
| Showtime Consulting | https://showtimeconsulting.in | Email-only: careers@showtimeconsulting.in | 2026-04-12 |
| Purplle | https://www.purplle.com/careers | Email-only: career@purplle.com — no automated portal | 2026-04-12 |

---

## ANTIBOT BLOCKED — DEPRIORITISED

*These portals are blocked by bot-detection (Cloudflare, Akamai, custom antibot) as of last verify.*
*Do not include in regular scrape runs — they waste time and credits with 0 output.*
*Try quarterly: URL may change, antibot config may relax. When reachable, move back to active section.*

| Company | Careers URL | ATS | Block Type | Last Verified |
|---------|-------------|-----|-----------|---------------|
| TCS | https://www.tcs.com/careers | iBegin | document_antibot (Firecrawl) | 2026-04-17 |
| S&P Global | https://www.spglobal.com/en/explore-s-p-global/careers | SmartRecruiters (unconfirmed) | document_antibot | 2026-04-17 |
| Coforge | https://careers.coforge.com | Custom / SmartRecruiters | All FC engines failed | 2026-04-17 |
| Elevation Capital | https://apply.workable.com/elevation-capital-3/ | Workable | All FC engines failed | 2026-04-17 |
| Yubi (formerly CredAvenue) | https://go-yubi.com/careers | Custom | document_antibot | 2026-04-17 |

---

## NO INDIA JOBS — EXCLUDED FROM SCRAPER

*These companies have been verified to have zero India job listings on their careers portals.*
*They are excluded from all scraping runs. Re-check periodically (e.g. quarterly) before re-adding.*
*Parser skips this entire section — entries here will never be scraped.*

| Company | Careers URL | ATS | Last Verified | Notes |
|---------|-------------|-----|---------------|-------|
| Volkswagen | https://jobs.volkswagen-group.com | Workday | 2026-04-02 | 0 India results — all "Indiana" false positives (US/DE/CA locations) |
| RTX (Raytheon) | https://careers.rtx.com/global/en | Workday (globalhr.wd5) | 2026-04-10 | 4,199 global jobs but 0 India facet — no India presence on this portal |
| Syngenta | https://www.syngenta.com/en/careers | SmartRecruiters | 2026-04-11 | ✅ MOVED TO SMARTRECRUITERS SECTION 2026-05-15 — correct company ID is SyngentaGroup (was Syngenta); 47 India jobs confirmed |
| Solvay | https://careers.solvay.com | SAP SuccessFactors | 2026-04-11 | Portal explicitly confirms "no open positions matching India" |
