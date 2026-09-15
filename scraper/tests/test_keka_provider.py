from __future__ import annotations

from providers.base import ScrapeReason
from providers.keka import KekaProvider


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return [
            {
                "id": "india-1",
                "title": "Data Engineer",
                "description": "<p>Build trustworthy pipelines</p>",
                "departmentName": "Engineering",
                "publishedOn": "2026-08-13",
                "jobLocations": [{"city": "Bengaluru", "state": "Karnataka", "countryName": "India"}],
            },
            {
                "id": "us-1",
                "title": "US role",
                "description": "<p>Not in scope</p>",
                "jobLocations": [{"city": "Austin", "state": "Texas", "countryName": "United States"}],
            },
        ]


def test_keka_maps_full_india_job_and_filters_other_countries(monkeypatch):
    monkeypatch.setattr("providers.keka.requests.get", lambda *args, **kwargs: _Response())
    portal = {
        "company": "TVS Next",
        "endpoint": "https://tvsnext.keka.com/careers/api/jobs/default/active",
        "careers_url": "https://tvsnext.keka.com/careers/",
        "india_only": True,
        "industry": "IT Services",
    }

    result = KekaProvider().scrape(portal)

    assert result.reason == ScrapeReason.SUCCESS
    assert len(result.jobs) == 1
    assert result.jobs[0]["job_url"].endswith("/careers/jobdetails/india-1")
    assert result.jobs[0]["raw_jd_text"] == "Build trustworthy pipelines"
    assert result.jobs[0]["business_unit"] == "Engineering"
