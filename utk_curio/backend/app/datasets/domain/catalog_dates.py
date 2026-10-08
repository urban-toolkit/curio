"""Catalog dates read as times.

A dataset's dates are written to the second, the millisecond or the
microsecond, with ``Z`` or an offset. The catalog compares them by when they
are: the listing's **Recent activity** order (``listing.py::_sort_catalog_items``)
and the date of a layer group (``layer_group.py::build_layer_group_item``).

The twin of ``services/datasetCatalog/catalogDates.ts``, with which the
canvas's Data palette dates a layer group; ``catalogDates.cases.json`` beside
it holds the cases both run.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

#: Where a missing or unreadable date sorts.
OLDEST = datetime.min.replace(tzinfo=timezone.utc)


def catalog_time(stamp: Any) -> datetime:
    """*stamp* as a time; one without an offset is UTC. A missing date, or one
    that does not read as a date, is :data:`OLDEST`."""
    if not isinstance(stamp, str) or not stamp.strip():
        return OLDEST
    try:
        moment = datetime.fromisoformat(stamp.strip())
    except ValueError:
        return OLDEST
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)
