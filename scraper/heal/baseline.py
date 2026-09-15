"""Baseline ledger — last-known-good India job counts per company.

The self-healing diagnostic needs a queryable answer to "was this company ever
working, and how many India jobs did it yield?". Today that fact lives only in
prose (CLAUDE.md CURRENT STATE, KNOWN_PORTALS.md) and in Supabase
`scrape_diagnostics` (official, post-load). This module gives it one home: a
local JSON ledger that works offline at Phase-1 diagnose time, synced forward
from the official counts after each successful `csv_importer.py` load.

Forward-only, per project philosophy: a bad run (0 jobs) never lowers a
company's baseline — that *is* the regression signal. We only ever record the
most recent run where the company yielded jobs. No backfill.

Matches the existing "crack once, reuse forever" registry pattern
(workday_registry.json, generic_registry.json).
"""

from __future__ import annotations

import json
import os
from typing import TypedDict

LEDGER_PATH = os.path.join(os.path.dirname(__file__), "..", "baseline_ledger.json")


class BaselineEntry(TypedDict, total=False):
    company: str
    ats: str
    last_good_count: int
    last_good_run: str
    route: str | None
    updated: str  # ISO date of the run that set this baseline


def load_ledger(path: str = LEDGER_PATH) -> dict[str, BaselineEntry]:
    """Return {company -> BaselineEntry}. Missing/empty file -> {}."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    # Tolerate a leading "_comment" string key, like the other registries.
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def update_ledger(
    ledger: dict[str, BaselineEntry],
    company: str,
    ats: str,
    count: int,
    run_id: str,
    *,
    route: str | None = None,
    updated: str = "",
) -> bool:
    """Forward-only upsert. Records a new last-known-good only when count > 0.

    Returns True if the ledger changed. A run that yields 0 is ignored here —
    detecting that drop is the classifier's job, not the ledger's.
    """
    if count <= 0:
        return False
    prev = ledger.get(company)
    if prev and prev.get("last_good_count") == count and prev.get("last_good_run") == run_id:
        return False
    ledger[company] = {
        "company": company,
        # Canonical output rows do not always carry the registry key. A later
        # successful import must not erase a known route family with "".
        "ats": ats or (prev or {}).get("ats", ""),
        "last_good_count": count,
        "last_good_run": run_id,
        "route": route if route is not None else (prev or {}).get("route"),
        "updated": updated,
    }
    return True


def save_ledger(ledger: dict[str, BaselineEntry], path: str = LEDGER_PATH) -> None:
    """Write the ledger sorted by company, with a leading _comment."""
    out: dict[str, object] = {
        "_comment": (
            "Last-known-good India job counts per company. Forward-only: synced "
            "from Supabase scrape_diagnostics after each successful csv_importer "
            "load. Never edit counts down by hand. See heal/baseline.py."
        )
    }
    for company in sorted(ledger):
        out[company] = ledger[company]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
        f.write("\n")
