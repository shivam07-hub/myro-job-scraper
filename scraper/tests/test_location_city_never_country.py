"""A country is never a city.

Measured 2026-09-28: 579 active jobs had lower(location_city) = lower(location_country)
(Oracle 283, TalentBrew 60, McKinsey 44, Workday 33, Greenhouse 27, Siemens 27,
UBS BrassRing 23, Firecrawl 22, ...). Myro's Admission check bars a job whose
city is not one the person named, so a city of "India" hid those jobs from
everyone who targets cities.

Fixtures below are trimmed from live provider responses captured that day.
Each adapter test runs the adapter output through ``writer.to_canonical`` and
the importer's ``_normalize_location`` — the path that fills ``jobs.location_city``.
"""
from __future__ import annotations

import json
from collections import Counter

import pytest

import providers.firecrawl_js as firecrawl_js
import providers.generic_json as generic_json
import providers.greenhouse as greenhouse
import providers.mckinsey as mckinsey
import providers.siemens_externaljobs as siemens
import providers.talentbrew as talentbrew
import providers.workday as workday
from csv_importer import _normalize_location, _upsert_jobs
from providers.ubs_brassring import parse_ubs_search_payload
from writer import to_canonical


def _published(job: dict, company: str = "Acme"):
    row = to_canonical(job, company)
    return _normalize_location(row["location"], row["locations"], row["location_states"])


def _assert_country_only(job: dict, country: str = "India") -> None:
    assert job["location_city"] is None
    published = _published(job)
    assert published.location_city is None
    assert published.location_country == country
    assert list(published.locations) == []


class _Response:
    def __init__(self, payload=None, text: str = "", status_code: int = 200) -> None:
        self._payload = payload
        self.text = text if payload is None else json.dumps(payload)
        self.status_code = status_code
        self.headers = {"Content-Type": "application/json" if payload is not None else "text/html"}

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class _Session:
    """requests.Session stand-in that serves pages by exact URL or prefix."""

    def __init__(self, pages: dict[str, str]) -> None:
        self.pages = pages
        self.headers: dict = {}

    def get(self, url, timeout=None, **_):
        for prefix, body in self.pages.items():
            if url == prefix or url.startswith(prefix):
                return _Response(text=body)
        return _Response(text="", status_code=404)


# ── importer: the one place jobs.location_city is derived ───────────────────


@pytest.mark.parametrize("raw", [
    # location_raw values of the 579 rows, verbatim.
    "India",
    "India, India",
    "India, IN",
    "India - Remote",
    "India - Remote, KA",
    "India | United Kingdom | Ireland",
])
def test_importer_never_writes_india_as_city(raw: str) -> None:
    normalized = _normalize_location(raw, ["India"])
    assert normalized.location_city is None
    assert normalized.location_country == "India"
    assert normalized.locations == ()


def test_importer_leaves_non_india_country_first_city_null() -> None:
    normalized = _normalize_location("United States - Indiana", None)
    assert normalized.location_city is None
    assert normalized.location_country == "United States"


@pytest.mark.parametrize(("raw", "city"), [
    ("India, Gujarat, Mehsana, 384421", "Mehsana"),
    ("India,Tamil Nadu,Kancheepuram,602118", "Kancheepuram"),
    ("India, Chandigarh, 160001", "Chandigarh"),
])
def test_importer_reads_city_after_state_in_country_first_india_string(raw: str, city: str) -> None:
    normalized = _normalize_location(raw, None)
    assert normalized.location_city == city
    assert normalized.location_country == "India"


@pytest.mark.parametrize(("raw", "city"), [
    ("Bengaluru, India", "Bengaluru"),
    ("India - Pune", "Pune"),
    ("Brussels", "Brussels"),
    ("London, UK", "London"),
])
def test_importer_keeps_real_cities(raw: str, city: str) -> None:
    assert _normalize_location(raw, None).location_city == city


class _FakeJobsTable:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def upsert(self, rows, on_conflict=None, ignore_duplicates=False):
        self.rows.extend(rows)
        return self

    def execute(self):
        return type("Response", (), {"data": []})()


def test_republish_sends_explicit_null_city_so_stale_country_city_is_overwritten(monkeypatch) -> None:
    # No backfill sweep: the next scrape re-observes the job, and the upsert
    # must carry location_city=None (an omitted key would keep "India").
    monkeypatch.setattr("csv_importer._jobs_has_job_content_hash_column", lambda: False)
    table = _FakeJobsTable()
    sb = type("SB", (), {"table": lambda self, name: table})()

    _upsert_jobs(
        sb,
        [{"job_id": "346978", "job_title": "IT Security Consultant", "job_description": "Run IAM.",
          "company_name": "UBS", "industry": "Financial Services", "location": "India",
          "locations": []}],
        batch_date=20260928,
        location_alias_counter=Counter(),
    )

    assert "location_city" in table.rows[0]
    assert table.rows[0]["location_city"] is None
    assert table.rows[0]["location_country"] == "India"


# ── writer ───────────────────────────────────────────────────────────────────


def test_writer_country_only_adapter_row_keeps_country_display() -> None:
    row = to_canonical({"job_id": "1", "location_city": None, "location_country": "India"}, "Acme")
    assert row["location"] == "India"
    assert row["location_city"] is None
    assert row["location_country"] == "India"


def test_writer_does_not_copy_a_country_into_the_city() -> None:
    row = to_canonical({"job_id": "1", "location_city": "India"}, "Acme")
    assert row["location_city"] is None
    assert row["location"] == "India"


# ── Workday (Accenture) ──────────────────────────────────────────────────────

_WORKDAY_PORTAL = {
    "company": "Accenture",
    "endpoint": "https://accenture.wd103.myworkdayjobs.com/wday/cxs/accenture/AccentureCareers/jobs",
    "tenant": "accenture",
    "instance": "wd103",
    "career_site": "AccentureCareers",
    "workday_facet_param": "locationCountry",
    "workday_india_uuids": ["c4f78be1a8f14da0ab49ce1162348a5e"],
    "india_only": True,
}

# Accenture's CXS listing returns locationsText=null for every posting.
_WORKDAY_LISTING = {"total": 3, "jobPostings": [
    {"title": "Technology Sales Senior Manager - Financial Services",
     "externalPath": "/job/Brussels/Technology-Sales-Senior-Manager---Financial-Services_R00313961",
     "locationsText": None, "bulletFields": ["R00313961"]},
    {"title": "Data Science Consultant",
     "externalPath": "/job/Pune-PDC2C/S-C-Global-Network---AI---Hi-Tech---Data-Science-Consultant_R00218611",
     "locationsText": None, "bulletFields": ["R00218611"]},
    {"title": "Corporate Account Executive",
     "externalPath": "/job/India---Remote/Corporate-Account-Executive--Remote--IND-_R27406",
     "locationsText": "India", "bulletFields": ["R27406"]},
]}


def test_workday_listing_reads_city_from_url_path(monkeypatch) -> None:
    monkeypatch.setattr(workday.requests, "post", lambda *a, **k: _Response(_WORKDAY_LISTING))
    monkeypatch.setattr(workday, "_fetch_workday_jds", lambda jobs, portal, limit=None: None)

    jobs, _ = workday.scrape_workday(_WORKDAY_PORTAL)
    by_id = {job["job_id"]: job for job in jobs}

    assert by_id["R00313961"]["location_city"] == "Brussels"
    assert _published(by_id["R00313961"]).location_city == "Brussels"
    assert _published(by_id["R00218611"]).location_city == "Pune"
    _assert_country_only(by_id["R27406"])


def test_workday_detail_country_only_falls_back_to_url_city(monkeypatch) -> None:
    # Detail payloads without a `location` expose only the country descriptor.
    detail = {"jobPostingInfo": {"jobDescription": "<p>Build things.</p>",
                                 "country": {"descriptor": "India"}}}
    monkeypatch.setattr(workday.requests, "get", lambda *a, **k: _Response(detail))
    jobs = [
        {"job_id": "a", "raw_jd_text": "", "location_city": None,
         "_ext": "/job/Bengaluru/Custom-Software-Engineering-Lead_ATCI-5750106-S2068598-1"},
        {"job_id": "b", "raw_jd_text": "", "location_city": None,
         "_ext": "/job/India---Remote/AI-Engineer--Remote--IND-_R28983"},
    ]

    workday._fetch_workday_jds(jobs, _WORKDAY_PORTAL)

    assert jobs[0]["location_city"] == "Bengaluru, India"
    assert _published(jobs[0]).location_city == "Bengaluru"
    _assert_country_only(jobs[1])


# ── Oracle HCM (Nokia, Honeywell, Texas Instruments, Oracle) ────────────────

_ORACLE_URL = (
    "https://fa-evmr-saasfaprod1.fa.ocs.oraclecloud.com/hcmRestApi/resources/latest/"
    "recruitingCEJobRequisitions?onlyData=true&finder=findReqs;siteNumber=CX_1,limit=25"
)
_ORACLE_PAYLOAD = {"items": [{"requisitionList": [
    {"Id": "38495", "Title": "SW QA Engineer 2", "PrimaryLocation": "India",
     "PrimaryLocationCountry": "IN",
     "workLocation": [{"TownOrCity": "Bangalore", "Region2": "Karnataka", "Country": "IN"}],
     "otherWorkLocations": [{"TownOrCity": "Gurgaon", "Country": "IN"}],
     "secondaryLocations": []},
    {"Id": "25003187", "Title": "Analog Design Engineer", "PrimaryLocation": "India",
     "workLocation": [], "otherWorkLocations": [],
     "secondaryLocations": [{"Name": "Bengaluru, Karnataka, India", "CountryCode": "IN"}]},
    {"Id": "146022", "Title": "Field Service Engineer", "PrimaryLocation": "India",
     "workLocation": [{"TownOrCity": None, "Country": "IN"}],
     "otherWorkLocations": [], "secondaryLocations": []},
]}]}


def test_oracle_country_only_primary_location_uses_work_location_city(monkeypatch) -> None:
    monkeypatch.setattr(generic_json, "_fetch_oracle_detail_jd", lambda *a, **k: "")
    monkeypatch.setattr(generic_json, "_fetch_oracle_html_jd", lambda *a, **k: "")

    jobs = generic_json._parse_json_response(
        _ORACLE_PAYLOAD,
        {"company": "Nokia", "ats": "oracle", "oracle_nested": True, "india_only": True},
        _ORACLE_URL,
    )
    by_id = {job["job_id"]: job for job in jobs}

    first = _published(by_id["38495"])
    assert first.location_city == "Bengaluru"
    assert list(first.locations) == ["Bengaluru", "Gurugram"]
    assert _published(by_id["25003187"]).location_city == "Bengaluru"
    _assert_country_only(by_id["146022"])


# ── TalentBrew (ADP) ─────────────────────────────────────────────────────────

_ADP_BASE = "https://jobs.adp.com/en/jobs/?mylocation=India&orderby=0&page=1&pagesize=20&rType=0&radius=100"
_ADP_LISTING = """
<div class="card card-job" data-id="ind170274"><div class="card-body">
  <h2 class="card-title"><a class="stretched-link js-view-job" href="/en/jobs/ind170274/wfsuite-impl-mas-pune-170274/">WFSuite IMPL-MAS-Pune 170274</a></h2>
  <div class="job-meta"><p><span class="job-meta-location"> Pune, Maharashtra, India </span></p></div>
</div></div>
<div class="card card-job" data-id="ind171453"><div class="card-body">
  <h2 class="card-title"><a class="stretched-link js-view-job" href="/en/jobs/ind171453/india-finance-payroll/">India Finance Payroll Accounting 171453</a></h2>
  <div class="job-meta"><p></p></div>
</div></div>
"""
_ADP_DETAIL = "<html><h2>Description</h2><p>Own payroll reconciliation for the India entity.</p></html>"


def test_talentbrew_adp_card_location_reaches_listing_items() -> None:
    items = {item["job_id"]: item for item in talentbrew._extract_listing_items(_ADP_LISTING)}
    assert items["ind170274"]["listing_loc"] == "Pune, Maharashtra, India"
    # The second card prints no location; it must not borrow the first card's.
    assert items["ind171453"]["listing_loc"] == ""


def test_talentbrew_adp_emits_city_or_country_only(monkeypatch) -> None:
    session = _Session({_ADP_BASE: _ADP_LISTING, "https://jobs.adp.com/en/jobs/ind": _ADP_DETAIL})
    monkeypatch.setattr(talentbrew.requests, "Session", lambda: session)

    jobs = talentbrew._scrape_talentbrew({"company": "ADP", "endpoint": _ADP_BASE, "india_only": True})
    by_id = {job["job_id"]: job for job in jobs}

    assert _published(by_id["ind170274"]).location_city == "Pune"
    _assert_country_only(by_id["ind171453"])


# ── McKinsey ─────────────────────────────────────────────────────────────────

_MCKINSEY_PAYLOAD = {"docs": [
    {"jobID": "104404", "title": "Consultant - Gurugram", "countries": ["India"],
     "cities": ["Gurugram"], "whatYouWillDo": "<p>Solve problems.</p>"},
    {"jobID": "104473", "title": "Engineer", "countries": ["India", "India"],
     "cities": ["Chennai", "Gurugram"], "whatYouWillDo": "<p>Build.</p>"},
    {"jobID": "104500", "title": "Analyst", "countries": ["Poland", "India"],
     "cities": ["Poznan", "Bengaluru"], "whatYouWillDo": "<p>Analyse.</p>"},
    {"jobID": "104501", "title": "Partner", "countries": ["India"],
     "cities": [], "whatYouWillDo": "<p>Lead.</p>"},
]}


def test_mckinsey_reads_india_cities_from_parallel_arrays(monkeypatch) -> None:
    monkeypatch.setattr(mckinsey.requests, "get", lambda *a, **k: _Response(_MCKINSEY_PAYLOAD))

    jobs = {job["job_id"]: job for job in mckinsey._scrape_mckinsey({"industry": "Consulting"})}

    assert _published(jobs["104404"]).location_city == "Gurugram"
    multi = _published(jobs["104473"])
    assert multi.location_city == "Chennai"
    assert list(multi.locations) == ["Chennai", "Gurugram"]
    assert _published(jobs["104500"]).location_city == "Bengaluru"
    _assert_country_only(jobs["104501"])


# ── Siemens ExternalJobs ─────────────────────────────────────────────────────

_SIEMENS_BASE = (
    "https://jobs.siemens.com/en_US/externaljobs/SearchJobs/"
    "?42386=%5B812053%5D&42386_format=17546&listFilterMode=1&folderRecordsPerPage=6&"
)
_SIEMENS_LISTING = """
<article class="article article--result">
  <a class="link" href="https://jobs.siemens.com/en_US/externaljobs/JobDetail/524041">Service Engineer</a>
  <span class="list-item-jobCity">Pune</span><span class="list-item-jobState">Maharashtra</span>
  <span class="list-item-jobCountry">India</span>
</article>
<article class="article article--result">
  <a class="link" href="https://jobs.siemens.com/en_US/externaljobs/JobDetail/485144">Services Senior Manager</a>
</article>
"""


def _siemens_detail(fields: list[tuple[str, str]]) -> str:
    blocks = "".join(
        f'<div class="article__content__view__field__label">{label}</div>'
        f'<div class="article__content__view__field__value">{value}</div>'
        for label, value in fields
    )
    return blocks + '<div class="article__content__view__field__value">Long description of the role.</div>'


def test_siemens_state_level_region_is_country_only(monkeypatch) -> None:
    session = _Session({
        "https://jobs.siemens.com/en_US/externaljobs/JobDetail/524041":
            _siemens_detail([("Job ID", "524041"), ("Location(s)", "Pune - Maharashtra - India")]),
        "https://jobs.siemens.com/en_US/externaljobs/JobDetail/485144":
            _siemens_detail([("Job ID", "485144"),
                             ("Any Siemens location in", "Karnataka - India Maharashtra - India")]),
        "https://jobs.siemens.com/en_US/externaljobs/SearchJobs/": _SIEMENS_LISTING,
    })
    monkeypatch.setattr(siemens.requests, "Session", lambda: session)

    jobs = siemens._scrape_siemens_externaljobs(
        {"company": "Siemens", "endpoint": _SIEMENS_BASE, "india_only": True}, max_jobs=2,
    )
    by_id = {job["job_id"]: job for job in jobs}

    assert _published(by_id["524041"]).location_city == "Pune"
    # Before: fallback "India" became the city; the region's first token would be "Karnataka".
    _assert_country_only(by_id["485144"])
    assert by_id["485144"]["location_raw"] == "Karnataka - India Maharashtra - India"
    # ...and keeps both states, so Myro can reach Bengaluru and Pune users only.
    assert _published(by_id["485144"]).location_states == ("Karnataka", "Maharashtra")


# ── UBS BrassRing ────────────────────────────────────────────────────────────


def test_ubs_country_only_search_result_has_no_city() -> None:
    payload = {"Jobs": {"Job": [{
        "Questions": [
            {"QuestionName": "reqid", "ActualValueFromSolar": "346978"},
            {"QuestionName": "jobtitle", "ActualValueFromSolar": "IT Security Consultant- IAM, PAM"},
            {"QuestionName": "formtext23", "ActualValueFromSolar": "India"},
            {"QuestionName": "jobdescription", "ActualValueFromSolar": "<p>Run identity controls.</p>"},
        ],
        "Link": "https://jobs.ubs.com/TGnewUI/Search/home/HomeWithPreLoad?PageType=JobDetails&jobid=346978",
    }]}}

    jobs = parse_ubs_search_payload(payload, {"company": "UBS", "india_only": True})

    _assert_country_only(jobs[0])


# ── Greenhouse (Point72, Netskope, Boomi) ────────────────────────────────────

_GREENHOUSE_BOARD = {"jobs": [
    {"id": 7001, "title": "Quant Developer", "absolute_url": "https://boards.greenhouse.io/point72/jobs/7001",
     "location": {"name": "India"}, "content": "&lt;p&gt;Build research tooling.&lt;/p&gt;",
     "offices": [{"name": "India", "location": "Bengaluru, Karnataka, India"}]},
    {"id": 7002, "title": "Security Engineer", "absolute_url": "https://boards.greenhouse.io/netskope/jobs/7002",
     "location": {"name": "India"}, "content": "&lt;p&gt;Defend the edge.&lt;/p&gt;",
     "offices": [{"name": "India", "location": "India"}]},
    {"id": 7003, "title": "Data Engineer", "absolute_url": "https://boards.greenhouse.io/databricks/jobs/7003",
     "location": {"name": "Bengaluru, India"}, "content": "&lt;p&gt;Pipelines.&lt;/p&gt;",
     "offices": [{"name": "Bengaluru, India", "location": "Bengaluru, India"}]},
]}


def test_greenhouse_country_only_location_uses_office_city(monkeypatch) -> None:
    monkeypatch.setattr(greenhouse.requests, "get", lambda *a, **k: _Response(_GREENHOUSE_BOARD))

    jobs = greenhouse.scrape_greenhouse({
        "company": "Point72",
        "endpoint": "https://boards-api.greenhouse.io/v1/boards/point72/jobs?content=true",
        "india_only": True,
    })
    by_id = {job["job_id"]: job for job in jobs}

    assert _published(by_id["7001"]).location_city == "Bengaluru"
    _assert_country_only(by_id["7002"])
    assert _published(by_id["7003"]).location_city == "Bengaluru"


# ── Firecrawl / Scrapling generic JS pages (Bain) ────────────────────────────


def test_firecrawl_generic_page_claims_country_not_city(monkeypatch) -> None:
    listing = ("# Search jobs\n\n" + "Careers at Bain. " * 20 +
               "\n[Associate - Vector Generalist](https://careers.bain.com/jobs/FolderDetail/Associate-Vector-Generalist/107097)\n")
    detail = "Associate - Vector Generalist. Join our India capability network. " * 5
    monkeypatch.setattr(firecrawl_js.scrapling, "fetch_listing_markdown", lambda url: listing)
    monkeypatch.setattr(firecrawl_js.scrapling, "fetch_text", lambda url: detail)

    jobs = firecrawl_js.scrape_extract({
        "company": "Bain & Company",
        "endpoint": "https://careers.bain.com/jobs/SearchJobs/india/?folderRecordsPerPage=10&folderOffset=0",
        "india_only": True,
    })

    assert len(jobs) == 1
    _assert_country_only(jobs[0])
