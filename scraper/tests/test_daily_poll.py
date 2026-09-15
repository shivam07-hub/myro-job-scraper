from __future__ import annotations

from daily_poll import build_commands


def test_daily_poll_publishes_source_without_linear_enrichment() -> None:
    commands = build_commands(
        python="python",
        run_date="2026_07_12",
        scope="india",
        company_cap=2000,
    )

    assert [name for name, _ in commands] == ["scrape", "resolve", "publish"]
    assert "--skip-enrich" in commands[0][1]
    assert commands[0][1][-2:] == ["--run-date", "2026_07_12"]
    assert "--source-only" in commands[2][1]
    assert "--enrich-only" not in " ".join(part for _, command in commands for part in command)


def test_career_band_is_resolved_before_publication() -> None:
    """The publish step rejects rows with no band provenance, and only the
    resolver writes it — so it must sit between the scrape and the publish."""
    commands = build_commands(
        python="python",
        run_date="2026_07_12",
        scope="india",
        company_cap=2000,
    )
    names = [name for name, _ in commands]
    assert names.index("resolve") < names.index("publish")

    resolve = dict(commands)["resolve"]
    assert resolve[1].endswith("source_matching_facts.py")
    assert resolve[2:4] == ["--run-date", "2026_07_12"]
    # Unclassified rows publish for browse with a truthful null career band.
    assert "--allow-unresolved" in resolve
    # The model pass is too slow and too low-yield to sit inside the daily cycle.
    assert "--skip-model" in resolve
    assert "--publish-unclassified" in dict(commands)["publish"]


def test_company_canary_scopes_both_steps() -> None:
    commands = build_commands(
        python="python",
        run_date="2026_07_12",
        scope="india",
        company_cap=50,
        company="Stripe",
    )

    for _, command in commands:
        assert command[-2:] == ["--company", "Stripe"]


def test_unlimited_company_cap_is_passed_to_main() -> None:
    commands = build_commands(
        python="python",
        run_date="2026_09_07",
        scope="india",
        company_cap=0,
    )
    scrape = dict(commands)["scrape"]
    assert scrape[scrape.index("--company-cap") + 1] == "0"


def test_one_logical_run_date_owns_scrape_resolve_and_publish() -> None:
    commands = build_commands(
        python="python",
        run_date="2026_07_12",
        scope="india",
        company_cap=2000,
    )

    assert [
        command[command.index("--run-date") + 1]
        for _, command in commands
    ] == ["2026_07_12", "2026_07_12", "2026_07_12"]
