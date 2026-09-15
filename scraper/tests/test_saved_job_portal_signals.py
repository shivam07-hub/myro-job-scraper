from __future__ import annotations

from discovery.saved_job_portal_signals import (
    SavedExtensionJob,
    assess_signals,
    build_portal_index,
    build_report,
    canonical_row_matches_signal,
    extract_ats_identity,
    normalize_company,
    render_markdown,
)


def _saved_job(
    *,
    job_id: str = "ext_test",
    company: str,
    platform: str,
    url: str,
) -> SavedExtensionJob:
    return SavedExtensionJob(
        extension_job_id=job_id,
        company_name=company,
        source_platform=platform,
        apply_url=url,
        source_url=url,
        saved_count=1,
        latest_saved_at="2026-07-25T09:07:51+00:00",
    )


def _portals() -> list[dict]:
    return [
        {
            "company": "Zscaler",
            "ats": "greenhouse",
            "board_token": "zscaler",
            "endpoint": "https://boards-api.greenhouse.io/v1/boards/zscaler/jobs?content=true",
            "careers_url": "https://www.zscaler.com/careers",
        },
        {
            "company": "Google",
            "ats": "google_careers",
            "endpoint": "https://www.google.com/about/careers/applications/jobs/results/?location=India",
            "careers_url": "https://www.google.com/about/careers/applications/jobs/results/",
        },
    ]


def test_company_normalization_handles_capture_aliases() -> None:
    assert normalize_company("Google Careers") == normalize_company("Google")
    assert normalize_company("GitHub, Inc.") == "github"


def test_extracts_greenhouse_native_identity() -> None:
    identity = extract_ats_identity(
        "greenhouse",
        "https://job-boards.greenhouse.io/zscaler/jobs/5082271007?gh_src=x",
        "",
    )
    assert identity is not None
    assert identity.ats == "greenhouse"
    assert identity.token == "zscaler"
    assert identity.native_job_id == "5082271007"


def test_tracked_greenhouse_job_reports_canonical_duplicate() -> None:
    signal = _saved_job(
        company="Zscaler",
        platform="greenhouse",
        url="https://job-boards.greenhouse.io/zscaler/jobs/5082271007?gh_src=x",
    )
    result = assess_signals(
        [signal],
        build_portal_index(_portals()),
        probe=False,
        canonical_job_ids={"5082271007"},
    )[0]
    assert result.status == "already_tracked"
    assert result.coverage_match_type == "ats_token"
    assert result.canonical_job_id == "5082271007"


def test_canonical_duplicate_guard_rejects_cross_company_id_collision() -> None:
    signal = _saved_job(
        company="Zscaler",
        platform="greenhouse",
        url="https://job-boards.greenhouse.io/zscaler/jobs/5082271007",
    )
    assert not canonical_row_matches_signal(
        {
            "company_name": "Unrelated Company",
            "source_platform": "greenhouse",
            "apply_url": "https://job-boards.greenhouse.io/unrelated/jobs/5082271007",
            "source_url": "",
        },
        signal,
    )
    assert canonical_row_matches_signal(
        {
            "company_name": "Zscaler, Inc.",
            "source_platform": "Greenhouse",
            "apply_url": "https://job-boards.greenhouse.io/zscaler/jobs/5082271007",
            "source_url": "",
        },
        signal,
    )


def test_company_alias_matches_existing_portal() -> None:
    signal = _saved_job(
        company="Google Careers",
        platform="generic",
        url="https://www.google.com/about/careers/applications/jobs/results/123",
    )
    result = assess_signals(
        [signal],
        build_portal_index(_portals()),
        probe=False,
    )[0]
    assert result.status == "already_tracked"
    assert result.covered_company == "Google"


def test_missing_ashby_board_can_be_ready_to_promote() -> None:
    signal = _saved_job(
        company="OpenAI",
        platform="ashby",
        url="https://jobs.ashbyhq.com/openai/abc-123",
    )

    def fake_probe(_session, token):
        assert token == "openai"
        return {
            "ats": "ashby",
            "slug": "openai",
            "endpoint": "https://api.ashbyhq.com/posting-api/job-board/openai",
            "total": 755,
            "india": 9,
            "board_name": "openai",
            "sample": "Technical Program Manager",
        }

    result = assess_signals(
        [signal],
        build_portal_index(_portals()),
        probe_functions={"ashby": fake_probe},
    )[0]
    assert result.status == "ready_to_promote"
    assert result.probe_india_jobs == 9
    assert result.probe_endpoint.endswith("/openai")


def test_unknown_supported_ats_stays_investigation_when_probe_disabled() -> None:
    signal = _saved_job(
        company="OpenAI",
        platform="ashby",
        url="https://jobs.ashbyhq.com/openai/abc-123",
    )
    result = assess_signals(
        [signal],
        build_portal_index(_portals()),
        probe=False,
    )[0]
    assert result.status == "needs_investigation"
    assert "validation was disabled" in result.reason


def test_shared_ats_host_never_matches_another_company_by_host() -> None:
    portals = [
        {
            "company": "Existing Ashby Company",
            "ats": "ashby",
            "board_token": "existing",
            "endpoint": "https://api.ashbyhq.com/posting-api/job-board/existing",
            "careers_url": "https://jobs.ashbyhq.com/existing",
        }
    ]
    signal = _saved_job(
        company="New Ashby Company",
        platform="ashby",
        url="https://jobs.ashbyhq.com/new-company/abc-123",
    )
    result = assess_signals(
        [signal],
        build_portal_index(portals),
        probe=False,
    )[0]
    assert result.status == "needs_investigation"
    assert result.covered_company == ""


def test_jibe_capture_requires_provider_investigation() -> None:
    signal = _saved_job(
        company="GitHub, Inc.",
        platform="generic",
        url="https://githubinc.jibeapply.com/jobs/123",
    )
    result = assess_signals(
        [signal],
        build_portal_index(_portals()),
        probe=False,
    )[0]
    assert result.status == "needs_investigation"
    assert result.ats == ""


def test_email_subject_is_rejected_as_invalid_company() -> None:
    signal = _saved_job(
        company="Onsite role in London (Visa Sponsorship by the client)",
        platform="generic",
        url="https://mail.google.com/mail/u/0/#inbox/123",
    )
    result = assess_signals(
        [signal],
        build_portal_index(_portals()),
        probe=False,
    )[0]
    assert result.status == "invalid_capture"
    assert "email" in result.reason or "prose" in result.reason


def test_report_keeps_promotions_proposed_and_relinks_report_only() -> None:
    zscaler = _saved_job(
        company="Zscaler",
        platform="greenhouse",
        url="https://job-boards.greenhouse.io/zscaler/jobs/5082271007",
    )
    openai = _saved_job(
        company="OpenAI",
        platform="ashby",
        url="https://jobs.ashbyhq.com/openai/abc-123",
    )

    def fake_probe(_session, _token):
        return {
            "ats": "ashby",
            "slug": "openai",
            "endpoint": "https://api.ashbyhq.com/posting-api/job-board/openai",
            "total": 755,
            "india": 9,
            "board_name": "openai",
            "sample": "Technical Program Manager",
        }

    assessments = assess_signals(
        [zscaler, openai],
        build_portal_index(_portals()),
        probe_functions={"ashby": fake_probe},
        canonical_job_ids={"5082271007"},
    )
    markdown = render_markdown(build_report(assessments))
    assert "⚠️ PROPOSED" in markdown
    assert "were **not** applied" in markdown
    assert "`ext_test`" in markdown
    assert "`5082271007`" in markdown


def test_report_escapes_captured_markdown_table_text() -> None:
    signal = _saved_job(
        company="Example | Company\nInjected row",
        platform="generic",
        url="https://example.com/jobs/123",
    )
    assessments = assess_signals(
        [signal],
        build_portal_index(_portals()),
        probe=False,
    )
    markdown = render_markdown(build_report(assessments))
    assert "Example \\| Company Injected row" in markdown
