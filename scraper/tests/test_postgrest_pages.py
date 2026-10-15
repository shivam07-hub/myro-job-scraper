"""The shared reader is the test surface for the 1,000-row response cap."""
import pytest

import postgrest_pages
from postgrest_pages import read_all_rows


class _Capped:
    MAX_ROWS = 1000

    def __init__(self, rows, *, fail_first=0):
        self._rows = list(rows)
        self._start, self._end = 0, None
        self._fail = fail_first

    def gt(self, column, value):
        self._rows = [row for row in self._rows if row[column] > value]
        return self

    def order(self, column):
        self._rows = sorted(self._rows, key=lambda row: row[column])
        return self

    def limit(self, count):
        self._start, self._end = 0, count - 1
        return self

    def execute(self):
        if self._fail:
            raise RuntimeError("canceling statement due to statement timeout")
        end = len(self._rows) if self._end is None else self._end + 1
        page = self._rows[self._start:end][: self.MAX_ROWS]
        return type("Response", (), {"data": page})()


def test_read_all_rows_passes_the_1000_row_cap() -> None:
    rows = [{"job_id": f"{i:05d}"} for i in range(2500)]

    fetched = read_all_rows(lambda: _Capped(rows), order_column="job_id", page_size=1000)

    assert [row["job_id"] for row in fetched] == [f"{i:05d}" for i in range(2500)]


def test_read_all_rows_retries_a_statement_timeout(monkeypatch) -> None:
    rows = [{"job_id": f"{i:05d}"} for i in range(1500)]
    pages = iter([1, 0, 0])
    monkeypatch.setattr(postgrest_pages, "_sleep", lambda _seconds: None)

    fetched = read_all_rows(
        lambda: _Capped(rows, fail_first=next(pages)),
        order_column="job_id",
        page_size=1000,
    )

    assert len(fetched) == 1500


def test_read_all_rows_refuses_a_page_larger_than_the_response_cap() -> None:
    with pytest.raises(ValueError):
        read_all_rows(lambda: _Capped([]), order_column="job_id", page_size=1001)
