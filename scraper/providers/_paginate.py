"""paginate() — one place that decides when to stop paginating.

Every ATS provider walks pages, and every one re-derived the stop condition.
The correctness of that condition rests on an implicit invariant — *did we
control the page size?* — that nothing named or tested. Two providers got it
wrong (Zwayam, H&M): they stopped on `len(page) < a_guessed_number`, which
truncates the moment the server returns a short page mid-stream.

This module is the deep version: the provider says only *how to fetch page N*
and *how to read total/continuation from the response*; the stop decision lives
here, once, tested. The three shapes in this codebase all reduce to it:

  - record-offset + total + has_more (Zwayam): step=None (advance by len), Page(total, has_more)
  - page-number, no total (H&M):              start=1, step=1, id_of= per-item id
  - fixed-size offset + total (Eightfold):     step=PAGE_SIZE, Page(total)

It yields each page's raw items; the provider still does its own filtering,
transforming, and cap. Stop signals owned here: empty page, has_more is False,
collected >= total, a page with no new id_of(item), or max_pages.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any


@dataclass
class Page:
    items: list[Any]
    total: int | None = None       # server's match count, if it gives one
    has_more: bool | None = None    # explicit continuation flag, if it gives one


def paginate(
    fetch_page: Callable[[int], Page | None],
    *,
    start: int = 0,
    step: int | None = None,
    max_pages: int = 1000,
    id_of: Callable[[Any], Any] | None = None,
) -> Iterator[list[Any]]:
    """Yield each page's items, stopping at the true end of the result set.

    fetch_page(offset) -> Page | None. Returning None or an empty page stops.
    step: how far to advance the offset each call.
        - None  -> advance by len(items)  (record-offset APIs like Zwayam)
        - int N -> advance by N            (fixed page size, or N=1 for page numbers)
    id_of: optional per-item identity. When given, a page that contributes no
        new id ends pagination (guards APIs that loop or repeat the last page).
    """
    seen = 0
    seen_ids: set[Any] = set()
    offset = start

    for _ in range(max_pages):
        page = fetch_page(offset)
        if page is None or not page.items:
            return

        items = page.items

        if id_of is not None:
            new_ids = [id_of(it) for it in items if id_of(it) not in seen_ids]
            if not new_ids:
                return
            seen_ids.update(new_ids)

        yield items

        seen += len(items)
        if page.total is not None and seen >= page.total:
            return
        if page.has_more is False:
            return

        offset += step if step is not None else len(items)
