"""Proposer: dedup detection, masking-row location, Firecrawl adapter (mocked)."""

from __future__ import annotations

import firecrawl_client
from heal.probe import probe_company_firecrawl
from heal.propose import (
    find_generic_duplicates,
    locate_masking_rows,
    propose_dedup_fixes,
    render_proposals,
)

_MD = """\
## RIPPLEHIRE COMPANIES

| Company | URL | x |
| Mphasis | https://careers.mphasis.com | real |

## CUSTOM / PROPRIETARY APIs

| Company | URL | x |
| Mphasis | https://careers.mphasis.com | masking index row |
| Amazon | https://amazon.jobs | genuine custom |
"""


def test_find_generic_duplicates():
    portals = [
        {"company": "Mphasis", "ats": "ripplehire"},
        {"company": "Mphasis", "ats": "custom"},
        {"company": "Amazon", "ats": "custom"},      # only generic -> not a dup
        {"company": "Stripe", "ats": "greenhouse"},  # only specific -> not a dup
    ]
    dups = find_generic_duplicates(portals)
    assert dups == {"Mphasis": "ripplehire"}


def test_locate_masking_rows(tmp_path):
    md = tmp_path / "K.md"
    md.write_text(_MD, encoding="utf-8")
    hits = locate_masking_rows({"Mphasis": "ripplehire"}, str(md))
    # Only the row under the CUSTOM header counts; the RIPPLEHIRE one does not.
    assert len(hits) == 1
    lineno, company, raw = hits[0]
    assert company == "Mphasis"
    assert "masking index row" in raw


def test_propose_dedup_emits_deletion_diff(tmp_path):
    md = tmp_path / "K.md"
    md.write_text(_MD, encoding="utf-8")
    portals = [{"company": "Mphasis", "ats": "ripplehire"}, {"company": "Mphasis", "ats": "custom"}]
    proposals = propose_dedup_fixes(portals, str(md))
    assert len(proposals) == 1
    assert proposals[0].kind == "DEDUP_GENERIC"
    assert "-| Mphasis |" in proposals[0].diff
    assert "```diff" in render_proposals(proposals)


def test_live_known_portals_has_no_generic_duplicates():
    # Regression guard: after the 2026-06-07 dedup fix, no company should have a
    # generic row masking a specific ATS.
    from portal_reader import parse_portals
    assert find_generic_duplicates(parse_portals()) == {}


def test_firecrawl_probe_ranks_candidates(monkeypatch):
    monkeypatch.setattr(firecrawl_client, "map_site", lambda url, **k: [
        {"url": "https://x.com/about", "title": "About", "description": ""},
        {"url": "https://x.com/api/jobs/search?location=India", "title": "Jobs", "description": "careers india"},
    ])
    monkeypatch.setattr(firecrawl_client, "scrape", lambda url, **k: "We are hiring in Bengaluru, India")
    r = probe_company_firecrawl({"company": "Uber", "endpoint": "https://x.com/careers"})
    assert r.verdict == "CANDIDATE_FOUND"
    assert "api/jobs" in r.candidate_urls[0]   # listing/API URL ranked first
    assert r.india_signal is True


def test_firecrawl_probe_no_signal(monkeypatch):
    monkeypatch.setattr(firecrawl_client, "map_site", lambda url, **k: [
        {"url": "https://x.com/about", "title": "About", "description": "company"},
    ])
    r = probe_company_firecrawl({"company": "Uber", "endpoint": "https://x.com/careers"})
    assert r.verdict == "NO_SIGNAL"
