from __future__ import annotations

import providers.generic_json as generic_json


class _Response:
    headers = {"Content-Type": "application/json"}

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_oracle_short_list_description_is_replaced_by_detail(monkeypatch):
    requests_seen = []

    def fake_get(url, headers=None, timeout=None):
        requests_seen.append(url)
        if "recruitingCEJobRequisitionDetails" in url:
            return _Response({
                "ExternalDescriptionStr": "<p>Full Oracle responsibilities.</p>",
                "ExternalQualificationsStr": "<p>Oracle qualifications.</p>",
            })
        return _Response({"items": [{"TotalJobsCount": 1, "requisitionList": [{
            "Id": "336649",
            "Title": "Multi-Cloud Sales Specialist",
            "PrimaryLocation": "Bengaluru, India",
            "ShortDescriptionStr": "<p>List teaser.</p>",
        }]}]})

    monkeypatch.setattr(generic_json.requests, "get", fake_get)
    jobs = generic_json.scrape_get({
        "company": "Oracle",
        "ats": "oracle",
        "oracle_nested": True,
        "india_only": True,
        "endpoint": (
            "https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/"
            "recruitingCEJobRequisitions?finder=findReqs;siteNumber=CX_45001,limit=25,sortBy=POSTING_DATES_DESC"
        ),
    })

    assert jobs[0]["raw_jd_text"] == "Full Oracle responsibilities.\n\nOracle qualifications."
    assert any("recruitingCEJobRequisitionDetails" in url for url in requests_seen)


def test_infosys_uses_roles_and_requirements_not_a_listing_summary():
    jobs = generic_json._parse_json_response([
        {
            "referenceCode": "INFSYS-EXTERNAL-1",
            "postingTitle": "Associate Consultant",
            "location": "Bengaluru, India",
            "rolesResponsibilities": "<p>Lead tax-domain analysis.</p>",
            "technicalRequirement": "<p>SQL and reporting.</p>",
            "educationalRequirement": "<p>Bachelor's degree.</p>",
        }
    ], {"company": "Infosys", "ats": "custom", "india_only": False}, "https://example.test")

    assert jobs[0]["raw_jd_text"] == (
        "Lead tax-domain analysis.\n\nSQL and reporting.\n\nBachelor's degree."
    )
