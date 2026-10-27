"""An India-only Workday career site has no country facet to filter on.

Carelon's `carelonglobal_in` site lists only India jobs, so India-UUID
discovery finds nothing and the run used to end in CONFIG_ERROR. Many of its
postings read "2 Locations", so searchText + is_india() would drop them too.
The registry flag `india_site` takes every posting with no facet.
"""
import providers.workday as wd


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_india_site_takes_every_posting_without_a_facet(monkeypatch):
    payloads: list[dict] = []
    postings = [
        {"title": "Data Engineer", "externalPath": "/job/Bengaluru/Data-Engineer_JR1",
         "locationsText": "IND-KA-Bengaluru, Bagmane Solarium City", "bulletFields": ["JR1"]},
        {"title": "Claims Analyst", "externalPath": "/job/Gurugram/Claims-Analyst_JR2",
         "locationsText": "2 Locations", "bulletFields": ["JR2"]},
    ]

    def fake_post(url, json=None, **kwargs):
        payloads.append(json)
        return _Resp({"total": 2, "jobPostings": postings if json["offset"] == 0 else []})

    def no_discovery(endpoint):
        raise AssertionError("an India-only site must not look for an India facet")

    monkeypatch.setattr(wd.requests, "post", fake_post)
    monkeypatch.setattr(wd, "_workday_india_uuid", no_discovery)
    monkeypatch.setattr(wd, "_fetch_workday_jds", lambda jobs, portal, limit=None: None)
    portal = {
        "company": "Carelon Global Solutions",
        "endpoint": "https://elevancehealth.wd1.myworkdayjobs.com/wday/cxs/elevancehealth/carelonglobal_in/jobs",
        "tenant": "elevancehealth", "instance": "wd1", "career_site": "carelonglobal_in",
        "india_only": True,
        "workday_india_site": True,
    }

    jobs, reason = wd.scrape_workday(portal)

    assert [j["title"] for j in jobs] == ["Data Engineer", "Claims Analyst"]
    assert payloads[0]["appliedFacets"] == {}
    assert payloads[0]["searchText"] == ""
