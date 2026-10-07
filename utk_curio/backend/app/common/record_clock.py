"""The clock catalog records are stamped with.

Datasets, node packages and models record when they were made or changed
(``createdAt``, ``updatedAt``), and the catalogs show those stamps as ages:
"3d ago", "Updated 141d ago". Every such stamp reads :func:`utc_now`.

It is the system clock. The one exception is an e2e test that photographs those
ages: ``/api/testing/clock`` (mounted only under ``CURIO_TESTING``) sets it to
the date the test's browser runs on, so what the test makes reads "1m ago" on
that date, beside the shipped items' fixed dates.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

_offset = timedelta(0)


def utc_now() -> datetime:
    """The current time on the record clock, in UTC."""
    return datetime.now(timezone.utc) + _offset


def set_now(moment: datetime | None) -> None:
    """Make :func:`utc_now` read *moment* now and run on from there.

    ``None`` puts it back on the system clock. Only the testing routes call
    this.
    """
    global _offset
    _offset = timedelta(0) if moment is None else moment - datetime.now(timezone.utc)
