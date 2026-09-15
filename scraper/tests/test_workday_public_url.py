"""Regression guards for addressable Workday public job URLs."""

import providers.workday as workday
from providers.base import ScrapeReason
from providers.workday import _workday_public_url


ACCENTURE = {
    "tenant": "accenture",
    "instance": "wd103",
    "career_site": "AccentureCareers",
}


def test_inserts_configured_site_before_job_path():
    external_path = (
        "/job/Chennai/"
        "Custom-Software-Engineer_ATCI-5436291-S1978254-1"
    )

    assert _workday_public_url(ACCENTURE, external_path) == (
        "https://accenture.wd103.myworkdayjobs.com/AccentureCareers/job/"
        "Chennai/Custom-Software-Engineer_ATCI-5436291-S1978254-1"
    )


def test_inserts_site_after_optional_locale():
    assert _workday_public_url(ACCENTURE, "/en-US/job/Chennai/Role_R123456") == (
        "https://accenture.wd103.myworkdayjobs.com/"
        "en-US/AccentureCareers/job/Chennai/Role_R123456"
    )


def test_preserves_path_that_already_contains_site():
    assert _workday_public_url(
        ACCENTURE,
        "/AccentureCareers/job/Chennai/Role_R123456",
    ) == (
        "https://accenture.wd103.myworkdayjobs.com/"
        "AccentureCareers/job/Chennai/Role_R123456"
    )


def test_preserves_locale_and_site_without_duplication():
    assert _workday_public_url(
        ACCENTURE,
        "/en-US/AccentureCareers/job/Chennai/Role_R123456?source=careers",
    ) == (
        "https://accenture.wd103.myworkdayjobs.com/"
        "en-US/AccentureCareers/job/Chennai/Role_R123456?source=careers"
    )


def test_empty_external_path_has_no_public_url():
    assert _workday_public_url(ACCENTURE, "") == ""


def test_scrape_publishes_site_qualified_url(monkeypatch):
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {
                "jobPostings": [
                    {
                        "title": "Custom Software Engineer",
                        "externalPath": "/job/Chennai/Custom-Software-Engineer_R00336753",
                        "bulletFields": ["R00336753", "Engineering"],
                        "jobDescription": "A complete source job description.",
                    }
                ]
            }

    monkeypatch.setattr(workday.requests, "post", lambda *args, **kwargs: Response())
    portal = {
        **ACCENTURE,
        "company": "Accenture",
        "endpoint": (
            "https://accenture.wd103.myworkdayjobs.com/"
            "wday/cxs/accenture/AccentureCareers/jobs"
        ),
        "india_only": False,
        "industry": "IT Services",
    }

    jobs, reason = workday.scrape_workday(portal, max_jobs=1, validate_mode=True)

    assert reason == ScrapeReason.SUCCESS
    assert jobs is not None
    assert jobs[0]["job_url"] == (
        "https://accenture.wd103.myworkdayjobs.com/AccentureCareers/job/"
        "Chennai/Custom-Software-Engineer_R00336753"
    )
