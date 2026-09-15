# HANDOFF — Multi-location per-city capture (`jobs.locations TEXT[]`)

> **Origin:** True_Yodha backlog "firecrawl #6". Paired with the True_Yodha geo-preference
> filter work shipped 2026-06-02. This is the **scraper half**. The consumption half
> (read + render + filter) is already done in True_Yodha — see "What True_Yodha already
> consumes" below. Your job: **populate the column**.

---

## The ask

When one posting spans several cities, ATS portals often return a **count phrase**
("2 Locations", "multiple locations", "various locations") in the summary string instead
of the actual city list. Capture the real cities into a new canonical `locations TEXT[]`
column so multi-city jobs stop collapsing to one unusable "N Locations" string.

## Root cause (exact)

`scraper/csv_importer.py::_normalize_location` (line 231):

```python
_MULTI_LOCATION_RE = re.compile(r"\b\d+\s*locations?\b|multiple locations|various locations")  # :130
...
if mode == "unknown" and _MULTI_LOCATION_RE.search(lower):   # :250
    quality = "unknown"
    city = None                                              # :252  ← real cities thrown away
```

→ row written with `location_city = NULL`, `location_quality = "unknown"`, and the count
phrase parked in `location`/`location_raw` (`csv_importer.py:478-489`). The real cities only
ever existed on the source page, never in our schema.

**Why it matters for True_Yodha's new filter:** the `/jobs/feed` location filter and the
geo-preference scope both match on the **scalar** `location_city`. A multi-loc row with
`location_city = NULL` is **invisible to city filtering** — a Bangalore-targeting user never
sees a "2 Locations" job that actually includes Bangalore. Populating `locations[]` is what
fixes that coverage gap.

---

## Fix path (this session)

### 1. Schema — `locations TEXT[]` (physical column already added)

The physical column **already exists** in the shared Supabase `jobs` table — True_Yodha
applied this migration on 2026-06-02:

```sql
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS locations TEXT[] NOT NULL DEFAULT '{}';
```

Canonical city names. Keep the scalar `location_city` as the **primary / first element**
for back-compat + the country match filter. `locations` is additive, never replaces the
scalar.

**You must sync `scraper/schema.py`:** append `"locations"` to the **end** of
`CANONICAL_FIELDS` (after `"location_quality"`, `schema.py:83`) so column order stays stable.
Add a header-map entry if the importer maps by header. Verify against
`test_writer_canonical.py` / `supabase_contract_probe.py` (canonical-order contract tests).

### 2. Provider extraction — pull the city array

Many ATS list/detail JSON payloads carry a real city array even when the human-readable
summary says "N Locations". Extract per provider in `scraper/providers/*`:

- **Workday** — `locations` / `locationHierarchy*` facets; detail JSON often has a
  `locationsText` + structured locations list. (`workday_facet_param` already tracked in
  schema.py:48 — reuse that knowledge.)
- **Phenom / PCSX (`phenom_ssr`)** — list JSON commonly carries a `locations[]` /
  `cityState[]` array per posting.
- **Lever** — `categories.allLocations[]` (Lever exposes the full list distinct from the
  single `categories.location`).
- Others (iCIMS, Ashby, Rippling, SAP, etc.) — check each payload; only wire providers that
  actually expose the array. Don't fabricate.

Emit the array up to `_normalize_location` (or alongside it — see step 3).

### 3. `_normalize_location` — emit the array, stop nulling recoverable cities

Extend `NormalizedLocation` with `locations: list[str]`. When a multi-location phrase is hit
**but the provider supplied a real city array**, set `locations = [normalized cities]`,
`location_city = locations[0]`, and `location_quality = "ok"` (no longer "unknown"). When no
array is recoverable, keep today's behavior (`location_city = None`, quality `"unknown"`,
`locations = []`).

For single-city rows, `locations = [location_city]` (so the array is always populated and
the filter has one consistent path). Write it in the row builder (`csv_importer.py:478-489`).

### 4. Backfill existing rows

Where `location_quality = 'unknown'` AND `source_url` still resolves AND the provider exposes
a city array — re-extract and update `locations` + `location_city` + `location_quality`.
One-off script; **delete it at session end** (True_Yodha rule: temp scripts don't persist).
Idempotent; chunk the updates.

---

## What True_Yodha already consumes (the contract — don't break it)

Shipped True_Yodha-side 2026-06-02. The moment you populate `locations[]`, this lights up:

- `JobFeedItem` / `JobMatch` carry `locations: list[str]` (defaults `[]`).
- Repo `SELECT` includes `locations`.
- `LocationLine` renders `locations[]` as city chips when non-empty; falls back to the
  scalar `location` string (count phrase → `source_url` link + mode chip) when empty.
- The geo-preference filter matches a job if a pref chip's city is the scalar `location_city`
  **OR** is in `locations[]`. So a populated array immediately restores multi-loc rows to
  city filtering.

**Invariant:** `locations[0]` should equal `location_city` for every row you write. True_Yodha
relies on the scalar staying the primary city + the country filter staying scalar-driven.

---

## Touch list

- `scraper/schema.py` — `CANONICAL_FIELDS` += `"locations"` (append, keep order).
- `scraper/csv_importer.py` — `NormalizedLocation` + `_normalize_location` (231) + row
  builder (478-489).
- `scraper/providers/*` — per-ATS city-array extraction (Workday, Phenom, Lever first).
- backfill one-off script (delete after).
- contract tests — `test_writer_canonical.py`, `test_csv_importer_skill_levels.py`,
  `supabase_contract_probe.py`.

## Session ritual reminder

Read this repo's `CLAUDE.md` + `CODEX_HANDOFF.md` first. Run the canonical-contract probe
before and after. Don't touch True_Yodha from the scraper session — the consumption side is
done and the column already exists.
