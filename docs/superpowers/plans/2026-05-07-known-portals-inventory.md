# Known Portals Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build a repeatable inventory mechanism that classifies every `KNOWN_PORTALS.md` company and optionally probes active providers to show which companies are currently hiring.

**Architecture:** Add a standalone scraper-side CLI that reuses `portal_reader.parse_portals()` and a conservative `providers.registry.probe_scrape()` helper rather than creating another bespoke data source. The tool writes timestamped JSON and Markdown reports under `logs/`, and skips JS/Firecrawl routes by default so it is safe to run without Docker.

**Tech Stack:** Python standard library, existing scraper provider registry, existing portal parser, existing logging-free direct provider calls.

---

### Task 1: Inventory CLI

**Files:**
- Create: `scraper/portal_inventory.py`

- [x] **Step 1: Implement status classification and safe probing**

Create a CLI with these behaviors:

```bash
cd /Users/incognito/firecrawl_Supabase/scraper
python3 portal_inventory.py --no-probe
python3 portal_inventory.py --probe --sample-size 3
python3 portal_inventory.py --probe --sample-size 3 --limit 25 --offset 25
python3 portal_inventory.py --probe --include-js --sample-size 3
```

Expected behavior:
- `--no-probe` reads and classifies portals only.
- `--probe` runs direct providers only and skips `js_required=True` portals.
- `--include-js` allows Firecrawl-backed portals only when Docker/cloud is intentionally available.
- Each run writes `logs/portal_inventory_<timestamp>.json` and `.md`.

- [x] **Step 2: Report fields**

Each company row must include:

```python
{
    "company": "Stripe",
    "ats": "greenhouse",
    "industry": "Fintech",
    "endpoint": "https://...",
    "route_state": "cracked",
    "probe_state": "hiring",
    "job_count_sample": 3,
    "sample_titles": ["Software Engineer"],
    "needs_docker": False,
    "notes": "✅ working"
}
```

- [x] **Step 3: Markdown executive summary**

The Markdown report must include counts by route state, counts by ATS, companies currently hiring from probe results, and companies needing Docker/fresh XHR.

### Task 2: Tests

**Files:**
- Create: `scraper/test_portal_inventory.py`

- [x] **Step 1: Test classification without network**

Run:

```bash
cd /Users/incognito/firecrawl_Supabase/scraper
python3 test_portal_inventory.py
```

Expected: PASS without requiring Docker, LM Studio, Supabase, or Firecrawl.

### Task 3: Docs

**Files:**
- Modify: `CLAUDE.md`
- Modify: `RUN_HISTORY.md`

- [x] **Step 1: Document inventory commands**

Add safe commands:

```bash
python3 portal_inventory.py --no-probe
python3 portal_inventory.py --probe --sample-size 3
python3 portal_inventory.py --probe --sample-size 3 --limit 25
python3 portal_inventory.py --probe --include-js --sample-size 3
```

- [x] **Step 2: Explain Docker rule**

Document that Docker is only needed for `--include-js` or full scrape fallback validation.

### Task 4: Verification

**Files:**
- Verify all files above.

- [x] **Step 1: Run syntax checks**

```bash
cd /Users/incognito/firecrawl_Supabase/scraper
python3 -m py_compile portal_inventory.py test_portal_inventory.py
```

Expected: no output, exit 0.

- [x] **Step 2: Run tests**

```bash
cd /Users/incognito/firecrawl_Supabase/scraper
python3 test_portal_inventory.py
```

Expected: all tests pass.

- [x] **Step 3: Generate no-network inventory**

```bash
cd /Users/incognito/firecrawl_Supabase/scraper
python3 portal_inventory.py --no-probe
```

Expected: JSON and Markdown reports are written under `../logs/`.

- [x] **Step 4: Generate direct-provider hiring sample**

```bash
cd /Users/incognito/firecrawl_Supabase/scraper
python3 portal_inventory.py --probe --sample-size 3 --limit 25
```

Expected: the first direct-provider batch is sampled; JS-required routes are skipped and marked `needs_docker=True`.

- [x] **Step 5: Merge batch reports**

```bash
cd /Users/incognito/firecrawl_Supabase/scraper
python3 portal_inventory.py --merge ../logs/portal_inventory_<batch>.json ...
```

Expected: one merged JSON and Markdown report with deduplicated rows sorted by inventory order.

---

Self-review:
- This plan does not introduce a second source of truth; it reuses `KNOWN_PORTALS.md`.
- Default run is safe without Docker or paid Firecrawl.
- Probe mode gives current hiring signal for direct providers and leaves JS-required routes for an intentional Docker run.
