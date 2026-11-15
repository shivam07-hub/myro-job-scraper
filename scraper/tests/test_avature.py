from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
import requests

import providers.avature as av
from providers.base import FALLBACK_FIRECRAWL_EXTRACT, ScrapeReason

_ORIGIN = "https://recruitment.macquarie.com/en_US/careers"
_SEARCH = f"{_ORIGIN}/SearchJobs/?10671=%5B871433%5D&10671_format=21337&listFilterMode=1&jobRecordsPerPage=9"
_PORTAL = {"company": "Macquarie Group", "ats": "avature", "endpoint": _SEARCH, "industry": "BFSI"}


def _card(jid: str, office: str = "Gurugram Office", posted: str = "06 Nov 2026", category: str = "Accounting / Finance") -> str:
    return f"""
    <article class="article article--result clearfix ">
      <div class="article__header"><h3 class="article__header__text__title title title--02">
        <a class="link" href="{_ORIGIN}/JobDetail?jobId={jid}">
          Executive - GT Regulatory &amp; Capital Reporting
        </a></h3></div>
      <div class="article__content"><div class="article__content__details">
        <div class="article__details__data"><p class="icon">ID</p><p>{jid}</p></div>
        <div class="article__details__data"><img class="icon" src="x.svg" alt="Office Location:" /><p>{office}</p></div>
        <div class="article__details__data"><img class="icon" src="x.svg" alt="Posted Date:" /><p>{posted}</p></div>
        <div class="article__details__data"><img class="icon" src="x.svg" alt="Job Category:" /><p>{category}</p></div>
      </div></div>
      <div class="article__footer"><div class="article__footer__buttons">
        <a class="button button--primary" href="{_ORIGIN}/ApplicationMethods?jobId={jid}&amp;record={jid}">Apply</a>
      </div></div>
    </article>"""


def _listing(cards: list[str], total: int | None) -> str:
    legend = f'<div class="list-controls__text__legend" aria-label="{total} results">' if total is not None else ""
    return f"<html><body>{legend}{''.join(cards)}</body></html>"


def _field(kind: str, label: str | None, value: str) -> str:
    label_html = f'<div class="article__content__view__field__label">{label}</div>' if label else ""
    return (
        f'<div class="article__content__view__field field--{kind} regular-field-label--hidden">'
        f'{label_html}<div class="article__content__view__field__value">{value}</div></div>'
    )


def _section(heading: str | None, text: str) -> str:
    header = (
        '<div class="article__header js_collapsible__header"><div class="article__header__text">'
        f'<h3 class="article__header__text__title title title--04">{heading}</h3></div>'
        '<p class="visibility--hidden--visually" aria-hidden="false">Press space or enter keys to toggle section visibility</p></div>'
        if heading
        else ""
    )
    return (
        f'<article class="article article--details js_collapsible">{header}'
        '<div class="article__content js_collapsible__content"><div class="article__content__view">'
        '<div class="article__content__view__field "><div class="article__content__view__field__value">'
        f"<div>{text}</div></div></div></div></div></article>"
    )


def _detail(employment: str = "Permanent - Full time, Junior", offices: tuple[str, ...] = ("Gurugram",)) -> str:
    meta = "".join(_field("location", "Additional office locations", o) for o in offices)
    meta += _field("jobcategory", "Job ID", "24990")
    meta += _field("date", "Date", "06-Nov-2026")
    meta += _field("employmentterm", None, employment)
    meta += _field("jobcategory", "Job category", "Accounting / Finance")
    return (
        '<html><body><article class="article article__content__fields">'
        '<article class="article article--details  js_collapsible"><div class="article__content js_collapsible__content">'
        f'<div class="article__content__view">{meta}</div></div></article>'
        + _section(None, "Join our GT Regulatory Reporting Team in Group Finance.")
        + _section("What role will you play?", "Run the capital &amp; credit risk process.")
        + "</article></body></html>"
    )


class _Resp:
    def __init__(self, text: str = "", status: int = 200) -> None:
        self.text = text
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


def _serve(monkeypatch, listing: dict[int, list], details: dict[str, list] | None = None) -> list[str]:
    """Answer listing offsets and job pages from queues; record every URL asked for."""
    asked: list[str] = []
    details = details or {}

    class _Session:
        headers: dict[str, str] = {}

        def get(self, url: str, timeout: int | None = None) -> _Resp:
            asked.append(url)
            query = parse_qs(urlsplit(url).query)
            if "/SearchJobs/" in url:
                queue = listing[int(query["jobOffset"][0])]
            else:
                queue = details.get(query["jobId"][0], [_Resp(_detail())])
            answer = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(answer, Exception):
                raise answer
            return answer

    monkeypatch.setattr(av.requests, "Session", _Session)
    monkeypatch.setattr(av.time, "sleep", lambda seconds: None)
    return asked


def _job_pages(asked: list[str]) -> list[str]:
    return [parse_qs(urlsplit(u).query)["jobId"][0] for u in asked if "/JobDetail" in u]


def test_reads_every_page_and_every_job_page(monkeypatch) -> None:
    first = [_card(str(100 + i)) for i in range(9)]
    asked = _serve(monkeypatch, {0: [_Resp(_listing(first, 10))], 9: [_Resp(_listing([_card("200")], 10))]})

    result = av.AvatureProvider().scrape(_PORTAL)

    assert result.reason == ScrapeReason.SUCCESS
    assert len(result.jobs) == 10
    offsets = [parse_qs(urlsplit(u).query)["jobOffset"][0] for u in asked if "/SearchJobs/" in u]
    assert offsets == ["0", "9"]
    assert "10671=%5B871433%5D" in asked[0]
    job = result.jobs[-1]
    assert job["job_id"] == "200"
    assert job["title"] == "Executive - GT Regulatory & Capital Reporting"
    assert job["job_url"] == f"{_ORIGIN}/ApplicationMethods?jobId=200&record=200"
    assert job["business_unit"] == "Accounting / Finance"
    assert job["location_city"] == "Gurugram"
    assert job["locations"] == ["Gurugram"]
    assert job["date_posted"] == "2026-11-06"
    assert job["seniority_level"] == "Junior"
    assert job["raw_jd_text"] == (
        "Join our GT Regulatory Reporting Team in Group Finance.\n\n"
        "What role will you play?\nRun the capital & credit risk process."
    )
    assert job["source_platform"] == "Avature"
    assert job["industry"] == "BFSI"


def test_every_office_on_the_job_page_is_kept_once(monkeypatch) -> None:
    _serve(
        monkeypatch,
        {0: [_Resp(_listing([_card("1")], 1))]},
        {"1": [_Resp(_detail(offices=("Gurugram", "Mumbai", "Gurugram")))]},
    )

    job = av.AvatureProvider().scrape(_PORTAL).jobs[0]

    assert job["locations"] == ["Gurugram", "Mumbai"]
    assert job["location_city"] == "Gurugram | Mumbai"


def test_a_card_outside_india_is_skipped_without_opening_its_page(monkeypatch) -> None:
    asked = _serve(monkeypatch, {0: [_Resp(_listing([_card("1"), _card("2", office="Singapore Office")], 2))]})

    result = av.AvatureProvider().scrape(_PORTAL)

    assert [j["job_id"] for j in result.jobs] == ["1"]
    assert _job_pages(asked) == ["1"]


def test_a_job_taken_down_after_listing_is_skipped(monkeypatch) -> None:
    _serve(monkeypatch, {0: [_Resp(_listing([_card("1"), _card("2")], 2))]}, {"1": [_Resp(status=404)]})

    result = av.AvatureProvider().scrape(_PORTAL)

    assert result.reason == ScrapeReason.SUCCESS
    assert [j["job_id"] for j in result.jobs] == ["2"]


def test_a_failed_fetch_is_retried(monkeypatch) -> None:
    asked = _serve(
        monkeypatch,
        {0: [_Resp(status=502), _Resp(_listing([_card("1")], 1))]},
        {"1": [requests.ConnectionError("reset"), _Resp(_detail())]},
    )

    result = av.AvatureProvider().scrape(_PORTAL)

    assert result.reason == ScrapeReason.SUCCESS
    assert len(asked) == 4


def test_a_job_page_that_keeps_failing_makes_the_run_partial(monkeypatch) -> None:
    # An empty description would be stored as "No JD provided", which the
    # company never said; the run is held back instead.
    _serve(monkeypatch, {0: [_Resp(_listing([_card("1"), _card("2")], 2))]}, {"2": [_Resp(status=503)]})

    result = av.AvatureProvider().scrape(_PORTAL)

    assert result.reason == ScrapeReason.PARTIAL
    assert [j["job_id"] for j in result.jobs] == ["1"]


def test_an_unreachable_first_page_goes_to_firecrawl(monkeypatch) -> None:
    _serve(monkeypatch, {0: [requests.Timeout("slow")]})

    result = av.AvatureProvider().scrape(_PORTAL)

    assert result.fallback_policy == FALLBACK_FIRECRAWL_EXTRACT
    assert result.fallback_reason == "avature_unreachable"


def test_a_failed_later_page_is_partial(monkeypatch) -> None:
    first = [_card(str(100 + i)) for i in range(9)]
    _serve(monkeypatch, {0: [_Resp(_listing(first, 12))], 9: [_Resp(status=500)]})

    result = av.AvatureProvider().scrape(_PORTAL)

    assert result.reason == ScrapeReason.PARTIAL
    assert len(result.jobs) == 9


def test_an_empty_page_ends_the_listing(monkeypatch) -> None:
    first = [_card(str(100 + i)) for i in range(9)]
    _serve(monkeypatch, {0: [_Resp(_listing(first, 12))], 9: [_Resp(_listing([], 12))]})

    result = av.AvatureProvider().scrape(_PORTAL)

    assert result.reason == ScrapeReason.SUCCESS
    assert len(result.jobs) == 9


def test_no_results_is_no_jobs(monkeypatch) -> None:
    _serve(monkeypatch, {0: [_Resp(_listing([], 0))]})

    assert av.AvatureProvider().scrape(_PORTAL).reason == ScrapeReason.NO_JOBS


@pytest.mark.parametrize(
    ("page", "note"),
    [(_listing([_card("1")], None), "avature_no_results_total"), (_listing([], 5), "avature_no_cards_of_5")],
)
def test_an_unrecognised_listing_is_a_parse_error(monkeypatch, page: str, note: str) -> None:
    _serve(monkeypatch, {0: [_Resp(page)]})

    result = av.AvatureProvider().scrape(_PORTAL)

    assert result.reason == ScrapeReason.PARSE_ERROR
    assert result.fallback_reason == note


def test_an_unrecognised_job_page_is_a_parse_error(monkeypatch) -> None:
    _serve(monkeypatch, {0: [_Resp(_listing([_card("1")], 1))]}, {"1": [_Resp("<html>maintenance</html>")]})

    assert av.AvatureProvider().scrape(_PORTAL).reason == ScrapeReason.PARSE_ERROR


def test_max_jobs_stops_early(monkeypatch) -> None:
    asked = _serve(monkeypatch, {0: [_Resp(_listing([_card("1"), _card("2"), _card("3")], 3))]})

    result = av.AvatureProvider().scrape(_PORTAL, max_jobs=2)

    assert len(result.jobs) == 2
    assert _job_pages(asked) == ["1", "2"]


def test_an_endpoint_without_searchjobs_is_a_config_error() -> None:
    result = av.AvatureProvider().scrape({**_PORTAL, "endpoint": f"{_ORIGIN}/JobDetail?jobId=1"})

    assert result.reason == ScrapeReason.CONFIG_ERROR


@pytest.mark.parametrize(
    ("employment", "level"),
    [("Permanent - Full time, Junior", "Junior"), ("Fixed term, Entry level", "Entry level"), ("Permanent", "")],
)
def test_the_level_follows_the_last_comma(employment: str, level: str) -> None:
    assert av._level(employment) == level


@pytest.mark.parametrize(("value", "iso"), [("06 Nov 2026", "2026-11-06"), ("06-Nov-2026", "2026-11-06"), ("soon", "")])
def test_posted_dates_become_iso(value: str, iso: str) -> None:
    assert av._iso_date(value) == iso
