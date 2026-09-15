"""paginate() owns the stop decision; these assert each stop signal + step mode."""

from __future__ import annotations

from providers._paginate import Page, paginate


def _collect(gen):
    out = []
    for items in gen:
        out.extend(items)
    return out


def test_record_offset_total_and_has_more_zwayam_shape():
    # 200 records, server returns 9/page (variable), advance by len. The exact
    # shape that truncated Zwayam.
    data = list(range(200))

    def fetch(offset):
        window = data[offset:offset + 9]
        return Page(items=window, total=200, has_more=(offset + 9) < 200)

    got = _collect(paginate(fetch, step=None))
    assert got == data  # all 200, not 9


def test_fixed_size_offset_total_eightfold_shape():
    data = list(range(120))

    def fetch(offset):
        return Page(items=data[offset:offset + 20], total=120)

    assert _collect(paginate(fetch, step=20)) == data


def test_page_number_no_total_stops_on_empty():
    pages = {1: [1, 2, 3], 2: [4, 5], 3: []}

    def fetch(page):
        return Page(items=pages.get(page, []))

    assert _collect(paginate(fetch, start=1, step=1)) == [1, 2, 3, 4, 5]


def test_no_new_ids_stops_a_repeating_api():
    # API that keeps returning the same last page forever.
    def fetch(page):
        return Page(items=[{"id": 1}, {"id": 2}])

    got = _collect(paginate(fetch, start=1, step=1, id_of=lambda x: x["id"]))
    assert got == [{"id": 1}, {"id": 2}]  # one page, then no-new -> stop


def test_has_more_false_stops_even_without_total():
    def fetch(offset):
        return Page(items=[1, 2], has_more=False)

    assert _collect(paginate(fetch, step=None)) == [1, 2]


def test_empty_first_page():
    assert _collect(paginate(lambda o: Page(items=[]), step=None)) == []


def test_max_pages_guard():
    # Infinite non-repeating API must still terminate.
    def fetch(offset):
        return Page(items=[offset])  # always one new item, never a stop signal

    got = _collect(paginate(fetch, step=1, max_pages=5))
    assert got == [0, 1, 2, 3, 4]
