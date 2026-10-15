"""Read every row of a PostgREST query.

One response holds at most 1,000 rows. Callers pass a factory that applies
filters and nothing else. This module turns the page on a unique column and
retries a statement timeout. Offset paging stays with callers whose order
column is not unique.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from lifecycle_writer import _RETRY_DELAYS, _is_statement_timeout

_MAX_PAGE = 1000
_sleep = time.sleep


def read_all_rows(
    new_query: Callable[[], Any],
    *,
    order_column: str,
    page_size: int,
) -> list[dict[str, Any]]:
    """Return every row, in ``order_column`` order.

    ``new_query`` must build a fresh filtered query on each call. The column
    must be unique within that filter, or a later page drops rows that share
    the cursor value. ``page_size`` above 1,000 is refused: PostgREST would
    still return 1,000 and the cursor would skip the rest.
    """
    if page_size < 1 or page_size > _MAX_PAGE:
        raise ValueError(f"page_size must be from 1 to {_MAX_PAGE}")
    rows: list[dict[str, Any]] = []
    after: Any = None
    while True:
        batch = _page(
            new_query,
            order_column=order_column,
            page_size=page_size,
            after=after,
        )
        rows.extend(batch)
        if len(batch) < page_size:
            return rows
        cursor = batch[-1][order_column]
        if cursor == after:
            raise RuntimeError(f"keyset on {order_column} did not advance")
        after = cursor


def _page(
    new_query: Callable[[], Any],
    *,
    order_column: str,
    page_size: int,
    after: Any,
    attempt: int = 0,
) -> list[dict[str, Any]]:
    query = new_query()
    if after is not None:
        query = query.gt(order_column, after)
    try:
        data = query.order(order_column).limit(page_size).execute().data or []
    except Exception as exc:
        if not _is_statement_timeout(exc) or attempt >= len(_RETRY_DELAYS):
            raise
        _sleep(_RETRY_DELAYS[attempt])
        return _page(
            new_query,
            order_column=order_column,
            page_size=page_size,
            after=after,
            attempt=attempt + 1,
        )
    return list(data)
