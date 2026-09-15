# Management Recruiter Data Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote the 2026-05-21 management-recruiter ATS discoveries into active scraper routes where they can safely produce canonical jobs table rows.

**Architecture:** Keep direct ATS routes in the existing provider registry and `KNOWN_PORTALS.md` parser flow. Add only small provider extensions for response shapes discovered during Firecrawl probing: RippleHire `jobVoList`, generalized Zoho Recruit apply URLs, Juspay Astro SSR jobs, and Waaree static markdown/page parsing. Park portals where Firecrawl found only rendered shells, forms, Cloudflare/session blocks, or no current jobs.

**Tech Stack:** Python scraper providers, markdown portal parser, existing canonical writer, direct HTTP APIs, Firecrawl only as fallback for portals with no direct route.

---

### Task 1: Add Failing Provider Unit Tests

**Files:**
- Modify: `scraper/test_direct_endpoint_providers.py`

- [ ] **Step 1: Add tests for the newly discovered response shapes**

Add tests covering:
- SAP Jobs2Web bare `IN` location token.
- RippleHire `jobVoList` listing + detail merge.
- Zoho Recruit configurable `page_id` and host.
- Juspay Astro embedded job parser.
- Waaree static markdown parser.

- [ ] **Step 2: Run test to verify red**

Run: `python3 scraper/test_direct_endpoint_providers.py`

Expected: FAIL because helper functions/providers are not implemented yet.

### Task 2: Implement Minimal Provider Changes

**Files:**
- Modify: `scraper/providers/sap_jobs2web_html.py`
- Modify: `scraper/providers/ripplehire.py`
- Modify: `scraper/providers/zoho_recruit.py`
- Create: `scraper/providers/juspay_astro.py`
- Create: `scraper/providers/waaree_static.py`
- Modify: `scraper/providers/registry.py`

- [ ] **Step 1: Implement just enough logic for the tests**

Keep all raw outputs in the existing raw job schema: `job_id`, `title`, `job_url`, `source_api_url`, `business_unit`, `raw_jd_text`, `location_city`, `date_posted`, `source_platform`, `industry`.

- [ ] **Step 2: Run provider tests**

Run: `python3 scraper/test_direct_endpoint_providers.py`

Expected: PASS.

### Task 3: Promote Safe Portals

**Files:**
- Modify: `KNOWN_PORTALS.md`
- Modify: `scraper/portal_reader.py`
- Modify: `scraper/workday_registry.json`
- Modify: `scraper/company_industries.json`
- Modify: `RUN_HISTORY.md`

- [ ] **Step 1: Add active rows**

Promote direct routes for SAP Jobs2Web, Workday, Oracle, RippleHire, Zoho Recruit, Juspay, and Waaree.

- [ ] **Step 2: Keep parked rows inactive**

Leave HDFC Ergo, ClearTax, Amul, Lava, Modelama, Policybazaar, and Dabur as discovery/parked notes until the blockers are solved.

- [ ] **Step 3: Run parser/routing checks**

Run: `python3 scraper/test_direct_endpoint_routing.py`

Expected: PASS and newly promoted companies route to direct providers without `js_required`.

### Task 4: Smoke Scrape Promoted Companies

**Files:**
- No production code changes.

- [ ] **Step 1: Run low-cap scrape probes without enrichment**

Run targeted commands such as:

```bash
SCRAPE_DIAGNOSTICS_DISABLED=1 python3 scraper/main.py --company "Asian Paints" --skip-enrich --company-cap 3
SCRAPE_DIAGNOSTICS_DISABLED=1 python3 scraper/main.py --company "Axis Bank" --skip-enrich --company-cap 3
```

Expected: Each promoted company either saves canonical rows or produces a concrete provider failure for follow-up.

