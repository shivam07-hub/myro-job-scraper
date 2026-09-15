# Direct ATS Endpoint Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Firecrawl-dependent extraction for the highest-value verified companies with direct ATS/API/HTML endpoints that emit table-ready job records.

**Architecture:** Add focused providers for repeatable direct endpoints, use `portal_reader.py` overrides to route known companies away from Firecrawl, and keep Firecrawl only for endpoint discovery/fallback. All provider outputs remain raw scraper dicts that `writer.to_canonical()` converts into `schema.CANONICAL_FIELDS`.

**Tech Stack:** Python `requests`, existing provider registry, `writer.to_canonical()`, `KNOWN_PORTALS.md`, local no-network/unit tests plus targeted live company runs.

---

### Task 1: Canonical Output Guard

**Files:**
- Modify: `scraper/writer.py`
- Create: `scraper/test_writer_canonical.py`

- [x] Add a test that `to_canonical()` returns exactly `CANONICAL_FIELDS` keys and includes defaults for location/enrichment fields.
- [x] Update `to_canonical()` so jobs saved to JSON/CSV are shaped for the current `jobs` table.
- [x] Run `python3 test_writer_canonical.py`.

### Task 2: Promote Direct Endpoint Providers

**Files:**
- Create providers under `scraper/providers/` only when a repeatable endpoint pattern is verified.
- Modify: `scraper/providers/registry.py`
- Modify: `scraper/portal_reader.py`

- [x] Crack direct listing/detail endpoints with `requests`/`curl`, not Firecrawl.
- [x] Write small provider tests for parsing helpers before provider code.
- [x] Route company overrides in `portal_reader.py` so `main.py --company ...` uses direct providers.

### Task 3: Documentation And Evidence

**Files:**
- Modify: `KNOWN_PORTALS.md`
- Modify: `RUN_HISTORY.md`

- [x] Record the direct endpoint, JD mechanism, live sample counts, and any known caveats.
- [x] Mark unsafe Firecrawl samples as needing direct parser rather than cracked.

### Task 4: Verification

- [x] Run no-network tests.
- [x] Run targeted `python3 main.py --company "<Company>" --skip-enrich --company-cap 3` for promoted companies.
- [x] Run `git diff --check` and remove generated `__pycache__` folders.
