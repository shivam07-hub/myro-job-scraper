from __future__ import annotations

import html
import json

import providers.bnp_paribas as bnp
import requests
from portal_reader import parse_portals
from providers.base import ScrapeReason

_ENDPOINT = "https://group.bnpparibas/en/careers/all-job-offers/india"
_PORTAL = {"company": "BNP Paribas", "endpoint": _ENDPOINT, "industry": "BFSI"}


def _offer(job_id: str | None, ref: str, title: str = "Associate - Reconciliation") -> dict:
    return {
        "href": f"/en/careers/job-offer/{title.lower().replace(' ', '-')}",
        "title": title,
        "location": "Mumbai, Maharashtra, India",
        "jobId": job_id,
        "datePosted": "2026-11-06",
        "ref": ref,
    }


def _rendered(*offers: dict) -> str:
    payload = html.escape(json.dumps({"lastPage": 34, "offers": list(offers)}), quote=False)
    return f'<main><a class="card-link"></a></main><pre id="myro-bnp">{payload}</pre>'


def _field(label: str, value: str) -> str:
    return (
        '<div class="article__content__view__field">'
        f'<div class="article__content__view__field__label">{label}</div>'
        f'<div class="article__content__view__field__value">{value}</div></div>'
    )


_JOB_PAGE = (
    '<article class="article article--details"><div class="article__header">'
    '<div class="article__header__text"><h2 class="article__header__text__title">General Information</h2>'
    '</div></div><div class="article__content"><div class="article__content__view">'
    + _field("Ref #", "1234567890100124366")
    + _field("Country", "India")
    + _field("City", "Mumbai")
    + _field("Contract type", "Permanent")
    + _field("Professional Family", "F15 - OPERATION PROCESSING")
    + '</div></div></article><article class="article article--details"><div class="article__header">'
    '<div class="article__header__text"><h2 class="article__header__text__title">Description</h2>'
    '</div></div><div class="article__content"><p><strong>Job Title: </strong>Associate</p>'
    "<p>Hands-on cash &amp; securities reconciliation.</p></div></article>"
)


def test_listing_actions_wait_for_the_script_result_before_scraping() -> None:
    actions = bnp.listing_actions()
    assert actions[0] == {"type": "wait", "selector": 'a.card-link[href*="/careers/job-offer/"]'}
    assert actions[1]["type"] == "executeJavascript"
    assert 'result.id = "myro-bnp"' in actions[1]["script"]
    assert actions[2:] == [{"type": "wait", "selector": "#myro-bnp"}, {"type": "scrape"}]


def test_script_starts_with_the_function_so_a_wrapping_return_keeps_it() -> None:
    script = bnp.listing_actions()[1]["script"]
    assert script.startswith("(async () => {")
    assert script.rstrip().endswith("})()")


def test_listing_reads_the_offers_the_script_wrote() -> None:
    offers = bnp.parse_listing(_rendered(_offer("114172", "1"), _offer(None, "2")))
    assert [o["jobId"] for o in offers] == ["114172", None]
    assert offers[0]["title"] == "Associate - Reconciliation"


def test_a_render_without_the_result_lists_nothing() -> None:
    assert bnp.parse_listing("<main></main>") == []


def test_job_page_reads_fields_and_description() -> None:
    fields, description = bnp.parse_job_page(_JOB_PAGE)
    assert fields["Country"] == "India"
    assert fields["Professional Family"] == "F15 - OPERATION PROCESSING"
    assert "Job Title: Associate" in description
    assert "cash & securities reconciliation" in description
    assert "<p>" not in description


def test_jd_text_leads_with_contract_and_family() -> None:
    fields, description = bnp.parse_job_page(_JOB_PAGE)
    assert bnp.jd_text(fields, description).startswith(
        "Contract type: Permanent\nProfessional Family: F15 - OPERATION PROCESSING\n"
    )


class _Resp:
    def __init__(self, text: str, status: int = 200) -> None:
        self.text = text
        self.status = status

    def raise_for_status(self) -> None:
        if self.status >= 400:
            raise requests.HTTPError(f"{self.status}")


def test_scrape_renders_once_then_reads_each_jd_from_avature(monkeypatch) -> None:
    import firecrawl_client as fc

    renders: list[tuple[str, int | None]] = []

    def fake_render(url, actions, *, timeout_ms=None):
        renders.append((url, timeout_ms))
        return [
            _rendered(
                _offer("114172", "1234567890100124366"),
                _offer(None, "1234567890100124000", "Unloaded"),
                _offer("114173", "1234567890100124367", "Closed"),
                _offer("114174", "1234567890100124368", "Down"),
            )
        ]

    pages = {"114172": _Resp(_JOB_PAGE), "114173": _Resp("<main>Offer closed</main>"), "114174": _Resp("", 503)}

    def fake_get(url, headers=None, timeout=None):
        return pages[url.rsplit("=", 1)[-1]]

    monkeypatch.setattr(fc, "cloud_scrape_action_pages", fake_render)
    monkeypatch.setattr(bnp.requests, "get", fake_get)
    result = bnp.BnpParibasProvider().scrape(_PORTAL)

    assert result.reason == ScrapeReason.SUCCESS
    assert renders == [(_ENDPOINT, bnp._RENDER_TIMEOUT_MS)]
    [job] = result.jobs
    assert job["job_id"] == "1234567890100124366"
    assert job["job_url"] == "https://bwelcome.hr.bnpparibas/en_US/externalcareers/JobDetails?jobId=114172"
    assert job["location_city"] == "Mumbai, Maharashtra, India"
    assert job["business_unit"] == "OPERATION PROCESSING"
    assert job["date_posted"] == "2026-11-06"
    assert job["industry"] == "BFSI"
    assert "securities reconciliation" in job["raw_jd_text"]


def test_an_empty_render_is_a_parse_error(monkeypatch) -> None:
    import firecrawl_client as fc

    monkeypatch.setattr(fc, "cloud_scrape_action_pages", lambda url, actions, *, timeout_ms=None: [])
    assert bnp.BnpParibasProvider().scrape(_PORTAL).reason == ScrapeReason.PARSE_ERROR


def test_bnp_portal_routes_to_the_provider() -> None:
    portal = [p for p in parse_portals() if p.get("company") == "BNP Paribas"]
    assert portal and portal[0]["ats"] == "bnp_paribas"
    assert portal[0]["endpoint"] == _ENDPOINT
    assert not portal[0].get("js_required")
