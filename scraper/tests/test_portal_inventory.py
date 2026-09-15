from __future__ import annotations

import json
import tempfile
from pathlib import Path

from portal_inventory import (
    annotate_quality,
    build_inventory,
    classify_probe_state,
    classify_route_state,
    looks_like_navigation_job,
    merge_inventory_files,
    render_markdown,
    select_inventory_rows,
    summarize_rows,
    write_reports,
)


def check(label: str, condition: bool) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS {label}")


def test_classification() -> None:
    check("cracked emoji", classify_route_state("✅ CRACKED 2026-05-07") == "cracked")
    check("working text", classify_route_state("working via Firecrawl") == "cracked")
    check("js required", classify_route_state("🟡 js-required", True) == "js_required")
    check("broken", classify_route_state("⚠️ broken — 404") == "broken")
    check("excluded", classify_route_state("🔴 no India UUID — skip") == "excluded")
    check("deprioritized", classify_route_state("⬇️ deprioritized") == "deprioritized")


def test_summary() -> None:
    rows = [
        {"route_state": "cracked", "probe_state": "hiring", "ats": "greenhouse", "industry": "Fintech", "needs_docker": False},
        {"route_state": "js_required", "probe_state": "skipped_needs_docker", "ats": "custom", "industry": "Technology", "needs_docker": True},
    ]
    summary = summarize_rows(rows)
    check("summary total", summary["total_active_portals"] == 2)
    check("summary hiring", summary["hiring_sampled"] == 1)
    check("summary docker", summary["needs_docker"] == 1)
    check("summary ats", summary["ats"]["greenhouse"] == 1)


def test_navigation_job_detection() -> None:
    check(
        "skip-to-content anchor is noise",
        looks_like_navigation_job({
            "title": "Skip to content",
            "job_url": "https://example.com/careers#skipToContent",
        }),
    )
    check(
        "normal job is not noise",
        not looks_like_navigation_job({
            "title": "Senior Software Engineer",
            "job_url": "https://example.com/jobs/123",
        }),
    )


def test_probe_state_success_without_usable_jobs_is_no_open_jobs() -> None:
    check("success with jobs is hiring", classify_probe_state([{"title": "Engineer"}], "success") == "hiring")
    check("success with zero jobs is no jobs", classify_probe_state([], "success") == "no_open_jobs")


def test_quality_flags_mark_weak_firecrawl_samples() -> None:
    row = {
        "company": "Example Co",
        "probe_state": "hiring",
        "sample_titles": ["Example Co", "See details", "icon Senior Engineer", "Retail Key Holder PT IN Greenwood 2402"],
        "sample_apply_urls": ["https://example.com/jobs#skipToContent"],
        "sample_with_jd": 1,
    }
    annotated = annotate_quality(row)
    check("quality needs review", annotated["sample_quality"] == "needs_review")
    check("company title flagged", "company_name_as_title" in annotated["quality_flags"])
    check("weak title flagged", "weak_title" in annotated["quality_flags"])
    check("possible US state flag", "possible_us_state_in_title" in annotated["quality_flags"])


def test_build_no_probe() -> None:
    inventory = build_inventory(probe=False, sample_size=1)
    rows = inventory["rows"]
    check("inventory has active portals", len(rows) >= 40)
    check("all rows unprobed", all(row["probe_state"] == "not_probed" for row in rows))
    check("stripe present", any(row["company"] == "Stripe" for row in rows))
    check("summary matches rows", inventory["summary"]["total_active_portals"] == len(rows))


def test_build_limit() -> None:
    inventory = build_inventory(probe=False, sample_size=1, limit=2)
    check("limit applies", len(inventory["rows"]) == 2)
    check("limit in meta", inventory["meta"]["limit"] == 2)


def test_build_exact_companies_preserves_source_index() -> None:
    inventory = build_inventory(
        probe=False,
        sample_size=1,
        company_names=["Stripe"],
        source_index_by_company={"Stripe": 42},
    )
    check("exact company filter applies", [row["company"] for row in inventory["rows"]] == ["Stripe"])
    check("source inventory index preserved", inventory["rows"][0]["inventory_index"] == 42)


def test_render_and_write() -> None:
    inventory = build_inventory(probe=False, company_filter="Stripe", sample_size=1)
    md = render_markdown(inventory)
    check("markdown title", "# Portal Inventory Report" in md)
    check("markdown all portals", "## All Active Portals" in md)
    with tempfile.TemporaryDirectory() as tmp:
        json_path, md_path = write_reports(inventory, Path(tmp))
        check("json written", json_path.exists())
        check("markdown written", md_path.exists())


def test_render_lists_unprobed_docker_routes() -> None:
    rows = [{
        "company": "Custom JS Co",
        "ats": "custom",
        "industry": "Technology",
        "endpoint": "https://example.com/jobs",
        "careers_url": "",
        "route_state": "js_required",
        "probe_state": "not_probed",
        "job_count_sample": None,
        "sample_titles": [],
        "sample_apply_urls": [],
        "sample_with_jd": 0,
        "needs_docker": True,
        "fallback_reason": "",
        "notes": "🟡 js-required",
    }]
    inventory = {
        "meta": {
            "generated_at": "2026-05-08T00:00:00",
            "probe": False,
            "include_js": False,
            "sample_size": 3,
            "scope": "india",
        },
        "summary": summarize_rows(rows),
        "rows": rows,
    }
    md = render_markdown(inventory)
    check("unprobed docker route listed", "Custom JS Co" in md and "Needs Docker Or Fresh JS/XHR" in md)


def test_merge_inventory_files() -> None:
    first = {
        "meta": {"offset": 0, "include_js": False, "scope": "india", "sample_size": 3},
        "rows": [{
            "inventory_index": 0,
            "company": "A",
            "route_state": "cracked",
            "probe_state": "hiring",
            "ats": "greenhouse",
            "industry": "Technology",
            "needs_docker": False,
        }],
    }
    second = {
        "meta": {"offset": 1, "include_js": False, "scope": "india", "sample_size": 3},
        "rows": [{
            "inventory_index": 1,
            "company": "B",
            "route_state": "js_required",
            "probe_state": "skipped_needs_docker",
            "ats": "custom",
            "industry": "Technology",
            "needs_docker": True,
        }],
    }
    with tempfile.TemporaryDirectory() as tmp:
        p1 = Path(tmp) / "one.json"
        p2 = Path(tmp) / "two.json"
        p1.write_text(json.dumps(first), encoding="utf-8")
        p2.write_text(json.dumps(second), encoding="utf-8")
        merged = merge_inventory_files([p1, p2])
    check("merge row count", len(merged["rows"]) == 2)
    check("merge summary hiring", merged["summary"]["hiring_sampled"] == 1)
    check("merge summary docker", merged["summary"]["needs_docker"] == 1)


def test_select_inventory_rows_for_docker_reprobe() -> None:
    source = {
        "meta": {"offset": 0, "include_js": False, "scope": "india", "sample_size": 3},
        "rows": [
            {
                "inventory_index": 4,
                "company": "Needs JS",
                "route_state": "js_required",
                "probe_state": "skipped_needs_docker",
                "needs_docker": True,
            },
            {
                "inventory_index": 5,
                "company": "Already Direct",
                "route_state": "cracked",
                "probe_state": "hiring",
                "needs_docker": False,
            },
            {
                "inventory_index": 9,
                "company": "Fallback Co",
                "route_state": "cracked",
                "probe_state": "fallback_needs_docker",
                "needs_docker": True,
            },
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        source_path = Path(tmp) / "inventory.json"
        source_path.write_text(json.dumps(source), encoding="utf-8")
        selected = select_inventory_rows(
            source_path,
            probe_states={"skipped_needs_docker", "fallback_needs_docker"},
            needs_docker_only=True,
        )
    check("selects docker reprobe companies", selected.company_names == ["Needs JS", "Fallback Co"])
    check("select preserves index", selected.source_index_by_company["Fallback Co"] == 9)


def test_select_inventory_rows_uses_source_position_when_index_missing() -> None:
    source = {
        "rows": [
            {"company": "Skip Me", "probe_state": "hiring", "needs_docker": False},
            {"company": "Needs JS", "probe_state": "skipped_needs_docker", "needs_docker": True},
            {"company": "Fallback Co", "probe_state": "fallback_needs_docker", "needs_docker": True},
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        source_path = Path(tmp) / "inventory.json"
        source_path.write_text(json.dumps(source), encoding="utf-8")
        selected = select_inventory_rows(
            source_path,
            probe_states={"skipped_needs_docker", "fallback_needs_docker"},
            needs_docker_only=True,
        )
    check("missing index uses source row position", selected.source_index_by_company["Needs JS"] == 1)
    check("missing index preserves later source row position", selected.source_index_by_company["Fallback Co"] == 2)


def main() -> None:
    test_classification()
    test_summary()
    test_navigation_job_detection()
    test_probe_state_success_without_usable_jobs_is_no_open_jobs()
    test_quality_flags_mark_weak_firecrawl_samples()
    test_build_no_probe()
    test_build_limit()
    test_build_exact_companies_preserves_source_index()
    test_render_and_write()
    test_render_lists_unprobed_docker_routes()
    test_merge_inventory_files()
    test_select_inventory_rows_for_docker_reprobe()
    test_select_inventory_rows_uses_source_position_when_index_missing()
    print("All portal inventory tests passed.")


if __name__ == "__main__":
    main()
