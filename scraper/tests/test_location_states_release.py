"""Location release — CEO decision record 2026-10-04.

Q1 a job with no city is shown, labeled "<country> — city not specified".
Q2 a job with only a state carries that state (Kotak "Maharashtra": 178 rows).
Q4 Myro is India-only: drop a posting only when it is positively outside India.
Q5 a known Indian city fills in country and state (Coimbatore: 152 rows had none).
Q6 Delhi NCR = Delhi, Gurugram, Noida.
Q7 Bain and UBS read their real cities.
Q9 the database enforces the rule; the importer reports the daily check.
Plus the expiry fix: an undated scraper row ages by batch_date.
"""
from __future__ import annotations

import json
from collections import Counter

import pytest

import location_vocab
import providers.bain_careers as bain
import trusted_job_lifecycle
from csv_importer import (
    _normalize_location,
    _outside_india,
    _report_location_rule_violations,
    _upsert_jobs,
    import_file,
)
from location_vocab import foreign_signal, india_city, metro_members, seed_sql, states_in
from providers.ubs_brassring import _with_detail_city, parse_ubs_detail_cities
from utils import job_hash
from writer import to_canonical


# ── importer: states, country fill-in, label ─────────────────────────────────


@pytest.mark.parametrize(("raw", "states", "label"), [
    # location_raw values of live rows whose city was a state (1,048 rows).
    ("Maharashtra, India", ("Maharashtra",), "Maharashtra — city not specified"),
    ("Karnataka, India", ("Karnataka",), "Karnataka — city not specified"),
    ("Goa - Goa - India", ("Goa",), "Goa — city not specified"),
    ("Karnataka - India Maharashtra - India", ("Karnataka", "Maharashtra"),
     "Karnataka or Maharashtra — city not specified"),
])
def test_state_only_posting_has_no_city_and_keeps_its_states(raw, states, label) -> None:
    normalized = _normalize_location(raw)
    assert normalized.location_city is None
    assert normalized.location_country == "India"
    assert normalized.location_states == states
    assert normalized.location == label


def test_country_only_posting_is_labeled_city_not_specified() -> None:
    normalized = _normalize_location("India")
    assert normalized.location == "India — city not specified"
    assert normalized.location_quality == "ok"


def test_remote_display_is_unchanged() -> None:
    assert _normalize_location("India - Remote").location == "Remote - India"
    assert _normalize_location("Remote").location_quality == "ok"


def test_adapter_states_reach_a_country_only_posting() -> None:
    normalized = _normalize_location("India", None, ["Karnataka", "Maharashtra"])
    assert normalized.location_states == ("Karnataka", "Maharashtra")
    assert normalized.location == "Karnataka or Maharashtra — city not specified"


@pytest.mark.parametrize(("raw", "city", "state"), [
    ("Coimbatore", "Coimbatore", "Tamil Nadu"),
    ("Indore", "Indore", "Madhya Pradesh"),
    ("Thane", "Thane", "Maharashtra"),
    ("Mysore, Karnataka", "Mysuru", "Karnataka"),
    ("Pune, Maharashtra, India", "Pune", "Maharashtra"),
])
def test_known_indian_city_fills_country_and_state(raw, city, state) -> None:
    normalized = _normalize_location(raw)
    assert normalized.location_city == city
    assert normalized.location_country == "India"
    assert state in normalized.location_states


@pytest.mark.parametrize("raw", ["In", "Mh", "Gcc Service India Pvt. Ltd."])
def test_codes_and_fragments_naming_india_are_not_cities(raw) -> None:
    assert _normalize_location(raw).location_city is None


def test_multi_city_posting_lists_every_state() -> None:
    normalized = _normalize_location("2 Locations", ["Bengaluru", "Pune"])
    assert normalized.location_states == ("Karnataka", "Maharashtra")


# ── India-only (Q4) ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("raw", [
    "Mississauga-Ontario-Ca", "Mississauga On", "Georgia", "Brussels", "London, UK",
    "United States - Indiana", "Warsaw", "New York",
])
def test_positively_foreign_posting_is_dropped(raw) -> None:
    assert _outside_india({"location": raw})


@pytest.mark.parametrize("raw", [
    "India", "Indore", "Maharashtra, India", "India | United Kingdom | Ireland",
    "Mh", "Project Office", "Haveli",
])
def test_unrecognised_or_indian_posting_is_kept(raw) -> None:
    assert not _outside_india({"location": raw})


def test_import_file_drops_foreign_postings_before_publishing(tmp_path) -> None:
    path = tmp_path / "Mphasis" / "Outputs" / "2026_10_07" / "jobs.json"
    path.parent.mkdir(parents=True)
    base = {
        "company_name": "Mphasis", "job_title": "SDET", "job_description": "Test.",
        "career_band": "", "seniority_level": "mid",
    }
    path.write_text(json.dumps([
        {**base, "job_id": "in-1", "location": "Pune, India"},
        {**base, "job_id": "us-1", "location": "Georgia"},
        {**base, "job_id": "ca-1", "location": "Toronto-Ontario-Ca"},
    ]), encoding="utf-8")

    result = import_file(
        object(), path, {}, Counter(), Counter(), True,
        source_only=True, publish_unclassified=True,
    )

    assert result["outside_india"] == 2
    assert result["job_ids"] == {"in-1"}


# ── importer write and writer ────────────────────────────────────────────────


class _FakeJobsTable:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def upsert(self, rows, on_conflict=None, ignore_duplicates=False):
        self.rows.extend(rows)
        return self

    def execute(self):
        return type("Response", (), {"data": []})()


def test_upsert_sends_location_states(monkeypatch) -> None:
    monkeypatch.setattr("csv_importer._jobs_has_job_content_hash_column", lambda: False)
    table = _FakeJobsTable()
    sb = type("SB", (), {"table": lambda self, name: table})()

    _upsert_jobs(
        sb,
        [{"job_id": "kotak-1", "job_title": "Relationship Manager", "job_description": "Grow the book.",
          "company_name": "Kotak Mahindra Bank", "industry": "Banking", "location": "Maharashtra, India"}],
        batch_date=20261007,
        location_alias_counter=Counter(),
    )

    row = table.rows[0]
    assert row["location_city"] is None
    assert row["location_states"] == ["Maharashtra"]
    assert row["location"] == "Maharashtra — city not specified"


def test_writer_keeps_adapter_states_and_never_writes_a_state_as_city() -> None:
    row = to_canonical(
        {"job_id": "1", "location_city": "Maharashtra", "location_states": ["Maharashtra"]}, "Acme",
    )
    assert row["location_city"] is None
    assert row["location_states"] == ["Maharashtra"]


# ── vocabulary and the Myro copy ─────────────────────────────────────────────


def test_seed_sql_matches_the_city_list() -> None:
    # Edit india_cities.json, then: python location_vocab.py --write-seed
    assert location_vocab.SEED_PATH.read_text(encoding="utf-8") == seed_sql()


def test_city_list_has_one_state_per_city_and_aliases_resolve() -> None:
    data = json.loads((location_vocab._CITIES_PATH).read_text(encoding="utf-8"))
    names = [name.lower() for cities in data["cities"].values() for name in cities]
    assert len(names) == len(set(names))
    for alias, target in data["aliases"].items():
        assert india_city(alias)[0] == target


def test_delhi_ncr_is_delhi_gurugram_and_noida() -> None:
    assert metro_members("Delhi NCR") == ("Delhi NCR", "Gurugram", "Noida")
    assert india_city("New Delhi") == ("Delhi NCR", "Delhi")
    assert india_city("Gurgaon") == ("Gurugram", "Haryana")


def test_states_and_foreign_signals() -> None:
    assert states_in("Jammu & Kashmir; Orissa") == ["Jammu and Kashmir", "Odisha"]
    assert not foreign_signal("Bengaluru, Karnataka, India")


# ── the daily check ──────────────────────────────────────────────────────────


class _RPC:
    def __init__(self, data=None, error: Exception | None = None) -> None:
        self.data, self.error = data, error

    def rpc(self, name):
        assert name == "location_rule_violations"
        return self

    def execute(self):
        if self.error:
            raise self.error
        return type("Response", (), {"data": self.data})()


def test_daily_check_reports_counts_and_never_fails_a_publish() -> None:
    counts = {"city_is_country": 0, "city_is_state": 3, "outside_india": 0,
              "indian_city_without_country": 0}
    assert _report_location_rule_violations(_RPC(counts)) == counts
    assert _report_location_rule_violations(_RPC(error=RuntimeError("down"))) is None


# ── expiry: undated scraper rows ─────────────────────────────────────────────


class _Query:
    def __init__(self, log: list, rows_by_shape: dict) -> None:
        self.filters: list[tuple] = []
        self._log, self._rows = log, rows_by_shape

    def select(self, *_):
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def is_(self, column, value):
        self.filters.append(("is", column, value))
        return self

    def lt(self, column, value):
        self.filters.append(("lt", column, value))
        return self

    @property
    def not_(self):
        self.filters.append(("not",))
        return self

    def range(self, *_):
        return self

    def execute(self):
        self._log.append(tuple(self.filters))
        undated = ("is", "last_seen", "null") in self.filters and ("not",) not in self.filters
        return type("Response", (), {"data": self._rows["undated" if undated else "dated"]})()


def test_undated_scraper_row_ages_by_batch_date_and_extension_saves_do_not() -> None:
    log: list = []
    rows = {"dated": [{"job_id": "ghost-dated"}], "undated": [{"job_id": "00d34a53997a518d"}]}
    sb = type("SB", (), {"table": lambda self, name: _Query(log, rows)})()

    ids = trusted_job_lifecycle._fetch_stale_active_ids(sb, 20260907)

    assert ids == ["ghost-dated", "00d34a53997a518d"]
    undated_filters = log[1]
    assert ("eq", "ingestion_source", "scraper") in undated_filters
    assert ("lt", "batch_date", 20260907) in undated_filters


# ── Bain (Q7) ────────────────────────────────────────────────────────────────

_BAIN_BASE = "https://careers.bain.com/jobs/SearchJobs/india/?folderRecordsPerPage=10&folderOffset=0"


def _bain_article(title: str, slug: str, cities: str) -> str:
    url = f"https://careers.bain.com/jobs/FolderDetail/{slug}"
    return f"""
    <article class="article article--result">
      <div class="article__header"><div class="article__header__text">
        <h3 class="article__header__text__title article__header__text__title--4">
          <a href="{url}">
              {title}
          </a>
        </h3>
        <div class="article__header__text__subtitle">
          <span>
              {cities}
          </span>
        </div>
      </div></div>
    </article>"""


_BAIN_PAGE = (
    _bain_article("Lead Platform Engineer", "Lead-Platform-Engineer-India/100975", "New Delhi")
    + _bain_article("Lead, AI Engineering", "Lead-AI-Engineer-India-Main/110462", "Bengaluru, Mumbai, New Delhi")
    + _bain_article("Staff Architect II", "Staff-Architect-II/110001", "Mexico City, Warsaw")
)


class _BainSession:
    def __init__(self) -> None:
        self.headers: dict = {}

    def get(self, url, timeout=None):
        body = _BAIN_PAGE if "folderOffset=0" in url else ""
        return type("Response", (), {"text": body, "raise_for_status": lambda self: None})()


def test_bain_reads_cities_from_the_listing_and_keeps_its_job_ids(monkeypatch) -> None:
    monkeypatch.setattr(bain.requests, "Session", _BainSession)
    fetched: list[str] = []
    monkeypatch.setattr(bain.scrapling, "fetch_text", lambda url: fetched.append(url) or "Full description. " * 10)
    monkeypatch.setattr(bain.fc, "batch_scrape", lambda urls: {})

    jobs = {job["title"]: job for job in bain._scrape_bain({"company": "Bain & Company", "endpoint": _BAIN_BASE})}

    platform = jobs["Lead Platform Engineer"]
    # The id the generic Firecrawl route wrote for this live row.
    assert platform["job_id"] == "3c60669ded611219"
    assert platform["job_id"] == job_hash(platform["title"], platform["job_url"])
    assert _normalize_location(platform["location_city"], platform["locations"]).location_city == "Delhi NCR"
    assert jobs["Lead, AI Engineering"]["locations"] == ["Bengaluru", "Mumbai", "Delhi NCR"]
    # Mexico City / Warsaw is skipped before its page is paid for.
    assert "Staff Architect II" not in jobs
    assert not any("Staff-Architect" in url for url in fetched)


# ── UBS (Q7) ─────────────────────────────────────────────────────────────────

_UBS_JOB_PAGE = (
    '<script>var preload = {"Questions":[{"QuestionName":"Job Reference #","AnswerValue":"339676BR"},'
    '{"QuestionName":"City","AnswerValue":"Pune","VerityZone":"formtext2"}]};</script>'
)


def test_ubs_job_page_city_replaces_the_country_only_search_result() -> None:
    assert parse_ubs_detail_cities(_UBS_JOB_PAGE) == ["Pune"]

    class Session:
        def get(self, url, timeout=None):
            return type("Response", (), {"text": _UBS_JOB_PAGE, "raise_for_status": lambda self: None})()

    job = _with_detail_city(Session(), {
        "job_id": "346978", "job_url": "https://jobs.ubs.com/x?jobid=346978",
        "location_city": None, "location_country": "India",
    })

    assert job["location_city"] == "Pune, India"
    assert job["locations"] == ["Pune"]
