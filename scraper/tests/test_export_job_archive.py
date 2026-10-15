"""Archive export reads. Offset pages of wide job rows time out under load."""
from export_job_archive import PAGE_SIZE, fetch_all, fetch_candidates


class _Page:
    MAX_ROWS = 1000

    def __init__(self, rows):
        self._rows = [dict(row) for row in rows]
        self._start, self._end = 0, None

    def select(self, *_args, **_kwargs):
        return self

    def or_(self, *_args, **_kwargs):
        return self

    def order(self, column):
        self._rows = sorted(self._rows, key=lambda row: row[column])
        return self

    def range(self, start, end):
        if start > 0:
            raise RuntimeError("canceling statement due to statement timeout")
        self._start, self._end = start, end
        return self

    def gt(self, column, value):
        self._rows = [row for row in self._rows if row[column] > value]
        return self

    def limit(self, count):
        self._start, self._end = 0, count - 1
        return self

    def execute(self):
        end = len(self._rows) if self._end is None else self._end + 1
        page = self._rows[self._start:end][: self.MAX_ROWS]
        return type("Response", (), {"data": page})()


def test_archive_candidates_are_read_when_a_later_offset_times_out() -> None:
    """24k inactive jobs, paged 500 at a time with the full description,
    timed out on a deep offset. Keyset on job_id must return every row."""
    rows = [{"job_id": f"{i:04d}", "is_active": False} for i in range(PAGE_SIZE + 100)]

    class _Sb:
        def table(self, _name):
            return _Page(rows)

    fetched = fetch_candidates(_Sb(), 20260914)

    assert len(fetched) == PAGE_SIZE + 100
    assert fetched[0]["job_id"] == "0000"
    assert fetched[-1]["job_id"] == f"{PAGE_SIZE + 99:04d}"


def test_protection_read_keeps_rows_that_share_a_job_id() -> None:
    """user_job_matches has many rows per job. A job_id cursor would drop them."""
    rows = [{"job_id": "same"}, {"job_id": "same"}, {"job_id": "other"}]

    fetched = fetch_all(_Page(rows).select("job_id").order("job_id"))

    assert [row["job_id"] for row in fetched] == ["other", "same", "same"]
