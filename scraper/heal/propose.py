"""Propose route fixes as reviewable diffs — never apply them.

The classifier says what's broken; the probe says whether the route still
works; this module says *what edit would fix it* — and hands a human a diff to
approve. Propose-only is the whole point: CLAUDE.md CHANGE DISCIPLINE forbids
silent config edits.

Two fix kinds today:

- DEDUP_GENERIC — the bug that silently broke HSBC/Mphasis/Persistent: a company
  listed in both its real ATS section *and* a generic (CUSTOM / industry) index
  section, so `portal_reader` emits a second portal with ats=custom/other that
  runs alongside the real one and returns 0. The fix is to delete the masking
  index row. This module finds those rows and emits the deletion diff.

- CRACK_STUB — for a NEEDS_CRACK company where the Firecrawl-cloud probe found a
  candidate listing/API URL, propose a KNOWN_PORTALS.md row stub to fill in.

The generic-section keyword list mirrors `portal_reader._section_portals`
(CUSTOM/PROPRIETARY + the industry/OTHER sections). Keep them in sync.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# Mirrors portal_reader._section_portals: headers that route a row to the
# generic _custom()/_other() parsers (ats = custom / other).
GENERIC_SECTION_KW = {
    "CUSTOM", "PROPRIETARY", "OTHER", "CONSULTING", "BFSI", "CONGLOMERATE",
    "CONSUMER", "INFORMATION TECHNOLOGY", "RETAIL", "PHARMA", "REAL ESTATE",
    "ENGINEERING", "AGRI",
}
GENERIC_ATS = {"custom", "other"}

KNOWN_PORTALS = os.path.join(os.path.dirname(__file__), "..", "..", "KNOWN_PORTALS.md")


@dataclass
class FixProposal:
    company: str
    kind: str          # DEDUP_GENERIC | CRACK_STUB | RERUN
    rationale: str
    diff: str = ""     # unified-diff-style text; empty for RERUN


def find_generic_duplicates(portals: list[dict]) -> dict[str, str]:
    """{company -> specific_ats} for companies that have BOTH a generic
    (custom/other) portal row and a specific-ATS row — the masking bug."""
    by: dict[str, set[str]] = {}
    for p in portals:
        by.setdefault(p["company"], set()).add(p.get("ats", ""))
    out: dict[str, str] = {}
    for company, ats in by.items():
        generic = ats & GENERIC_ATS
        specific = ats - GENERIC_ATS - {""}
        if generic and specific:
            out[company] = sorted(specific)[0]
    return out


def _is_generic_header(header: str) -> bool:
    h = header.upper()
    # CUSTOM/PROPRIETARY and the industry/OTHER sections are generic; a header
    # naming a specific ATS (RIPPLEHIRE, ZWAYAM, EIGHTFOLD, ...) is not.
    return ("CUSTOM" in h or "PROPRIETARY" in h
            or any(kw in h for kw in GENERIC_SECTION_KW if kw not in ("CUSTOM", "PROPRIETARY")))


def locate_masking_rows(targets: dict[str, str], md_path: str = KNOWN_PORTALS) -> list[tuple[int, str, str]]:
    """Return (lineno, company, raw_line) for each masking row — a row whose
    company is a dedup target and whose section header is generic."""
    with open(md_path, encoding="utf-8") as f:
        lines = f.readlines()
    section = ""
    hits: list[tuple[int, str, str]] = []
    for i, line in enumerate(lines, start=1):
        if line.lstrip().startswith("#"):
            section = line.strip().lstrip("#").strip()
            continue
        if not line.lstrip().startswith("|"):
            continue
        parts = [c.strip() for c in line.strip().strip("|").split("|")]
        if not parts:
            continue
        company = parts[0]
        if company in targets and _is_generic_header(section):
            hits.append((i, company, line.rstrip("\n")))
    return hits


def propose_dedup_fixes(portals: list[dict], md_path: str = KNOWN_PORTALS) -> list[FixProposal]:
    targets = find_generic_duplicates(portals)
    if not targets:
        return []
    masking = locate_masking_rows(targets, md_path)
    proposals: list[FixProposal] = []
    for lineno, company, raw in masking:
        specific = targets[company]
        diff = (
            f"--- a/KNOWN_PORTALS.md\n"
            f"+++ b/KNOWN_PORTALS.md\n"
            f"@@ line {lineno} (generic section) @@\n"
            f"-{raw}\n"
        )
        proposals.append(FixProposal(
            company=company,
            kind="DEDUP_GENERIC",
            rationale=(
                f"{company} also has a real ats={specific} row; this generic row "
                f"parses as a duplicate portal that returns 0 and masks the working route. "
                f"Delete it."
            ),
            diff=diff,
        ))
    return proposals


def propose_crack_stub(company: str, careers_url: str, candidate_url: str, evidence: str) -> FixProposal:
    """A reviewable KNOWN_PORTALS.md row stub for a Firecrawl-discovered route."""
    row = f"| {company} | {careers_url} | TODO-ats | `{candidate_url}` | Python is_india() | ? | 🔍 DISCOVERED — {evidence}; promote to a direct provider |"
    diff = (
        "--- a/KNOWN_PORTALS.md\n"
        "+++ b/KNOWN_PORTALS.md\n"
        "@@ append under the right ATS section @@\n"
        f"+{row}\n"
    )
    return FixProposal(company=company, kind="CRACK_STUB",
                       rationale=f"Firecrawl found a candidate listing URL for {company}: {candidate_url}",
                       diff=diff)


def render_proposals(proposals: list[FixProposal]) -> str:
    if not proposals:
        return "# No auto-fixable proposals.\n"
    out = ["# Proposed route fixes (REVIEW — not applied)", ""]
    for p in proposals:
        out += [f"## {p.kind} — {p.company}", "", p.rationale, ""]
        if p.diff:
            out += ["```diff", p.diff.rstrip("\n"), "```", ""]
    return "\n".join(out)
