# Myro Job Scraper

The job-discovery pipeline behind [Myro](https://himyro.com). It scrapes 300+ company
career portals worldwide, pulls **full job descriptions**, normalizes them into one
canonical schema, and publishes them to Supabase where the Myro product reads them.

**Current scale:** ~53k jobs tracked, ~46k active, 316 portal parsers, 414k skill links.

---

## The one rule that shapes everything

> **If a company's ATS exposes a direct API, we use it. Scraping is the fallback,
> never the default.**

Almost every careers page in the world is a thin frontend over one of ~25 applicant
tracking systems — Workday, Greenhouse, Lever, Ashby, SmartRecruiters, Phenom, Darwinbox
and friends. Those systems have JSON endpoints. They are fast, free, stable, and return
the complete job description in one call.

Rendering the page with a headless browser is slower, costs money, breaks whenever the
site ships CSS, and returns worse data. So we only do it when a portal is genuinely
JS-opaque or anti-bot.

The corollary is **"crack once, reuse forever"** — when someone works out a company's
real endpoint, that knowledge gets written to a registry file and never has to be
rediscovered. See [Registries](#registries).

---

## Pipeline

```
KNOWN_PORTALS.md ──► main.py / providers/ ──► raw jobs.json
                                                    │
                                    source_matching_facts.py   ◄── MANDATORY
                                    (stamps career_band + provenance)
                                                    │
                              csv_importer.py --source-only
                                                    │
                                    job is live in Supabase
                                     ╱                    ╲
                     embedding queue                    enrichment queue
                             │                                 │
                   job_embedding_worker.py            enrichment_worker.py
                             │                                 │
                   semantic search RPC              job_summary + role_domain
```

Three ideas to hold onto:

1. **Publication does not wait for AI.** Source fields go live immediately. Summaries,
   role domains, and embeddings arrive later and are treated as *upgrades* to a row that
   is already useful. A re-scrape never overwrites an enrichment.
2. **The resolver step is not optional.** `csv_importer` will reject an entire run whose
   rows lack `career_band_source` + `career_band_source_hash`. Scrape → publish with no
   `source_matching_facts.py` in between fails. `daily_poll.py` wires all three in order.
3. **Forward-only.** Fixes apply from the next scrape onward. We do not backfill
   historical rows. If a normalizer improves, old rows keep their old values.

---

## Setup

Requires Python 3.11+ (3.13 in use), and a `scraper/.env` file — ask the maintainer.

```bash
git clone <this-repo> && cd myro-job-scraper/scraper
python3 -m venv ../.venv && source ../.venv/bin/activate
pip install -r requirements.txt
```

Then check what your environment can actually run. This reports **presence, never
values** — it will not print a secret:

```bash
python environment.py
```

`environment.py` is the single source of truth for every env key and the capability it
unlocks. Nothing else in the codebase calls `load_dotenv` or guesses a key name. If you
need a new config value, declare it there.

### Optional local services

| Service | Needed for | Notes |
|---|---|---|
| **LM Studio** | enrichment + embeddings | Local inference. Only **one** worker may run at a time — see [Local inference](#local-inference). |
| **Firecrawl** (cloud key) | JS-opaque portal fallback | Free tier throttles at 6 req/min. Spend deliberately. |

Neither is required to scrape a direct-ATS portal, which is most of them.

---

## First commands to run

Start read-only. Nothing here writes to Supabase.

```bash
cd scraper

# 1. Does every portal in KNOWN_PORTALS.md still parse? (~316 rows, no network)
python main.py --dry-run

# 2. What routes do we have, and what state are they in? (no Docker, no Firecrawl)
python portal_inventory.py --no-probe

# 3. Scrape exactly one company and look at the output
python main.py --company "Stripe"

# 4. Read the run's own self-diagnosis
python diagnose.py
```

Output lands in `All_CSV_Outputs/<Company>/Outputs/<YYYY_MM_DD>/jobs.{json,csv}`
(git-ignored — generated job dumps are never committed).

### The real daily sequence

```bash
RUN_DATE=$(date +%Y_%m_%d)

python main.py --skip-enrich --scope global            # 1. scrape
python source_matching_facts.py --run-date "$RUN_DATE" --allow-unresolved   # 2. resolve
python csv_importer.py --source-only --publish-unclassified --run-date "$RUN_DATE" --dry-run
python csv_importer.py --source-only --publish-unclassified --run-date "$RUN_DATE"
```

`daily_poll.py` runs all of this in order with the run date pinned, so a scrape that
crosses midnight still resolves and publishes as one folder. **Always `--dry-run` an
importer command before the real one.**

---

## Repo layout

| Path | What it is |
|---|---|
| `KNOWN_PORTALS.md` | **The registry of every company we scrape.** Source of truth, human-edited. Start here. |
| `scraper/main.py` | Orchestrator. Every CLI flag. Runs self-diagnosis at the end. |
| `scraper/providers/` | One module per ATS type. All scraping logic lives here. |
| `scraper/portal_reader.py` | Parses `KNOWN_PORTALS.md` into portal dicts |
| `scraper/schema.py` | `Portal` TypedDict + `CANONICAL_FIELDS` — the schema contract |
| `scraper/environment.py` | Every env key and the capability it unlocks. The only `load_dotenv`. |
| `scraper/config.py` | Resolved config values and tuning knobs |
| `scraper/source_matching_facts.py` | Mandatory pre-publish pass (career band + provenance) |
| `scraper/csv_importer.py` | Publishes to Supabase |
| `scraper/source_snapshot.py` | Owns the jobs upsert and feed close. Never deletes rows. |
| `scraper/enrichment_worker.py` | Drains the enrichment queue against LM Studio |
| `scraper/job_embedding_worker.py` | Builds semantic-search vectors |
| `scraper/diagnose.py` + `scraper/heal/` | Self-healing diagnostic — classifies failures into buckets, re-probes routes |
| `scraper/discovery/` | Scale-out: finds new company boards to add |
| `scraper/tests/` | pytest suite |
| `docs/` | Design docs, handoffs, incident reports |
| `CLAUDE.md` | **The full architecture record.** Deeper than this README. Read it second. |

### Registries — the "crack once" memory

| File | Holds | Written by |
|---|---|---|
| `workday_registry.json` | Per-tenant India UUID, facet params, `blocked=true` | auto |
| `generic_registry.json` | Which JSON keys worked for a company | auto |
| `company_industries.json` | Company → industry | manual |
| `baseline_ledger.json` | Per-company last-known-good count (regression detection) | auto |

`blocked=true` means Cloudflare rejects all POSTs to that tenant — the scraper skips the
API and goes straight to the fallback. Never hand-clear that flag without evidence.

---

## Working here

### Change discipline

Prefer **running existing code** over writing new code. The pipeline has a lot of CLI
flags, env toggles, providers, and diagnostics already. Before proposing an
implementation change:

1. Reproduce the failure and capture the actual error.
2. Check whether an existing flag, provider, or registry entry already handles it.
3. Only then bring the root cause, the options, and the tradeoffs to the maintainer.

A company returning 0 jobs is usually a stale parameter or a changed endpoint, not a bug
in the orchestrator. `python diagnose.py --probe` re-tests routes live and tells you
which.

### Local inference

LM Studio keeps few models resident. If the embedding worker and the enrichment worker
run at once, one evicts the other and the loser fails with a confusing network error.
A file lock enforces one at a time — **the second worker exits with code 3**. That exit
code is not a crash; it means "another worker holds the slot."

### Firecrawl credit discipline

Firecrawl is a paid discovery microscope, not the architecture. Only three calls are
permitted: `map_site()`, `scrape()`, `extract()`. Never `crawl()`. Use it to *find* a
company's real endpoint, then promote that direct route and stop paying.

### Don't

- Don't backfill historical Supabase rows.
- Don't use `--resume` on a fresh weekly run — it skips companies that already have an
  output folder.
- Don't write `job_skills` from here. That table belongs to Myro's skill engine.
- Don't commit anything from `All_CSV_Outputs/`, `logs/`, or a `.env`.
- Don't promote a staffing agency or job aggregator into `KNOWN_PORTALS.md`. We index
  **single identifiable employers** — that's the product promise.

---

## Good first tasks

1. **Run `python diagnose.py --probe`** on the latest run and pick one company from the
   `REGRESSION` bucket. It had a working baseline and now returns 0 — usually the
   cheapest possible win, and it teaches you the provider layer.
2. **Add a portal.** Find a company on Greenhouse/Lever/Ashby, confirm its token with the
   free probes in `scraper/discovery/`, add a row to `KNOWN_PORTALS.md`, verify with
   `python main.py --company "<Name>"`.
3. **Read `CLAUDE.md` end to end.** It is long on purpose — it is the durable record of
   why the architecture looks the way it does.

---

## License

Proprietary — all rights reserved. See [LICENSE](LICENSE).
