"""
Pipeline validation script (v2 schema) — run before a full weekly scrape.

Tests portal parsing, HTML stripping, Greenhouse live fetch, LLM enrichment,
and writer output. Does NOT call Firecrawl — Firecrawl is only called during
real scrape runs, not tests.

Run: python3 test_pipeline.py
"""
import json
import sys
from pathlib import Path

from utils import strip_html
from providers.greenhouse import scrape_greenhouse
from enricher import enrich_job
from writer import to_canonical, save_jobs, SCHEMA
from portal_reader import parse_portals

PASS = "✓"
FAIL = "✗"
_failures = []


def check(label, condition, detail=""):
    status = PASS if condition else FAIL
    if not condition:
        _failures.append(label)
    print(f"  {status}  {label}" + (f"  [{detail}]" if detail else ""))
    return condition


def section(title):
    print(f"\n{'─'*55}")
    print(f"  {title}")
    print(f"{'─'*55}")


# ── 1. Portal reader ──────────────────────────────────────────────────────────
section("PORTAL READER")
portals = parse_portals()
check("Parses portals", len(portals) >= 40, f"{len(portals)} portals")
ats_types = {p['ats'] for p in portals}
for ats in ['workday', 'smartrecruiters', 'greenhouse']:
    check(f"Has {ats} portals", ats in ats_types)
check("All portals have industry", all(p.get('industry') for p in portals),
      f"{sum(1 for p in portals if not p.get('industry'))} missing")
js_portals    = [p for p in portals if p['js_required']]
direct_portals = [p for p in portals if not p['js_required']]
check("JS-required portals flagged", len(js_portals) > 0,  f"{len(js_portals)}")
check("Direct-API portals present",  len(direct_portals) > 0, f"{len(direct_portals)}")

# ── 2. HTML stripping ─────────────────────────────────────────────────────────
section("HTML STRIPPING")
cases = [
    ("normal HTML",    "<p><b>Python</b>, SQL</p>",           "Python"),
    ("entity-encoded", "&lt;p&gt;5+ years&lt;/p&gt;",        "5+ years"),
    ("nested",         "<ul><li>AWS</li><li>Docker</li></ul>","AWS"),
    ("empty string",   "",                                    ""),
]
for label, inp, expected in cases:
    result = strip_html(inp)
    check(f"strip_html: {label}", expected in result or result == expected, repr(result[:40]))

# ── 3. Greenhouse live fetch (Stripe) — no Firecrawl ─────────────────────────
section("GREENHOUSE — Stripe (live API, no Firecrawl)")
stripe = next((p for p in portals if p['company'] == 'Stripe'), None)
jobs = scrape_greenhouse(stripe) if stripe else []
check("Returns jobs",        len(jobs) > 0,  f"{len(jobs)} jobs")
if jobs:
    j = jobs[0]
    check("Has job_id",       bool(j.get('job_id')))
    check("Has title",        bool(j.get('title')))
    check("Has job_url",      bool(j.get('job_url')))
    check("Has raw_jd_text",  bool(j.get('raw_jd_text')), f"{len(j.get('raw_jd_text',''))} chars")
    check("JD is plain text", '<p>' not in j.get('raw_jd_text','') and '&lt;' not in j.get('raw_jd_text',''))
    check("industry passed",  j.get('industry') == 'Fintech', repr(j.get('industry')))

# ── 4. to_canonical() — v2 schema ────────────────────────────────────────────
section("WRITER — to_canonical() v2 schema")
if jobs:
    canonical = to_canonical(jobs[0], 'Stripe')
    check("10 fields",          len(canonical) == 10,           f"got {len(canonical)}")
    check("Has job_id",         bool(canonical.get('job_id')))
    check("Has job_title",      bool(canonical.get('job_title')))
    check("Has job_description",bool(canonical.get('job_description')))
    check("industry = Fintech", canonical.get('industry') == 'Fintech', repr(canonical.get('industry')))
    check("no role_domain",     'role_domain' not in canonical)
    check("company_name",       canonical.get('company_name') == 'Stripe')
    check("Has apply_url",      bool(canonical.get('apply_url')))
    check("main_skills = []",   canonical.get('main_skills') == [])
    check("side_skills = []",   canonical.get('side_skills') == [])
    check("batch_date int",     isinstance(canonical.get('batch_date'), int))
    # Old 25-field fields must NOT appear
    for dead_field in ('raw_jd_text', 'skills_required', 'seniority_level', 'location_country', 'is_active', 'salary_currency'):
        check(f"No '{dead_field}' in v2", dead_field not in canonical)

# ── 5. LLM enrichment (requires LM Studio running) ───────────────────────────
section("LLM ENRICHMENT — role_domain + main_skills (requires LM Studio)")
if jobs and canonical.get('job_description'):
    try:
        enriched = enrich_job(dict(canonical))
        check("role_domain set",    bool(enriched.get('role_domain')),    str(enriched.get('role_domain')))
        check("main_skills list",   isinstance(enriched.get('main_skills'), list))
        check("main_skills filled", len(enriched.get('main_skills') or []) > 0, str(enriched.get('main_skills')))
        check("side_skills list",   isinstance(enriched.get('side_skills'), list))
        check("short skill strings",all(len(s) <= 50 for s in (enriched.get('main_skills') or [])))
    except Exception as e:
        print(f"  ⚠  LM Studio not running or error: {e}")
        print(f"  ℹ  Skipping enrichment checks — run 'python main.py --enrich-only' when LM Studio is up")

# ── 6. Writer — file output ───────────────────────────────────────────────────
section("WRITER — file output")
if jobs:
    canonical_all = [to_canonical(j, 'Stripe') for j in jobs]
    path, n = save_jobs('Stripe_test', canonical_all)
    check("Output file created", Path(path).exists(), path)
    saved = json.loads(Path(path).read_text(encoding='utf-8'))
    check("Output is array",     isinstance(saved, list))
    check("Dedup works",         len(saved) == len({j['job_id'] for j in saved}))
    if saved:
        sample = saved[0]
        missing = [f for f in SCHEMA if f not in sample]
        check("All 10 SCHEMA fields in output", not missing, f"missing: {missing}" if missing else "")
    # Clean up test output
    import shutil
    from config import OUTPUT_BASE
    from utils import company_slug
    test_dir = Path(OUTPUT_BASE) / company_slug('Stripe_test')
    if test_dir.exists():
        shutil.rmtree(test_dir)

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'─'*55}")
if _failures:
    print(f"  FAILED: {len(_failures)} check(s):")
    for f in _failures:
        print(f"    - {f}")
    sys.exit(1)
else:
    print(f"  All checks passed.")
print(f"{'─'*55}\n")
